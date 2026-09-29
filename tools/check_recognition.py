#!/usr/bin/env python3
"""Checks how well the quads can be told apart by their profile photos.

Compares the colour fingerprint with a pre-trained neural network
(pi/laptimer/models/mobilenetv2-12.onnx). Each profile photo is matched against the other
photos ("leave one out") and it is counted how often the right quad comes out.

Usage (copy the database + photos/ from the Pi into a folder):
    python tools/check_recognition.py path/to/copied/data
Needs OpenCV and NumPy.
"""
import sqlite3
import sys
import time
from pathlib import Path

import cv2
import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "pi" / "laptimer"))
import embedding  # noqa: E402
import fingerprint  # noqa: E402

net = embedding.load(PROJECT / "pi" / "laptimer" / "models" / "mobilenetv2-12.onnx")


def colour_fingerprint(image):
    # estimate the quad pixels roughly: everything clearly different from the border (= background)
    h, w = image.shape[:2]
    border = np.ones((h, w), bool)
    border[4:-4, 4:-4] = False
    mask = (np.abs(image.astype(float) - image[border].mean(0)).max(2) > 25) & ~border
    if mask.sum() < 30:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[mask]
    return fingerprint.fingerprint(hsv[:, 0], hsv[:, 1], int(mask.sum()), w / h, v=hsv[:, 2])


def main(folder):
    folder = Path(folder)
    photos = folder / "photos" if (folder / "photos").is_dir() else folder / "bilder"
    con = sqlite3.connect(folder / "laptimer.db")
    if con.execute("SELECT name FROM sqlite_master WHERE name = 'quads'").fetchone():
        quads = dict(con.execute("SELECT id, name FROM quads"))
        rows = con.execute("SELECT quad_id, photo FROM samples WHERE photo IS NOT NULL")
    else:  # database of the German version
        quads = dict(con.execute("SELECT id, name FROM copter"))
        rows = con.execute("SELECT copter_id, foto FROM merkmale WHERE foto IS NOT NULL")
    data = []
    for quad_id, photo in rows:
        image = cv2.imread(str(photos / photo))
        if image is None:
            continue
        fp = colour_fingerprint(image)
        if fp is not None:
            data.append((quad_id, np.array(net.embed(image)), fp))
    ids = sorted({d[0] for d in data})
    if len(ids) < 2:
        sys.exit("At least two quads with profile photos are needed.")

    def check(similarity):
        right = 0
        for i, (target, _, _) in enumerate(data):
            score = {q: np.mean(sorted((similarity(data[i], d) for j, d in enumerate(data)
                                        if j != i and d[0] == q), reverse=True)[:5]) for q in ids}
            right += max(score, key=score.get) == target
        return right

    start = time.perf_counter()
    for _ in range(10):
        net.embed(np.zeros((60, 60, 3), np.uint8))
    ms = (time.perf_counter() - start) * 100

    net_sim = lambda a, b: float(a[1] @ b[1])  # noqa: E731
    colour_sim = lambda a, b: fingerprint.similarity(a[2], b[2])  # noqa: E731
    print(f"{len(data)} photos: " + ", ".join(f"{quads[q]} {sum(d[0] == q for d in data)}" for q in ids))
    print(f"Net: {ms:.0f} ms per photo on this computer")
    for name, sim in (("Colour fingerprint", colour_sim), ("Neural network", net_sim),
                      ("Combined 50/50", lambda a, b: 0.5 * net_sim(a, b) + 0.5 * colour_sim(a, b))):
        r = check(sim)
        print(f"{name:20s} {r}/{len(data)} right ({100 * r / len(data):.0f} %)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
