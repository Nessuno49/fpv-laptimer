"""Camera Module 3 (camera.Csi) with a simulated picamera2. Skipped without OpenCV."""
import time
import types
import unittest

import numpy as np

try:
    import cv2  # noqa: F401
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

CFG = {"fps": 100, "photo_size": [1536, 864], "detection_size": [640, 360],
       "exposure_ms": 3.0, "gain": 4.0, "focus_m": 1.0}


class FakeRequest:
    def __init__(self, ts_ns, camera):
        self.ts_ns, self.camera = ts_ns, camera
        self.arrays = {"lores": np.zeros((540, 640), np.uint8),          # YUV420: 360 * 1.5 rows
                       "main": np.zeros((864, 1536, 3), np.uint8)}

    def get_metadata(self):
        return {"SensorTimestamp": self.ts_ns}

    def make_array(self, name):
        self.camera.copied.append(name)
        return self.arrays[name].copy()

    def release(self):
        self.camera.released += 1


class FakeCamera:
    def __init__(self):
        self.camera_controls = {}      # no noise/focus controls -> libcamera is not needed
        self.set, self.released, self.running, self.copied = [], 0, False, []
        self.timestamps = []

    def create_video_configuration(self, **kw):
        return kw

    def configure(self, config):
        self.config = config

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def close(self):
        pass

    def set_controls(self, c):
        self.set.append(c)

    def capture_request(self):
        return FakeRequest(self.timestamps.pop(0), self)


@unittest.skipUnless(HAS_OPENCV, "OpenCV not installed")
class RotateTest(unittest.TestCase):
    def test_rotate_image_clockwise(self):
        import camera
        image = np.zeros((2, 3), np.uint8)
        image[0, 2] = 9                                   # top right
        self.assertEqual(camera.rotate(image, 0).shape, (2, 3))
        rotated = camera.rotate(image, 90)
        self.assertEqual(rotated.shape, (3, 2))
        self.assertEqual(rotated[2, 1], 9)                # top right -> bottom right
        self.assertEqual(camera.rotate(image, 180)[1, 0], 9)
        self.assertEqual(camera.rotate(image, 270)[0, 0], 9)

    def test_zone_rotates_along(self):
        import camera
        # 640x360 image, zone at the top left 100x50 from (10, 20)
        z90 = camera.rotate_zone([10, 20, 100, 50], 640, 360, 1)
        self.assertEqual(z90, [360 - 70, 10, 50, 100])   # in the 360x640 image at the top right
        # four rotations = as before
        z = [10, 20, 100, 50]
        width, height = 640, 360
        for _ in range(4):
            z = camera.rotate_zone(z, width, height, 1)
            width, height = height, width
        self.assertEqual(z, [10, 20, 100, 50])

    def test_zone_matches_rotated_image(self):
        """What lies in the zone lies in the rotated zone after rotating."""
        import camera
        image = np.zeros((360, 640), np.uint8)
        x, y, w, h = 10, 20, 100, 50
        image[y:y + h, x:x + w] = 1
        for steps in (1, 2, 3):
            rotated = camera.rotate(image, 90 * steps)
            rx, ry, rw, rh = camera.rotate_zone([x, y, w, h], 640, 360, steps)
            self.assertEqual(int(rotated[ry:ry + rh, rx:rx + rw].sum()), w * h, steps)


