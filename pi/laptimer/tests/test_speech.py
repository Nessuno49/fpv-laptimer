import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from speech import Speech, split, voice_language, whole_sentence


class SplitTest(unittest.TestCase):
    def test_lap_callout(self):
        self.assertEqual(split("Anna. 8.3. Best lap!"),
                         [("Anna", True), ("8", False), ("point", False), ("3", True), ("Best lap!", True)])
        self.assertEqual(split("Anna. 8,3. Bestzeit!", "de"),
                         [("Anna", True), ("8", False), ("Komma", False), ("3", True), ("Bestzeit!", True)])

    def test_result(self):
        self.assertEqual(
            [s for s, _ in split("Rennen beendet. Sieger: Anna, 5 Runden, in 45,32 Sekunden.", "de")],
            ["Rennen beendet", "Sieger", "Anna", "5", "Runden", "in", "45", "Komma", "32", "Sekunden"])
        self.assertEqual(
            [s for s, _ in split("Race over. Winner: Anna, 5 laps, in 45.32 seconds.")],
            ["Race over", "Winner", "Anna", "5", "laps", "in", "45", "point", "32", "seconds"])

    def test_decimals_with_zero(self):
        self.assertEqual([s for s, _ in split("12,05", "de")], ["12", "Komma", "0", "5"])
        self.assertEqual([s for s, _ in split("12.05")], ["12", "point", "0", "5"])

    def test_whole_sentence(self):
        self.assertEqual(whole_sentence("Rennen beendet.  Sieger: Anna, in 3 Minuten, 40,05 Sekunden.", "de"),
                         "Rennen beendet. Sieger: Anna, in 3 Minuten, 40 Komma 0 5 Sekunden.")
        self.assertEqual(whole_sentence("Race over. Anna, in 40.5 seconds."),
                         "Race over. Anna, in 40 point 5 seconds.")

    def test_spaces_and_empty(self):
        self.assertEqual(split("  Go!  "), [("Go!", True)])
        self.assertEqual(split("..."), [])

    def test_voice_language(self):
        self.assertEqual(voice_language("de_DE-thorsten-high"), "de")
        self.assertEqual(voice_language("en_GB-alan-medium"), "en")
        self.assertEqual(voice_language("fr_FR-siwis-low"), "en")


class FakeWorker:
    """Instead of Piper: writes a small file and remembers the jobs."""

    def __init__(self, error=None, piper=True):
        self.jobs = []
        self.error = error
        self.caps = {"piper": piper}

    def capabilities(self):
        return self.caps

    def generate(self, job):
        self.jobs.append(job)
        if self.error:
            raise RuntimeError(self.error)
        Path(job["target"]).write_bytes(b"RIFF")


def wait_until(condition, s=5):
    end = time.monotonic() + s
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("Timeout")
        time.sleep(0.01)


