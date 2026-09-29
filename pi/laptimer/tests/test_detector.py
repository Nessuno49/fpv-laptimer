"""Object detection with synthetic images. Skipped without OpenCV."""
import tempfile
import threading
import unittest

import numpy as np

try:
    import cv2  # noqa: F401
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

import fingerprint


class FakeConfig:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = {"zone": [220, 140, 200, 200], "pixel_threshold": 25, "min_size": 60}


FPS = 30
BG = (100, 100, 100)
RED, BLUE = (0, 0, 255), (255, 0, 0)  # BGR


def image(*squares):
    """640x480 grey with coloured squares [(x, y, colour), ...] (edge length 24)."""
    b = np.full((480, 640, 3), BG, dtype=np.uint8)
    for x, y, colour in squares:
        b[y:y + 24, x:x + 24] = colour
    return b


def main_hue(fp):
    hist = np.array(fp["hist"][:fingerprint.COLOR_BINS]).reshape(fingerprint.H_BINS, fingerprint.S_BINS)
    return int(hist.sum(axis=1).argmax())


@unittest.skipUnless(HAS_OPENCV, "OpenCV not installed")
class DetectorTest(unittest.TestCase):
    def setUp(self):
        from detector import Detector
        from photos import Photos
        self.reported = []
        self.photos = Photos(tempfile.mkdtemp())
        self.det = Detector(FakeConfig(), self.reported.append, self.photos)
        self.t = 0.0
        self.empty(3.0)  # warm-up (2 s) + learn the background

    def step(self, b):
        self.det.process(b, self.t)
        self.t += 1 / FPS

    def empty(self, seconds):
        for _ in range(int(seconds * FPS)):
            self.step(image())

    def test_nothing_to_card_without_race(self):
        """Outside races/practice: photo only in memory, no net."""
        class Net:
            calls = 0

            def embed(self, image):
                Net.calls += 1
                return [0.0]
        self.det.net = Net()
        self.det.to_card = lambda: False
        for x in (230, 280, 330, 380):
            self.step(image((x, 220, RED)))
        self.empty(0.5)
        self.assertEqual(len(self.reported), 1)
        name = self.reported[0].photo
        self.assertFalse(self.photos.path(name).exists())       # not on the SD card
        self.assertIsNotNone(self.photos.read(name))            # but there for the camera tab
        self.assertEqual(Net.calls, 0)                          # net not computed

    def test_one_crossing(self):
        start = self.t
        for x in (230, 280, 330, 380):          # flies through the zone in 4 images
            self.step(image((x, 220, RED)))
        self.empty(0.5)
        self.assertEqual(len(self.reported), 1)
        c = self.reported[0]
        self.assertAlmostEqual(c.t, start)       # time = first image
        self.assertTrue(self.photos.path(c.photo).exists())
        self.assertEqual(main_hue(c.fingerprint), 0)  # hue red

    def test_flicker_gives_one_crossing(self):
        self.step(image((250, 220, RED)))
        self.step(image())                       # not visible for one image
        self.step(image((300, 220, RED)))
        self.empty(0.5)
        self.assertEqual(len(self.reported), 1)

    def test_two_at_once(self):
        for dy in (0, 10, 20):
            self.step(image((240, 150 + dy, RED), (380, 290 + dy, BLUE)))
        self.empty(0.5)
        self.assertEqual(len(self.reported), 2)
        hues = sorted(main_hue(c.fingerprint) for c in self.reported)
        self.assertEqual(hues[0], 0)             # red
        self.assertGreater(hues[1], 10)          # blue (hue ~120)

    def test_quad_in_pieces_is_one_crossing(self):
        # frame and props as two blobs with a 15 px gap, flying through together
        for x in (240, 290, 340):
            self.step(image((x, 220, RED), (x + 39, 220, RED)))
        self.empty(0.5)
        self.assertEqual(len(self.reported), 1)

    def test_two_crossings_shortly_after_each_other(self):
        self.step(image((250, 220, RED)))
        self.empty(0.5)                          # the first is through
        self.step(image((250, 220, BLUE)))
        self.empty(0.5)
        self.assertEqual(len(self.reported), 2)

    def test_small_stuff_is_ignored(self):
        b = image()
        b[200:204, 300:304] = (0, 0, 255)        # 4x4 pixels, below the minimum size
        self.step(b)
        self.empty(0.5)
        self.assertEqual(self.reported, [])

    def test_nothing_outside_the_zone(self):
        self.step(image((20, 20, RED)))
        self.empty(0.5)
        self.assertEqual(self.reported, [])

    def test_object_left_lying_does_not_keep_triggering(self):
        for _ in range(int(5 * FPS)):            # something lies in the zone for 5 s
            self.step(image((300, 220, RED)))
        self.empty(1.0)
        self.assertEqual(self.reported, [])