@unittest.skipUnless(HAS_OPENCV, "OpenCV not installed")
class CsiTest(unittest.TestCase):
    def setUp(self):
        import camera
        self.fake = FakeCamera()
        module = types.SimpleNamespace(Picamera2=lambda: self.fake)
        self.cam = camera.Csi(dict(CFG), picamera2_module=module)

    def test_configuration(self):
        c = self.fake.config
        self.assertEqual(c["main"]["size"], (1536, 864))
        self.assertEqual(c["lores"], {"size": (640, 360), "format": "YUV420"})
        self.assertEqual(c["controls"]["FrameDurationLimits"], (10000, 10000))
        self.assertEqual(c["controls"]["ExposureTime"], 3000)
        self.assertTrue(self.fake.running)

    def test_frames_times_and_losses(self):
        now = time.monotonic_ns() - 100_000_000  # camera images are slightly in the past
        # 4 images every 10 ms, two missing between the 2nd and 3rd
        self.fake.timestamps = [now, now + 10_000_000, now + 40_000_000, now + 50_000_000]
        frames = self.cam.frames()
        results = [next(frames) for _ in range(4)]
        frames.close()
        image, t, photo = results[0]
        self.assertEqual(image.shape, (360, 640, 3))
        self.assertEqual(photo.shape, (864, 1536, 3))
        self.assertAlmostEqual(t, now / 1e9, places=6)
        self.assertEqual(self.cam.time_source, "camera")
        self.assertEqual((self.cam.delivered, self.cam.lost), (4, 2))
        self.assertEqual(self.fake.released, 4)  # every buffer goes back to the camera

    def test_large_image_only_when_needed(self):
        self.fake.timestamps = [time.monotonic_ns() - 100_000_000] * 2
        frames = self.cam.frames()
        _, _, photo = next(frames)
        self.assertEqual(self.fake.copied, ["lores"])  # large image not touched yet
        crop = photo[10:20, 30:50].copy()
        self.assertEqual(crop.shape, (10, 20, 3))
        self.assertEqual(self.fake.copied, ["lores", "main"])
        photo[0:5, 0:5]
        self.assertEqual(self.fake.copied.count("main"), 1)  # only copied once per image
        next(frames)
        frames.close()
        self.assertEqual(self.fake.copied, ["lores", "main", "lores"])

    def test_foreign_time_base(self):
        self.fake.timestamps = [123]  # does not match the system clock
        frames = self.cam.frames()
        _, t, _ = next(frames)
        frames.close()
        self.assertEqual(self.cam.time_source, "system")
        self.assertLess(abs(t - time.monotonic()), 1.0)

    def test_adjust_limits_exposure_to_frame_duration(self):
        self.cam.adjust(exposure_ms=50, gain=8)
        self.assertEqual(self.fake.set[-1], {"ExposureTime": 10000, "AnalogueGain": 8.0, "AeEnable": False})

    def test_calibrate_freezes_values(self):
        # the automatic finds 8 ms at gain 2 -> too long for sharp quads: 4 ms at gain 4 (same brightness)
        self.cam._metadata = {"ExposureTime": 8000, "AnalogueGain": 2.0, "ColourGains": (1.9, 1.6)}
        values = self.cam.calibrate(duration_s=0)
        self.assertEqual(values, {"exposure_ms": 4.0, "gain": 4.0, "white_balance": [1.9, 1.6]})
        auto, fixed = self.fake.set[-2:]
        self.assertEqual(auto, {"AwbEnable": True, "AeEnable": True})
        self.assertEqual(fixed, {"ExposureTime": 4000, "AnalogueGain": 4.0, "AeEnable": False,
                                 "AwbEnable": False, "ColourGains": (1.9, 1.6)})
        # with the next exposure slider move the white balance stays fixed
        self.cam.adjust(exposure_ms=2.0)
        self.assertEqual(self.fake.set[-1]["ColourGains"], (1.9, 1.6))

    def test_calibrate_gain_at_most_16(self):
        self.cam._metadata = {"ExposureTime": 10000, "AnalogueGain": 12.0}  # very dark
        values = self.cam.calibrate(duration_s=0)
        self.assertEqual((values["exposure_ms"], values["gain"], values["white_balance"]), (4.0, 16.0, None))

    def test_set_white_balance_and_back_to_automatic(self):
        self.cam.adjust(white_balance=[1.8, 1.5])
        self.assertEqual(self.fake.set[-1]["ColourGains"], (1.8, 1.5))
        self.cam.adjust(white_balance=None)
        self.assertTrue(self.fake.set[-1]["AwbEnable"])
        self.assertNotIn("ColourGains", self.fake.set[-1])
        count = len(self.fake.set)
        self.cam.adjust(focus_m=2.0)  # without white balance: don't touch exposure/colours
        self.assertEqual(len(self.fake.set), count)  # (the test camera has no focus)
        self.assertIsNone(self.cam.cfg["white_balance"])

    def test_capture_stays_until_released(self):
        """Fetching and processing run in parallel: the buffer only goes back with release()."""
        import threading
        self.fake.timestamps = [time.monotonic_ns() - 100_000_000] * 2
        captures = self.cam.captures()
        first = next(captures)
        second = next(captures)                          # already fetched the next one ...
        self.assertEqual(self.fake.released, 0)          # ... the first is still valid
        self.assertEqual(first.photo_image[0:4, 0:4].shape, (4, 4, 3))
        thread = threading.Thread(target=first.release)  # release from another thread
        thread.start()
        thread.join()
        second.release()
        second.release()                                 # twice does no harm
        self.assertEqual(self.fake.released, 2)
        captures.close()

    def test_rotate_90_degrees(self):
        self.fake.timestamps = [time.monotonic_ns() - 100_000_000]
        self.cam.set_rotation(90)
        frames = self.cam.frames()
        image, _, photo = next(frames)
        self.assertEqual(image.shape, (640, 360, 3))    # portrait
        self.assertEqual(photo.shape, (1536, 864, 3))
        self.assertEqual(photo[0:10, 0:20].shape, (10, 20, 3))
        frames.close()
        self.assertEqual(self.cam.cfg["rotation"], 90)

    def test_actual_values(self):
        self.cam._metadata = {"ExposureTime": 3000, "AnalogueGain": 4.0, "ColourGains": (1.9, 1.6),
                              "LensPosition": 0.769}
        self.assertEqual(self.cam.actual(), {"exposure_ms": 3.0, "gain": 4.0, "white_balance": [1.9, 1.6],
                                             "focus_m": 1.3})

    def test_close(self):
        self.cam.close()
        self.assertFalse(self.fake.running)


if __name__ == "__main__":
    unittest.main()
