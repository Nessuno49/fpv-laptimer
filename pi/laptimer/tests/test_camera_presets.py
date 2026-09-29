import copy
import datetime
import unittest

import camera_presets
from config import DEFAULTS


def csi_config():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["camera"] = "csi"
    cfg["zone"] = [300, 0, 60, 360]
    cfg["pixel_threshold"] = 30
    cfg["csi"].update(exposure_ms=2.5, gain=6.0, focus_m=1.2, white_balance=[1.9, 1.6])
    return cfg


class CameraPresetsTest(unittest.TestCase):
    def test_save_and_load(self):
        cfg = csi_config()
        name = camera_presets.save(cfg, "  Garage   left ", datetime.datetime(2026, 9, 25, 20, 15))
        self.assertEqual(name, "Garage left")  # spaces tidied up
        # the next day everything is changed ...
        cfg["zone"], cfg["pixel_threshold"] = [0, 0, 10, 10], 50
        cfg["csi"].update(exposure_ms=8.0, gain=1.0, focus_m=3.0, white_balance=None)
        # ... loading the preset restores everything
        values = camera_presets.load(cfg, "Garage left")
        self.assertEqual(cfg["zone"], [300, 0, 60, 360])
        self.assertEqual(cfg["pixel_threshold"], 30)
        self.assertEqual(cfg["csi"]["white_balance"], [1.9, 1.6])
        self.assertEqual(values, {"exposure_ms": 2.5, "gain": 6.0, "focus_m": 1.2, "white_balance": [1.9, 1.6],
                                  "rotation": 0})

    def test_rotation_belongs_to_the_preset(self):
        cfg = csi_config()
        cfg["csi"]["rotation"] = 90
        camera_presets.save(cfg, "Portrait")
        cfg["csi"]["rotation"] = 0
        self.assertEqual(camera_presets.load(cfg, "Portrait")["rotation"], 90)
        self.assertEqual(cfg["csi"]["rotation"], 90)

    def test_preset_is_a_copy(self):
        cfg = csi_config()
        camera_presets.save(cfg, "Hall 3")
        cfg["zone"][0] = 999  # a later change must not alter the preset
        self.assertEqual(cfg["camera_presets"]["Hall 3"]["zone"][0], 300)

    def test_automatic_white_balance_is_loaded_too(self):
        cfg = csi_config()
        cfg["csi"]["white_balance"] = None
        camera_presets.save(cfg, "Not calibrated")
        cfg["csi"]["white_balance"] = [2.0, 1.5]
        values = camera_presets.load(cfg, "Not calibrated")
        self.assertIsNone(values["white_balance"])
        self.assertIsNone(cfg["csi"]["white_balance"])

    def test_list_newest_first_and_delete(self):
        cfg = csi_config()
        camera_presets.save(cfg, "Old", datetime.datetime(2026, 1, 1))
        camera_presets.save(cfg, "New", datetime.datetime(2026, 9, 1))
        self.assertEqual([p["name"] for p in camera_presets.list_presets(cfg)], ["New", "Old"])
        camera_presets.delete(cfg, "Old")
        self.assertEqual([p["name"] for p in camera_presets.list_presets(cfg)], ["New"])

    def test_errors(self):
        cfg = csi_config()
        for name in ("", "   ", None, "x" * 41):
            with self.assertRaises(ValueError):
                camera_presets.save(cfg, name)
        with self.assertRaises(ValueError):
            camera_presets.load(cfg, "Does not exist")
        with self.assertRaises(ValueError):
            camera_presets.delete(cfg, "Does not exist")

    def test_webcam(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["camera"] = "webcam"
        cfg["webcam"]["v4l2"].update(exposure_time_absolute=50, gain=100)
        camera_presets.save(cfg, "Webcam")
        cfg["webcam"]["v4l2"].update(exposure_time_absolute=300, gain=10)
        values = camera_presets.load(cfg, "Webcam")
        self.assertEqual(values, {"exposure_ms": 5.0, "gain": 100})
        self.assertEqual(cfg["webcam"]["v4l2"]["exposure_time_absolute"], 50)


if __name__ == "__main__":
    unittest.main()
