"""Wi-Fi QR code as a 3D print (STL): white base plate + black raised code and text.

Usage (needs segno, numpy, opencv):  python tools/qr_stl.py
Creates in 3d-print/:
  laptimer_qr_plate.stl     base plate (white)
  laptimer_qr_code.stl      QR code + text, sits exactly on the plate (black)
  laptimer_qr_complete.stl  both in one file (for printers without multi-part import)
  laptimer_qr_preview.png   top view for checking
"""
import struct
from pathlib import Path

import cv2
import numpy as np
import segno

SSID, PASSWORD = "Laptimer", "choose-your-own-password"   # use the password of YOUR hotspot
CONTENT = f"WIFI:T:WPA;S:{SSID};P:{PASSWORD};;"

MODULE_MM = 2.0         # edge length of one QR module
BORDER_MODULES = 3      # white border around the code (quiet zone), in modules
PLATE_MM = 1.6          # thickness of the base plate (8 layers of 0.2 mm)
RAISED_MM = 0.6         # code and text stand out this far (3 layers)
TEXT_PIXEL_MM = 0.2     # grid size for the lettering
TEXT = ["Wi-Fi: " + SSID, "Password: " + PASSWORD]
TEXT_HEIGHT_MM = 4.5
TEXT_GAP_MM = 2.5

TARGET = Path(__file__).resolve().parent.parent / "3d-print"


def qr_grid():
    qr = segno.make(CONTENT, error="q", micro=False)
    return np.array([[bool(v) for v in row] for row in qr.matrix]), qr.version


def text_grid(width_mm):
    """Text as a pixel grid (True = raised), fitting into width_mm."""
    width_px = int(width_mm / TEXT_PIXEL_MM)
    rows = []
    for text in TEXT:
        scale = 1.0
        (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 1)
        scale = TEXT_HEIGHT_MM / TEXT_PIXEL_MM / h                        # wanted height
        thickness = max(2, round(0.5 / TEXT_PIXEL_MM))                    # stroke ~0.5 mm (nozzle 0.4)
        (w, h), below = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thickness)
        if w > width_px:                                                  # too wide: make smaller
            scale *= width_px / w
            (w, h), below = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, thickness)
        image = np.zeros((h + below + 2 * thickness, width_px), np.uint8)
        cv2.putText(image, text, ((width_px - w) // 2, h + thickness), cv2.FONT_HERSHEY_DUPLEX, scale, 255,
                    thickness, cv2.LINE_8)
        rows.append(image > 127)
        rows.append(np.zeros((int(TEXT_GAP_MM / TEXT_PIXEL_MM), width_px), bool))
    return np.vstack(rows[:-1])


def grid_mesh(grid, cell, x0, y0, z0, z1):
    """Triangles for all True cells as boxes from z0 to z1 (side walls only facing outwards).

    grid[0] is the TOP row. Returns a list of triangles (3 points each).
    """
    rows, cols = grid.shape
    padded = np.pad(grid, 1)
    triangles = []

    def quad(a, b, c, d):  # points counter-clockwise seen from outside
        triangles.append((a, b, c))
        triangles.append((a, c, d))

    for r, s in zip(*np.nonzero(grid)):
        xa, xb = x0 + s * cell, x0 + (s + 1) * cell
        yb, ya = y0 + (rows - r) * cell, y0 + (rows - r - 1) * cell
        quad((xa, ya, z1), (xb, ya, z1), (xb, yb, z1), (xa, yb, z1))      # top
        quad((xa, ya, z0), (xa, yb, z0), (xb, yb, z0), (xb, ya, z0))      # bottom
        R, S = r + 1, s + 1
        if not padded[R, S - 1]:  # left
            quad((xa, ya, z0), (xa, ya, z1), (xa, yb, z1), (xa, yb, z0))
        if not padded[R, S + 1]:  # right
            quad((xb, ya, z0), (xb, yb, z0), (xb, yb, z1), (xb, ya, z1))
        if not padded[R - 1, S]:  # back (top in the image)
            quad((xa, yb, z0), (xa, yb, z1), (xb, yb, z1), (xb, yb, z0))
        if not padded[R + 1, S]:  # front (bottom in the image)
            quad((xa, ya, z0), (xb, ya, z0), (xb, ya, z1), (xa, ya, z1))
    return triangles


def box(x0, y0, z0, x1, y1, z1):
    """A box: the unit cube from grid_mesh stretched to the wanted size."""
    cube = grid_mesh(np.ones((1, 1), bool), 1.0, 0, 0, 0, 1)
    return [tuple((x0 + x * (x1 - x0), y0 + y * (y1 - y0), z0 + z * (z1 - z0)) for x, y, z in t)
            for t in cube]


def write_stl(path, triangles, name):
    with open(path, "wb") as f:
        f.write(name.encode().ljust(80, b" "))
        f.write(struct.pack("<I", len(triangles)))
        for a, b, c in triangles:
            a, b, c = (np.array(p, float) for p in (a, b, c))
            n = np.cross(b - a, c - a)
            n = n / (np.linalg.norm(n) or 1)
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))


