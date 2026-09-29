"""Fingerprint of a quad and matching it against recognition profiles.

The fingerprint is the colour distribution of the quad's pixels (coloured pixels by hue
and saturation, colourless ones by brightness) plus a rough shape feature.
Pure NumPy functions, no OpenCV.
"""
import math

import numpy as np

H_BINS, S_BINS = 18, 8          # coloured pixels: hue 0..179 (OpenCV) × saturation
V_BINS = 8                      # colourless pixels (white/grey/black): by brightness
COLORED_FROM = 40               # saturation from which a pixel counts as coloured
COLOR_BINS = H_BINS * S_BINS
# Measured on real flights (2 whoops, clean profiles): wrong matches were
# 0.002–0.028 ahead of the runner-up, correct ones 0.09 on average.
UNCERTAIN_MARGIN = 0.03         # this close to the runner-up the match counts as uncertain
UNCERTAIN_MIN = 0.35            # below this even the best one does not really fit
EMBEDDING_WEIGHT = 0.7          # share of the neural network when both fingerprints have it
BEST_SAMPLES = 5


def fingerprint(h, s, area, aspect, v=None):
    """h, s, v: hue, saturation and brightness values of the quad's pixels.

    One combined histogram: coloured pixels by hue × saturation, colourless ones by
    brightness. For colourless pixels the hue is just noise – this way a white and a
    black quad still differ clearly.
    """
    h, s = np.asarray(h, dtype=float), np.asarray(s, dtype=float)
    colored = s >= COLORED_FROM if v is not None else np.ones(len(s), dtype=bool)
    color_hist, _, _ = np.histogram2d(h[colored], s[colored], bins=(H_BINS, S_BINS), range=((0, 180), (0, 256)))
    grey_hist = np.zeros(V_BINS)
    if v is not None:
        grey_hist, _ = np.histogram(np.asarray(v, dtype=float)[~colored], bins=V_BINS, range=(0, 256))
    hist = np.concatenate([color_hist.ravel(), grey_hist]).astype(float)
    total = hist.sum()
    if total > 0:
        hist /= total
    return {"hist": [round(float(x), 5) for x in hist],
            "area": int(area), "aspect": round(float(aspect), 3)}


def similarity(a, b):
    """0 = completely different, 1 = identical."""
    n = min(len(a["hist"]), len(b["hist"]))  # older samples have no brightness bins
    color = float(np.minimum(a["hist"][:n], b["hist"][:n]).sum())  # histogram intersection
    aa, ab = max(a["aspect"], 0.01), max(b["aspect"], 0.01)
    shape = max(0.0, 1.0 - abs(math.log(aa / ab)))
    classic = 0.85 * color + 0.15 * shape
    if "embedding" in a and "embedding" in b:
        net = float(np.dot(a["embedding"], b["embedding"]))  # both have length 1 -> cosine similarity
        return EMBEDDING_WEIGHT * net + (1 - EMBEDDING_WEIGHT) * classic
    return classic


def profile_similarity(fp, samples):
    if not samples:
        return 0.0
    values = sorted((similarity(fp, s) for s in samples), reverse=True)[:BEST_SAMPLES]
    return sum(values) / len(values)


def match(fp, profiles):
    """profiles: {quad_id: [fingerprint, ...]} of the possible candidates.

    Returns (quad_id, uncertain). Without a fingerprint: (None, True).
    """
    if fp is None or not profiles:
        return None, True
    ranking = sorted(((profile_similarity(fp, s), q) for q, s in profiles.items()), reverse=True)
    best_value, best = ranking[0]
    second_value = ranking[1][0] if len(ranking) > 1 else 0.0
    uncertain = best_value < UNCERTAIN_MIN or best_value - second_value < UNCERTAIN_MARGIN
    return best, uncertain
