"""Web server: JSON interface for the UI, live image, photos, static files."""
import collections
import datetime
import http.cookies
import json
import re
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import access
import camera
import camera_presets
import formats
import i18n
import stats
import system
from database import ALL
from i18n import UserError
from race import DUPLICATE_S

WEB_FOLDER = Path(__file__).resolve().parent / "web"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".jpg": "image/jpeg",
                 ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg"}
# Events you can assign your own sound to (see SOUNDS in web/app.js)
SOUND_EVENTS = {"countdown", "go", "holeshot", "lap", "best_lap", "last_lap", "30s_left",
                "time_up", "finish", "record", "practice", "aborted", "unassigned"}


def _id(value):
    """'' / None / 'none' -> None, otherwise int."""
    if value in (None, "", "none", "null"):
        return None
    return int(value)


class App:
    """Everything the web server needs."""

    def __init__(self, config, db, race, photos, sounds, speech=None):
        self.config = config
        self.db = db
        self.race = race           # race.RaceController
        self.photos = photos
        self.sounds = sounds       # sound library (sounds.Library)
        self.access = access.Access(config)  # sign-in: race director (PIN) / spectator
        self.local_is_race_director = True   # requests from the Pi itself (e.g. pin.py) may do everything
        self.speech = speech       # voices on the Pi (speech.Speech), None = browser only
        self.detector = None       # set after creating it
        self.camera = None         # camera.Csi / camera.Webcam, set after creating it
        self.recent = collections.deque(maxlen=10)  # recent crossings for the camera tab

    def crossing(self, c):
        """Callback of the detector: hand to the race controller and remember for the display."""
        info = self.race.crossing(c)
        self.recent.appendleft({
            "photo": c.photo,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "pilot": info["pilot"] if info else None,
            "uncertain": info["uncertain"] if info else False,
            "counted": info is not None and not info.get("ignored"),
            "ignored": bool(info and info.get("ignored")),
        })