def main():
    TARGET.mkdir(exist_ok=True)
    qr, version = qr_grid()
    n = qr.shape[0]
    qr_mm = n * MODULE_MM
    border = BORDER_MODULES * MODULE_MM
    width = qr_mm + 2 * border
    text = text_grid(width - 2 * border)
    text_h = text.shape[0] * TEXT_PIXEL_MM
    height = border + text_h + border + qr_mm + border       # from the bottom: border, text, border, QR, border

    plate = box(0, 0, 0, width, height, PLATE_MM)
    z0, z1 = PLATE_MM, PLATE_MM + RAISED_MM
    code = grid_mesh(qr, MODULE_MM, border, height - border - qr_mm, z0, z1)
    code += grid_mesh(text, TEXT_PIXEL_MM, border, border, z0, z1)
    write_stl(TARGET / "laptimer_qr_plate.stl", plate, "Laptimer QR plate")
    write_stl(TARGET / "laptimer_qr_code.stl", code, "Laptimer QR code")
    write_stl(TARGET / "laptimer_qr_complete.stl", plate + code, "Laptimer QR complete")

    # preview (top view, 10 px per mm) and scan test
    px = 10
    preview = np.full((int(height * px), int(width * px)), 255, np.uint8)
    qr_px = cv2.resize(qr.astype(np.uint8), (int(qr_mm * px),) * 2, interpolation=cv2.INTER_NEAREST)
    y_qr, x_qr = int(border * px), int(border * px)
    preview[y_qr:y_qr + qr_px.shape[0], x_qr:x_qr + qr_px.shape[1]][qr_px > 0] = 0
    text_px = cv2.resize(text.astype(np.uint8), (int(text.shape[1] * TEXT_PIXEL_MM * px),
                                                 int(text.shape[0] * TEXT_PIXEL_MM * px)),
                         interpolation=cv2.INTER_NEAREST)
    y_t = int((height - border - text_h) * px)
    preview[y_t:y_t + text_px.shape[0], x_qr:x_qr + text_px.shape[1]][text_px > 0] = 0
    cv2.imwrite(str(TARGET / "laptimer_qr_preview.png"), preview)
    read, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.cvtColor(preview, cv2.COLOR_GRAY2BGR))

    print(f"QR version {version}, {n}x{n} modules of {MODULE_MM} mm")
    print(f"Plate {width:.1f} x {height:.1f} x {PLATE_MM} mm, code/text +{RAISED_MM} mm")
    print(f"Triangles: plate {len(plate)}, code+text {len(code)}")
    print(f"Scan test: {'OK – ' + read if read == CONTENT else 'ERROR: ' + repr(read)}")


if __name__ == "__main__":
    main()
