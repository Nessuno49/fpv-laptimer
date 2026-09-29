import unittest

import fingerprint
from database import Database
from race import Crossing, RaceController

import numpy as np


def fp(hue, seed=0):
    rng = np.random.default_rng(seed)
    return fingerprint.fingerprint(np.clip(rng.normal(hue, 4, 300), 0, 179),
                                   np.clip(rng.normal(200, 15, 300), 0, 255), 300, 1.5)


RED, BLUE = 2, 115


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.anna = self.db.add_pilot("Anna")
        self.ben = self.db.add_pilot("Ben")
        self.anna_q = self.db.quads(pilot_id=self.anna)[0]["id"]
        self.ben_q = self.db.quads(pilot_id=self.ben)[0]["id"]
        self.track = self.db.add_track("T1")
        self.rc = RaceController(self.db, clock=self.clock, now_iso=lambda: "2026-09-24T12:00:00")
        self.read = 0

    def until(self, t):
        """Advance the clock and call tick() (like the ticker thread)."""
        while self.clock.t < t:
            self.clock.t = min(t, self.clock.t + 0.05)
            self.rc.tick()

    def crossing(self, t, fingerprint=None, photo=None):
        self.until(t)
        return self.rc.crossing(Crossing(t, photo=photo, fingerprint=fingerprint))

    def new_events(self):
        self.read, events = self.rc.events_since(self.read)
        return [e["type"] for e in events]

    def start(self, format="laps", settings=None, participants=None):
        participants = participants or [(self.anna, self.anna_q)]
        self.rc.start(participants, self.track, format, settings if settings is not None else {"laps": 2})
        if format != "practice":
            self.until(self.clock.t + 3.0)  # wait for the countdown
        return self.clock.t                  # time of "go"

    def p(self, name):
        return next(p for p in self.rc.state()["participants"] if p["pilot"] == name)