class Handler(BaseHTTPRequestHandler):
    app = None  # set at start

    def log_message(self, *args):
        pass  # no access logs on the console

    # ------------------------------------------------------------ helpers

    def respond(self, code, content, type="application/json", cache=False, cookie=None):
        if type == "application/json" and not isinstance(content, (str, bytes)):
            content = json.dumps(content)
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.send_response(code)
        self.send_header("Content-Type", type)
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def raw_body(self):
        """The data sent along with the request (read only once)."""
        if self._raw_body is None:
            self._raw_body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        return self._raw_body

    def body(self):
        return json.loads(self.raw_body() or b"{}")

    def language(self):
        """Language of the requesting device (the UI sends X-Language, otherwise the browser's language)."""
        return i18n.language(self.headers.get("X-Language") or self.headers.get("Accept-Language"))

    def token(self):
        """The sign-in token from the cookie (or None)."""
        cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return cookies[COOKIE].value if COOKIE in cookies else None

    def role(self):
        """access.RACE_DIRECTOR, access.SPECTATOR or None (not signed in)."""
        if self.app.local_is_race_director and self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return access.RACE_DIRECTOR
        return self.app.access.role(self.token())

    def is_admin(self):
        return self.role() == access.RACE_DIRECTOR

    def dispatch(self, routes, changes=False):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        lang = self.language()
        self._raw_body = None
        try:
            self._dispatch(routes, changes, url, query, lang)
        finally:
            # Always read what was sent along, even if the command didn't need it: closing a connection
            # with unread data resets it, and the browser may then get an error instead of the answer.
            try:
                self.raw_body()
            except OSError:
                pass

    def _dispatch(self, routes, changes, url, query, lang):
        for pattern, function in routes:
            match = re.fullmatch(pattern, url.path)
            if match:
                # Without signing in only the login page; spectators may not change anything and not
                # look into the camera
                if function not in WITHOUT_SIGN_IN:
                    role = self.role()
                    refused = None
                    if role is None:
                        refused = 401, {"error": i18n.text("sign_in", lang), "sign_in": True}
                    elif role == access.SPECTATOR and (
                            (function not in SPECTATOR_CHANGES) if changes else (function in RACE_DIRECTOR_READS)):
                        refused = 403, {"error": i18n.text("race_director_only", lang)}
                    if refused:
                        # Read the data sent along first – otherwise the operating system aborts the
                        # connection hard and the browser never gets the error message
                        self.raw_body()
                        self.respond(*refused)
                        return
                try:
                    result = function(self, query, *match.groups())
                    if result is not None:
                        self.respond(200, result)
                except UserError as e:
                    self.respond(400, {"error": e.text(lang)})
                except ValueError as e:
                    self.respond(400, {"error": str(e)})
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
        self.respond(404, {"error": i18n.text("not_found", lang)})

    def do_GET(self):
        path = urlparse(self.path).path
        if path in CAPTIVE_CHECKS or self.headers.get("Host", "").split(":")[0] in CAPTIVE_HOSTS:
            self.to_start_page()
            return
        self.dispatch(GET_ROUTES)

    def to_start_page(self):
        """After joining a Wi-Fi, phones check whether they reach the internet. If they get a redirect
        instead of the expected answer, they take the Wi-Fi for a "sign-in Wi-Fi" (like in a hotel)
        and open the page by themselves – here: the lap timer."""
        ip, port = self.connection.getsockname()[:2]
        ip = ip.removeprefix("::ffff:")                   # IPv4 over an IPv6 socket
        if ":" in ip:
            ip = f"[{ip}]"
        target = f"http://{ip}{'' if port == 80 else f':{port}'}/"
        print(f"Captive portal check from {self.client_address[0]}: {self.headers.get('Host')}{self.path} -> {target}",
              flush=True)
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        self.dispatch(POST_ROUTES, changes=True)

    # ------------------------------------------------------------ sign-in

    def session(self, query):
        """For the login page: am I signed in? Is there a race director PIN yet?"""
        return {"role": self.role(), "pin_set": self.app.access.pin_set()}

    def sign_in(self, query):
        token = self.app.access.sign_in(self.body().get("pin"))
        self.respond(200, {}, cookie=_cookie(token))

    def spectator(self, query):
        self.respond(200, {}, cookie=_cookie(self.app.access.spectator()))

    def sign_out(self, query):
        self.app.access.sign_out(self.token())
        self.respond(200, {}, cookie=_cookie(""))

    def set_pin(self, query):
        token = self.app.access.set_pin(self.body().get("pin"))
        self.respond(200, {}, cookie=_cookie(token))

    # ------------------------------------------------------------ files

    def file(self, query, name="index.html"):
        path = (WEB_FOLDER / name).resolve()
        if path.parent != WEB_FOLDER or not path.is_file():
            raise UserError("not_found")
        self.respond(200, path.read_bytes(), CONTENT_TYPES.get(path.suffix, "application/octet-stream"))

    def sound_file(self, query, name):
        path = self.app.sounds.path(name)
        self.respond(200, path.read_bytes(), CONTENT_TYPES[path.suffix.lower()])

    def sounds(self, query):
        """All files of the library and which file plays for which event."""
        with self.app.config.lock:
            mapping = dict(self.app.config.data["sound_mapping"])
        return {"files": self.app.sounds.list(), "mapping": mapping}

    def sound_map(self, query):
        d = self.body()
        event, file = d.get("event"), d.get("file") or None
        if event not in SOUND_EVENTS:
            raise UserError("unknown_event")
        if file is not None:
            self.app.sounds.path(file)  # does the file exist?
        with self.app.config.lock:
            mapping = self.app.config.data["sound_mapping"]
            if file is None:
                mapping.pop(event, None)
            else:
                mapping[event] = file
            self.app.config.save()
        return {}

    def sound_upload(self, query):
        from sounds import MAX_BYTES
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BYTES:
            raise UserError("sound_too_big", mb=MAX_BYTES // (1024 * 1024))
        return {"file": self.app.sounds.save(query.get("name", ""), self.raw_body())}

    def sound_delete(self, query):
        file = self.body().get("file", "")
        self.app.sounds.delete(file)
        with self.app.config.lock:  # mappings to this file go back to "built-in"
            mapping = self.app.config.data["sound_mapping"]
            for event in [e for e, f in mapping.items() if f == file]:
                del mapping[event]
            self.app.config.save()
        return {}

    # ------------------------------------------------------------ voices on the Pi

    def _speech(self):
        if self.app.speech is None:
            raise UserError("no_pi_voices")
        return self.app.speech

    def voices(self, query):
        return {"voices": self.app.speech.voices() if self.app.speech else []}

    def voice_status(self, query):
        return self._speech().status(query.get("voice", ""))

    def voice_prepare(self, query):
        self._speech().prepare(self.body().get("voice", ""))
        return {}

    def speech_parts(self, query):
        return {"parts": self._speech().parts(query.get("voice", ""), query.get("text", "")[:300],
                                              whole=query.get("whole") == "1")}

    def speech_file(self, query, folder, file):
        path = self._speech().file_path(folder, file)
        self.respond(200, path.read_bytes(), CONTENT_TYPES[path.suffix], cache=True)

    def photo(self, query, name):
        try:
            data = self.app.photos.read(name)  # from the SD card or from memory
        except ValueError:
            raise UserError("photo_not_found") from None
        if data is None:
            self.respond(404, {"error": i18n.text("photo_expired", self.language())})
            return
        self.respond(200, data, "image/jpeg", cache=True)

    def stream(self, query):
        """Live image as MJPEG: an endless sequence of JPEG images."""
        import cv2  # only load here: everything else also runs without OpenCV (tests on the PC)
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        while True:
            preview = self.app.detector.preview() if self.app.detector else None
            if preview is None:
                time.sleep(0.1)
                continue
            image, mask, (x, y, w, h), boxes = preview
            # changed pixels red, detection zone green, detected objects yellow
            if mask is not None and mask.shape == (h, w):
                image[y:y + h, x:x + w][mask] = (0, 0, 255)
            cv2.rectangle(image, (x, y), (x + w - 1, y + h - 1), (0, 200, 0), 2)
            for nr, (bx, by, bw, bh) in boxes:
                cv2.rectangle(image, (bx, by), (bx + bw, by + bh), (0, 220, 255), 2)
                cv2.putText(image, str(nr), (bx, max(12, by - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (0, 220, 255), 1, cv2.LINE_AA)
            ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                self.wfile.write(jpg.tobytes())
                self.wfile.write(b"\r\n")
            time.sleep(1 / 15)  # a preview at 15 fps is enough and saves computing time

    # ------------------------------------------------------------ state

    def state(self, query):
        app = self.app
        since = int(query.get("since", -1))
        nr, events = app.race.events_since(max(since, 0))
        if since < 0:
            events = []  # browser just opened: don't catch up on old callouts
        det = app.detector
        with app.config.lock:
            cfg = app.config.data
            exposure_ms, gain = _exposure(cfg)
            csi = cfg.get("camera") == "csi"
            camera_info = {
                "kind": cfg.get("camera", "webcam"),
                "fps": round(det.fps, 1) if det else 0,
                "lost": round(getattr(det, "lost", 0.0), 3) if det else 0,
                "share": det.share if det else 0,
                "time_source": det.time_source if det else "–",
                "zone": cfg["zone"],
                "pixel_threshold": cfg["pixel_threshold"],
                "min_size": cfg["min_size"],
                "exposure_ms": exposure_ms,
                "gain": gain,
                "focus_m": cfg["csi"].get("focus_m") if csi else None,
                "rotation": cfg["csi"].get("rotation", 0) if csi else None,
                "limits": app.camera.limits if app.camera else {},
                "actual": app.camera.actual() if app.camera and hasattr(app.camera, "actual") else None,
            }
            settings = {"min_lap_s": cfg["min_lap_s"], "photo_months": cfg["photo_months"]}
            selection = json.loads(json.dumps(cfg["selection"]))
        role = {"admin": self.is_admin(), "pin_set": app.access.pin_set()}  # for the UI
        return {"race": app.race.state(), "event_nr": nr, "events": events, "role": role,
                "camera": camera_info, "settings": settings, "selection": selection,
                "recent_crossings": list(app.recent)}

    def formats_list(self, query):
        return [{"format": f, "defaults": defaults, "limits": {k: formats.LIMITS[k] for k in defaults}}
                for f, defaults in formats.FORMATS.items()]

    # ------------------------------------------------------------ race

    def _remember_selection(self, data):
        with self.app.config.lock:
            selection = self.app.config.data["selection"]
            for key in ("track_id", "format", "participants", "staging_s"):
                if key in data:
                    selection[key] = data[key]
            if "settings" in data and data.get("format"):
                selection.setdefault("settings", {})[data["format"]] = data["settings"]
            self.app.config.save()

    def selection(self, query):
        self._remember_selection(self.body())
        return {}

    def race_start(self, query):
        data = self.body()
        self._remember_selection(data)
        participants = [(int(p["pilot_id"]), int(p["quad_id"])) for p in data.get("participants", [])
                        if p.get("pilot_id") and p.get("quad_id")]
        self.app.race.start(participants, _id(data.get("track_id")), data.get("format"),
                            data.get("settings") or {}, staging_s=int(data.get("staging_s") or 0))
        return {}

    def race_command(self, query, command):
        getattr(self.app.race, command)()
        return {}

    def race_assign(self, query):
        d = self.body()
        self.app.race.assign_live(int(d["nr"]), int(d["quad_id"]))
        return {}

    # ------------------------------------------------------------ pilots, quads, tracks

    def pilots(self, query):
        return self.app.db.pilots(include_archived=query.get("all") == "1")

    def _prepare_names(self):
        if self.app.speech:
            self.app.speech.prepare_names()  # generate the names for the Pi voices

    def add_pilot(self, query):
        id = self.app.db.add_pilot(self.body().get("name", ""))
        self._prepare_names()
        return {"id": id}

    def update_pilot(self, query, id):
        d = self.body()
        self.app.db.update_pilot(int(id), name=d.get("name"), archived=d.get("archived"))
        if d.get("name"):
            self._prepare_names()
        return {}

    def quads(self, query):
        return self.app.db.quads(pilot_id=_id(query.get("pilot")), include_archived=query.get("all") == "1")

    def add_quad(self, query):
        d = self.body()
        return {"id": self.app.db.add_quad(int(d["pilot_id"]), d.get("name", ""))}

    def update_quad(self, query, id):
        d = self.body()
        self.app.db.update_quad(int(id), name=d.get("name"), archived=d.get("archived"))
        return {}

    def quad_profile(self, query, id):
        return self.app.db.profile_info(int(id))

    def quad_profile_clear(self, query, id):
        self.app.db.clear_samples(int(id))
        return {}

    def tracks(self, query):
        return self.app.db.tracks(include_archived=query.get("all") == "1")

    def add_track(self, query):
        d = self.body()
        return {"id": self.app.db.add_track(d.get("name", ""), d.get("description", ""))}

    def update_track(self, query, id):
        d = self.body()
        self.app.db.update_track(int(id), name=d.get("name"), description=d.get("description"),
                                 archived=d.get("archived"))
        return {}

    # ------------------------------------------------------------ race history

    def races(self, query):
        track = query.get("track", "")
        return self.app.db.races(pilot_id=_id(query.get("pilot")), track_id=ALL if track == "" else _id(track))

    def race_detail(self, query, id):
        race = self.app.db.load_race(int(id))
        if race is None:
            raise UserError("not_found")
        for r in race["pilot_races"]:
            previous = None
            for c in r["crossings"]:
                c["lap"] = None
                if not c["deleted"]:
                    if previous is not None:
                        c["lap"] = c["t"] - previous
                    previous = c["t"]
            times = [c["t"] for c in r["crossings"] if not c["deleted"]]
            r["laps"] = formats.laps_from_times(times)
            r["best_lap"] = min(r["laps"]) if r["laps"] else None
            r["holeshot_s"] = times[0] if times else None
            r["result"] = formats.result(r["format"], r["settings"], times)
        # ranking like at the end of the race; without a result at the back
        ranked = sorted(race["pilot_races"],
                        key=lambda r: (r["result"] is None, r["result"]["sort_key"] if r["result"] else ()))
        for i, r in enumerate(ranked):
            r["rank"] = i + 1
        return race

    def update_race(self, query, id):
        d = self.body()
        if "track_id" in d:
            self.app.db.update_race(int(id), _id(d["track_id"]))
        return {}

    def delete_race(self, query, id):
        self.app.photos.delete(self.app.db.delete_race(int(id)))
        return {}

    def delete_pilot(self, query, id):
        """Delete a pilot for good – only with the race director PIN."""
        self._not_during_race()
        app = self.app
        app.access.check_pin(self.body().get("pin"))
        photos = app.db.delete_pilot(int(id))
        app.photos.delete(photos)
        with app.config.lock:  # also remove from the remembered participant selection
            selection = app.config.data["selection"]
            selection["participants"] = [p for p in selection.get("participants", [])
                                         if p.get("pilot_id") != int(id)]
            app.config.save()
        return {"photos": len(photos)}

    def crossing(self, query, id, action):
        if action == "assign":
            self.app.db.assign_crossing(int(id), int(self.body()["pilot_id"]), min_gap=DUPLICATE_S)
        else:
            self.app.db.mark_crossing(int(id), action == "delete")
        return {}

    def reassign_pilot_race(self, query, id):
        self.app.db.reassign_pilot_race(int(id), int(self.body()["pilot_id"]))
        return {}

    # ------------------------------------------------------------ statistics

    def _stats(self, query):
        """track=<id> or track=none (pop-up course: races without a fixed track)."""
        return _id(query["track"]), _id(query.get("quad"))

    def stats_categories(self, query):
        track, quad = self._stats(query)
        return stats.categories(self.app.db, track, quad)

    def stats_leaderboard(self, query):
        track, quad = self._stats(query)
        return stats.leaderboard(self.app.db, track, query["category"], quad)

    def stats_pilot(self, query):
        track, quad = self._stats(query)
        return stats.pilot_records(self.app.db, track, int(query["pilot"]), quad)

    def stats_progress(self, query):
        track, quad = self._stats(query)
        return stats.progress(self.app.db, track, int(query["pilot"]), query["category"], quad)

    # ------------------------------------------------------------ switch off the Pi

    def system_command(self, query, action):
        self._not_during_race()
        system.run(action)
        return {}

    def hotspot_password(self, query):
        """New password for the hotspot. Not during a race: the hotspot restarts and all phones drop out."""
        self._not_during_race()
        system.set_hotspot_password(self.body().get("password"))
        return {}

    def _not_during_race(self):
        if self.app.race.state()["status"] in ("countdown", "running"):
            raise UserError("finish_race_first")

    # ------------------------------------------------------------ camera

    def camera_presets(self, query):
        with self.app.config.lock:
            return camera_presets.list_presets(self.app.config.data)

    def camera_preset_save(self, query):
        with self.app.config.lock:
            name = camera_presets.save(self.app.config.data, self.body().get("name"))
            self.app.config.save()
        return {"name": name}

    def camera_preset_load(self, query):
        self._not_during_race()
        app = self.app
        with app.config.lock:
            camera_values = camera_presets.load(app.config.data, self.body().get("name"))
            app.config.save()
        if app.camera:
            app.camera.adjust(**camera_values)
        if app.detector:
            app.detector.relearn()
        return {}

    def camera_preset_delete(self, query):
        with self.app.config.lock:
            camera_presets.delete(self.app.config.data, self.body().get("name"))
            self.app.config.save()
        return {}

    def camera_rotate(self, query):
        """Rotate the image by another 90° clockwise (0 → 90 → 180 → 270 → 0)."""
        self._not_during_race()
        app = self.app
        if not hasattr(app.camera, "set_rotation"):
            raise UserError("csi_only")
        with app.config.lock:
            cfg = app.config.data
            old = cfg["csi"].get("rotation", 0)
            new = (old + 90) % 360
            width, height = cfg["csi"]["detection_size"]
            if old in (90, 270):  # the zone lies in the rotated (portrait) image
                width, height = height, width
            cfg["zone"] = camera.rotate_zone(cfg["zone"], width, height, 1)
            cfg["csi"]["rotation"] = new
            app.config.save()
        app.camera.set_rotation(new)
        if app.detector:
            app.detector.relearn()
        return {"rotation": new}

    def camera_calibrate(self, query):
        app = self.app
        if not hasattr(app.camera, "calibrate"):
            raise UserError("csi_only")
        self._not_during_race()
        values = app.camera.calibrate()
        with app.config.lock:
            app.config.data["csi"].update(values)
            app.config.save()
        if app.detector:
            app.detector.relearn()  # the brightness has changed
        return values

    # ------------------------------------------------------------ settings

    def settings(self, query):
        data = self.body()
        app = self.app
        camera_values = {}
        with app.config.lock:
            cfg = app.config.data
            if "zone" in data:
                cfg["zone"] = [int(v) for v in data["zone"]]
            for name in ("pixel_threshold", "min_lap_s", "photo_months"):
                if name in data:
                    cfg[name] = float(data[name])
            if "min_size" in data:
                cfg["min_size"] = int(data["min_size"])
            for name in ("exposure_ms", "gain"):
                if name in data:
                    camera_values[name] = float(data[name])
            if camera_values:
                _remember_exposure(cfg, **camera_values)
            if "focus_m" in data and cfg.get("camera") == "csi":
                cfg["csi"]["focus_m"] = camera_values["focus_m"] = float(data["focus_m"])
            app.config.save()
        if camera_values and app.camera:
            app.camera.adjust(**camera_values)
        if app.detector and ("zone" in data or camera_values):
            app.detector.relearn()
        return {}


COOKIE = "laptimer"

# Addresses phones and computers use to check whether they reach the internet (captive portal detection)
CAPTIVE_CHECKS = {
    "/generate_204", "/gen_204",                       # Android, Chrome
    "/hotspot-detect.html", "/library/test/success.html",  # Apple
    "/connecttest.txt", "/ncsi.txt", "/redirect",      # Windows
    "/success.txt", "/canonical.html",                 # Firefox
}
CAPTIVE_HOSTS = {"captive.apple.com", "connectivitycheck.gstatic.com", "clients3.google.com",
                 "www.msftconnecttest.com", "detectportal.firefox.com"}


def _cookie(token):
    """Set-Cookie for the sign-in token (empty = delete). Lasts a year."""
    age = 365 * 24 * 3600 if token else 0
    return f"{COOKIE}={token}; Path=/; Max-Age={age}; HttpOnly; SameSite=Strict"


def _exposure(cfg):
    """(exposure in ms, gain) of the configured camera from the config."""
    if cfg.get("camera") == "csi":
        return cfg["csi"]["exposure_ms"], cfg["csi"]["gain"]
    v4l2 = cfg["webcam"]["v4l2"]
    return v4l2["exposure_time_absolute"] / 10, v4l2["gain"]


def _remember_exposure(cfg, exposure_ms=None, gain=None):
    if cfg.get("camera") == "csi":
        if exposure_ms is not None:
            cfg["csi"]["exposure_ms"] = exposure_ms
        if gain is not None:
            cfg["csi"]["gain"] = gain
    else:
        v4l2 = cfg["webcam"]["v4l2"]
        if exposure_ms is not None:
            v4l2["exposure_time_absolute"] = max(1, round(exposure_ms * 10))
        if gain is not None:
            v4l2["gain"] = int(gain)


GET_ROUTES = [
    (r"/", Handler.file),
    (r"/([\w.-]+\.(?:js|css|html|svg))", Handler.file),
    (r"/sounds/([\w.-]+)", Handler.sound_file),
    (r"/speech/([\w.-]+)/([0-9a-f]{16}\.wav)", Handler.speech_file),
    (r"/photos/(\d{4}-\d{2}-\d{2}/[\w-]+\.jpg)", Handler.photo),
    (r"/stream\.mjpg", Handler.stream),
    (r"/api/sounds", Handler.sounds),
    (r"/api/session", Handler.session),
    (r"/api/voices", Handler.voices),
    (r"/api/voices/status", Handler.voice_status),
    (r"/api/speech", Handler.speech_parts),
    (r"/api/state", Handler.state),
    (r"/api/formats", Handler.formats_list),
    (r"/api/pilots", Handler.pilots),
    (r"/api/quads", Handler.quads),
    (r"/api/quads/(\d+)/profile", Handler.quad_profile),
    (r"/api/tracks", Handler.tracks),
    (r"/api/races", Handler.races),
    (r"/api/races/(\d+)", Handler.race_detail),
    (r"/api/camera/presets", Handler.camera_presets),
    (r"/api/stats/categories", Handler.stats_categories),
    (r"/api/stats/leaderboard", Handler.stats_leaderboard),
    (r"/api/stats/pilot", Handler.stats_pilot),
    (r"/api/stats/progress", Handler.stats_progress),
]

POST_ROUTES = [
    (r"/api/selection", Handler.selection),
    (r"/api/race/start", Handler.race_start),
    (r"/api/race/(finish|abort|dismiss|end_practice|skip_staging)", Handler.race_command),
    (r"/api/race/assign", Handler.race_assign),
    (r"/api/pilots", Handler.add_pilot),
    (r"/api/pilots/(\d+)", Handler.update_pilot),
    (r"/api/quads", Handler.add_quad),
    (r"/api/quads/(\d+)", Handler.update_quad),
    (r"/api/quads/(\d+)/clear_profile", Handler.quad_profile_clear),
    (r"/api/tracks", Handler.add_track),
    (r"/api/tracks/(\d+)", Handler.update_track),
    (r"/api/races/(\d+)", Handler.update_race),
    (r"/api/races/(\d+)/delete", Handler.delete_race),
    (r"/api/pilots/(\d+)/delete", Handler.delete_pilot),
    (r"/api/crossings/(\d+)/(delete|restore|assign)", Handler.crossing),
    (r"/api/pilot_races/(\d+)", Handler.reassign_pilot_race),
    (r"/api/settings", Handler.settings),
    (r"/api/sounds/map", Handler.sound_map),
    (r"/api/sounds/upload", Handler.sound_upload),
    (r"/api/sounds/delete", Handler.sound_delete),
    (r"/api/voices/prepare", Handler.voice_prepare),
    (r"/api/system/(shutdown|reboot)", Handler.system_command),
    (r"/api/hotspot/password", Handler.hotspot_password),
    (r"/api/camera/calibrate", Handler.camera_calibrate),
    (r"/api/camera/rotate", Handler.camera_rotate),
    (r"/api/camera/presets", Handler.camera_preset_save),
    (r"/api/camera/presets/load", Handler.camera_preset_load),
    (r"/api/camera/presets/delete", Handler.camera_preset_delete),
    (r"/api/sign_in", Handler.sign_in),
    (r"/api/spectator", Handler.spectator),
    (r"/api/sign_out", Handler.sign_out),
    (r"/api/pin", Handler.set_pin),
]

# Without signing in: only the page itself (HTML/JS/CSS) and signing in
WITHOUT_SIGN_IN = {Handler.file, Handler.session, Handler.sign_in, Handler.spectator, Handler.sign_out}
# Spectators: read everything except camera, change only what concerns their own device
SPECTATOR_CHANGES = {Handler.voice_prepare}
RACE_DIRECTOR_READS = {Handler.stream, Handler.camera_presets, Handler.quad_profile,
                       Handler.races, Handler.race_detail}  # camera and race history


class DualStackServer(ThreadingHTTPServer):
    """Web server listening on IPv6 and IPv4 at the same time.

    Windows often resolves "laptimer.local" to the IPv6 address only.
    """
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def start(app, port):
    Handler.app = app
    return DualStackServer(("::", port), Handler)
