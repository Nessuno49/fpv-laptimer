"""Settings in config.json: camera, detection and the last selection.

Config files from the German version are converted automatically when loaded (see migrate).
"""
import copy
import json
import threading
from pathlib import Path

DEFAULTS = {
    "camera": "csi",                  # "csi" = Camera Module 3 (ribbon cable), "webcam" = USB webcam
    # Camera Module 3
    "csi": {
        "fps": 100,                       # 100 matches the 100 Hz flicker of lamps (every image equally bright)
        "photo_size": [1536, 864],        # the photos of the quads are cut from this
        "detection_size": [640, 360],     # detection runs on this (small = fast; width divisible by 64)
        "exposure_ms": 3.0,               # short = sharp quads, but needs light
        "gain": 4.0,                      # amplification 1–16: more = brighter, but more noise
        "focus_m": 1.3,                   # distance camera–gate in metres (fixed focus, sharp approx. 0.8–2 m)
        "rotation": 0,                    # rotate the image: 0, 90, 180 or 270 degrees (clockwise)
        "white_balance": None,            # [red, blue] – found when calibrating; None = automatic
    },
    # USB webcam
    "webcam": {
        "device": 0,
        "width": 640,
        "height": 480,
        "fps": 30,
        # Camera settings for v4l2-ctl. The order matters:
        # first switch to manual exposure, then set the exposure time.
        "v4l2": {
            "power_line_frequency": 1,          # 50 Hz
            "auto_exposure": 1,                 # manual
            "exposure_dynamic_framerate": 0,    # don't lower the frame rate
            "exposure_time_absolute": 100,      # in 0.1 ms -> 10 ms
            "gain": 50,
            "focus_automatic_continuous": 0,
            "white_balance_automatic": 0,
        },
    },
    "zone": [220, 140, 200, 200],     # detection zone: x, y, width, height in the camera image
    "pixel_threshold": 25,            # brightness change from which a pixel counts as "changed"
    "min_size": 60,                   # an object needs at least this many changed pixels
    "min_lap_s": 3.0,                 # shorter laps count as false triggers (not for the holeshot)
    "photo_months": 6,                # keep photos of races this long
    "admin_pin": None,                # race director PIN (hash only, see access.py); None = not set yet
    "admin_devices": [],              # signed-in race director devices (hashes)
    "camera_presets": {},             # name -> saved location settings (see camera_presets.py)
    "sound_mapping": {},              # event -> file from sounds/, e.g. {"record": "fanfare.mp3"}
    # Voices on the Pi: Python of the Piper environment (with piper-tts) and folder of the Piper voices
    "voice": {
        "python": "~/piper-venv/bin/python",
        "voices_dir": "~/voices",
    },
    # Last chosen in the browser
    "selection": {
        "track_id": None,
        "format": "laps",
        "settings": {},               # per format, e.g. {"laps": {"laps": 5}}
        "participants": [],           # [{"pilot_id": 1, "quad_id": 1}, ...]
        "staging_s": 0,               # time to put on the goggles before the 3-2-1 (0, 15, 30, 45, 60)
    },
}

# ---------------------------------------------------------------- conversion of German config files

_TOP = {"kamera": "camera", "bereich": "zone", "pixel_schwelle": "pixel_threshold", "mindestgroesse": "min_size",
        "mindest_rundenzeit": "min_lap_s", "foto_monate": "photo_months", "admin_geraete": "admin_devices",
        "zuschauer_geheimnis": "spectator_secret", "kamera_profile": "camera_presets",
        "sound_zuordnung": "sound_mapping", "sprache": "voice", "auswahl": "selection"}
_CSI = {"foto_groesse": "photo_size", "erkennung_groesse": "detection_size", "belichtung_ms": "exposure_ms",
        "fokus_m": "focus_m", "drehung": "rotation", "weissabgleich": "white_balance"}
_WEBCAM = {"geraet": "device", "breite": "width", "hoehe": "height", "fps": "fps", "v4l2": "v4l2"}
_PRESET = {**_CSI, "bereich": "zone", "pixel_schwelle": "pixel_threshold", "mindestgroesse": "min_size",
           "kamera": "camera", "gespeichert": "saved"}
_EVENTS = {"los": "go", "runde": "lap", "bestzeit": "best_lap", "letzte_runde": "last_lap", "noch_30": "30s_left",
           "zeit_abgelaufen": "time_up", "ziel": "finish", "rekord": "record", "training": "practice",
           "abbruch": "aborted", "unbekannt": "unassigned"}
_FORMATS = {"training": "practice", "runden": "laps", "zeit": "timed", "beste_n": "consecutive",
            "schnellste": "fastest"}
_SETTINGS = {"runden": "laps", "dauer_s": "duration_s"}


def _rename(d, names):
    return {names.get(k, k): v for k, v in d.items()}


def migrate(data):
    """Converts a config from the German version. Returns (data, changed)."""
    if not any(k in data for k in ("kamera", "auswahl", "bereich", "sprache", "geraet")):
        return data, False
    old = dict(data)
    old.pop("ausloese_anteil", None)  # unused leftover
    webcam = {_WEBCAM[k]: old.pop(k) for k in list(old) if k in _WEBCAM}
    data = _rename(old, _TOP)
    if webcam:
        data["webcam"] = webcam
    if isinstance(data.get("csi"), dict):
        data["csi"] = _rename(data["csi"], _CSI)
    if isinstance(data.get("voice"), dict):
        data["voice"] = _rename(data["voice"], {"stimmen_ordner": "voices_dir"})
    if isinstance(data.get("admin_pin"), dict):
        data["admin_pin"] = _rename(data["admin_pin"], {"salz": "salt"})
    data["camera_presets"] = {name: _rename(p, _PRESET) for name, p in (data.get("camera_presets") or {}).items()}
    data["sound_mapping"] = _rename(data.get("sound_mapping") or {}, _EVENTS)
    if isinstance(data.get("selection"), dict):
        s = _rename(data["selection"], {"einstellungen": "settings", "teilnehmer": "participants",
                                        "vorbereitung_s": "staging_s"})
        s["format"] = _FORMATS.get(s.get("format"), s.get("format"))
        s["settings"] = {_FORMATS.get(f, f): _rename(v, _SETTINGS) if isinstance(v, dict) else v
                         for f, v in (s.get("settings") or {}).items()}
        s["participants"] = [_rename(p, {"copter_id": "quad_id"}) for p in s.get("participants") or []]
        data["selection"] = s
    return data, True


class Config:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        changed = False
        if self.path.exists():
            saved, changed = migrate(json.loads(self.path.read_text(encoding="utf-8")))
            for key, value in saved.items():
                if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                    self.data[key].update(value)
                else:
                    self.data[key] = value
        if changed:
            self.save()

    def save(self):
        with self.lock:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
