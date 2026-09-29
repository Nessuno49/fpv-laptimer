"""Speech from the Pi: callouts are put together from ready-made snippets.

A callout like "Anna. 8.3. Best lap!" is split into "Anna" · "8" · "point" · "3" · "Best lap!"
(German: "Anna. 8,3. Bestzeit!" -> "Anna" · "8" · "Komma" · "3" · "Bestzeit!").
Each snippet is generated once per voice with Piper and stored in the folder voice_cache/. Preparing
a voice generates all common snippets in advance – during a race the browser only plays finished files.

The language of a voice comes from its model name (de_DE-… speaks German, en_US-… English).
Generation happens in the helper process speech_worker.py (runs in ~/piper-venv).
"""
import hashlib
import itertools
import json
import os
import queue
import re
import subprocess
import threading
from pathlib import Path

from i18n import UserError

LANGUAGES = ("en", "de")

# Word for the decimal separator when spoken, and the separator itself
DECIMAL = {"en": ("point", "."), "de": ("Komma", ",")}

# Everything web/app.js calls out (without names and numbers) – generated when preparing a voice.
# Anything missing here is generated the first time it is used.
FIXED_TEXTS = {
    "en": [
        "Go!", "Callouts on", "Last lap", "Finished", "30 seconds left", "Time's up. Last lap",
        "Race over.", "Winner:", "lap", "laps", "in", "seconds", "minute", "minutes", "point", "Best lap!",
        "Personal best!", "New record!", "Practice", "Practice over", "Race aborted",
        "60 seconds to start",  # staging (the number becomes its own snippet)
        "Ben. Lap 4. 8.3. Best lap!",  # "Test voice"
    ],
    "de": [
        "Los!", "Ansage an", "Letzte Runde", "Im Ziel", "Noch 30 Sekunden", "Zeit abgelaufen. Letzte Runde",
        "Rennen beendet.", "Sieger:", "Runde", "Runden", "in", "Sekunden", "Minute", "Minuten", "Komma",
        "Bestzeit!", "Persönliche Bestzeit!", "Neuer Rekord!", "Training", "Training beendet",
        "Rennen abgebrochen",
        "Noch 60 Sekunden bis zum Start",  # staging (the number becomes its own snippet)
        "Ben. Runde 4. 8,3. Bestzeit!",  # "Test voice"
    ],
}
NUMBERS_UP_TO = 100       # generate 0 … 99 in advance
WAIT_S = 15               # a callout waits at most this long for missing snippets


def _decimals(digits):
    # "05" -> "0 5" (zero five), otherwise as a number ("3", "32")
    return " ".join(digits) if len(digits) > 1 and digits[0] == "0" else digits


def _spell_decimals(text, lang):
    word, sep = DECIMAL[lang]
    return re.sub(rf"(\d+){re.escape(sep)}(\d+)", lambda m: f"{m[1]} {word} {_decimals(m[2])}", text)


def whole_sentence(text, lang="en"):
    """The whole callout as one snippet – sounds smoother but needs computing time (after the race)."""
    return " ".join(_spell_decimals(text, lang).split())


def split(text, lang="en"):
    """Text -> [(snippet, pause_after), …]. Numbers become snippets of their own."""
    text = _spell_decimals(text, lang)
    parts = []
    for sentence in re.findall(r"[^.,:;!?]+[.,:;!?]*", text):
        sentence = " ".join(sentence.split())
        content = sentence.rstrip(".,:;!? ")
        if not content:
            continue
        rest = sentence[len(content):]
        end = "!" if "!" in rest else "?" if "?" in rest else ""
        pieces = [s.strip() for s in re.split(r"(\d+)", content) if s.strip()]
        for i, piece in enumerate(pieces):
            last = i == len(pieces) - 1
            parts.append((piece + end if last else piece, last))
    return parts


def voice_language(model):
    """de_DE-thorsten-high -> "de"; unknown languages count as English."""
    code = model.split("_")[0].split("-")[0].lower()
    return code if code in LANGUAGES else "en"


