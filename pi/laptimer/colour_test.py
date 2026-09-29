#!/usr/bin/env python3
"""Colour check for the Camera Module 3: save one image in four conversions side by side.

Run on the Pi (stop the lap timer first):
    systemctl --user stop laptimer
    python3 ~/laptimer/colour_test.py
Result: ~/colour_test.jpg – which of the four tiles shows the colours correctly?
"""
from pathlib import Path

import cv2
import numpy as np
from picamera2 import Picamera2

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(
    main={"size": (1536, 864), "format": "RGB888"},
    lores={"size": (640, 360), "format": "YUV420"},
    sensor={"output_size": (1536, 864), "bit_depth": 10}))
picam2.start()
for _ in range(30):              # let exposure and white balance settle
    picam2.capture_request().release()
request = picam2.capture_request()
large = request.make_array("main")
small = request.make_array("lores")
request.release()
picam2.stop()
picam2.close()

large = cv2.resize(large, (640, 360))
tiles = [
    ("A: large image as it is", large.copy()),
    ("B: large image, red/blue swapped", np.ascontiguousarray(large[..., ::-1])),
    ("C: small image as I420", cv2.cvtColor(small, cv2.COLOR_YUV2BGR_I420)),
    ("D: small image as YV12", cv2.cvtColor(small, cv2.COLOR_YUV2BGR_YV12)),
]
for text, image in tiles:
    cv2.rectangle(image, (0, 0), (640, 34), (0, 0, 0), -1)
    cv2.putText(image, text, (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
collage = np.vstack([np.hstack([tiles[0][1], tiles[1][1]]), np.hstack([tiles[2][1], tiles[3][1]])])
target = Path.home() / "colour_test.jpg"
cv2.imwrite(str(target), collage)
print(f"Saved: {target}")
