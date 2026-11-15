"""Feature flag evaluation with percentage rollout and overrides.

The design keeps evaluation pure and deterministic: the same ``FlagSet`` and
``context`` always produce the same result. Rollout bucketing hashes the flag
name together with a caller-supplied bucketing key, so a user who falls into a
rollout for one flag is not forced into the same bucket for every other flag.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

__all__ = [
    "Flag",
    "FlagSet",
    "Override",
    "PercentageRollout",
    "evaluate",
]


# 2**32 gives a uniform integer range for the first 4 bytes of a SHA-256 digest.
_BUCKET_SPACE = 2 ** 32


def _bucket(flag_name: str, key: str) -> int:
    """Return a stable bucket in ``[0, 2**32)`` for a flag/key pair.

    SHA-256 is used rather than a language-level hash because Python's builtin
    ``hash`` is salted per process; a salted hash would make the same user
    land in different rollouts across restarts.
    """
    digest = hashlib.sha256()
    digest.update(flag_name.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(key.encode("utf-8"))
    return int.from_bytes(digest.digest()[:4], "big")


@dataclass(frozen=True)
class PercentageRollout:
    """A percentage rollout that enables a flag for a stable subset of keys.

    ``percentage`` is in ``[0, 100]``. The rollout is inclusive of the lower
    bound and exclusive of the upper bound, so a 0% rollout never enables and
    a 100% rollout always enables.
    """

    percentage: float

    def __post_init__(self) -> None:
        if not isinstance(self.percentage, (int, float)):
            raise TypeError("percentage must be a number")
        if self.percentage < 0 or self.percentage > 100:
            raise ValueError("percentage must be between 0 and 100")

    def matches(self, flag_name: str, bucketing_key: str) -> bool:
        """Return whether ``bucketing_key`` is inside the rollout for ``flag_name``."""
        if self.percentage <= 0:
            return False
        if self.percentage >= 100:
            return True
        threshold = int((self.percentage / 100.0) * _BUCKET_SPACE)
        return _bucket(flag_name, bucketing_key) < threshold


@dataclass(frozen=True)
class Override:
    """An explicit per-key decision that wins over any rollout.

    ``enabled`` is the value returned for ``bucketing_key``. Overrides are
    checked before the rollout so an operator can force a flag on or off for
    a specific user without changing the rollout percentage.
    """

    bucketing_key: str
    enabled: bool


@dataclass(frozen=True)
class Flag:
    """A single feature flag.

    Exactly one of ``rollout`` and ``enabled`` should be used. When ``rollout``
    is set it takes precedence; otherwise ``enabled`` is returned as a static
    default. This keeps the common case (a plain on/off flag) simple while
    still allowing percentage rollouts.
    """

    name: str
    enabled: bool = False
    rollout: Optional[PercentageRollout] = None
    overrides: Tuple[Override, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("flag name must not be empty")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        # Normalise overrides so callers can pass a list and still get a
        # hashable, frozen dataclass.
        if not isinstance(self.overrides, tuple):
            object.__setattr__(self, "overrides", tuple(self.overrides))

    def override_for(self, bucketing_key: str) -> Optional[bool]:
        """Return the override value for ``bucketing_key``, if any.

        Later overrides win, which makes it natural to append a specific
        override after a catch-all one and have it take effect.
        """
        result: Optional[bool] = None
        for override in self.overrides:
            if override.bucketing_key == bucketing_key:
                result = override.enabled
        return result


class FlagSet:
    """A collection of flags keyed by name.

    The set is intentionally mutable at construction time and cheap to query.
    Callers who need to change flags at runtime can replace the whole set; the
    evaluation path itself does not mutate anything.
    """

    def __init__(self, flags: Iterable[Flag] = ()) -> None:
        self._flags: Dict[str, Flag] = {}
        for flag in flags:
            self.add(flag)

    def add(self, flag: Flag) -> None:
        """Add or replace a flag by name."""
        if not isinstance(flag, Flag):
            raise TypeError("flag must be a Flag instance")
        self._flags[flag.name] = flag

    def get(self, name: str) -> Optional[Flag]:
        """Return the flag with ``name``, or ``None`` if it is not defined."""
        return self._flags.get(name)

    def names(self) -> List[str]:
        """Return the names of all defined flags in insertion order."""
        return list(self._flags.keys())

    def evaluate(self, name: str, context: Mapping[str, Any]) -> bool:
        """Evaluate the flag ``name`` against ``context``.

        Unknown flags evaluate to ``False``. This is deliberate: a typo in a
        flag name should fail closed rather than randomly enable a feature.
        """
        flag = self._flags.get(name)
        if flag is None:
            return False
        return _evaluate_flag(flag, context)


def _evaluate_flag(flag: Flag, context: Mapping[str, Any]) -> bool:
    bucketing_key = _bucketing_key(context)

    override = flag.override_for(bucketing_key)
    if override is not None:
        return override

    if flag.rollout is not None:
        return flag.rollout.matches(flag.name, bucketing_key)

    return flag.enabled


def _bucketing_key(context: Mapping[str, Any]) -> str:
    """Extract the bucketing key from ``context``.

    ``bucketing_key`` is preferred, then ``user_id``, then ``key``. If none is
    present we fall back to the empty string, which still produces a stable
    bucket and therefore a stable (if arbitrary) decision.
    """
    for candidate in ("bucketing_key", "user_id", "key"):
        value = context.get(candidate)
        if value is not None:
            return str(value)
    return ""


def evaluate(
    flag: Union[Flag, FlagSet],
    context: Mapping[str, Any],
) -> bool:
    """Evaluate a flag or flag set against a context.

    Passing a ``Flag`` evaluates that flag directly. Passing a ``FlagSet``
    requires ``context`` to contain a ``"flag"`` entry naming the flag to
    evaluate; this keeps the top-level helper usable for both shapes without
    inventing a second signature.
    """
    if isinstance(flag, Flag):
        return _evaluate_flag(flag, context)
    if isinstance(flag, FlagSet):
        name = context.get("flag")
        if name is None:
            raise KeyError("context must contain a 'flag' name when evaluating a FlagSet")
        return flag.evaluate(str(name), context)
    raise TypeError("flag must be a Flag or FlagSet")
