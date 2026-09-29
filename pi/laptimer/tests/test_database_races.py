"""Quads, races, recognition samples and the migration of old (German) databases."""
import json
import os
import sqlite3
import tempfile
import unittest

from database import SCHEMA_VERSION, Database

# Schema version 2 as it was in September 2026 (German names) – for the migration test.
GERMAN_SCHEMA_V2 = """
CREATE TABLE piloten (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, erstellt TEXT NOT NULL,
  archiviert INTEGER NOT NULL DEFAULT 0);
CREATE TABLE tracks (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, beschreibung TEXT NOT NULL DEFAULT '',
  erstellt TEXT NOT NULL, archiviert INTEGER NOT NULL DEFAULT 0);
CREATE TABLE rennen (id INTEGER PRIMARY KEY, pilot_id INTEGER NOT NULL REFERENCES piloten(id),
  track_id INTEGER REFERENCES tracks(id), format TEXT NOT NULL, einstellungen TEXT NOT NULL,
  start TEXT NOT NULL, ende TEXT NOT NULL, copter_id INTEGER REFERENCES copter(id),
  lauf_id INTEGER REFERENCES laeufe(id));
CREATE TABLE copter (id INTEGER PRIMARY KEY, pilot_id INTEGER NOT NULL REFERENCES piloten(id),
  name TEXT NOT NULL, erstellt TEXT NOT NULL, archiviert INTEGER NOT NULL DEFAULT 0, UNIQUE (pilot_id, name));
CREATE TABLE laeufe (id INTEGER PRIMARY KEY, format TEXT NOT NULL, einstellungen TEXT NOT NULL,
  track_id INTEGER REFERENCES tracks(id), start TEXT NOT NULL, ende TEXT NOT NULL);
CREATE TABLE merkmale (id INTEGER PRIMARY KEY, copter_id INTEGER NOT NULL REFERENCES copter(id) ON DELETE CASCADE,
  daten TEXT NOT NULL, foto TEXT, erstellt TEXT NOT NULL);
CREATE TABLE durchfahrten (id INTEGER PRIMARY KEY, rennen_id INTEGER REFERENCES rennen(id) ON DELETE CASCADE,
  lauf_id INTEGER REFERENCES laeufe(id) ON DELETE CASCADE, t REAL NOT NULL, geloescht INTEGER NOT NULL DEFAULT 0,
  foto TEXT, unsicher INTEGER NOT NULL DEFAULT 0, merkmal TEXT);
CREATE INDEX durchfahrten_rennen ON durchfahrten(rennen_id);
CREATE INDEX durchfahrten_lauf ON durchfahrten(lauf_id);
CREATE INDEX merkmale_copter ON merkmale(copter_id);
PRAGMA user_version = 2;
"""