BEIGE = (150, 175, 200)  # BGR: wall/floor with a bit of colour


def beige_image(squares=(), shadows=()):
    """Beige background; shadow = same colour, only darker (factor 0.6)."""
    b = np.full((480, 640, 3), BEIGE, dtype=np.uint8)
    for x, y, w, h in shadows:
        b[y:y + h, x:x + w] = (b[y:y + h, x:x + w] * 0.6).astype(np.uint8)
    for x, y, colour in squares:
        b[y:y + 24, x:x + 24] = colour
    return b


@unittest.skipUnless(HAS_OPENCV, "OpenCV not installed")
class ShadowTest(unittest.TestCase):
    def setUp(self):
        from detector import Detector
        from photos import Photos
        self.reported = []
        self.photos = Photos(tempfile.mkdtemp())
        self.config = FakeConfig()
        self.det = Detector(self.config, self.reported.append, self.photos)
        self.t = 0.0
        self.empty(3.0)

    def step(self, b):
        self.det.process(b, self.t)
        self.t += 1 / FPS

    def empty(self, seconds):
        for _ in range(int(seconds * FPS)):
            self.step(beige_image())

    def test_shadow_alone_does_not_trigger(self):
        for x in (230, 260, 290, 320):
            self.step(beige_image(shadows=[(x, 300, 40, 20)]))
        self.empty(0.5)
        self.assertEqual(self.reported, [])

    def test_saturated_wall_shadow_does_not_trigger(self):
        # real wall shadow (measured): brightness x0.7, saturation +45, same hue
        import cv2

        def saturated_shadow(x):
            b = beige_image()
            hsv = cv2.cvtColor(b, cv2.COLOR_BGR2HSV).astype(np.int16)
            part = hsv[300:320, x:x + 40]
            part[..., 2] = part[..., 2] * 7 // 10
            part[..., 1] = np.clip(part[..., 1] + 45, 0, 255)
            return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        for x in (230, 260, 290, 320):
            self.step(saturated_shadow(x))
        self.empty(0.5)
        self.assertEqual(self.reported, [])

    def test_whoop_with_shadow_is_one_crossing(self):
        for x in (240, 290, 340):
            self.step(beige_image(squares=[(x, 160, RED)], shadows=[(x, 300, 40, 20)]))
        self.empty(0.5)
        self.assertEqual(len(self.reported), 1)
        self.assertEqual(main_hue(self.reported[0].fingerprint), 0)  # it's the red whoop, not the shadow

    def test_black_whoop_is_detected(self):
        for x in (240, 290, 340):
            self.step(beige_image(squares=[(x, 200, (25, 25, 25))]))
        self.empty(0.5)
        self.assertEqual(len(self.reported), 1)

    def test_photo_not_cut_off_at_the_zone(self):
        # narrow zone (40 px), the whoop sticks out left and right
        self.config.data["zone"] = [300, 100, 40, 300]
        self.det.relearn()
        self.empty(1.5)
        self.step(beige_image(squares=[(290, 200, RED), (314, 200, RED)]))  # 48 px wide
        self.empty(0.5)
        self.assertEqual(len(self.reported), 1)
        import cv2
        photo = cv2.imread(str(self.photos.path(self.reported[0].photo)))
        self.assertGreater(photo.shape[1], 48)  # wider than the zone and than the whoop


