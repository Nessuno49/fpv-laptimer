"""Statistics per track: categories, leaderboards, records, progress.

Categories:
  "fastest_lap"  - best single lap over all races on the track
  "best_3"       - best 3 consecutive laps over all races
  "<format key>" - result of a format with certain settings,
                   e.g. "laps:10" or "timed:120" (see formats.py)
track_id None = pop-up course: all races without a fixed track, compared with each other.
There are no record callouts for them (rating), because the course is different every time.
The browser turns keys and numbers into text in its own language.
"""
import formats

CROSS_FORMAT = ("fastest_lap", "best_3")
_FORMAT_ORDER = list(formats.FORMATS)


def _value(category, pilot_race):
    """Value of a pilot race in a category (like formats.result) or None."""
    times = pilot_race["times"]
    laps = formats.laps_from_times(times)
    if category == "fastest_lap":
        if not laps:
            return None
        best = min(laps)
        return {"sort_key": (best,), "value": best, "time_s": best, "laps": None, "higher_is_better": False}
    if category == "best_3":
        total = formats.best_consecutive(laps, 3)
        if total is None:
            return None
        return {"sort_key": (total,), "value": total, "time_s": total, "laps": None, "higher_is_better": False}
    settings = formats.check_settings(pilot_race["format"], pilot_race["settings"])
    if formats.category_key(pilot_race["format"], settings) != category:
        return None
    return formats.result(pilot_race["format"], settings, times)


def _values(db, track_id, category, quad_id=None):
    """All pilot races on the track with a value in the category, oldest first."""
    values = []
    for r in db.pilot_races_with_times(track_id, quad_id=quad_id):
        v = _value(category, r)
        if v is not None:
            values.append({**v, "pilot_race_id": r["id"], "race_id": r.get("race_id"), "pilot_id": r["pilot_id"],
                           "pilot": r["pilot"], "date": r["started"]})
    values.sort(key=lambda v: (v["date"], v["pilot_race_id"]))
    return values


def categories(db, track_id, quad_id=None):
    """Cross-format categories first, then one per format + settings (with format and settings for the name)."""
    result = [{"key": k} for k in CROSS_FORMAT]
    found = {}
    for r in db.pilot_races_with_times(track_id, quad_id=quad_id):
        settings = formats.check_settings(r["format"], r["settings"])
        if r["format"] != "practice":
            found[formats.category_key(r["format"], settings)] = (r["format"], settings)
    for key, (format, settings) in sorted(
            found.items(), key=lambda k: (_FORMAT_ORDER.index(k[1][0]), sorted(k[1][1].items()))):
        result.append({"key": key, "format": format, "settings": settings})
    return result


def _best_values(values):
    """Best value per pilot (on a tie the earlier one)."""
    best = {}
    for v in values:  # oldest first -> on a tie the earlier one stays
        before = best.get(v["pilot_id"])
        if before is None or v["sort_key"] < before["sort_key"]:
            best[v["pilot_id"]] = v
    return sorted(best.values(), key=lambda v: (v["sort_key"], v["date"]))


def leaderboard(db, track_id, category, quad_id=None):
    board = []
    for i, v in enumerate(_best_values(_values(db, track_id, category, quad_id))):
        # same value -> same rank
        rank = board[-1]["rank"] if board and board[-1]["_sort_key"] == v["sort_key"] else i + 1
        board.append({"rank": rank, "pilot_id": v["pilot_id"], "pilot": v["pilot"],
                      "time_s": v["time_s"], "laps": v["laps"], "date": v["date"],
                      "pilot_race_id": v["pilot_race_id"], "race_id": v["race_id"], "_sort_key": v["sort_key"]})
    for entry in board:
        del entry["_sort_key"]
    return board


def pilot_records(db, track_id, pilot_id, quad_id=None):
    records = []
    for c in categories(db, track_id, quad_id):
        for entry in leaderboard(db, track_id, c["key"], quad_id):
            if entry["pilot_id"] == pilot_id:
                records.append({"category": c["key"], "format": c.get("format"), "settings": c.get("settings"),
                                "time_s": entry["time_s"], "laps": entry["laps"],
                                "date": entry["date"], "rank": entry["rank"],
                                "pilot_race_id": entry["pilot_race_id"], "race_id": entry["race_id"]})
    return records


def progress(db, track_id, pilot_id, category, quad_id=None):
    points, best = [], None
    values = [v for v in _values(db, track_id, category, quad_id) if v["pilot_id"] == pilot_id]
    for v in values:
        if best is None or v["sort_key"] < best["sort_key"]:
            best = v
        points.append({"date": v["date"], "value": v["value"], "time_s": v["time_s"], "laps": v["laps"],
                       "best": best["value"], "pilot_race_id": v["pilot_race_id"]})
    higher_is_better = values[0]["higher_is_better"] if values else False
    return {"higher_is_better": higher_is_better, "points": points}


def rating(db, pilot_race_id):
    """How does a pilot race do in its format category? record: "track", "personal" or None."""
    empty = {"rank": None, "record": None}
    pilot_race = db.load_pilot_race(pilot_race_id)
    if pilot_race is None or pilot_race["track_id"] is None:
        return empty
    settings = formats.check_settings(pilot_race["format"], pilot_race["settings"])
    category = formats.category_key(pilot_race["format"], settings)
    values = _values(db, pilot_race["track_id"], category)
    this = next((v for v in values if v["pilot_race_id"] == pilot_race_id), None)
    if this is None:
        return empty

    others = [v for v in values if v["pilot_race_id"] != pilot_race_id]
    other_pilots = _best_values([v for v in others if v["pilot_id"] != this["pilot_id"]])
    rank = 1 + sum(1 for v in other_pilots if v["sort_key"] < this["sort_key"])

    if all(this["sort_key"] < v["sort_key"] for v in others):
        record = "track"
    else:
        own = [v for v in others if v["pilot_id"] == this["pilot_id"]]
        record = ("personal"
                  if own and all(this["sort_key"] < v["sort_key"] for v in own)
                  else None)
    return {"rank": rank, "record": record}
