import unittest

import numpy as np

import fingerprint


def fp(hue, saturation=200, n=400, spread=4, aspect=1.5, seed=0):
    """Fingerprint of a single-coloured quad (hue 0..179 as in OpenCV)."""
    rng = np.random.default_rng(seed)
    h = np.clip(rng.normal(hue, spread, n), 0, 179)
    s = np.clip(rng.normal(saturation, 15, n), 0, 255)
    return fingerprint.fingerprint(h, s, area=n, aspect=aspect)


RED, GREEN, BLUE = 2, 60, 115


class FingerprintTest(unittest.TestCase):
    def test_histogram_normalised(self):
        f = fp(RED)
        self.assertEqual(len(f["hist"]), fingerprint.H_BINS * fingerprint.S_BINS + fingerprint.V_BINS)
        self.assertAlmostEqual(sum(f["hist"]), 1.0, places=5)

    def test_empty_pixels(self):
        f = fingerprint.fingerprint(np.array([]), np.array([]), 0, 1.0)
        self.assertEqual(sum(f["hist"]), 0)


class SimilarityTest(unittest.TestCase):
    def test_same_colour_similar(self):
        self.assertGreater(fingerprint.similarity(fp(RED, seed=1), fp(RED, seed=2)), 0.8)

    def test_other_colour_dissimilar(self):
        self.assertLess(fingerprint.similarity(fp(RED), fp(BLUE)), 0.3)

    def test_profile_without_samples(self):
        self.assertEqual(fingerprint.profile_similarity(fp(RED), []), 0.0)


def grey_fp(brightness, seed=0):
    """Almost colourless quad (white/black): differs only in brightness."""
    rng = np.random.default_rng(seed)
    n = 400
    h = rng.uniform(0, 179, n)                       # hue of grey = noise
    s = np.clip(rng.normal(15, 8, n), 0, 255)
    v = np.clip(rng.normal(brightness, 12, n), 0, 255)
    return fingerprint.fingerprint(h, s, area=n, aspect=1.5, v=v)


class BrightnessTest(unittest.TestCase):
    def test_white_and_black_distinguishable(self):
        white, black = grey_fp(220, 1), grey_fp(35, 2)
        self.assertGreater(fingerprint.similarity(white, grey_fp(220, 3)), 0.8)
        self.assertLess(fingerprint.similarity(white, black), 0.5)

    def test_match_white_black(self):
        profiles = {1: [grey_fp(220, i) for i in range(8)], 2: [grey_fp(35, i + 20) for i in range(8)]}
        self.assertEqual(fingerprint.match(grey_fp(215, 99), profiles), (1, False))
        self.assertEqual(fingerprint.match(grey_fp(40, 98), profiles), (2, False))

    def test_old_samples_without_brightness(self):
        old = fp(RED)
        old["hist"] = old["hist"][:fingerprint.COLOR_BINS]   # what samples looked like before the change
        new = fingerprint.fingerprint(np.full(100, 2.0), np.full(100, 200.0), 100, 1.5, v=np.full(100, 150.0))
        self.assertGreater(fingerprint.similarity(old, new), 0.5)   # still works, just without brightness


class EmbeddingTest(unittest.TestCase):
    def test_network_counts_more_than_colour(self):
        # same colour, but the network sees two different quads
        a, b, c = fp(RED, seed=1), fp(RED, seed=2), fp(RED, seed=3)
        e1, e2 = np.zeros(1280), np.zeros(1280)
        e1[0], e2[1] = 1.0, 1.0
        a["embedding"], b["embedding"], c["embedding"] = list(e1), list(e1), list(e2)
        self.assertGreater(fingerprint.similarity(a, b), fingerprint.similarity(a, c) + 0.5)

    def test_without_embedding_as_before(self):
        a, b = fp(RED, seed=1), fp(RED, seed=2)
        without = fingerprint.similarity(a, b)
        a["embedding"] = [1.0] + [0.0] * 1279           # only one of them has network data
        self.assertAlmostEqual(fingerprint.similarity(a, b), without)


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            1: [fp(RED, seed=i) for i in range(10)],
            2: [fp(BLUE, seed=i) for i in range(10)],
        }

    def test_clear(self):
        self.assertEqual(fingerprint.match(fp(BLUE, seed=99), self.profiles), (2, False))
        self.assertEqual(fingerprint.match(fp(RED, seed=99), self.profiles), (1, False))

    def test_uncertain_when_both_similar(self):
        profiles = {1: [fp(RED, seed=i) for i in range(5)], 2: [fp(RED + 1, seed=i + 50) for i in range(5)]}
        _, uncertain = fingerprint.match(fp(RED, seed=99), profiles)
        self.assertTrue(uncertain)

    def test_uncertain_when_nothing_fits(self):
        quad, uncertain = fingerprint.match(fp(GREEN), self.profiles)
        self.assertIn(quad, (1, 2))
        self.assertTrue(uncertain)

    def test_without_fingerprint(self):
        self.assertEqual(fingerprint.match(None, self.profiles), (None, True))

    def test_without_profile_uncertain(self):
        _, uncertain = fingerprint.match(fp(RED), {1: [], 2: []})
        self.assertTrue(uncertain)


if __name__ == "__main__":
    unittest.main()
