"""The race controller: one race with 1–8 participants (pilot + quad).

Gets crossings from the detector, assigns them to a participant
(plausibility + recognition profile), applies the format rules per participant,
saves the race and creates events for the callouts.
tick() must be called regularly (countdown, time limit).

States:
  ready     -> start()  -> [staging] -> countdown (3 s) -> running   (practice: running at once)
               Staging (15–60 s, to put on the goggles) ends with the 3-2-1 countdown;
               skip_staging() jumps straight to the countdown.
  running   -> everyone finished / grace period over / finish() -> finished (saved)
  running   -> abort() / end_practice() -> ready (not saved)
  finished  -> dismiss() -> ready
"""
import datetime
import threading
import time
from dataclasses import dataclass, field

import fingerprint
import formats
import stats
from i18n import UserError

COUNTDOWN_S = 3
STAGING_S = (0, 15, 30, 45, 60)            # selectable staging times (0 = only 3-2-1)
STAGING_CALLOUTS = (60, 45, 30, 15, 10, 5)  # seconds before the start that are called out
GRACE_S = 60
MAX_EVENTS = 200
MAX_PARTICIPANTS = 8
INFINITY = float("inf")
# Two crossings of the same pilot closer than this are physically impossible
# -> detected twice (shadow, flicker). Such assignments are refused.
DUPLICATE_S = 0.5


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _check_gap(t, times):
    """Prevents 0 s laps: a crossing right next to one already counted is a duplicate."""
    nearest = min((abs(t - x) for x in times), default=None)
    if nearest is not None and nearest < DUPLICATE_S:
        raise UserError("crossing_too_close", gap=float(nearest))


@dataclass
class Crossing:
    """Report from the detector: time (time.monotonic), photo name, fingerprint."""
    t: float
    photo: str | None = None
    fingerprint: dict | None = None


@dataclass
class Participant:
    pilot_id: int
    pilot: str
    quad_id: int
    quad: str
    times: list = field(default_factory=list)       # seconds since "go"
    crossings: list = field(default_factory=list)   # {t, photo, uncertain, fingerprint}
    finished: bool = False
    pilot_race_id: int | None = None
    result: dict | None = None
    rating: dict | None = None
    rank: int | None = None


