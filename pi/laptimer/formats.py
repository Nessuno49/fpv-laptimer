"""Race formats: compute laps, detect the end of a race, evaluate results.

Pure functions without camera or database.
Input is always the sorted list of valid crossings in seconds since "Go".
times[0] is the holeshot, every further crossing completes a lap.

No texts are produced here: the browser formats results in the viewer's language.
"""

FORMATS = {
    "practice": {},                                  # free flying without an end, not saved
    "laps": {"laps": 10},                            # first to X laps
    "timed": {"duration_s": 120},                    # as many laps as possible in X minutes
    "consecutive": {"duration_s": 120, "n": 3},      # fastest N consecutive laps
    "fastest": {"duration_s": 120},                  # fastest single lap
}

LIMITS = {"laps": (1, 99), "duration_s": (30, 600), "n": (2, 10)}


def check_settings(format, settings):
    if format not in FORMATS:
        raise ValueError(f"Unknown format: {format}")
    result = {}
    for name, default in FORMATS[format].items():
        value = int(settings.get(name, default))
        low, high = LIMITS[name]
        result[name] = max(low, min(high, value))
    return result


def laps_from_times(times):
    return [b - a for a, b in zip(times, times[1:])]


def best_consecutive(laps, n):
    if len(laps) < n:
        return None
    return min(sum(laps[i:i + n]) for i in range(len(laps) - n + 1))


def crossing_ends_race(format, settings, times):
    """Does the last crossing in `times` end the race?"""
    if format == "practice":
        return False
    if format == "laps":
        return len(times) - 1 >= settings["laps"]
    # formats with a duration: the first lap that ends after the time is up is the last one
    return len(times) >= 2 and times[-1] >= settings["duration_s"]


def _result(sort_key, value, time_s, laps=None, higher_is_better=False):
    return {"sort_key": sort_key, "value": value, "time_s": time_s, "laps": laps,
            "higher_is_better": higher_is_better}


def result(format, settings, times):
    """Result of a pilot race, or None if there is none.

    "sort_key" is for sorting: smaller is always better.
    "value" is the number for the chart (lap count for timed races).
    "time_s" and "laps" are what the browser displays ("laps" only for timed races).
    """
    laps = laps_from_times(times)
    if format == "practice":
        return None
    if format == "laps":
        x = settings["laps"]
        if len(laps) < x:
            return None
        total = times[x]
        return _result((total,), total, total)
    if not laps:
        return None
    if format == "timed":
        n, total = len(laps), times[-1]
        return _result((-n, total), n, total, laps=n, higher_is_better=True)
    if format == "consecutive":
        total = best_consecutive(laps, settings["n"])
        if total is None:
            return None
        return _result((total,), total, total)
    if format == "fastest":
        best = min(laps)
        return _result((best,), best, best)
    raise ValueError(f"Unknown format: {format}")


def category_key(format, settings):
    """Races with the same key are compared in the statistics."""
    if format == "practice":
        return "practice"
    if format == "laps":
        return f"laps:{settings['laps']}"
    if format == "consecutive":
        return f"consecutive:{settings['duration_s']}:{settings['n']}"
    return f"{format}:{settings['duration_s']}"


def category_from_key(key):
    """Inverse of category_key: (format, settings)."""
    parts = key.split(":")
    format = parts[0]
    if format == "practice":
        return format, {}
    if format == "laps":
        return format, {"laps": int(parts[1])}
    if format == "consecutive":
        return format, {"duration_s": int(parts[1]), "n": int(parts[2])}
    return format, {"duration_s": int(parts[1])}


def live_sort_key(format, settings, times):
    """Order during a running race: smaller = further ahead."""
    laps = laps_from_times(times)
    infinity = float("inf")
    if format in ("consecutive", "fastest"):
        value = best_consecutive(laps, settings["n"]) if format == "consecutive" else (min(laps) if laps else None)
        return (0 if value is not None else 1, value if value is not None else infinity, -len(laps))
    # laps, timed, practice: more laps ahead; on a tie whoever crossed earlier
    return (-len(times), times[-1] if times else infinity)
