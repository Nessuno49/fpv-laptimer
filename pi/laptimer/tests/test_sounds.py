import tempfile
import unittest
from pathlib import Path

from sounds import MAX_BYTES, Library


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.lib = Library(self.folder)

    def test_save_and_list(self):
        self.lib.save("Airhorn.mp3", b"abc")
        self.lib.save("f1 start.WAV", b"abc")
        (self.folder / "README.md").write_text("x")          # not a sound -> not in the list
        self.assertEqual(self.lib.list(), ["Airhorn.mp3", "f1_start.WAV"])

    def test_name_is_cleaned(self):
        self.assertEqual(self.lib.save("../../bäd file!.mp3", b"x"), "b_d_file_.mp3")
        self.assertTrue((self.folder / "b_d_file_.mp3").exists())

    def test_only_sound_extensions(self):
        with self.assertRaises(ValueError):
            self.lib.save("virus.exe", b"x")

    def test_too_big(self):
        with self.assertRaises(ValueError):
            self.lib.save("big.mp3", b"x" * (MAX_BYTES + 1))

    def test_empty(self):
        with self.assertRaises(ValueError):
            self.lib.save("empty.mp3", b"")

    def test_path_stays_in_folder(self):
        self.lib.save("good.mp3", b"x")
        self.assertEqual(self.lib.path("good.mp3"), (self.folder / "good.mp3").resolve())
        for bad in ("../x.mp3", "missing.mp3", "README.md"):
            with self.assertRaises(ValueError):
                self.lib.path(bad)

    def test_delete(self):
        self.lib.save("gone.mp3", b"x")
        self.lib.delete("gone.mp3")
        self.assertEqual(self.lib.list(), [])


if __name__ == "__main__":
    unittest.main()
