import unittest

from database import Database


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def pilot_race(self, pilot, track=None, times=(1.0, 9.0, 17.0)):
        return self.db.save_pilot_race(pilot, track, "laps", {"laps": 2},
                                       "2026-09-24T12:00:00", "2026-09-24T12:01:00", list(times))

    def test_pilots(self):
        a = self.db.add_pilot("Anna")
        self.db.add_pilot("Ben")
        self.assertEqual([p["name"] for p in self.db.pilots()], ["Anna", "Ben"])
        self.db.update_pilot(a, name="Anni")
        self.assertEqual(self.db.pilots()[0]["name"], "Anni")

    def test_duplicate_or_empty_name(self):
        self.db.add_pilot("Anna")
        with self.assertRaises(ValueError):
            self.db.add_pilot("Anna")
        with self.assertRaises(ValueError):
            self.db.add_pilot("  ")

    def test_names_are_unique_regardless_of_case_and_spaces(self):
        a = self.db.add_pilot("Anna")
        for same in ("anna", " ANNA ", "Anna "):
            with self.assertRaises(ValueError):
                self.db.add_pilot(same)
        self.assertEqual(self.db.add_pilot("  Anna   Lena "), self.db.pilots()[1]["id"])
        self.assertEqual(self.db.pilots()[1]["name"], "Anna Lena")      # spaces tidied up
        b = self.db.add_pilot("Ben")
        with self.assertRaises(ValueError):
            self.db.update_pilot(b, name="aNNa")                        # renaming too
        self.db.update_pilot(a, name="ANNA")                            # own name in other case: fine
        self.assertEqual(self.db.pilots()[0]["name"], "ANNA")
        self.db.add_track("Hall")
        with self.assertRaises(ValueError):
            self.db.add_track("hall")

    def test_archived_name_is_taken_with_a_hint(self):
        a = self.db.add_pilot("Anna")
        self.db.update_pilot(a, archived=True)
        with self.assertRaises(ValueError) as e:
            self.db.add_pilot("anna")
        self.assertEqual(e.exception.key, "name_exists_archived")

    def test_quad_names_unique_per_pilot(self):
        a, b = self.db.add_pilot("Anna"), self.db.add_pilot("Ben")
        q = self.db.add_quad(a, "Pavo")
        with self.assertRaises(ValueError):
            self.db.add_quad(a, "pavo")
        self.db.add_quad(b, "Pavo")                                     # another pilot may use it
        other = self.db.add_quad(a, "Mobula")
        with self.assertRaises(ValueError):
            self.db.update_quad(other, name="PAVO")
        self.db.update_quad(q, name="PAVO")

    def test_archiving_hides(self):
        a = self.db.add_pilot("Anna")
        self.db.update_pilot(a, archived=True)
        self.assertEqual(self.db.pilots(), [])
        self.assertEqual(len(self.db.pilots(include_archived=True)), 1)

    def test_tracks(self):
        t = self.db.add_track("Club hall 1", "Slalom")
        self.assertEqual(self.db.tracks()[0]["description"], "Slalom")
        self.db.update_track(t, description="Slalom + tunnel")
        self.assertEqual(self.db.tracks()[0]["description"], "Slalom + tunnel")

    def test_save_and_load_pilot_race(self):
        p = self.db.add_pilot("Anna")
        t = self.db.add_track("T1")
        r = self.pilot_race(p, t)
        loaded = self.db.load_pilot_race(r)
        self.assertEqual(loaded["pilot"], "Anna")
        self.assertEqual(loaded["track"], "T1")
        self.assertEqual(loaded["settings"], {"laps": 2})
        self.assertEqual([c["t"] for c in loaded["crossings"]], [1.0, 9.0, 17.0])
        self.assertEqual(self.db.pilot_races()[0]["id"], r)

    def test_pilot_race_filter(self):
        a, b = self.db.add_pilot("Anna"), self.db.add_pilot("Ben")
        t = self.db.add_track("T1")
        self.pilot_race(a, t)
        self.pilot_race(b, None)
        self.assertEqual(len(self.db.pilot_races(pilot_id=a)), 1)
        self.assertEqual(len(self.db.pilot_races(track_id=t)), 1)
        self.assertEqual(len(self.db.pilot_races(track_id=None)), 1)  # only "no track"
        self.assertEqual(len(self.db.pilot_races()), 2)

    def test_mark_crossing(self):
        p = self.db.add_pilot("Anna")
        t = self.db.add_track("T1")
        r = self.pilot_race(p, t, times=(1.0, 5.0, 9.0))
        wrong = self.db.load_pilot_race(r)["crossings"][1]["id"]
        self.db.mark_crossing(wrong, True)
        self.assertEqual(self.db.pilot_races_with_times(t)[0]["times"], [1.0, 9.0])
        self.db.mark_crossing(wrong, False)
        self.assertEqual(self.db.pilot_races_with_times(t)[0]["times"], [1.0, 5.0, 9.0])

    def test_update_pilot_race(self):
        a, b = self.db.add_pilot("Anna"), self.db.add_pilot("Ben")
        t = self.db.add_track("T1")
        r = self.pilot_race(a, t)
        self.db.update_pilot_race(r, pilot_id=b)
        self.assertEqual(self.db.load_pilot_race(r)["pilot"], "Ben")
        self.assertEqual(self.db.load_pilot_race(r)["track_id"], t)
        self.db.update_pilot_race(r, track_id=None)
        self.assertIsNone(self.db.load_pilot_race(r)["track_id"])

    def test_delete_pilot_race(self):
        p = self.db.add_pilot("Anna")
        r = self.pilot_race(p)
        self.db.delete_pilot_race(r)
        self.assertIsNone(self.db.load_pilot_race(r))
        self.assertEqual(self.db._con.execute("SELECT COUNT(*) FROM crossings").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
