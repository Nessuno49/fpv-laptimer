import datetime
import tempfile
import unittest
from pathlib import Path

from database import Database
from photos import Photos

try:
    import cv2  # noqa: F401
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False


class PhotosTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.photos = Photos(self.folder)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.anna = self.db.add_pilot("Anna")

    def create(self, date, name):
        path = self.folder / date / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpg")
        return f"{date}/{name}"

    def test_new_name_and_path(self):
        now = datetime.datetime(2026, 9, 24, 12, 30, 5, 123000)
        a = self.photos.new_name(now)
        b = self.photos.new_name(now)
        self.assertTrue(a.startswith("2026-09-24/"))
        self.assertNotEqual(a, b)
        self.assertTrue(self.photos.path(a).parent.is_dir())

    def test_path_stays_in_folder(self):
        with self.assertRaises(ValueError):
            self.photos.path("../secret.txt")

    def test_clean_up(self):
        now = datetime.datetime(2026, 9, 24, 12, 0)
        unused_new = self.create("2026-09-24", "010000_000_1.jpg")    # 11 h old: stays
        unused_old = self.create("2026-09-23", "235900_000_2.jpg")    # 12 h 1 min old: gone
        race_new = self.create("2026-08-01", "r1.jpg")
        race_old = self.create("2026-01-01", "r2.jpg")
        for photo in (race_new, race_old):
            self.db.save_pilot_race(self.anna, None, "laps", {"laps": 1}, "2026-01-01T10:00:00",
                                    "2026-01-01T10:01:00", [{"t": 1.0, "photo": photo}])

        deleted = self.photos.clean_up(self.db, months=6, now=now)

        self.assertEqual(sorted(deleted), sorted([unused_old, race_old]))
        self.assertTrue(self.photos.path(unused_new).exists())
        self.assertTrue(self.photos.path(race_new).exists())
        self.assertFalse((self.folder / "2026-01-01").exists())   # empty folder gone
        self.assertNotIn(race_old, self.db.referenced_photos())

    @unittest.skipUnless(HAS_OPENCV, "OpenCV not installed")
    def test_outside_races_only_in_memory(self):
        import numpy as np
        from photos import IN_MEMORY
        image = np.zeros((20, 30, 3), np.uint8)
        on_card = self.photos.save(image)
        in_memory = self.photos.save(image, to_card=False)
        self.assertTrue(self.photos.path(on_card).is_file())
        self.assertFalse(self.photos.path(in_memory).exists())        # nothing on the SD card
        jpeg_start = bytes([0xFF, 0xD8])
        self.assertTrue(self.photos.read(in_memory).startswith(jpeg_start))  # but readable (JPEG)
        self.assertTrue(self.photos.read(on_card).startswith(jpeg_start))
        for _ in range(IN_MEMORY):
            self.photos.save(image, to_card=False)
        self.assertIsNone(self.photos.read(in_memory))                # only the latest stay

    def test_delete(self):
        name = self.create("2026-09-24", "x.jpg")
        self.photos.delete([name, None, "2026-09-24/missing.jpg"])
        self.assertFalse(self.photos.path(name).exists())


if __name__ == "__main__":
    unittest.main()