class MigrationTest(unittest.TestCase):
    def test_german_database_is_converted(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(path)
        con.executescript(GERMAN_SCHEMA_V2)
        fp = json.dumps({"hist": [1.0], "flaeche": 300, "verhaeltnis": 1.4, "netz": [1.0]})
        con.executescript(f"""
            INSERT INTO piloten VALUES (1, 'Anna', '2026-09-20', 0);
            INSERT INTO tracks VALUES (1, 'Hall', 'Slalom', '2026-09-20', 0);
            INSERT INTO copter VALUES (3, 1, 'Red whoop', '2026-09-20', 0);
            INSERT INTO laeufe VALUES (6, 'runden', '{{"runden": 5}}', 1, '2026-09-26T23:47:57', '2026-09-26T23:49:00');
            INSERT INTO rennen VALUES (9, 1, 1, 'runden', '{{"runden": 5}}', '2026-09-26T23:47:57',
                                       '2026-09-26T23:49:00', 3, 6);
            INSERT INTO durchfahrten VALUES (1, 9, 6, 5.09, 0, 'a.jpg', 1, '{fp}');
            INSERT INTO durchfahrten VALUES (2, NULL, 6, 5.06, 1, 'b.jpg', 0, NULL);
            INSERT INTO merkmale VALUES (1, 3, '{fp}', 'a.jpg', '2026-09-26');
            INSERT INTO laeufe VALUES (7, 'beste_n', '{{"dauer_s": 120, "n": 3}}', NULL, '2026-09-27', '2026-09-27');
            INSERT INTO rennen VALUES (10, 1, NULL, 'beste_n', '{{"dauer_s": 120, "n": 3}}', '2026-09-27',
                                       '2026-09-27', 3, 7);
        """)
        con.close()

        db = Database(path)
        self.addCleanup(db.close)
        self.assertEqual(db._con.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual([p["name"] for p in db.pilots()], ["Anna"])
        self.assertEqual(db.tracks()[0]["description"], "Slalom")
        self.assertEqual([q["name"] for q in db.quads(pilot_id=1)], ["Red whoop"])
        race = db.load_race(6)
        self.assertEqual((race["format"], race["settings"]), ("laps", {"laps": 5}))
        pilot_race = race["pilot_races"][0]
        self.assertEqual((pilot_race["pilot"], pilot_race["quad"], pilot_race["format"]),
                         ("Anna", "Red whoop", "laps"))
        self.assertEqual([(c["t"], c["photo"], c["uncertain"]) for c in pilot_race["crossings"]],
                         [(5.09, "a.jpg", True)])
        self.assertEqual([(c["t"], c["deleted"]) for c in race["unassigned"]], [(5.06, True)])
        converted = {"hist": [1.0], "area": 300, "aspect": 1.4, "embedding": [1.0]}
        self.assertEqual(db.samples(3), [converted])
        self.assertEqual(db.crossing_fingerprint(1), converted)
        self.assertEqual(db.load_race(7)["settings"], {"duration_s": 120, "n": 3})
        self.assertEqual(db.load_race(7)["format"], "consecutive")
        # everything still works after the migration (foreign keys point to the new tables)
        db.assign_crossing(2, 1)
        self.assertEqual(len(db.load_race(6)["pilot_races"][0]["crossings"]), 2)
        self.assertEqual(db.delete_pilot(1), ["a.jpg", "b.jpg"])

    def test_opening_twice_does_not_migrate_again(self):
        path = os.path.join(tempfile.mkdtemp(), "new.db")
        db = Database(path)
        db.add_pilot("Anna")
        db.close()
        again = Database(path)
        self.addCleanup(again.close)
        self.assertEqual([p["name"] for p in again.pilots()], ["Anna"])


class QuadTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.anna = self.db.add_pilot("Anna")

    def test_new_pilot_has_default_quad(self):
        self.assertEqual([q["name"] for q in self.db.quads(pilot_id=self.anna)], ["Default"])

    def test_add_and_update_quad(self):
        q = self.db.add_quad(self.anna, "Pavo red")
        self.db.update_quad(q, name="Pavo Pico red")
        names = [x["name"] for x in self.db.quads(pilot_id=self.anna)]
        self.assertIn("Pavo Pico red", names)
        with self.assertRaises(ValueError):
            self.db.add_quad(self.anna, "Default")
        self.db.update_quad(q, archived=True)
        self.assertEqual(len(self.db.quads(pilot_id=self.anna)), 1)

    def test_samples_max_50(self):
        q = self.db.quads(pilot_id=self.anna)[0]["id"]
        for i in range(55):
            self.db.add_sample(q, {"hist": [i], "area": 1, "aspect": 1.0}, photo=f"f{i}.jpg")
        samples = self.db.samples(q)
        self.assertEqual(len(samples), 50)
        self.assertEqual(samples[-1]["hist"], [54])              # newest is in
        self.assertNotIn([0], [s["hist"] for s in samples])      # oldest is out
        info = self.db.profile_info(q)
        self.assertEqual(info["count"], 50)
        self.assertEqual(info["photos"][0], "f54.jpg")
        self.db.clear_samples(q)
        self.assertEqual(self.db.samples(q), [])


class RaceTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.anna, self.ben = self.db.add_pilot("Anna"), self.db.add_pilot("Ben")
        self.t1 = self.db.add_track("T1")
        self.race = self.db.save_race("laps", {"laps": 2}, self.t1, "2026-09-24T12:00:00", "2026-09-24T12:01:00")
        self.ra = self.db.save_pilot_race(self.anna, self.t1, "laps", {"laps": 2}, "2026-09-24T12:00:00",
                                          "2026-09-24T12:01:00",
                                          [{"t": 1.0, "photo": "a1.jpg", "uncertain": False},
                                           {"t": 9.0, "photo": "a2.jpg", "uncertain": True}],
                                          race_id=self.race)
        self.rb = self.db.save_pilot_race(self.ben, self.t1, "laps", {"laps": 2}, "2026-09-24T12:00:00",
                                          "2026-09-24T12:01:00", [1.5, 10.0], race_id=self.race)
        self.db.save_unassigned(self.race, [{"t": 17.0, "photo": "x.jpg"}])

    def test_load_race(self):
        race = self.db.load_race(self.race)
        self.assertEqual(sorted(r["pilot"] for r in race["pilot_races"]), ["Anna", "Ben"])
        self.assertEqual([c["t"] for c in race["unassigned"]], [17.0])
        anna = next(r for r in race["pilot_races"] if r["pilot"] == "Anna")
        self.assertEqual([(c["photo"], c["uncertain"]) for c in anna["crossings"]],
                         [("a1.jpg", False), ("a2.jpg", True)])

    def test_delete_pilot_for_good(self):
        anna_quad = self.db.quads(pilot_id=self.anna)[0]["id"]
        self.db.add_sample(anna_quad, {"x": 1}, photo="a1.jpg")
        # a second race in which only Anna flew (with an unassigned crossing)
        alone = self.db.save_race("laps", {"laps": 2}, self.t1, "2026-09-25T12:00:00", "2026-09-25T12:01:00")
        self.db.save_pilot_race(self.anna, self.t1, "laps", {"laps": 2}, "2026-09-25T12:00:00",
                                "2026-09-25T12:01:00", [{"t": 2.0, "photo": "a3.jpg"}], race_id=alone)
        self.db.save_unassigned(alone, [{"t": 5.0, "photo": "y.jpg"}])

        photos = self.db.delete_pilot(self.anna)

        self.assertEqual(photos, ["a1.jpg", "a2.jpg", "a3.jpg", "y.jpg"])    # x.jpg still belongs to race 1
        self.assertEqual([p["name"] for p in self.db.pilots(include_archived=True)], ["Ben"])
        self.assertEqual(self.db.quads(pilot_id=self.anna), [])
        self.assertEqual(self.db.samples(anna_quad), [])
        race = self.db.load_race(self.race)                                  # Ben stays in the shared race
        self.assertEqual([r["pilot"] for r in race["pilot_races"]], ["Ben"])
        self.assertEqual(len(race["unassigned"]), 1)
        self.assertEqual([r["id"] for r in self.db.races()], [self.race])    # Anna's solo race is gone
        with self.assertRaises(ValueError):
            self.db.delete_pilot(self.anna)

    def test_race_list(self):
        races = self.db.races()
        self.assertEqual(len(races), 1)
        self.assertEqual(sorted(races[0]["pilots"]), ["Anna", "Ben"])
        self.assertEqual(races[0]["unassigned"], 1)
        self.assertEqual(len(self.db.races(pilot_id=self.ben)), 1)
        self.assertEqual(len(self.db.races(track_id=None)), 0)

    def test_assign_crossing(self):
        open_id = self.db.load_race(self.race)["unassigned"][0]["id"]
        self.db.assign_crossing(open_id, self.anna)
        race = self.db.load_race(self.race)
        self.assertEqual(race["unassigned"], [])
        anna = next(r for r in race["pilot_races"] if r["pilot"] == "Anna")
        self.assertEqual([c["t"] for c in anna["crossings"]], [1.0, 9.0, 17.0])
        # move to Ben
        self.db.assign_crossing(open_id, self.ben)
        self.assertEqual([c["t"] for c in self.db.load_pilot_race(self.rb)["crossings"]], [1.5, 10.0, 17.0])

    def test_assign_refuses_duplicates(self):
        # unassigned crossing 0.1 s next to Anna's crossing at 9.0
        self.db.save_unassigned(self.race, [{"t": 9.1}])
        duplicate = [c for c in self.db.load_race(self.race)["unassigned"] if c["t"] == 9.1][0]["id"]
        with self.assertRaises(ValueError):
            self.db.assign_crossing(duplicate, self.anna, min_gap=0.5)
        self.db.assign_crossing(duplicate, self.ben, min_gap=0.5)   # 0.9 s next to Ben: allowed

    def test_assign_only_to_participants(self):
        carl = self.db.add_pilot("Carl")
        open_id = self.db.load_race(self.race)["unassigned"][0]["id"]
        with self.assertRaises(ValueError):
            self.db.assign_crossing(open_id, carl)

    def test_change_track_and_delete_race(self):
        self.db.update_race(self.race, track_id=None)
        self.assertIsNone(self.db.load_pilot_race(self.ra)["track_id"])
        photos = self.db.delete_race(self.race)
        self.assertEqual(sorted(photos), ["a1.jpg", "a2.jpg", "x.jpg"])
        self.assertIsNone(self.db.load_race(self.race))
        self.assertIsNone(self.db.load_pilot_race(self.ra))

    def test_photos(self):
        self.assertEqual(self.db.referenced_photos(), {"a1.jpg", "a2.jpg", "x.jpg"})
        self.db.remove_photo("a1.jpg")
        self.assertIsNone(self.db.load_pilot_race(self.ra)["crossings"][0]["photo"])

    def test_quad_filter(self):
        pavo = self.db.add_quad(self.anna, "Pavo")
        self.db.save_pilot_race(self.anna, self.t1, "laps", {"laps": 2}, "2026-09-25T12:00:00",
                                "2026-09-25T12:01:00", [0, 5, 10], quad_id=pavo)
        self.assertEqual(len(self.db.pilot_races_with_times(self.t1)), 3)
        self.assertEqual(len(self.db.pilot_races_with_times(self.t1, quad_id=pavo)), 1)

    def test_reassign_pilot_race(self):
        self.db.reassign_pilot_race(self.ra, self.ben)
        r = self.db.load_pilot_race(self.ra)
        self.assertEqual(r["pilot"], "Ben")
        self.assertEqual(r["quad"], "Default")


class HistoryLearnsTest(unittest.TestCase):
    """Corrections in the race history improve the profiles."""

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.anna, self.ben = self.db.add_pilot("Anna"), self.db.add_pilot("Ben")
        self.anna_q = self.db.quads(pilot_id=self.anna)[0]["id"]
        self.ben_q = self.db.quads(pilot_id=self.ben)[0]["id"]
        self.race = self.db.save_race("laps", {"laps": 2}, None, "2026-09-25T12:00:00", "2026-09-25T12:01:00")
        # the crossing at 9.0 was wrongly given to Anna (and learned into her profile)
        self.fp = {"hist": [0.5, 0.5], "area": 100, "aspect": 1.0}
        self.ra = self.db.save_pilot_race(self.anna, None, "laps", {"laps": 2}, "2026-09-25T12:00:00",
                                          "2026-09-25T12:01:00",
                                          [{"t": 1.0}, {"t": 9.0, "photo": "f9.jpg", "fingerprint": self.fp}],
                                          quad_id=self.anna_q, race_id=self.race)
        self.rb = self.db.save_pilot_race(self.ben, None, "laps", {"laps": 2}, "2026-09-25T12:00:00",
                                          "2026-09-25T12:01:00", [1.5], quad_id=self.ben_q, race_id=self.race)
        self.db.add_sample(self.anna_q, self.fp, "f9.jpg")
        self.c9 = [c for c in self.db.load_pilot_race(self.ra)["crossings"] if c["t"] == 9.0][0]["id"]

    def test_fingerprint_is_stored(self):
        self.assertEqual(self.db.crossing_fingerprint(self.c9), self.fp)

    def test_assigning_moves_sample(self):
        self.db.assign_crossing(self.c9, self.ben)
        self.assertEqual(self.db.profile_info(self.anna_q)["count"], 0)
        self.assertEqual(self.db.samples(self.ben_q), [self.fp])

    def test_delete_removes_sample_and_restore_brings_it_back(self):
        self.db.mark_crossing(self.c9, True)
        self.assertEqual(self.db.profile_info(self.anna_q)["count"], 0)
        self.db.mark_crossing(self.c9, False)
        self.assertEqual(self.db.samples(self.anna_q), [self.fp])

    def test_moving_whole_pilot_race_takes_samples_along(self):
        self.db.reassign_pilot_race(self.ra, self.ben)
        self.assertEqual(self.db.profile_info(self.anna_q)["count"], 0)
        self.assertEqual(self.db.samples(self.ben_q), [self.fp])

    def test_without_fingerprint_nothing_bad_happens(self):
        c1 = [c for c in self.db.load_pilot_race(self.ra)["crossings"] if c["t"] == 1.0][0]["id"]
        self.db.assign_crossing(c1, self.ben)            # old crossing without fingerprint
        self.assertEqual(self.db.profile_info(self.anna_q)["count"], 1)  # Anna's sample stays


if __name__ == "__main__":
    unittest.main()