class Worker:
    """Starts speech_worker.py with the Python of the Piper environment and sends it jobs."""

    def __init__(self, python, script):
        self.python, self.script = str(python), str(script)
        self.proc = None
        self.info = None
        self.lock = threading.Lock()

    def _start(self):
        if self.proc and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen([self.python, self.script], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        line = self.proc.stdout.readline()
        if not line:
            self.proc = None
            raise RuntimeError("Speech worker does not start")
        self.info = json.loads(line)

    def capabilities(self):
        """{"piper": bool} – whether Piper is installed in the Piper environment."""
        if self.info is not None:
            return {"piper": self.info["piper"]}
        with self.lock:
            try:
                self._start()
            except (OSError, RuntimeError, ValueError):
                return {"piper": False}
            return {"piper": self.info["piper"]}

    def generate(self, job):
        with self.lock:
            try:
                self._start()
            except OSError as e:
                raise RuntimeError(f"Cannot start the speech worker ({self.python}): {e}") from e
            self.proc.stdin.write(json.dumps(job) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
            if not line:
                self.proc = None
                raise RuntimeError("Speech worker crashed")
            answer = json.loads(line)
            if "error" in answer:
                raise RuntimeError(answer["error"])


class _Job:
    def __init__(self, voice, text):
        self.voice, self.text = voice, text
        self.done = threading.Event()
        self.error = None
        self.run = None  # number of the preparation this job belongs to


class Speech:
    def __init__(self, cache_folder, voices_folder, worker, names=lambda: []):
        self.cache = Path(cache_folder).resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.voices_folder = Path(voices_folder)
        self.worker = worker
        self.names = names                    # returns the pilot names
        self.progress = {}                    # voice -> {"done", "total", "error", "run"}
        self.lock = threading.Lock()
        self.jobs = queue.PriorityQueue()
        self.counter = itertools.count()      # same priority: in order
        threading.Thread(target=self._work, daemon=True).start()

    # ------------------------------------------------------------ voices

    def voices(self):
        """All available voices for the dropdown."""
        found = []
        if self.worker.capabilities()["piper"]:
            for onnx in sorted(self.voices_folder.glob("*.onnx")):
                entry = self._piper_entry(onnx)
                if entry:
                    found.append(entry)
        return found

    def _piper_entry(self, onnx):
        try:
            info = json.loads(Path(f"{onnx}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # not usable without .onnx.json
        parts = onnx.stem.split("-")  # de_DE-thorsten_emotional-medium
        name = parts[1].replace("_", " ").capitalize() if len(parts) > 1 else onnx.stem
        if len(parts) > 2:
            name += f" ({parts[2]})"
        entry = {"id": f"piper:{onnx.stem}", "name": name, "locale": parts[0],
                 "language": voice_language(onnx.stem)}
        if info.get("num_speakers", 1) > 1:
            names = {nr: n for n, nr in (info.get("speaker_id_map") or {}).items()}
            # name None: the browser shows "Speaker <nr>"; emotions ("amused" …) it translates itself
            entry["speakers"] = [{"nr": nr, "name": self._speaker_name(names.get(nr))}
                                 for nr in range(info["num_speakers"])]
        return entry

    @staticmethod
    def _speaker_name(raw):
        return raw if raw and not raw.isdigit() else None

    def _base_job(self, voice):
        """Checks the voice ID and returns the base job for the speech worker."""
        kind, _, rest = voice.partition(":")
        if kind == "piper":
            model, _, speaker = rest.partition(":")
            path = self.voices_folder / f"{model}.onnx"
            if re.fullmatch(r"[\w.-]+", model) and path.is_file() and (not speaker or speaker.isdigit()):
                return {"kind": "piper", "model": str(path.resolve()),
                        "speaker": int(speaker) if speaker else None}
        raise UserError("unknown_voice", voice=voice)

    def language(self, voice):
        self._base_job(voice)
        return voice_language(voice.partition(":")[2])

    # ------------------------------------------------------------ files

    def _folder(self, voice):
        return re.sub(r"[^\w.-]", "_", voice)

    def _file(self, voice, text):
        self._base_job(voice)  # valid voice?
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16] + ".wav"

    def _path(self, voice, text):
        return self.cache / self._folder(voice) / self._file(voice, text)

    def file_path(self, folder, file):
        """Path of a cache file for the web server (only inside voice_cache/)."""
        path = (self.cache / folder / file).resolve()
        if path.parent.parent != self.cache or not path.is_file():
            raise UserError("not_found")
        return path

    # ------------------------------------------------------------ generating

    def _work(self):
        while True:
            _, _, job = self.jobs.get()
            try:
                self._generate(job.voice, job.text)
            except Exception as e:
                job.error = str(e) or e.__class__.__name__
            job.done.set()
            with self.lock:
                p = self.progress.get(job.voice)
                if p and job.run is not None and p["run"] == job.run:
                    p["done"] += 1
                    if job.error:
                        p["error"] = job.error

    def _generate(self, voice, text):
        path = self._path(voice, text)
        if path.is_file():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "voice.txt").write_text(voice, encoding="utf-8")
        base = self._base_job(voice)
        tmp = path.with_name(path.stem + ".tmp.wav")
        self.worker.generate({**base, "text": text, "target": str(tmp)})
        if not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("The speech worker did not create a file")
        os.replace(tmp, path)

    def parts(self, voice, text, wait=WAIT_S, whole=False):
        """Snippets of a callout as URLs. Missing ones are generated at once (with priority).

        whole=True: the whole text becomes a single snippet (for callouts after the race).
        """
        lang = self.language(voice)
        if whole:
            sentence = whole_sentence(text, lang)
            snippets = [(sentence, True)] if sentence else []
        else:
            snippets = split(text, lang)
        missing = [_Job(voice, s) for s in dict.fromkeys(s for s, _ in snippets)
                   if not self._path(voice, s).is_file()]
        for job in missing:
            self.jobs.put((0, next(self.counter), job))
        for job in missing:
            if not job.done.wait(wait):
                raise UserError("voice_too_slow")
            if job.error:
                raise ValueError(job.error)
        folder = self._folder(voice)
        return [{"url": f"/speech/{folder}/{self._file(voice, s)}", "pause": pause}
                for s, pause in snippets]

    def all_snippets(self, lang):
        texts = FIXED_TEXTS[lang] + [str(n) for n in range(NUMBERS_UP_TO)] + list(self.names())
        return list(dict.fromkeys(s for t in texts for s, _ in split(t, lang)))

    def prepare(self, voice):
        """Generates all common snippets of this voice in the background."""
        snippets = self.all_snippets(self.language(voice))
        missing = [s for s in snippets if not self._path(voice, s).is_file()]
        run = next(self.counter)
        with self.lock:
            self.progress[voice] = {"done": len(snippets) - len(missing),
                                    "total": len(snippets), "error": None, "run": run}
        for s in missing:
            job = _Job(voice, s)
            job.run = run
            self.jobs.put((1, next(self.counter), job))

    def prepare_names(self):
        """After a new/renamed pilot: generate the names for all voices already in use."""
        for file in self.cache.glob("*/voice.txt"):
            voice = file.read_text(encoding="utf-8").strip()
            try:
                self.prepare(voice)
            except ValueError:
                pass  # voice no longer exists

    def status(self, voice):
        """How far is the preparation? Without preparation in this session: counted from the cache."""
        lang = self.language(voice)
        with self.lock:
            if voice in self.progress:
                p = self.progress[voice]
                return {"done": p["done"], "total": p["total"], "error": p["error"]}
        snippets = self.all_snippets(lang)
        done = sum(self._path(voice, s).is_file() for s in snippets)
        return {"done": done, "total": len(snippets), "error": None}
