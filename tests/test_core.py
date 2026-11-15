import unittest

from mini_feature_flag import (
    Flag,
    FlagSet,
    Override,
    PercentageRollout,
    evaluate,
)


class PercentageRolloutTests(unittest.TestCase):
    def test_zero_percent_never_matches(self):
        rollout = PercentageRollout(0)
        self.assertFalse(rollout.matches("search", "user-1"))
        self.assertFalse(rollout.matches("search", "user-2"))

    def test_hundred_percent_always_matches(self):
        rollout = PercentageRollout(100)
        self.assertTrue(rollout.matches("search", "user-1"))
        self.assertTrue(rollout.matches("search", "user-2"))

    def test_negative_percentage_rejected(self):
        with self.assertRaises(ValueError):
            PercentageRollout(-1)

    def test_over_hundred_percentage_rejected(self):
        with self.assertRaises(ValueError):
            PercentageRollout(101)

    def test_non_numeric_percentage_rejected(self):
        with self.assertRaises(TypeError):
            PercentageRollout("50")  # type: ignore[arg-type]

    def test_matches_are_deterministic(self):
        rollout = PercentageRollout(50)
        first = rollout.matches("search", "user-42")
        second = rollout.matches("search", "user-42")
        self.assertEqual(first, second)

    def test_bucketing_is_flag_specific(self):
        # A 50% rollout should not put every key into the same bucket across
        # flags; sampling a few keys makes the test stable while still
        # exercising the flag-name salt.
        rollout = PercentageRollout(50)
        keys = ["user-%d" % i for i in range(20)]
        search = [rollout.matches("search", k) for k in keys]
        billing = [rollout.matches("billing", k) for k in keys]
        self.assertNotEqual(search, billing)

    def test_roughly_half_enabled_at_fifty_percent(self):
        rollout = PercentageRollout(50)
        enabled = sum(
            1 for i in range(2000) if rollout.matches("search", "user-%d" % i)
        )
        # Tolerance is wide enough to be deterministic across platforms while
        # still catching a rollout that is wildly off (e.g. always on/off).
        self.assertGreater(enabled, 800)
        self.assertLess(enabled, 1200)


class FlagTests(unittest.TestCase):
    def test_static_flag_returns_enabled(self):
        flag = Flag("search", enabled=True)
        self.assertTrue(evaluate(flag, {}))

    def test_static_flag_returns_disabled(self):
        flag = Flag("search", enabled=False)
        self.assertFalse(evaluate(flag, {}))

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            Flag("")

    def test_non_bool_enabled_rejected(self):
        with self.assertRaises(TypeError):
            Flag("search", enabled=1)  # type: ignore[arg-type]

    def test_override_wins_over_rollout(self):
        flag = Flag(
            "search",
            rollout=PercentageRollout(0),
            overrides=(Override("user-1", True),),
        )
        self.assertTrue(evaluate(flag, {"user_id": "user-1"}))
        self.assertFalse(evaluate(flag, {"user_id": "user-2"}))

    def test_override_can_force_off(self):
        flag = Flag(
            "search",
            enabled=True,
            overrides=(Override("user-1", False),),
        )
        self.assertFalse(evaluate(flag, {"user_id": "user-1"}))
        self.assertTrue(evaluate(flag, {"user_id": "user-2"}))

    def test_later_override_wins(self):
        flag = Flag(
            "search",
            enabled=False,
            overrides=(
                Override("user-1", True),
                Override("user-1", False),
            ),
        )
        self.assertFalse(evaluate(flag, {"user_id": "user-1"}))

    def test_rollout_overrides_static_enabled(self):
        flag = Flag(
            "search",
            enabled=True,
            rollout=PercentageRollout(0),
        )
        self.assertFalse(evaluate(flag, {"user_id": "user-1"}))


class BucketingKeyTests(unittest.TestCase):
    def test_bucketing_key_preferred(self):
        flag = Flag(
            "search",
            overrides=(Override("explicit", True),),
        )
        self.assertTrue(
            evaluate(flag, {"bucketing_key": "explicit", "user_id": "other"})
        )

    def test_user_id_used_when_no_bucketing_key(self):
        flag = Flag(
            "search",
            overrides=(Override("user-7", True),),
        )
        self.assertTrue(evaluate(flag, {"user_id": "user-7"}))

    def test_key_used_as_last_resort(self):
        flag = Flag(
            "search",
            overrides=(Override("anon-1", True),),
        )
        self.assertTrue(evaluate(flag, {"key": "anon-1"}))

    def test_missing_key_is_stable(self):
        flag = Flag("search", enabled=True)
        self.assertTrue(evaluate(flag, {}))
        self.assertTrue(evaluate(flag, {}))


class FlagSetTests(unittest.TestCase):
    def test_unknown_flag_is_false(self):
        flags = FlagSet([Flag("search", enabled=True)])
        self.assertFalse(flags.evaluate("missing", {}))

    def test_add_and_get(self):
        flags = FlagSet()
        flag = Flag("search", enabled=True)
        flags.add(flag)
        self.assertIs(flags.get("search"), flag)
        self.assertIsNone(flags.get("missing"))

    def test_add_replaces_by_name(self):
        flags = FlagSet([Flag("search", enabled=False)])
        flags.add(Flag("search", enabled=True))
        self.assertTrue(flags.evaluate("search", {}))

    def test_add_rejects_non_flag(self):
        flags = FlagSet()
        with self.assertRaises(TypeError):
            flags.add("search")  # type: ignore[arg-type]

    def test_names_preserves_insertion_order(self):
        flags = FlagSet([Flag("a"), Flag("b"), Flag("c")])
        self.assertEqual(flags.names(), ["a", "b", "c"])

    def test_evaluate_via_flag_set_helper(self):
        flags = FlagSet([Flag("search", enabled=True)])
        self.assertTrue(evaluate(flags, {"flag": "search"}))

    def test_evaluate_flag_set_requires_flag_name(self):
        flags = FlagSet([Flag("search", enabled=True)])
        with self.assertRaises(KeyError):
            evaluate(flags, {})

    def test_evaluate_rejects_other_types(self):
        with self.assertRaises(TypeError):
            evaluate("search", {})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