class SpeechTest(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.voices = base / "voices"
        self.voices.mkdir()
        (self.voices / "de_DE-thorsten-high.onnx").write_bytes(b"x")
        (self.voices / "de_DE-thorsten-high.onnx.json").write_text(json.dumps({"num_speakers": 1}))
        (self.voices / "de_DE-thorsten_emotional-medium.onnx").write_bytes(b"x")
        (self.voices / "de_DE-thorsten_emotional-medium.onnx.json").write_text(
            json.dumps({"num_speakers": 3, "speaker_id_map": {"amused": 0, "angry": 1, "2": 2}}))
        (self.voices / "en_US-lessac-high.onnx").write_bytes(b"x")
        (self.voices / "en_US-lessac-high.onnx.json").write_text(json.dumps({"num_speakers": 1}))
        (self.voices / "no-json.onnx").write_bytes(b"x")
        self.cache = base / "cache"
        self.names = ["Anna", "Ben"]
        self.worker = FakeWorker()
        self.sp = Speech(self.cache, self.voices, self.worker, names=lambda: self.names)

    def test_voice_list(self):
        found = self.sp.voices()
        ids = [v["id"] for v in found]
        self.assertIn("piper:de_DE-thorsten-high", ids)
        self.assertNotIn("piper:no-json", ids)
        emo = next(v for v in found if v["id"] == "piper:de_DE-thorsten_emotional-medium")
        self.assertEqual([s["name"] for s in emo["speakers"]], ["amused", "angry", None])
        self.assertEqual((emo["name"], emo["language"], emo["locale"]),
                         ("Thorsten emotional (medium)", "de", "de_DE"))
        lessac = next(v for v in found if v["id"] == "piper:en_US-lessac-high")
        self.assertEqual(lessac["language"], "en")

    def test_without_worker_no_pi_voices(self):
        sp = Speech(self.cache, self.voices, FakeWorker(piper=False))
        self.assertEqual(sp.voices(), [])

    def test_parts_generates_and_uses_cache(self):
        parts = self.sp.parts("piper:de_DE-thorsten_emotional-medium:1", "Anna. 8,3. Bestzeit!")
        self.assertEqual(len(parts), 5)
        self.assertTrue(parts[0]["url"].startswith("/speech/piper_de_DE-thorsten_emotional-medium_1/"))
        self.assertTrue(parts[0]["url"].endswith(".wav"))
        self.assertEqual(self.worker.jobs[0]["speaker"], 1)
        count = len(self.worker.jobs)
        self.assertEqual(count, 5)
        self.sp.parts("piper:de_DE-thorsten_emotional-medium:1", "Anna. 8,3. Bestzeit!")
        self.assertEqual(len(self.worker.jobs), count)   # everything from the cache
        folder, file = parts[0]["url"].split("/")[2:]
        self.assertTrue(self.sp.file_path(folder, file).is_file())

    def test_english_voice_says_point(self):
        self.sp.parts("piper:en_US-lessac-high", "Anna. 8.3. Best lap!")
        self.assertEqual([j["text"] for j in self.worker.jobs], ["Anna", "8", "point", "3", "Best lap!"])

    def test_whole_is_one_snippet(self):
        parts = self.sp.parts("piper:de_DE-thorsten-high", "Rennen beendet. Sieger: Anna, 8,3 Sekunden.", whole=True)
        self.assertEqual(len(parts), 1)
        self.assertEqual(self.worker.jobs[-1]["text"], "Rennen beendet. Sieger: Anna, 8 Komma 3 Sekunden.")
        self.assertEqual(self.sp.parts("piper:de_DE-thorsten-high", "  ", whole=True), [])

    def test_invalid_voices(self):
        for bad in ("piper:../../etc/passwd", "piper:missing", "edge:Hacker", "browser:x",
                    "piper:de_DE-thorsten-high:abc"):
            with self.assertRaises(ValueError):
                self.sp.parts(bad, "Go!")

    def test_file_path_stays_in_cache(self):
        with self.assertRaises(ValueError):
            self.sp.file_path("..", "secret.wav")

    def test_error_is_reported(self):
        sp = Speech(self.cache, self.voices, FakeWorker(error="no internet"))
        with self.assertRaisesRegex(ValueError, "no internet"):
            sp.parts("piper:de_DE-thorsten-high", "Los!")

    def test_prepare(self):
        voice = "piper:de_DE-thorsten-high"
        self.sp.prepare(voice)
        wait_until(lambda: self.sp.status(voice)["done"] == self.sp.status(voice)["total"])
        texts = {j["text"] for j in self.worker.jobs}
        self.assertTrue({"0", "42", "99", "Komma", "Anna", "Ben", "Neuer Rekord!"} <= texts)
        self.assertNotIn("point", texts)
        # new pilot: only the name is generated
        before = len(self.worker.jobs)
        self.names.append("Carla")
        self.sp.prepare_names()
        wait_until(lambda: len(self.worker.jobs) == before + 1)
        self.assertEqual(self.worker.jobs[-1]["text"], "Carla")

    def test_prepare_english(self):
        voice = "piper:en_US-lessac-high"
        self.sp.prepare(voice)
        wait_until(lambda: self.sp.status(voice)["done"] == self.sp.status(voice)["total"])
        texts = {j["text"] for j in self.worker.jobs}
        self.assertTrue({"point", "New record!", "Best lap!", "Anna"} <= texts)
        self.assertNotIn("Komma", texts)

    def test_status_from_cache(self):
        voice = "piper:de_DE-thorsten-high"
        self.sp.parts(voice, "Anna")
        fresh = Speech(self.cache, self.voices, self.worker, names=lambda: self.names)
        s = fresh.status(voice)
        self.assertEqual(s["done"], 1)
        self.assertGreater(s["total"], 100)

    def test_live_callout_before_preparation(self):
        """A callout does not wait until the whole preparation is through."""
        slow = threading.Event()
        worker = self.worker
        original = worker.generate

        def slowed(job):
            if not slow.is_set():
                time.sleep(0.005)
            original(job)
        worker.generate = slowed
        voice = "piper:de_DE-thorsten-high"
        self.sp.prepare(voice)
        self.sp.parts(voice, "Meanwhile")
        s = self.sp.status(voice)
        self.assertLess(s["done"], s["total"])  # preparation was still running
        slow.set()


if __name__ == "__main__":
    unittest.main()
