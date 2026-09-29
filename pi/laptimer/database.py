"""SQLite database: pilots, quads, tracks, races, pilot races, crossings, recognition samples.

A race is one start of 1–8 participants. Every participant has their own pilot race in it.
Crossings without a pilot race belong only to the race ("unassigned") and can be assigned
to a participant later.
"""
import datetime
import json
import sqlite3
import threading

from i18n import UserError

SCHEMA_VERSION = 3
SCHEMA = """
CREATE TABLE pilots (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tracks (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE quads (
  id INTEGER PRIMARY KEY,
  pilot_id INTEGER NOT NULL REFERENCES pilots(id),
  name TEXT NOT NULL,
  created TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0,
  UNIQUE (pilot_id, name)
);
CREATE TABLE races (
  id INTEGER PRIMARY KEY,
  format TEXT NOT NULL,
  settings TEXT NOT NULL,
  track_id INTEGER REFERENCES tracks(id),
  started TEXT NOT NULL,
  ended TEXT NOT NULL
);
CREATE TABLE pilot_races (
  id INTEGER PRIMARY KEY,
  pilot_id INTEGER NOT NULL REFERENCES pilots(id),
  track_id INTEGER REFERENCES tracks(id),
  format TEXT NOT NULL,
  settings TEXT NOT NULL,
  started TEXT NOT NULL,
  ended TEXT NOT NULL,
  quad_id INTEGER REFERENCES quads(id),
  race_id INTEGER REFERENCES races(id)
);
CREATE TABLE crossings (
  id INTEGER PRIMARY KEY,
  pilot_race_id INTEGER REFERENCES pilot_races(id) ON DELETE CASCADE,
  race_id INTEGER REFERENCES races(id) ON DELETE CASCADE,
  t REAL NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,
  photo TEXT,
  uncertain INTEGER NOT NULL DEFAULT 0,
  fingerprint TEXT
);
CREATE TABLE samples (
  id INTEGER PRIMARY KEY,
  quad_id INTEGER NOT NULL REFERENCES quads(id) ON DELETE CASCADE,
  data TEXT NOT NULL,
  photo TEXT,
  created TEXT NOT NULL
);
CREATE INDEX crossings_pilot_race ON crossings(pilot_race_id);
CREATE INDEX crossings_race ON crossings(race_id);
CREATE INDEX samples_quad ON samples(quad_id);
"""

# ---------------------------------------------------------------- migration of German databases
# Up to version 2 (September 2026) tables, columns and stored values had German names.
# Version 3 renames everything; the old names appear only here.
RENAME_TABLES = [("piloten", "pilots"), ("copter", "quads"), ("laeufe", "races"),
                 ("rennen", "pilot_races"), ("durchfahrten", "crossings"), ("merkmale", "samples")]
RENAME_COLUMNS = {
    "pilots": [("erstellt", "created"), ("archiviert", "archived")],
    "tracks": [("beschreibung", "description"), ("erstellt", "created"), ("archiviert", "archived")],
    "quads": [("erstellt", "created"), ("archiviert", "archived")],
    "races": [("einstellungen", "settings"), ("start", "started"), ("ende", "ended")],
    "pilot_races": [("einstellungen", "settings"), ("start", "started"), ("ende", "ended"),
                    ("copter_id", "quad_id"), ("lauf_id", "race_id")],
    "crossings": [("rennen_id", "pilot_race_id"), ("lauf_id", "race_id"), ("geloescht", "deleted"),
                  ("foto", "photo"), ("unsicher", "uncertain"), ("merkmal", "fingerprint")],
    "samples": [("copter_id", "quad_id"), ("daten", "data"), ("foto", "photo"), ("erstellt", "created")],
}
OLD_FORMATS = {"training": "practice", "runden": "laps", "zeit": "timed", "beste_n": "consecutive",
               "schnellste": "fastest"}
OLD_SETTINGS = {"runden": "laps", "dauer_s": "duration_s"}
OLD_FINGERPRINT = {"flaeche": "area", "verhaeltnis": "aspect", "netz": "embedding"}


def _rename_keys(text, names):
    """JSON text with renamed keys (None stays None)."""
    if text is None:
        return None
    data = json.loads(text)
    return json.dumps({names.get(k, k): v for k, v in data.items()})


DEFAULT_QUAD = "Default"
MAX_SAMPLES = 50

# Placeholders for "parameter not given" (None means "no track" for track_id)
ALL = object()
UNCHANGED = object()

