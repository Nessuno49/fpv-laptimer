import unittest

import stats
from database import Database


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.anna = self.db.add_pilot("Anna")
        self.ben = self.db.add_pilot("Ben")
        self.track = self.db.add_track("T1")
        self.day = 0

    def race(self, pilot, times, format="laps", settings=None, track="default"):
        self.day += 1
        settings = settings or {"laps": 2}
        track_id = self.track if track == "default" else track
        date = f"2026-09-{self.day:02d}T12:00:00"
        return self.db.save_pilot_race(pilot, track_id, format, settings, date, date, times)

    def test_categories(self):
        self.race(self.anna, [0, 8, 16])
        self.race(self.anna, [0, 8, 16, 25], "timed", {"duration_s": 120})
        self.race(self.anna, [0, 8, 16], "practice", {})
        cats = stats.categories(self.db, self.track)
        self.assertEqual([c["key"] for c in cats], ["fastest_lap", "best_3", "laps:2", "timed:120"])
        self.assertEqual(cats[3], {"key": "timed:120", "format": "timed", "settings": {"duration_s": 120}})

    def test_leaderboard_best_value_per_pilot(self):
        self.race(self.anna, [0, 9, 18])     # 18 s
        self.race(self.anna, [0, 8, 16])     # 16 s  <- Anna's best
        self.race(self.ben, [0, 8.5, 17])    # 17 s
        board = stats.leaderboard(self.db, self.track, "laps:2")
        self.assertEqual([(e["rank"], e["pilot"], e["time_s"]) for e in board],
                         [(1, "Anna", 16), (2, "Ben", 17)])

    def test_timed_race_laps_first_then_time(self):
        settings = {"duration_s": 30}
        self.race(self.anna, [0, 10, 20, 31], "timed", settings)       # 3 laps in 31 s
        self.race(self.ben, [0, 9, 18, 27, 33], "timed", settings)     # 4 laps in 33 s
        board = stats.leaderboard(self.db, self.track, "timed:30")
        self.assertEqual([(e["pilot"], e["laps"]) for e in board], [("Ben", 4), ("Anna", 3)])

    def test_race_without_track_does_not_count(self):
        self.race(self.anna, [0, 5, 10], track=None)
        self.assertEqual(stats.leaderboard(self.db, self.track, "fastest_lap"), [])

    def test_fastest_lap_over_all_formats(self):
        self.race(self.anna, [0, 9, 18])
        self.race(self.ben, [0, 7, 20], "fastest", {"duration_s": 60})
        board = stats.leaderboard(self.db, self.track, "fastest_lap")
        self.assertEqual((board[0]["pilot"], board[0]["time_s"]), ("Ben", 7))

    def test_deleted_crossing_changes_leaderboard(self):
        r = self.race(self.anna, [0, 4, 9, 18])  # false trigger at 4 s -> lap of 4 s
        self.assertEqual(stats.leaderboard(self.db, self.track, "fastest_lap")[0]["time_s"], 4)
        wrong = self.db.load_pilot_race(r)["crossings"][1]["id"]
        self.db.mark_crossing(wrong, True)
        self.assertEqual(stats.leaderboard(self.db, self.track, "fastest_lap")[0]["time_s"], 9)

    def test_pilot_records(self):
        self.race(self.anna, [0, 8, 16])
        self.race(self.ben, [0, 7, 14])
        records = {r["category"]: r for r in stats.pilot_records(self.db, self.track, self.anna)}
        self.assertEqual(records["laps:2"]["rank"], 2)
        self.assertEqual(records["laps:2"]["time_s"], 16)
        self.assertEqual(records["laps:2"]["format"], "laps")
        self.assertNotIn("best_3", records)  # Anna has no 3 laps

    def test_progress(self):
        self.race(self.anna, [0, 10, 20])  # 20
        self.race(self.anna, [0, 8, 16])   # 16
        self.race(self.anna, [0, 9, 18])   # 18
        p = stats.progress(self.db, self.track, self.anna, "laps:2")
        self.assertFalse(p["higher_is_better"])
        self.assertEqual([x["value"] for x in p["points"]], [20, 16, 18])
        self.assertEqual([x["best"] for x in p["points"]], [20, 16, 16])

    def test_rating(self):
        first = self.race(self.anna, [0, 8, 16])
        self.assertEqual(stats.rating(self.db, first), {"rank": 1, "record": "track"})
        slower = self.race(self.ben, [0, 9, 18])
        self.assertEqual(stats.rating(self.db, slower), {"rank": 2, "record": None})
        better = self.race(self.ben, [0, 8.5, 17])
        self.assertEqual(stats.rating(self.db, better), {"rank": 2, "record": "personal"})
        record = self.race(self.ben, [0, 7, 14])
        self.assertEqual(stats.rating(self.db, record), {"rank": 1, "record": "track"})

    def test_quad_filter(self):
        pavo = self.db.add_quad(self.anna, "Pavo")
        self.race(self.anna, [0, 9, 18])                        # default quad
        self.db.save_pilot_race(self.anna, self.track, "laps", {"laps": 2},
                                "2026-09-30T12:00:00", "2026-09-30T12:00:00", [0, 7, 14], quad_id=pavo)
        everything = stats.leaderboard(self.db, self.track, "laps:2")
        only_pavo = stats.leaderboard(self.db, self.track, "laps:2", quad_id=pavo)
        self.assertEqual(everything[0]["time_s"], 14)
        self.assertEqual(len(only_pavo), 1)
        default = self.db.quads(pilot_id=self.anna)[0]["id"]
        self.assertEqual(stats.leaderboard(self.db, self.track, "laps:2", quad_id=default)[0]["time_s"], 18)
        self.assertEqual(len(stats.progress(self.db, self.track, self.anna, "laps:2", quad_id=pavo)["points"]), 1)
        # only 2 laps -> fastest lap + "2 laps", but no "best 3 consecutive"
        self.assertEqual(len(stats.pilot_records(self.db, self.track, self.anna, quad_id=pavo)), 2)

    def test_pop_up_course_has_its_own_statistics(self):
        self.race(self.anna, [0, 5, 10], track=None)             # pop-up course: 10 s
        self.race(self.ben, [0, 6, 12], track=None)              # pop-up course: 12 s
        self.race(self.ben, [0, 4, 8])                           # on track T1
        board = stats.leaderboard(self.db, None, "laps:2")
        self.assertEqual([(e["pilot"], e["time_s"]) for e in board], [("Anna", 10), ("Ben", 12)])
        self.assertEqual([c["key"] for c in stats.categories(self.db, None)], ["fastest_lap", "best_3", "laps:2"])
        self.assertEqual(len(stats.progress(self.db, None, self.ben, "laps:2")["points"]), 1)

    def test_rating_without_track(self):
        r = self.race(self.anna, [0, 8, 16], track=None)
        self.assertEqual(stats.rating(self.db, r), {"rank": None, "record": None})


if __name__ == "__main__":
    unittest.main()