class RaceController:
    def __init__(self, db, clock=time.monotonic, now_iso=_now_iso, min_lap=lambda: 0.0):
        self.db = db
        self.clock = clock
        self.now_iso = now_iso
        # Function returning the current minimum lap time (adjustable in the browser).
        # Shorter laps count as false triggers. It does not apply to the holeshot.
        self.min_lap = min_lap
        self.lock = threading.RLock()
        self.events = []
        self.event_nr = 0
        self._reset()

    # ---------------------------------------------------------------- internal

    def _reset(self):
        self.status = "ready"
        self.format = None
        self.settings = {}
        self.track_id = None
        self.participants = []
        self.unassigned = []     # crossings not assigned {nr, t, photo, fingerprint}
        self.unassigned_nr = 0
        self.last = None         # last crossing, for the photo in the display
        self.go_t = None
        self.go_planned = None   # when "go" will be (during staging and countdown)
        self.started_iso = None

    def _event(self, type, **data):
        self.event_nr += 1
        self.events.append({"nr": self.event_nr, "type": type, **data})
        del self.events[:-MAX_EVENTS]

    def _pilot_event(self, type, p, **data):
        self._event(type, pilot=p.pilot, multiple=len(self.participants) > 1, **data)

    def _practice(self):
        return self.format == "practice"

    def _has_duration(self):
        return self.format in ("timed", "consecutive", "fastest")

    def _count(self, p, rel, photo, uncertain, fp=None):
        p.times.append(rel)
        p.times.sort()
        p.crossings.append({"t": rel, "photo": photo, "uncertain": uncertain, "fingerprint": fp})
        p.crossings.sort(key=lambda c: c["t"])
        laps = formats.laps_from_times(p.times)
        if not laps:
            self._pilot_event("first" if self._practice() else "holeshot", p)
        else:
            nr = len(laps)
            self._pilot_event(
                "lap", p, lap=nr, time=laps[-1],
                best_lap=nr > 1 and laps[-1] <= min(laps),
                last_lap=self.format == "laps" and nr == self.settings["laps"] - 1)
        if formats.crossing_ends_race(self.format, self.settings, p.times):
            p.finished = True
            if len(self.participants) > 1:
                self._pilot_event("finish", p)
            if all(x.finished for x in self.participants):
                self._finish()

    def _finish(self):
        self.status = "finished"
        ended = self.now_iso()
        for p in self.participants:
            p.result = formats.result(self.format, self.settings, p.times)
        has_data = any(p.times for p in self.participants) or self.unassigned
        if has_data:
            race_id = self.db.save_race(self.format, self.settings, self.track_id, self.started_iso, ended)
            for p in self.participants:
                p.pilot_race_id = self.db.save_pilot_race(
                    p.pilot_id, self.track_id, self.format, self.settings, self.started_iso, ended,
                    p.crossings, quad_id=p.quad_id, race_id=race_id)
            if self.unassigned:
                self.db.save_unassigned(
                    race_id, [{"t": u["t"], "photo": u["photo"], "fingerprint": u["fingerprint"]}
                              for u in self.unassigned])
        for p in self.participants:
            p.rating = (stats.rating(self.db, p.pilot_race_id)
                        if p.pilot_race_id and p.result else {"rank": None, "record": None})
        # rank in the race by result; without a result at the back
        order = sorted(self.participants,
                       key=lambda p: (p.result is None, p.result["sort_key"] if p.result else ()))
        for i, p in enumerate(order):
            p.rank = i + 1
        self._event("race_end", multiple=len(self.participants) > 1, results=[
            {"pilot": p.pilot, "time_s": p.result["time_s"] if p.result else None,
             "laps": p.result["laps"] if p.result else None,
             "rank": p.rank, "record": p.rating["record"]} for p in order])

    def _live_order(self):
        if self.status == "finished":
            return sorted(self.participants, key=lambda p: p.rank or 99)
        if self._practice():
            return list(self.participants)
        return sorted(self.participants,
                      key=lambda p: formats.live_sort_key(self.format, self.settings, p.times))

    def _gap(self, p, leader):
        """Gap to the leader: {"laps": n} or {"time_s": x}, or None."""
        if p is leader or not p.times or self._practice():
            return None
        if self.format in ("laps", "timed"):
            difference = len(leader.times) - len(p.times)
            if difference > 0:
                return {"laps": difference}
            return {"time_s": p.times[-1] - leader.times[-1]}
        a = formats.result(self.format, self.settings, p.times)
        b = formats.result(self.format, self.settings, leader.times)
        if a and b:
            return {"time_s": a["value"] - b["value"]}
        return None

    # ---------------------------------------------------------------- inputs

    def start(self, participants, track_id, format, settings, staging_s=0):
        """participants: [(pilot_id, quad_id), ...]; staging_s: time until the start (see STAGING_S)."""
        with self.lock:
            if staging_s not in STAGING_S:
                raise UserError("invalid_staging")
            if self.status not in ("ready", "finished"):
                raise UserError("race_running")
            if not participants:
                raise UserError("no_participants")
            if len(participants) > MAX_PARTICIPANTS:
                raise UserError("too_many_participants", n=MAX_PARTICIPANTS)
            pilots = [p for p, _ in participants]
            if len(set(pilots)) != len(pilots):
                raise UserError("pilot_twice")
            settings = formats.check_settings(format, settings)
            quads = {q["id"]: q for q in self.db.quads(include_archived=True)}
            chosen = []
            for pilot_id, quad_id in participants:
                q = quads.get(quad_id)
                if q is None or q["pilot_id"] != pilot_id:
                    raise UserError("quad_not_of_pilot")
                chosen.append(Participant(pilot_id, q["pilot"], quad_id, q["name"]))
            self._reset()
            self.participants = chosen
            self.format, self.settings, self.track_id = format, settings, track_id
            if self._practice():
                self.status = "running"
                self.go_t = self.clock()
                self.started_iso = self.now_iso()
                self._event("practice")
            else:
                self.said_30_left = False
                self.said_time_up = False
                self.go_planned = self.clock() + max(staging_s, COUNTDOWN_S)
                if staging_s > COUNTDOWN_S:
                    self.status = "staging"
                    self.staging_said = {v for v in STAGING_CALLOUTS if v >= staging_s}
                    self._event("staging", value=staging_s)
                else:
                    self._start_countdown()

    def _start_countdown(self):
        """The last 3 seconds before the start: 3-2-1 beeps."""
        self.status = "countdown"
        self.countdown_start = self.go_planned - COUNTDOWN_S
        self.countdown_step = 0
        self._event("countdown", value=COUNTDOWN_S)

    def skip_staging(self):
        """Cut staging short: straight to the 3-2-1 countdown."""
        with self.lock:
            if self.status == "staging":
                self.go_planned = self.clock() + COUNTDOWN_S
                self._start_countdown()

    def crossing(self, c):
        """Assigns a crossing. Returns {pilot, quad, uncertain} or None if nothing is running."""
        with self.lock:
            if self.status != "running":
                return None
            rel = c.t - self.go_t
            if rel < 0:
                return None
            min_lap = self.min_lap()
            candidates = [p for p in self.participants if not p.finished and
                          (not p.times or rel - p.times[-1] >= min_lap)]

            # 1. Who is it according to the fingerprint – compared with ALL participants?
            recognised = None
            if len(self.participants) > 1 and c.fingerprint:
                profiles = {p.quad_id: self.db.samples(p.quad_id) for p in self.participants}
                quad_id, uncertain = fingerprint.match(c.fingerprint, profiles)
                if not uncertain:
                    recognised = next(p for p in self.participants if p.quad_id == quad_id)

            # 2. Clearly a quad that may not count right now (finished, or just crossed =
            #    duplicate): ignore it, do NOT pass it on to another pilot.
            if recognised is not None and recognised not in candidates:
                self.last = {"pilot": recognised.pilot, "photo": c.photo, "uncertain": False,
                             "t": rel, "ignored": True}
                return {"pilot": recognised.pilot, "quad": recognised.quad, "uncertain": False,
                        "ignored": True}

            if not candidates:
                self.unassigned_nr += 1
                self.unassigned.append({"nr": self.unassigned_nr, "t": rel, "photo": c.photo,
                                        "fingerprint": c.fingerprint})
                self._event("unassigned", multiple=len(self.participants) > 1)
                self.last = {"pilot": None, "photo": c.photo, "uncertain": True, "t": rel}
                return {"pilot": None, "quad": None, "uncertain": True}

            # 3. Assign: clearly recognised > only candidate > best among the candidates
            if recognised is not None:
                p, uncertain = recognised, False
            elif len(candidates) == 1:
                p, uncertain = candidates[0], False
            else:
                profiles = {x.quad_id: self.db.samples(x.quad_id) for x in candidates}
                quad_id, uncertain = fingerprint.match(c.fingerprint, profiles)
                p = next((x for x in candidates if x.quad_id == quad_id), None)
                if p is None:
                    # no fingerprint: whoever has not crossed for the longest time is most likely
                    p = max(candidates, key=lambda x: rel - x.times[-1] if x.times else INFINITY)
                    uncertain = True
            # 4. The profile only learns when it is certain who it was: alone in the race, or the
            #    fingerprint was clear. Never by elimination – otherwise photos of the wrong
            #    quad end up in the profile.
            if c.fingerprint and (len(self.participants) == 1 or recognised is p):
                self.db.add_sample(p.quad_id, c.fingerprint, c.photo)
            self.last = {"pilot": p.pilot, "photo": c.photo, "uncertain": uncertain, "t": rel}
            self._count(p, rel, c.photo, uncertain, c.fingerprint)
            return {"pilot": p.pilot, "quad": p.quad, "uncertain": uncertain}

    def assign_live(self, nr, quad_id):
        with self.lock:
            u = next((x for x in self.unassigned if x["nr"] == nr), None)
            p = next((x for x in self.participants if x.quad_id == quad_id), None)
            if u is None or p is None:
                raise UserError("unassigned_not_found")
            if self.status != "running":
                raise UserError("race_over_assign_in_history")
            _check_gap(u["t"], p.times)
            self.unassigned.remove(u)
            if u["fingerprint"]:
                self.db.add_sample(p.quad_id, u["fingerprint"], u["photo"])
            self._event("assigned", pilot=p.pilot)
            self._count(p, u["t"], u["photo"], False, u["fingerprint"])

    def finish(self):
        with self.lock:
            if self.status != "running" or self._practice():
                raise UserError("no_race_running")
            self._finish()

    def abort(self):
        with self.lock:
            if self.status in ("staging", "countdown", "running"):
                self._reset()
                self._event("aborted")

    def end_practice(self):
        with self.lock:
            if self.status == "running" and self._practice():
                self._reset()
                self._event("practice_end")

    def dismiss(self):
        with self.lock:
            if self.status == "finished":
                self._reset()

    def tick(self):
        with self.lock:
            now = self.clock()
            if self.status == "staging":
                left = self.go_planned - now
                for value in STAGING_CALLOUTS:
                    if value not in self.staging_said and left <= value:
                        self.staging_said.add(value)
                        if left > value - 1:  # late (e.g. after a hang): better say nothing outdated
                            self._event("staging", value=value)
                if left <= COUNTDOWN_S:
                    self._start_countdown()
            if self.status == "countdown":
                elapsed = now - self.countdown_start
                while self.countdown_step + 1 <= min(elapsed, COUNTDOWN_S - 1):
                    self.countdown_step += 1
                    self._event("countdown", value=COUNTDOWN_S - self.countdown_step)
                if elapsed >= COUNTDOWN_S:
                    self.status = "running"
                    self.go_t = self.countdown_start + COUNTDOWN_S
                    self.started_iso = self.now_iso()
                    self._event("go")
            elif self.status == "running" and self._has_duration():
                rel = now - self.go_t
                duration = self.settings["duration_s"]
                if duration > 30 and not self.said_30_left and rel >= duration - 30:
                    self.said_30_left = True
                    self._event("30s_left")
                if not self.said_time_up and rel >= duration:
                    self.said_time_up = True
                    self._event("time_up")
                active = [p for p in self.participants if not p.finished]
                latest = max([duration] + [p.times[-1] for p in active if p.times])
                if rel >= latest + GRACE_S:
                    self._finish()

    # ---------------------------------------------------------------- outputs

    def events_since(self, nr):
        with self.lock:
            return self.event_nr, [e for e in self.events if e["nr"] > nr]

    def state(self):
        with self.lock:
            now = self.clock()
            running = self.status == "running"
            race_time = now - self.go_t if running else None
            remaining = (max(0.0, self.settings["duration_s"] - race_time)
                         if race_time is not None and self._has_duration() else None)
            order = self._live_order()
            leader = order[0] if order else None
            participants = []
            for i, p in enumerate(order):
                laps = formats.laps_from_times(p.times)
                participants.append({
                    "pilot_id": p.pilot_id, "pilot": p.pilot,
                    "quad_id": p.quad_id, "quad": p.quad,
                    "laps": laps,
                    "best": min(laps) if laps else None,
                    "holeshot_s": p.times[0] if p.times and not self._practice() else None,
                    "started": bool(p.times),
                    "since_last_s": now - self.go_t - p.times[-1] if running and p.times else None,
                    "finished": p.finished,
                    "rank": p.rank if self.status == "finished" else i + 1,
                    "gap": self._gap(p, leader),
                    "result": p.result,
                    "rating": p.rating,
                    "pilot_race_id": p.pilot_race_id,
                })
            return {
                "status": self.status,
                "format": self.format,
                "settings": self.settings,
                "track_id": self.track_id,
                "countdown": COUNTDOWN_S - self.countdown_step if self.status == "countdown" else None,
                "staging_s": max(0.0, self.go_planned - now) if self.status == "staging" else None,
                "race_time_s": race_time,
                "remaining_s": remaining,
                "participants": participants,
                "unassigned": [{"nr": u["nr"], "t": u["t"], "photo": u["photo"]} for u in self.unassigned],
                "last": self.last,
            }
