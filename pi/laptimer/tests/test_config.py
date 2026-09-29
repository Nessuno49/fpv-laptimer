import json
import tempfile
import unittest
from pathlib import Path

from config import Config

# config.json of the German version (September 2026), with invented values
GERMAN = {
    "kamera": "csi",
    "csi": {"fps": 100, "foto_groesse": [1536, 864], "erkennung_groesse": [640, 360], "belichtung_ms": 2.5,
            "gain": 6.0, "fokus_m": 1.5, "drehung": 90, "weissabgleich": [1.5, 2.5]},
    "geraet": 0, "breite": 640, "hoehe": 480, "fps": 30,
    "v4l2": {"power_line_frequency": 1, "auto_exposure": 1, "exposure_dynamic_framerate": 0,
             "exposure_time_absolute": 50, "gain": 100, "focus_automatic_continuous": 0,
             "white_balance_automatic": 0},
    "bereich": [100, 50, 200, 150], "pixel_schwelle": 25, "mindestgroesse": 60, "mindest_rundenzeit": 4.0,
    "foto_monate": 6, "admin_pin": {"salz": "ab", "hash": "cd"}, "admin_geraete": ["abc"],
    "kamera_profile": {"Halle": {"bereich": [1, 2, 3, 4], "pixel_schwelle": 20, "mindestgroesse": 50,
                                 "belichtung_ms": 3.0, "gain": 4.0, "fokus_m": 1.0, "weissabgleich": None,
                                 "drehung": 90, "kamera": "csi", "gespeichert": "2026-09-25T20:15"}},
    "sound_zuordnung": {"countdown": "beep.mp3", "los": "start.mp3", "rekord": "fanfare.mp3"},
    "sprache": {"python": "~/piper-venv/bin/python", "stimmen_ordner": "~/piper-voices"},
    "auswahl": {"track_id": 2, "format": "runden",
                "einstellungen": {"training": {}, "runden": {"runden": 6}, "zeit": {"dauer_s": 120}},
                "teilnehmer": [{"pilot_id": 1, "copter_id": 3}], "vorbereitung_s": 15},
    "ausloese_anteil": 0.02,
    "zuschauer_geheimnis": "s3cret",
}


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "config.json"

    def test_defaults_without_file(self):
        c = Config(self.path)
        self.assertEqual(c.data["selection"]["format"], "laps")
        self.assertFalse(self.path.exists())

    def test_german_config_is_converted_and_saved(self):
        self.path.write_text(json.dumps(GERMAN), encoding="utf-8")
        d = Config(self.path).data
        self.assertEqual(d["camera"], "csi")
        self.assertEqual(d["csi"]["rotation"], 90)
        self.assertEqual(d["csi"]["white_balance"], [1.5, 2.5])
        self.assertEqual(d["csi"]["photo_size"], [1536, 864])
        self.assertEqual(d["webcam"]["v4l2"]["exposure_time_absolute"], 50)
        self.assertEqual((d["webcam"]["device"], d["webcam"]["fps"]), (0, 30))
        self.assertEqual(d["zone"], [100, 50, 200, 150])
        self.assertEqual((d["pixel_threshold"], d["min_size"], d["min_lap_s"]), (25, 60, 4.0))
        self.assertEqual((d["admin_pin"], d["admin_devices"], d["spectator_secret"]),
                         ({"salt": "ab", "hash": "cd"}, ["abc"], "s3cret"))
        self.assertEqual(d["camera_presets"]["Halle"]["zone"], [1, 2, 3, 4])
        self.assertEqual(d["camera_presets"]["Halle"]["rotation"], 90)
        self.assertEqual(d["camera_presets"]["Halle"]["saved"], "2026-09-25T20:15")
        self.assertEqual(d["sound_mapping"], {"countdown": "beep.mp3", "go": "start.mp3",
                                              "record": "fanfare.mp3"})
        self.assertEqual(d["voice"], {"python": "~/piper-venv/bin/python", "voices_dir": "~/piper-voices"})
        self.assertEqual(d["selection"], {
            "track_id": 2, "format": "laps",
            "settings": {"practice": {}, "laps": {"laps": 6}, "timed": {"duration_s": 120}},
            "participants": [{"pilot_id": 1, "quad_id": 3}], "staging_s": 15})
        for german in ("kamera", "geraet", "fps", "v4l2", "bereich", "auswahl", "ausloese_anteil"):
            self.assertNotIn(german, d)
        # the file on disk is English now, and loading it again changes nothing
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved, d)
        self.assertEqual(Config(self.path).data, d)


if __name__ == "__main__":
    unittest.main()