class SingleTest(Base):
    def test_ready_counts_nothing(self):
        self.assertIsNone(self.crossing(1001))
        self.assertEqual(self.rc.state()["status"], "ready")
        self.assertEqual(self.new_events(), [])

    def test_start_checks(self):
        with self.assertRaises(ValueError):
            self.rc.start([], None, "laps", {})
        with self.assertRaises(ValueError):
            self.rc.start([(self.anna, self.anna_q), (self.anna, self.anna_q)], None, "laps", {})
        self.start()
        with self.assertRaises(ValueError):
            self.start()

    def test_countdown_ignores_crossings(self):
        self.rc.start([(self.anna, self.anna_q)], self.track, "laps", {"laps": 2})
        self.assertEqual(self.rc.state()["status"], "countdown")
        self.crossing(1001.5)
        self.until(1003.1)
        self.assertEqual(self.rc.state()["status"], "running")
        self.assertEqual(self.p("Anna")["laps"], [])
        self.assertEqual(self.new_events(), ["countdown", "countdown", "countdown", "go"])

    def test_laps_race(self):
        go = self.start("laps", {"laps": 2})
        self.new_events()
        self.crossing(go + 2)
        self.crossing(go + 10)
        self.crossing(go + 17)
        self.assertEqual(self.new_events(), ["holeshot", "lap", "lap", "race_end"])
        lap1 = self.rc.events_since(0)[1][-3]
        self.assertTrue(lap1["last_lap"])
        self.assertEqual(self.rc.state()["status"], "finished")
        anna = self.p("Anna")
        self.assertEqual(anna["result"]["time_s"], 17)
        self.assertEqual(anna["holeshot_s"], 2)
        self.assertEqual(anna["rating"]["record"], "track")
        saved = self.db.load_pilot_race(anna["pilot_race_id"])
        self.assertEqual([c["t"] for c in saved["crossings"]], [2, 10, 17])
        self.assertEqual(saved["quad_id"], self.anna_q)
        end = self.rc.events_since(0)[1][-1]
        self.assertEqual(end["results"], [{"pilot": "Anna", "time_s": 17, "laps": None, "rank": 1,
                                           "record": "track"}])

    def test_timed_race(self):
        go = self.start("timed", {"duration_s": 60})
        self.new_events()
        self.crossing(go + 2)
        self.crossing(go + 20)
        self.until(go + 30.1)
        self.assertEqual(self.new_events(), ["holeshot", "lap", "30s_left"])
        self.crossing(go + 45)
        self.until(go + 60.1)
        self.assertEqual(self.new_events(), ["lap", "time_up"])
        self.crossing(go + 64)
        self.assertEqual(self.new_events(), ["lap", "race_end"])
        result = self.p("Anna")["result"]
        self.assertEqual((result["laps"], result["time_s"]), (3, 64))

    def test_grace_period(self):
        go = self.start("timed", {"duration_s": 30})
        self.crossing(go + 2)
        self.crossing(go + 12)
        self.until(go + 89)
        self.assertEqual(self.rc.state()["status"], "running")
        self.until(go + 90.1)
        self.assertEqual(self.rc.state()["status"], "finished")
        result = self.p("Anna")["result"]
        self.assertEqual((result["laps"], result["time_s"]), (1, 12))

    def test_finish_saves_abort_does_not(self):
        go = self.start("laps", {"laps": 5})
        self.crossing(go + 2)
        self.crossing(go + 10)
        self.rc.finish()
        self.assertIsNone(self.p("Anna")["result"])
        self.assertEqual(len(self.db.races()), 1)
        self.rc.dismiss()
        go = self.start()
        self.crossing(go + 2)
        self.rc.abort()
        self.assertEqual(self.rc.state()["status"], "ready")
        self.assertEqual(len(self.db.races()), 1)

    def test_finished_ignores_and_dismiss(self):
        go = self.start("laps", {"laps": 1})
        self.crossing(go + 2)
        self.crossing(go + 9)
        self.crossing(go + 15)
        self.assertEqual(self.p("Anna")["laps"], [7])
        self.rc.dismiss()
        self.assertEqual(self.rc.state()["status"], "ready")

    def test_min_lap(self):
        self.rc.min_lap = lambda: 3.0
        go = self.start("laps", {"laps": 5})
        self.crossing(go + 0.5)    # holeshot right after go counts
        self.crossing(go + 2)      # too short -> nobody
        self.crossing(go + 10)
        anna = self.p("Anna")
        self.assertEqual(anna["holeshot_s"], 0.5)
        self.assertEqual(anna["laps"], [9.5])
        self.assertEqual(len(self.rc.state()["unassigned"]), 1)

    def test_remaining_time_and_current_lap(self):
        go = self.start("timed", {"duration_s": 60})
        self.crossing(go + 2)
        self.until(go + 5)
        self.assertAlmostEqual(self.rc.state()["remaining_s"], 55)
        self.assertAlmostEqual(self.p("Anna")["since_last_s"], 3)

    def test_profile_learns_with_one_participant(self):
        go = self.start("laps", {"laps": 5})
        self.crossing(go + 2, fingerprint=fp(RED), photo="a.jpg")
        self.crossing(go + 9, fingerprint=fp(RED, 1))
        self.assertEqual(self.db.profile_info(self.anna_q)["count"], 2)


class StagingTest(Base):
    """Time to put on the goggles before the 3-2-1."""

    def events_with_time(self, until):
        """Advance the clock in small steps and collect (second since start, type, value)."""
        start, found = self.clock.t, []
        while self.clock.t < until:
            self.until(self.clock.t + 0.05)
            self.read, new = self.rc.events_since(self.read)
            found += [(round(self.clock.t - start), e["type"], e.get("value")) for e in new]
        return found

    def test_sequence_30_seconds(self):
        start = self.clock.t
        self.rc.start([(self.anna, self.anna_q)], self.track, "laps", {"laps": 2}, staging_s=30)
        self.assertEqual(self.rc.state()["status"], "staging")
        self.assertAlmostEqual(self.rc.state()["staging_s"], 30)
        sequence = self.events_with_time(start + 30.5)
        self.assertEqual(sequence, [
            (0, "staging", 30),
            (15, "staging", 15), (20, "staging", 10), (25, "staging", 5),
            (27, "countdown", 3), (28, "countdown", 2), (29, "countdown", 1), (30, "go", None)])
        self.assertAlmostEqual(self.rc.go_t, start + 30)   # exactly 30 s after the click

    def test_60_seconds_calls_out_45(self):
        start = self.clock.t
        self.rc.start([(self.anna, self.anna_q)], self.track, "laps", {"laps": 2}, staging_s=60)
        callouts = [v for _, type, v in self.events_with_time(start + 57) if type == "staging"]
        self.assertEqual(callouts, [60, 45, 30, 15, 10, 5])

    def test_crossing_during_staging_does_not_count(self):
        self.rc.start([(self.anna, self.anna_q)], self.track, "laps", {"laps": 2}, staging_s=15)
        self.assertIsNone(self.crossing(self.clock.t + 5))   # warm-up flight
        self.until(self.clock.t + 15)
        self.assertFalse(self.p("Anna")["started"])          # no holeshot either

    def test_skip_staging(self):
        self.rc.start([(self.anna, self.anna_q)], self.track, "laps", {"laps": 2}, staging_s=60)
        self.until(self.clock.t + 5)
        self.rc.skip_staging()
        self.assertEqual(self.rc.state()["status"], "countdown")
        now = self.clock.t
        self.until(now + 3.05)
        self.assertEqual(self.rc.state()["status"], "running")
        self.assertAlmostEqual(self.rc.go_t, now + 3)

    def test_abort_during_staging(self):
        self.rc.start([(self.anna, self.anna_q)], self.track, "laps", {"laps": 2}, staging_s=30)
        self.new_events()
        self.rc.abort()
        self.assertEqual(self.rc.state()["status"], "ready")
        self.assertEqual(self.new_events(), ["aborted"])

    def test_without_staging(self):
        self.rc.start([(self.anna, self.anna_q)], self.track, "laps", {"laps": 2}, staging_s=0)
        self.assertEqual(self.rc.state()["status"], "countdown")

    def test_practice_without_staging_and_invalid_values(self):
        self.rc.start([(self.anna, self.anna_q)], self.track, "practice", {}, staging_s=30)
        self.assertEqual(self.rc.state()["status"], "running")
        self.rc.end_practice()
        with self.assertRaises(ValueError):
            self.rc.start([(self.anna, self.anna_q)], self.track, "laps", {"laps": 2}, staging_s=20)


