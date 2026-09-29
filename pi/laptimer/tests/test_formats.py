import unittest

import formats


class LapsTest(unittest.TestCase):
    def test_laps_from_times(self):
        self.assertEqual(formats.laps_from_times([2.0, 10.5, 18.0]), [8.5, 7.5])

    def test_holeshot_only_gives_no_lap(self):
        self.assertEqual(formats.laps_from_times([2.0]), [])
        self.assertEqual(formats.laps_from_times([]), [])

    def test_best_consecutive(self):
        # windows: 9+8+7=24, 8+7+10=25, 7+10+6=23
        self.assertAlmostEqual(formats.best_consecutive([9, 8, 7, 10, 6], 3), 23)
        self.assertAlmostEqual(formats.best_consecutive([9, 8, 7], 3), 24)

    def test_best_consecutive_too_few_laps(self):
        self.assertIsNone(formats.best_consecutive([9, 8], 3))


class EndTest(unittest.TestCase):
    def test_laps_ends_exactly_at_x(self):
        settings = {"laps": 2}
        self.assertFalse(formats.crossing_ends_race("laps", settings, [1.0, 9.0]))
        self.assertTrue(formats.crossing_ends_race("laps", settings, [1.0, 9.0, 17.0]))

    def test_timed_ends_only_after_time_is_up(self):
        settings = {"duration_s": 30}
        self.assertFalse(formats.crossing_ends_race("timed", settings, [1.0, 12.0, 25.0]))
        self.assertTrue(formats.crossing_ends_race("timed", settings, [1.0, 12.0, 25.0, 33.0]))

    def test_timed_does_not_end_on_holeshot(self):
        # holeshot only after the time is up: no lap yet, keep flying
        self.assertFalse(formats.crossing_ends_race("timed", {"duration_s": 30}, [31.0]))

    def test_other_timed_formats(self):
        for fmt in ("consecutive", "fastest"):
            self.assertTrue(formats.crossing_ends_race(fmt, {"duration_s": 30, "n": 3}, [1.0, 31.0]))


class ResultTest(unittest.TestCase):
    def test_laps(self):
        r = formats.result("laps", {"laps": 2}, [1.0, 9.0, 17.5])
        self.assertEqual(r["sort_key"], (17.5,))
        self.assertEqual((r["time_s"], r["laps"]), (17.5, None))
        self.assertFalse(r["higher_is_better"])

    def test_laps_incomplete(self):
        self.assertIsNone(formats.result("laps", {"laps": 3}, [1.0, 9.0, 17.5]))

    def test_timed(self):
        r = formats.result("timed", {"duration_s": 30}, [1.0, 12.0, 22.0, 32.5])
        self.assertEqual(r["sort_key"], (-3, 32.5))
        self.assertEqual(r["value"], 3)
        self.assertTrue(r["higher_is_better"])
        self.assertEqual((r["laps"], r["time_s"]), (3, 32.5))

    def test_timed_more_laps_is_better(self):
        three = formats.result("timed", {"duration_s": 30}, [1, 12, 22, 32.5])
        two = formats.result("timed", {"duration_s": 30}, [1, 10, 31])
        self.assertLess(three["sort_key"], two["sort_key"])

    def test_timed_without_lap(self):
        self.assertIsNone(formats.result("timed", {"duration_s": 30}, [1.0]))

    def test_consecutive(self):
        r = formats.result("consecutive", {"duration_s": 60, "n": 2}, [0, 9, 17, 24, 34])
        self.assertEqual(r["sort_key"], (15,))

    def test_consecutive_too_few(self):
        self.assertIsNone(formats.result("consecutive", {"duration_s": 60, "n": 3}, [0, 9, 17]))

    def test_fastest(self):
        r = formats.result("fastest", {"duration_s": 60}, [0, 9, 16, 26])
        self.assertEqual(r["sort_key"], (7,))
        self.assertEqual(r["time_s"], 7)


class CategoryTest(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(formats.category_key("laps", {"laps": 10}), "laps:10")
        self.assertEqual(formats.category_key("timed", {"duration_s": 120}), "timed:120")
        self.assertEqual(formats.category_key("consecutive", {"duration_s": 120, "n": 3}), "consecutive:120:3")
        self.assertEqual(formats.category_key("fastest", {"duration_s": 90}), "fastest:90")

    def test_key_round_trip(self):
        for format, settings in [("laps", {"laps": 10}), ("timed", {"duration_s": 120}),
                                 ("consecutive", {"duration_s": 90, "n": 3}), ("fastest", {"duration_s": 60}),
                                 ("practice", {})]:
            self.assertEqual(formats.category_from_key(formats.category_key(format, settings)), (format, settings))


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(formats.check_settings("laps", {}), {"laps": 10})
        self.assertEqual(formats.check_settings("consecutive", {}), {"duration_s": 120, "n": 3})

    def test_limits(self):
        self.assertEqual(formats.check_settings("laps", {"laps": 500}), {"laps": 99})
        self.assertEqual(formats.check_settings("timed", {"duration_s": 5}), {"duration_s": 30})
        self.assertEqual(formats.check_settings("consecutive", {"n": 1, "duration_s": 60}), {"duration_s": 60, "n": 2})

    def test_foreign_keys_are_dropped(self):
        self.assertEqual(formats.check_settings("timed", {"duration_s": 60, "laps": 3}), {"duration_s": 60})

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            formats.check_settings("nonsense", {})


class PracticeTest(unittest.TestCase):
    def test_practice(self):
        self.assertEqual(formats.check_settings("practice", {"laps": 5}), {})
        self.assertEqual(formats.category_key("practice", {}), "practice")
        self.assertFalse(formats.crossing_ends_race("practice", {}, [1, 9, 17, 25]))
        self.assertIsNone(formats.result("practice", {}, [1, 9, 17]))


class LiveTest(unittest.TestCase):
    def test_more_laps_ahead(self):
        a = formats.live_sort_key("laps", {"laps": 5}, [1, 9, 17])   # 2 laps
        b = formats.live_sort_key("laps", {"laps": 5}, [2, 10])      # 1 lap
        self.assertLess(a, b)

    def test_same_laps_earlier_ahead(self):
        a = formats.live_sort_key("timed", {"duration_s": 60}, [1, 9, 17])
        b = formats.live_sort_key("timed", {"duration_s": 60}, [1, 9, 18])
        self.assertLess(a, b)

    def test_without_crossing_behind(self):
        a = formats.live_sort_key("laps", {"laps": 5}, [1])
        b = formats.live_sort_key("laps", {"laps": 5}, [])
        self.assertLess(a, b)

    def test_fastest_and_consecutive(self):
        self.assertLess(formats.live_sort_key("fastest", {"duration_s": 60}, [0, 7, 16]),
                        formats.live_sort_key("fastest", {"duration_s": 60}, [0, 8, 16]))
        self.assertLess(formats.live_sort_key("consecutive", {"duration_s": 60, "n": 2}, [0, 7, 14]),
                        formats.live_sort_key("consecutive", {"duration_s": 60, "n": 2}, [0, 7]))


if __name__ == "__main__":
    unittest.main()
