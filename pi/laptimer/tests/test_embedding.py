"""Neural network as fingerprint. Skipped without OpenCV or without the model file."""
import unittest
from pathlib import Path

import numpy as np

MODEL = Path(__file__).resolve().parent.parent / "models" / "mobilenetv2-12.onnx"
try:
    import cv2  # noqa: F401
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False


def quad_image(colour, seed):
    """Small noisy image: grey background, coloured 'X' as a quad."""
    rng = np.random.default_rng(seed)
    b = np.clip(rng.normal(150, 8, (60, 70, 3)), 0, 255).astype(np.uint8)
    for i in range(10, 50):
        for d in (-1, 0, 1):
            b[i, np.clip(i + 5 + d, 0, 69)] = colour
            b[i, np.clip(65 - i + d, 0, 69)] = colour
    return b


@unittest.skipUnless(HAS_OPENCV and MODEL.exists(), "OpenCV or model missing")
class EmbeddingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import embedding
        cls.net = embedding.load(MODEL)
        assert cls.net is not None, "Could not load the network (see message above)"

    def test_embedding(self):
        e = np.array(self.net.embed(quad_image((0, 0, 255), 1)))
        self.assertEqual(e.shape, (1280,))
        self.assertAlmostEqual(float(np.linalg.norm(e)), 1.0, places=3)

    def test_similar_is_more_similar(self):
        red1 = np.array(self.net.embed(quad_image((0, 0, 255), 1)))
        red2 = np.array(self.net.embed(quad_image((0, 0, 255), 2)))
        blue = np.array(self.net.embed(quad_image((255, 0, 0), 3)))
        self.assertGreater(red1 @ red2, red1 @ blue)

    def test_detector_with_net_in_the_background(self):
        import tempfile
        import threading
        from detector import Detector
        from photos import Photos

        class Config:
            lock = threading.RLock()
            data = {"zone": [220, 140, 200, 200], "pixel_threshold": 25, "min_size": 60}

        reported = []
        det = Detector(Config(), reported.append, Photos(tempfile.mkdtemp()), self.net)
        empty = np.full((480, 640, 3), 100, np.uint8)
        t = 0.0
        for i in range(120):                            # 4 s: warm-up + crossing + quiet
            b = empty.copy()
            if i in (95, 96, 97):
                b[220:244, 250 + 40 * (i - 95):274 + 40 * (i - 95)] = (0, 0, 255)
            det.process(b, t)
            t += 1 / 30
        det._worker.shutdown(wait=True)                 # wait for the background work
        self.assertEqual(len(reported), 1)
        self.assertEqual(len(reported[0].fingerprint["embedding"]), 1280)

    def test_missing_model(self):
        import embedding
        self.assertIsNone(embedding.load(Path("does/not/exist.onnx")))


if __name__ == "__main__":
    unittest.main()