PILOT_RACE_SQL = """
SELECT r.id, r.pilot_id, p.name AS pilot, r.quad_id, q.name AS quad, r.race_id,
       r.track_id, t.name AS track, r.format, r.settings, r.started, r.ended
FROM pilot_races r
JOIN pilots p ON p.id = r.pilot_id
LEFT JOIN quads q ON q.id = r.quad_id
LEFT JOIN tracks t ON t.id = r.track_id
"""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _crossing(c):
    """float or dict -> (t, photo, uncertain, fingerprint as JSON)"""
    if isinstance(c, dict):
        fp = c.get("fingerprint")
        return (c["t"], c.get("photo"), int(bool(c.get("uncertain"))), json.dumps(fp) if fp else None)
    return c, None, 0, None


class Database:
    def __init__(self, path):
        self.lock = threading.RLock()
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._set_up()
        self._con.execute("PRAGMA foreign_keys = ON")
        self._con.commit()

    def close(self):
        with self.lock:
            self._con.close()

    # ---------------------------------------------------------- schema & migration

    def _tables(self):
        return {r[0] for r in self._con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def _set_up(self):
        version = self._con.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        if "piloten" in self._tables():
            if version < 2:
                raise RuntimeError("Database too old to migrate (schema version < 2).")
            self._migrate_from_german()
        else:  # new database
            self._con.executescript("BEGIN;" + SCHEMA + f"PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")

    def _migrate_from_german(self):
        con = self._con
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN")
        try:
            for old, new in RENAME_TABLES:
                con.execute(f"ALTER TABLE {old} RENAME TO {new}")
            for table, columns in RENAME_COLUMNS.items():
                for old, new in columns:
                    con.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
            for index in ("durchfahrten_rennen", "durchfahrten_lauf", "merkmale_copter"):
                con.execute(f"DROP INDEX IF EXISTS {index}")
            con.execute("CREATE INDEX crossings_pilot_race ON crossings(pilot_race_id)")
            con.execute("CREATE INDEX crossings_race ON crossings(race_id)")
            con.execute("CREATE INDEX samples_quad ON samples(quad_id)")
            for table in ("races", "pilot_races"):
                for row in con.execute(f"SELECT id, format, settings FROM {table}").fetchall():
                    con.execute(f"UPDATE {table} SET format = ?, settings = ? WHERE id = ?",
                                (OLD_FORMATS.get(row["format"], row["format"]),
                                 _rename_keys(row["settings"], OLD_SETTINGS), row["id"]))
            for row in con.execute("SELECT id, data FROM samples").fetchall():
                con.execute("UPDATE samples SET data = ? WHERE id = ?",
                            (_rename_keys(row["data"], OLD_FINGERPRINT), row["id"]))
            for row in con.execute("SELECT id, fingerprint FROM crossings WHERE fingerprint IS NOT NULL").fetchall():
                con.execute("UPDATE crossings SET fingerprint = ? WHERE id = ?",
                            (_rename_keys(row["fingerprint"], OLD_FINGERPRINT), row["id"]))
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise

    # ---------------------------------------------------------- helpers

    def _execute(self, sql, values=()):
        with self.lock:
            cur = self._con.execute(sql, values)
            self._con.commit()
            return cur

    def _query(self, sql, values=()):
        with self.lock:
            return [dict(r) for r in self._con.execute(sql, values).fetchall()]

    def _value(self, sql, values=()):
        with self.lock:
            row = self._con.execute(sql, values).fetchone()
            return row[0] if row else None

    def _check_name(self, table, name, exists_key, id=None, pilot_id=None):
        """Tidy up a name and make sure it is free: "Anna", "anna" and " Anna " are the same name.

        Quads only need a unique name per pilot. An archived entry keeps its name taken
        (with a hint, so it is reactivated instead of created a second time).
        """
        name = " ".join(str(name or "").split())
        if not name:
            raise UserError("name_empty")
        scope, values = ("AND pilot_id = ?", [pilot_id]) if table == "quads" else ("", [])
        for row in self._query(f"SELECT id, name, archived FROM {table} WHERE id != ? {scope}", [id or -1, *values]):
            if row["name"].casefold() == name.casefold():
                raise UserError("name_exists_archived" if row["archived"] and exists_key == "name_exists" else exists_key,
                                name=row["name"])
        return name

    def _add(self, table, columns, exists_key):
        name = self._check_name(table, columns["name"], exists_key, pilot_id=columns.get("pilot_id"))
        columns = {**columns, "name": name, "created": _now()}
        try:
            cur = self._execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                list(columns.values()))
        except sqlite3.IntegrityError:
            raise UserError(exists_key, name=name) from None
        return cur.lastrowid

    def _update(self, table, id, columns, exists_key="name_exists"):
        columns = {k: v for k, v in columns.items() if v is not None}
        if "name" in columns:
            pilot_id = self._value("SELECT pilot_id FROM quads WHERE id = ?", (id,)) if table == "quads" else None
            columns["name"] = self._check_name(table, columns["name"], exists_key, id=id, pilot_id=pilot_id)
        if "archived" in columns:
            columns["archived"] = int(bool(columns["archived"]))
        if not columns:
            return
        try:
            self._execute(
                f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in columns)} WHERE id = ?",
                [*columns.values(), id])
        except sqlite3.IntegrityError:
            raise UserError(exists_key, name=columns.get("name", "")) from None

    def _list(self, table, columns, include_archived):
        condition = "" if include_archived else "WHERE archived = 0"
        rows = self._query(f"SELECT {columns} FROM {table} {condition} ORDER BY name COLLATE NOCASE")
        for r in rows:
            r["archived"] = bool(r["archived"])
        return rows

    # ---------------------------------------------------------- pilots & tracks

    def add_pilot(self, name):
        with self.lock:
            pilot_id = self._add("pilots", {"name": name}, "name_exists")
            self.add_quad(pilot_id, DEFAULT_QUAD)
        return pilot_id

    def pilots(self, include_archived=False):
        return self._list("pilots", "id, name, archived", include_archived)

    def update_pilot(self, id, name=None, archived=None):
        self._update("pilots", id, {"name": name, "archived": archived})

    def add_track(self, name, description=""):
        return self._add("tracks", {"name": name, "description": description.strip()}, "name_exists")

    def tracks(self, include_archived=False):
        return self._list("tracks", "id, name, description, archived", include_archived)

    def update_track(self, id, name=None, description=None, archived=None):
        self._update("tracks", id, {"name": name, "description": description, "archived": archived})

    # ---------------------------------------------------------- quads & recognition samples

    def add_quad(self, pilot_id, name):
        return self._add("quads", {"pilot_id": pilot_id, "name": name}, "quad_name_exists")

    def quads(self, pilot_id=None, include_archived=False):
        conditions, values = [], []
        if pilot_id is not None:
            conditions.append("q.pilot_id = ?")
            values.append(pilot_id)
        if not include_archived:
            conditions.append("q.archived = 0")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._query(
            f"""SELECT q.id, q.pilot_id, p.name AS pilot, q.name, q.archived,
                       (SELECT COUNT(*) FROM samples s WHERE s.quad_id = q.id) AS samples
                FROM quads q JOIN pilots p ON p.id = q.pilot_id {where}
                ORDER BY p.name COLLATE NOCASE, q.id""", values)
        for r in rows:
            r["archived"] = bool(r["archived"])
        return rows

    def update_quad(self, id, name=None, archived=None):
        self._update("quads", id, {"name": name, "archived": archived}, "quad_name_exists")

    def _default_quad(self, pilot_id):
        return self._value("SELECT id FROM quads WHERE pilot_id = ? ORDER BY archived, id LIMIT 1", (pilot_id,))

    def add_sample(self, quad_id, data, photo=None):
        with self.lock:
            self._con.execute("INSERT INTO samples (quad_id, data, photo, created) VALUES (?, ?, ?, ?)",
                              (quad_id, json.dumps(data), photo, _now()))
            # keep only the newest MAX_SAMPLES
            self._con.execute("""DELETE FROM samples WHERE quad_id = ? AND id NOT IN
                                 (SELECT id FROM samples WHERE quad_id = ? ORDER BY id DESC LIMIT ?)""",
                              (quad_id, quad_id, MAX_SAMPLES))
            self._con.commit()

    def samples(self, quad_id):
        return [json.loads(r["data"]) for r in
                self._query("SELECT data FROM samples WHERE quad_id = ? ORDER BY id", (quad_id,))]

    def clear_samples(self, quad_id):
        self._execute("DELETE FROM samples WHERE quad_id = ?", (quad_id,))

    def profile_info(self, quad_id, photo_count=6):
        photos = [r["photo"] for r in self._query(
            "SELECT photo FROM samples WHERE quad_id = ? AND photo IS NOT NULL ORDER BY id DESC LIMIT ?",
            (quad_id, photo_count))]
        return {"count": self._value("SELECT COUNT(*) FROM samples WHERE quad_id = ?", (quad_id,)),
                "photos": photos}

    # ---------------------------------------------------------- races & pilot races

    def save_race(self, format, settings, track_id, started, ended):
        return self._execute(
            "INSERT INTO races (format, settings, track_id, started, ended) VALUES (?, ?, ?, ?, ?)",
            (format, json.dumps(settings), track_id, started, ended)).lastrowid

    def save_pilot_race(self, pilot_id, track_id, format, settings, started, ended, crossings,
                        quad_id=None, race_id=None):
        with self.lock:
            if quad_id is None:
                quad_id = self._default_quad(pilot_id)
            if race_id is None:
                race_id = self.save_race(format, settings, track_id, started, ended)
            cur = self._con.execute(
                "INSERT INTO pilot_races (pilot_id, quad_id, race_id, track_id, format, settings, started, ended)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pilot_id, quad_id, race_id, track_id, format, json.dumps(settings), started, ended))
            pilot_race_id = cur.lastrowid
            self._con.executemany(
                "INSERT INTO crossings (pilot_race_id, race_id, t, photo, uncertain, fingerprint)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [(pilot_race_id, race_id, *_crossing(c)) for c in crossings])
            self._con.commit()
        return pilot_race_id

    def save_unassigned(self, race_id, crossings):
        with self.lock:
            self._con.executemany(
                "INSERT INTO crossings (pilot_race_id, race_id, t, photo, uncertain, fingerprint)"
                " VALUES (NULL, ?, ?, ?, ?, ?)",
                [(race_id, *_crossing(c)) for c in crossings])
            self._con.commit()

    @staticmethod
    def _pilot_race_row(r):
        r["settings"] = json.loads(r["settings"])
        return r

    def _crossings(self, condition, values):
        rows = self._query(
            f"SELECT id, t, deleted, photo, uncertain FROM crossings WHERE {condition} ORDER BY t", values)
        for c in rows:
            c["deleted"] = bool(c["deleted"])
            c["uncertain"] = bool(c["uncertain"])
        return rows

    def pilot_races(self, pilot_id=None, track_id=ALL):
        conditions, values = [], []
        if pilot_id is not None:
            conditions.append("r.pilot_id = ?")
            values.append(pilot_id)
        if track_id is None:
            conditions.append("r.track_id IS NULL")
        elif track_id is not ALL:
            conditions.append("r.track_id = ?")
            values.append(track_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return [self._pilot_race_row(r) for r in
                self._query(f"{PILOT_RACE_SQL} {where} ORDER BY r.started DESC, r.id DESC", values)]

    def load_pilot_race(self, id):
        rows = self._query(f"{PILOT_RACE_SQL} WHERE r.id = ?", (id,))
        if not rows:
            return None
        pilot_race = self._pilot_race_row(rows[0])
        pilot_race["crossings"] = self._crossings("pilot_race_id = ?", (id,))
        return pilot_race

    def update_pilot_race(self, id, pilot_id=UNCHANGED, track_id=UNCHANGED):
        if pilot_id is not UNCHANGED:
            self.reassign_pilot_race(id, pilot_id)
        if track_id is not UNCHANGED:
            self._execute("UPDATE pilot_races SET track_id = ? WHERE id = ?", (track_id, id))

    def reassign_pilot_race(self, pilot_race_id, pilot_id):
        """Wrong pilot selected: move the pilot race (quad = the pilot's first quad).

        Samples that were learned from this pilot race move along.
        """
        with self.lock:
            quad_id = self._default_quad(pilot_id)
            self._execute("UPDATE pilot_races SET pilot_id = ?, quad_id = ? WHERE id = ?",
                          (pilot_id, quad_id, pilot_race_id))
            learned = {r[0] for r in self._con.execute("SELECT photo FROM samples WHERE photo IS NOT NULL")}
            for (crossing_id, photo) in self._con.execute(
                    "SELECT id, photo FROM crossings WHERE pilot_race_id = ? AND fingerprint IS NOT NULL",
                    (pilot_race_id,)).fetchall():
                if photo in learned:
                    self._relearn_sample(crossing_id, quad_id)

    def delete_pilot_race(self, id):
        self._execute("DELETE FROM pilot_races WHERE id = ?", (id,))

    def mark_crossing(self, id, deleted):
        """Delete = false trigger: take the sample out of the profile. Restore = real: learn it."""
        with self.lock:
            self._execute("UPDATE crossings SET deleted = ? WHERE id = ?", (int(bool(deleted)), id))
            quad_id = self._value("SELECT r.quad_id FROM crossings c JOIN pilot_races r ON r.id = c.pilot_race_id "
                                  "WHERE c.id = ?", (id,))
            self._relearn_sample(id, None if deleted else quad_id)

    def crossing_fingerprint(self, id):
        data = self._value("SELECT fingerprint FROM crossings WHERE id = ?", (id,))
        return json.loads(data) if data else None

    def _relearn_sample(self, crossing_id, quad_id):
        """Take this crossing's sample out of all profiles and (if quad_id) learn it there."""
        photo = self._value("SELECT photo FROM crossings WHERE id = ?", (crossing_id,))
        fp = self.crossing_fingerprint(crossing_id)
        if fp is None:
            return  # old crossing without fingerprint: profiles stay as they are
        if photo:
            self._execute("DELETE FROM samples WHERE photo = ?", (photo,))
        if quad_id is not None:
            self.add_sample(quad_id, fp, photo)

    def assign_crossing(self, crossing_id, pilot_id, min_gap=0.0):
        """Give a crossing to a pilot's pilot race in the same race (also moving it).

        If it is closer than min_gap to a valid crossing of that pilot, it was probably
        detected twice -> UserError.
        """
        with self.lock:
            race_id, t = self._con.execute("SELECT race_id, t FROM crossings WHERE id = ?",
                                           (crossing_id,)).fetchone()
            pilot_race_id = self._value("SELECT id FROM pilot_races WHERE race_id = ? AND pilot_id = ?",
                                        (race_id, pilot_id))
            if pilot_race_id is None:
                raise UserError("pilot_not_in_race")
            others = [r[0] for r in self._con.execute(
                "SELECT t FROM crossings WHERE pilot_race_id = ? AND deleted = 0 AND id != ?",
                (pilot_race_id, crossing_id))]
            nearest = min((abs(t - o) for o in others), default=None)
            if nearest is not None and nearest < min_gap:
                raise UserError("crossing_too_close", gap=float(nearest))
            self._execute("UPDATE crossings SET pilot_race_id = ?, uncertain = 0 WHERE id = ?",
                          (pilot_race_id, crossing_id))
            # The correction is the best information: relearn the sample into the right profile
            quad_id = self._value("SELECT quad_id FROM pilot_races WHERE id = ?", (pilot_race_id,))
            self._relearn_sample(crossing_id, quad_id)

    def races(self, pilot_id=None, track_id=ALL):
        conditions, values = [], []
        if pilot_id is not None:
            conditions.append("EXISTS (SELECT 1 FROM pilot_races r WHERE r.race_id = a.id AND r.pilot_id = ?)")
            values.append(pilot_id)
        if track_id is None:
            conditions.append("a.track_id IS NULL")
        elif track_id is not ALL:
            conditions.append("a.track_id = ?")
            values.append(track_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        races = self._query(
            f"""SELECT a.id, a.format, a.settings, a.track_id, t.name AS track, a.started, a.ended
                FROM races a LEFT JOIN tracks t ON t.id = a.track_id {where}
                ORDER BY a.started DESC, a.id DESC""", values)
        for race in races:
            race["settings"] = json.loads(race["settings"])
            race["pilots"] = [r["name"] for r in self._query(
                "SELECT p.name FROM pilot_races r JOIN pilots p ON p.id = r.pilot_id WHERE r.race_id = ? ORDER BY r.id",
                (race["id"],))]
            race["unassigned"] = self._value(
                "SELECT COUNT(*) FROM crossings WHERE race_id = ? AND pilot_race_id IS NULL AND deleted = 0",
                (race["id"],))
        return [r for r in races if r["pilots"]]

    def load_race(self, id):
        rows = self._query(
            """SELECT a.id, a.format, a.settings, a.track_id, t.name AS track, a.started, a.ended
               FROM races a LEFT JOIN tracks t ON t.id = a.track_id WHERE a.id = ?""", (id,))
        if not rows:
            return None
        race = rows[0]
        race["settings"] = json.loads(race["settings"])
        race["pilot_races"] = [self.load_pilot_race(r["id"]) for r in
                               self._query("SELECT id FROM pilot_races WHERE race_id = ? ORDER BY id", (id,))]
        race["unassigned"] = self._crossings("race_id = ? AND pilot_race_id IS NULL", (id,))
        return race

    def update_race(self, id, track_id):
        with self.lock:
            self._con.execute("UPDATE races SET track_id = ? WHERE id = ?", (track_id, id))
            self._con.execute("UPDATE pilot_races SET track_id = ? WHERE race_id = ?", (track_id, id))
            self._con.commit()

    def delete_race(self, id):
        """Deletes the race, its pilot races and crossings. Returns the photos that can go."""
        with self.lock:
            photos = [r["photo"] for r in self._query(
                "SELECT photo FROM crossings WHERE race_id = ? AND photo IS NOT NULL", (id,))]
            self._con.execute("DELETE FROM crossings WHERE race_id = ?", (id,))
            self._con.execute("DELETE FROM pilot_races WHERE race_id = ?", (id,))
            self._con.execute("DELETE FROM races WHERE id = ?", (id,))
            self._con.commit()
        return photos

    def delete_pilot(self, id):
        """Delete a pilot for good: with their quads and profiles, pilot races and crossings.

        Races in which nobody else flew disappear completely; in the others the remaining
        pilots stay. Returns the photos that are not needed anywhere any more.
        """
        with self.lock:
            if not self._query("SELECT id FROM pilots WHERE id = ?", (id,)):
                raise UserError("pilot_not_found")
            pilot_races = [r["id"] for r in self._query("SELECT id FROM pilot_races WHERE pilot_id = ?", (id,))]
            races = {r["race_id"] for r in self._query(
                "SELECT DISTINCT race_id FROM pilot_races WHERE pilot_id = ? AND race_id IS NOT NULL", (id,))}
            quads = [r["id"] for r in self._query("SELECT id FROM quads WHERE pilot_id = ?", (id,))]
            photos = set()
            for pr in pilot_races:
                photos |= {r["photo"] for r in self._query(
                    "SELECT photo FROM crossings WHERE pilot_race_id = ? AND photo IS NOT NULL", (pr,))}
                self._con.execute("DELETE FROM crossings WHERE pilot_race_id = ?", (pr,))
            for q in quads:
                photos |= {r["photo"] for r in self._query(
                    "SELECT photo FROM samples WHERE quad_id = ? AND photo IS NOT NULL", (q,))}
                self._con.execute("DELETE FROM samples WHERE quad_id = ?", (q,))
            self._con.execute("DELETE FROM pilot_races WHERE pilot_id = ?", (id,))
            self._con.execute("DELETE FROM quads WHERE pilot_id = ?", (id,))
            self._con.execute("DELETE FROM pilots WHERE id = ?", (id,))
            for race in races:  # races without other pilots go completely (with unassigned crossings)
                if not self._query("SELECT id FROM pilot_races WHERE race_id = ?", (race,)):
                    photos |= {r["photo"] for r in self._query(
                        "SELECT photo FROM crossings WHERE race_id = ? AND photo IS NOT NULL", (race,))}
                    self._con.execute("DELETE FROM crossings WHERE race_id = ?", (race,))
                    self._con.execute("DELETE FROM races WHERE id = ?", (race,))
            self._con.commit()
            return sorted(photos - self.referenced_photos())

    # ---------------------------------------------------------- statistics & photos

    def pilot_races_with_times(self, track_id, quad_id=None):
        """All pilot races of a track with their valid crossings (for the statistics)."""
        pilot_races = self.pilot_races(track_id=track_id)
        if quad_id is not None:
            pilot_races = [r for r in pilot_races if r["quad_id"] == quad_id]
        with self.lock:
            for r in pilot_races:
                r["times"] = [row[0] for row in self._con.execute(
                    "SELECT t FROM crossings WHERE pilot_race_id = ? AND deleted = 0 ORDER BY t", (r["id"],))]
        return pilot_races

    def referenced_photos(self):
        return {r["photo"] for r in self._query(
            "SELECT photo FROM crossings WHERE photo IS NOT NULL UNION SELECT photo FROM samples WHERE photo IS NOT NULL")}

    def remove_photo(self, name):
        with self.lock:
            self._con.execute("UPDATE crossings SET photo = NULL WHERE photo = ?", (name,))
            self._con.execute("UPDATE samples SET photo = NULL WHERE photo = ?", (name,))
            self._con.commit()