class PracticeTest(Base):
    def test_practice(self):
        self.start("practice", {})
        self.assertEqual(self.rc.state()["status"], "running")
        self.crossing(1001)
        self.crossing(1009)
        self.crossing(1016)
        anna = self.p("Anna")
        self.assertEqual(anna["laps"], [8, 7])
        self.assertIsNone(anna["holeshot_s"])
        self.assertEqual(self.new_events(), ["practice", "first", "lap", "lap"])
        self.rc.end_practice()
        self.assertEqual(self.rc.state()["status"], "ready")
        self.assertEqual(self.new_events(), ["practice_end"])
        self.assertEqual(self.db.races(), [])


class MultipleTest(Base):
    def setUp(self):
        super().setUp()
        for i in range(5):  # train profiles: Anna red, Ben blue
            self.db.add_sample(self.anna_q, fp(RED, i))
            self.db.add_sample(self.ben_q, fp(BLUE, i))
        self.both = [(self.anna, self.anna_q), (self.ben, self.ben_q)]

    def test_assignment_by_colour(self):
        go = self.start("laps", {"laps": 3}, self.both)
        info = self.crossing(go + 2, fingerprint=fp(BLUE, 9))
        self.assertEqual(info["pilot"], "Ben")
        self.crossing(go + 2.6, fingerprint=fp(RED, 9))
        self.assertAlmostEqual(self.p("Anna")["holeshot_s"], 2.6)
        self.assertAlmostEqual(self.p("Ben")["holeshot_s"], 2)

    def test_plausibility_without_fingerprint(self):
        self.rc.min_lap = lambda: 3.0
        go = self.start("laps", {"laps": 3}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))    # Anna
        info = self.crossing(go + 3)                  # no fingerprint: Anna locked -> only Ben possible
        self.assertEqual(info["pilot"], "Ben")
        self.assertFalse(info["uncertain"])

    def test_unassigned_and_live_assign(self):
        self.rc.min_lap = lambda: 5.0
        go = self.start("laps", {"laps": 3}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))
        self.crossing(go + 2.5, fingerprint=fp(BLUE))
        info = self.crossing(go + 3.5)                # both locked
        self.assertIsNone(info["pilot"])
        unassigned = self.rc.state()["unassigned"]
        self.assertEqual(len(unassigned), 1)
        self.assertIn("unassigned", self.new_events())
        self.rc.assign_live(unassigned[0]["nr"], self.ben_q)
        self.assertEqual(self.rc.state()["unassigned"], [])
        self.assertEqual(self.p("Ben")["laps"], [1.0])

    def test_live_assign_refuses_duplicates(self):
        self.rc.min_lap = lambda: 2.0
        go = self.start("laps", {"laps": 3}, [(self.anna, self.anna_q)])
        self.crossing(go + 2)
        self.crossing(go + 2.05)                      # shadow of the same crossing -> unassigned
        unassigned = self.rc.state()["unassigned"]
        self.assertEqual(len(unassigned), 1)
        with self.assertRaises(ValueError):
            self.rc.assign_live(unassigned[0]["nr"], self.anna_q)
        self.assertEqual(self.p("Anna")["holeshot_s"], 2)
        self.assertEqual(self.p("Anna")["laps"], [])

    def test_finish_and_end_when_everyone_is_done(self):
        go = self.start("laps", {"laps": 1}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))
        self.crossing(go + 3, fingerprint=fp(BLUE))
        self.crossing(go + 9, fingerprint=fp(RED))    # Anna finished
        self.assertTrue(self.p("Anna")["finished"])
        self.assertEqual(self.rc.state()["status"], "running")
        self.assertIn("finish", self.new_events())
        info = self.crossing(go + 12, fingerprint=fp(BLUE))  # Ben
        self.assertEqual(info["pilot"], "Ben")
        state = self.rc.state()
        self.assertEqual(state["status"], "finished")
        self.assertEqual([p["pilot"] for p in state["participants"]], ["Anna", "Ben"])
        self.assertEqual([p["rank"] for p in state["participants"]], [1, 2])
        self.assertEqual(sorted(self.db.races()[0]["pilots"]), ["Anna", "Ben"])

    def test_finished_pilot_is_ignored_not_passed_on(self):
        go = self.start("laps", {"laps": 1}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))
        self.crossing(go + 3, fingerprint=fp(BLUE))
        self.crossing(go + 9, fingerprint=fp(RED))      # Anna finished
        info = self.crossing(go + 15, fingerprint=fp(RED, 7))  # Anna keeps flying around
        self.assertTrue(info["ignored"])
        self.assertEqual(info["pilot"], "Anna")
        self.assertEqual(self.p("Ben")["laps"], [])     # Ben does NOT get it
        self.assertEqual(self.rc.state()["unassigned"], [])

    def test_locked_pilot_duplicate_is_ignored(self):
        self.rc.min_lap = lambda: 3.0
        go = self.start("laps", {"laps": 3}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))
        info = self.crossing(go + 2.4, fingerprint=fp(RED, 8))   # Anna detected twice
        self.assertTrue(info["ignored"])
        self.assertFalse(self.p("Ben")["started"])

    def test_does_not_learn_by_elimination(self):
        go = self.start("laps", {"laps": 1}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))
        self.crossing(go + 3, fingerprint=fp(BLUE))
        self.crossing(go + 9, fingerprint=fp(RED))      # Anna finished -> only Ben possible
        before = self.db.profile_info(self.ben_q)["count"]
        info = self.crossing(go + 12, fingerprint=fp(60, 5))  # green: clearly matches nobody
        self.assertEqual(info["pilot"], "Ben")           # counts for Ben (only candidate) ...
        self.assertEqual(self.db.profile_info(self.ben_q)["count"], before)  # ... but is not learned

    def test_timed_everyone_finishes_their_lap(self):
        go = self.start("timed", {"duration_s": 30}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))
        self.crossing(go + 3, fingerprint=fp(BLUE))
        self.until(go + 30.5)
        self.crossing(go + 31, fingerprint=fp(RED))     # Anna crosses after the time -> done
        self.assertTrue(self.p("Anna")["finished"])
        self.assertEqual(self.rc.state()["status"], "running")
        self.crossing(go + 33, fingerprint=fp(BLUE))    # Ben too -> race over
        self.assertEqual(self.rc.state()["status"], "finished")

    def test_live_order(self):
        go = self.start("laps", {"laps": 5}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))
        self.crossing(go + 3, fingerprint=fp(BLUE))
        self.crossing(go + 9, fingerprint=fp(BLUE))     # Ben completes a lap first
        state = self.rc.state()
        self.assertEqual([p["pilot"] for p in state["participants"]], ["Ben", "Anna"])
        self.assertEqual(state["participants"][1]["gap"], {"laps": 1})
        self.assertIsNone(state["participants"][0]["gap"])

    def test_events_with_names(self):
        go = self.start("laps", {"laps": 3}, self.both)
        self.crossing(go + 2, fingerprint=fp(RED))
        e = self.rc.events_since(0)[1][-1]
        self.assertEqual(e["pilot"], "Anna")
        self.assertTrue(e["multiple"])


if __name__ == "__main__":
    unittest.main()
