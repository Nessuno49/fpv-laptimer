#!/usr/bin/env python3
"""Benchmark: how many images per second do the Camera Module 3 and our detector manage on the Pi?

Measures exactly the path the lap timer takes (camera.Csi + Detector).

Run on the Pi (the lap timer must be stopped, otherwise the camera is busy):
    systemctl --user stop laptimer
    python3 ~/laptimer/camera_benchmark.py

For several settings it measures:
  fetch    only fetch images from the camera and convert them for processing
  detect   additionally our detector on every image (with photos from the large image)
Tip: during "detect" move your hand through the detection zone now and then –
with movement the detector computes more than with an empty image.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import camera  # noqa: E402
from config import migrate  # noqa: E402
from detector import Detector  # noqa: E402

MEASURE_S = 6.0
SETTLE_S = 2.5      # the detector first learns the background for 2 s

# images/s, size of the detection image
SETTINGS = [
    (120, (640, 360)),
    (100, (640, 360)),
    (120, (768, 432)),
    (100, (768, 432)),
]
MODES = ("fetch", "detect")


def load_config():
    """Detection zone (as a share of the image) and thresholds from the lap timer config."""
    try:
        cfg, _ = migrate(json.loads((HERE / "config.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        cfg = {}
    x, y, w, h = cfg.get("zone", [256, 0, 128, 480])
    webcam = cfg.get("webcam", {})
    iw, ih = (640, 360) if cfg.get("camera") == "csi" else (webcam.get("width", 640), webcam.get("height", 480))
    return (x / iw, y / ih, w / iw, h / ih), cfg.get("pixel_threshold", 25), cfg.get("min_size", 60)


def cpu_counters():
    """(total, idle) from /proc/stat – for the load of all 4 cores."""
    with open("/proc/stat") as f:
        values = [int(v) for v in f.readline().split()[1:]]
    return sum(values), values[3] + values[4]


def temperature():
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (OSError, ValueError):
        return float("nan")


def new_detector(size, shares, threshold, min_size):
    iw, ih = size
    sx, sy, sw, sh = shares
    zone = [round(sx * iw), round(sy * ih), round(sw * iw), round(sh * ih)]
    config = SimpleNamespace(lock=threading.Lock(),
                             data={"zone": zone, "pixel_threshold": threshold, "min_size": min_size})
    crossings = []
    return Detector(config, crossings.append), crossings, zone


def measure(cam, mode, detector):
    frames = cam.frames()
    end = time.monotonic() + SETTLE_S
    for image, t, photo in frames:
        if mode == "detect":
            detector.process(image, t, photo)
        if time.monotonic() > end:
            break
    cpu0, idle0 = cpu_counters()
    process0, start = sum(os.times()[:2]), time.monotonic()
    delivered0, lost0 = cam.delivered, cam.lost
    n = 0
    for image, t, photo in frames:
        if mode == "detect":
            detector.process(image, t, photo)
        n += 1
        if time.monotonic() - start >= MEASURE_S:
            break
    duration = time.monotonic() - start
    frames.close()
    cpu1, idle1 = cpu_counters()
    lost = cam.lost - lost0
    return {
        "images_s": n / duration,
        "share_lost": lost / (cam.delivered - delivered0 + lost or 1),
        "cpu_total": 100 * (1 - (idle1 - idle0) / max(1, cpu1 - cpu0)),
        "cpu_process": 100 * (sum(os.times()[:2]) - process0) / duration,
        "temp": temperature(),
    }


def main():
    shares, threshold, min_size = load_config()
    rows = []
    for fps, small in SETTINGS:
        name = f"{fps}/s, detection {small[0]}x{small[1]}"
        cam = camera.Csi({"fps": fps, "photo_size": [1536, 864], "detection_size": list(small),
                          "exposure_ms": 3.0, "gain": 4.0, "focus_m": 1.0})
        try:
            for mode in MODES:
                detector, crossings, zone = new_detector(small, shares, threshold, min_size)
                print(f"\n▶ {name} – {mode}"
                      + (f" (zone {zone[2]}x{zone[3]} px – now move your hand through the image now and then!)"
                         if mode == "detect" else ""), flush=True)
                e = measure(cam, mode, detector)
                e.update(name=name, mode=mode, crossings=len(crossings))
                rows.append(e)
                print(f"  {e['images_s']:.1f} images/s, {e['share_lost']:.0%} lost, "
                      f"CPU {e['cpu_total']:.0f} % total / {e['cpu_process']:.0f} % process, {e['temp']:.0f} °C",
                      flush=True)
        finally:
            cam.close()

    print("\n" + "=" * 94)
    print(f"{'Setting':<30}{'Mode':<10}{'Images/s':>9}{'lost':>10}{'CPU tot.':>10}"
          f"{'CPU proc.':>11}{'Temp':>7}{'Cross.':>9}")
    for e in rows:
        print(f"{e['name']:<30}{e['mode']:<10}{e['images_s']:>9.1f}{e['share_lost']:>9.0%} "
              f"{e['cpu_total']:>9.0f}%{e['cpu_process']:>10.0f}%{e['temp']:>6.0f}°{e['crossings']:>9}")
    print("=" * 94)
    print("CPU total: 100 % = all 4 cores; CPU process: 100 % = one core fully busy.")


if __name__ == "__main__":
    main()
