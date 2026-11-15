# mini_feature_flag

Evaluate feature flags with percentage rollout and overrides, using only the
Python standard library.

```python
from mini_feature_flag import Flag, FlagSet, Override, PercentageRollout

flags = FlagSet([
    Flag(
        "new-search",
        rollout=PercentageRollout(25),
        overrides=(Override("user-1", True),),
    ),
    Flag("dark-mode", enabled=True),
])

flags.evaluate("new-search", {"user_id": "user-1"})  # True, override
flags.evaluate("new-search", {"user_id": "user-2"})  # depends on the rollout
flags.evaluate("dark-mode", {})                        # True, static flag
flags.evaluate("unknown", {})                          # False, fail closed
```

The top-level `evaluate` helper accepts either a `Flag` or a `FlagSet`:

```python
from mini_feature_flag import Flag, evaluate

evaluate(Flag("dark-mode", enabled=True), {})  # True
```

When passed a `FlagSet`, the context must include a `"flag"` entry naming the
flag to evaluate:

```python
from mini_feature_flag import Flag, FlagSet, evaluate

flags = FlagSet([Flag("dark-mode", enabled=True)])
evaluate(flags, {"flag": "dark-mode"})  # True
```

## Why this exists

The problem is deciding whether a given user sees a feature without storing a
per-user decision in a database. The trade-off made here is that bucketing is
deterministic and local: a SHA-256 digest of the flag name and the bucketing
key decides the bucket, so the same user always lands in the same rollout for
the same flag, and different flags do not accidentally share a bucket. That
costs a hash per evaluation and means changing the flag name reshuffles the
rollout, which is the intended behaviour when a flag is renamed.

## The awkward edge

Overrides are matched on the bucketing key, not on the flag name. If a context
contains both `bucketing_key` and `user_id`, the `bucketing_key` wins. If it
contains neither, the empty string is used, which is stable but arbitrary. The
lookup order is `bucketing_key`, then `user_id`, then `key`.

Unknown flags evaluate to `False` rather than raising, so a typo fails closed
instead of silently enabling a feature. Pass a `FlagSet` to `evaluate` without
a `"flag"` entry in the context and it raises `KeyError`, because there is no
sensible flag to choose.