class FakeCamera:
    """Delivers ready-made images via captures() and counts the releases (like camera.Csi)."""

    def __init__(self, images):
        self.images = images
        self.delivered = self.lost = 0
        self.time_source = "camera"
        self.open = set()

    def captures(self):
        from camera import Capture

        cam = self

        class Buffer:
            def __init__(self, nr):
                self.nr = nr
                cam.open.add(nr)

            def release(self):
                cam.open.discard(self.nr)

        for nr, (img, t) in enumerate(self.images):
            self.delivered += 1
            yield Capture(img, t, None, Buffer(nr))


@unittest.skipUnless(HAS_OPENCV, "OpenCV not installed")
class TwoThreadsTest(unittest.TestCase):
    """run(): fetching and processing in two threads – each image exactly once, each buffer back."""

    def test_run_processes_everything_and_releases_everything(self):
        from detector import Detector
        reported = []
        det = Detector(FakeConfig(), reported.append)
        images, t = [], 0.0
        for _ in range(3 * FPS):                        # learn the background
            images.append((image(), t))
            t += 1 / FPS
        for x in (230, 280, 330, 380):                  # one crossing
            images.append((image((x, 220, RED)), t))
            t += 1 / FPS
        for _ in range(FPS):
            images.append((image(), t))
            t += 1 / FPS
        cam = FakeCamera(images)
        processed = []
        original = det.process
        det.process = lambda b, when, photo=None: (processed.append(when), original(b, when, photo))
        thread = threading.Thread(target=det.run, args=(cam,))
        thread.start()
        thread.join(timeout=20)
        self.assertFalse(thread.is_alive())             # ends when the camera delivers nothing more
        self.assertEqual(processed, [w for _, w in images])  # all of them, in the right order
        self.assertEqual(cam.open, set())               # every buffer returned to the camera
        self.assertEqual(len(reported), 1)


@unittest.skipUnless(HAS_OPENCV, "OpenCV not installed")
class CameraModule3Test(unittest.TestCase):
    """Detection on the small image, photos from the large one; frame rate up to 120/s."""

    def new(self):
        from detector import Detector
        from photos import Photos
        self.reported = []
        self.photos = Photos(tempfile.mkdtemp())
        return Detector(FakeConfig(), self.reported.append, self.photos)

    def test_photo_from_the_large_image(self):
        import cv2
        det, t = self.new(), 0.0
        large = lambda b: cv2.resize(b, (1920, 1440), interpolation=cv2.INTER_NEAREST)  # 3 times
        for _ in range(3 * 30):
            det.process(image(), t, large(image()))
            t += 1 / 30
        for x in (230, 280, 330):
            b = image((x, 220, RED))
            det.process(b, t, large(b))
            t += 1 / 30
        for _ in range(15):
            det.process(image(), t, large(image()))
            t += 1 / 30
        self.assertEqual(len(self.reported), 1)
        photo = cv2.imread(str(self.photos.path(self.reported[0].photo)))
        self.assertGreaterEqual(photo.shape[1], 3 * 24)  # whoop (24 px) in triple resolution
        red = (photo[..., 2] > 200) & (photo[..., 0] < 50)
        self.assertGreater(red.sum(), 3 * 24 * 3 * 24 * 0.5)  # the whoop really is on it

    def test_background_follows_equally_fast_at_any_frame_rate(self):
        brighter = np.full((480, 640, 3), 110, dtype=np.uint8)  # light gets a bit brighter (below the threshold)
        mean = {}
        for fps in (30, 120):
            det, t = self.new(), 0.0
            for _ in range(3 * fps):
                det.process(image(), t)
                t += 1 / fps
            for _ in range(fps // 2):  # half a second
                det.process(brighter, t)
                t += 1 / fps
            mean[fps] = float(det._background.mean())
        self.assertGreater(mean[30], 105)                   # has adapted clearly
        self.assertAlmostEqual(mean[30], mean[120], delta=0.5)


if __name__ == "__main__":
    unittest.main()
