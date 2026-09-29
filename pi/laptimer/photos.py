"""Photos of crossings: storage in one folder per day, and cleaning up.

Name of a photo: "YYYY-MM-DD/HHMMSS_mmm_n.jpg" relative to the photo folder.
Photos only go to the SD card while a race or practice is running. Otherwise only the
last IN_MEMORY photos are kept in memory (for "Recent crossings" in the camera tab).
Photos not referenced in the database (practice, false triggers) are deleted after UNUSED_H
hours, photos of races after the configured number of months.
"""
import collections
import datetime
import itertools
import shutil
import threading
from pathlib import Path

UNUSED_H = 12    # keep photos that are not used anywhere this long
IN_MEMORY = 20   # this many photos outside of races are kept in memory


class Photos:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self._counter = itertools.count(1)
        self._memory = collections.OrderedDict()  # name -> JPEG (in memory only)
        self._lock = threading.Lock()

    def save(self, image, to_card=True, now=None):
        """Store an image as JPEG – on the SD card or only in memory. Returns the name."""
        import cv2
        ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError("Could not encode the photo")
        name = self.new_name(now, make_folder=to_card)
        if to_card:
            self.path(name).write_bytes(jpg.tobytes())
        else:
            with self._lock:
                self._memory[name] = jpg.tobytes()
                while len(self._memory) > IN_MEMORY:
                    self._memory.popitem(last=False)
        return name

    def read(self, name):
        """JPEG data of a photo, or None if it is not (or no longer) there."""
        with self._lock:
            if name in self._memory:
                return self._memory[name]
        path = self.path(name)
        return path.read_bytes() if path.is_file() else None

    def new_name(self, now=None, make_folder=True):
        now = now or datetime.datetime.now()
        name = f"{now:%Y-%m-%d}/{now:%H%M%S}_{now.microsecond // 1000:03d}_{next(self._counter)}.jpg"
        if make_folder:
            self.path(name).parent.mkdir(parents=True, exist_ok=True)
        return name

    def path(self, name):
        path = (self.folder / name).resolve()
        if self.folder not in path.parents:
            raise ValueError("Invalid photo name")
        return path

    def delete(self, names):
        for name in names:
            if name:
                try:
                    self.path(name).unlink(missing_ok=True)
                except (ValueError, OSError):
                    pass

    def clean_up(self, db, months, now=None):
        """Deletes expired photos. Returns the deleted names."""
        now = now or datetime.datetime.now()
        unused_limit = now - datetime.timedelta(hours=UNUSED_H)
        race_limit = (now - datetime.timedelta(days=round(months * 30.4))).date()
        referenced = db.referenced_photos()
        deleted = []
        for day in sorted(self.folder.iterdir()):
            try:
                date = datetime.date.fromisoformat(day.name)
            except ValueError:
                continue  # some other folder
            for file in day.iterdir():
                name = f"{day.name}/{file.name}"
                if name in referenced:
                    if date < race_limit:
                        file.unlink(missing_ok=True)
                        db.remove_photo(name)
                        deleted.append(name)
                elif _taken_at(date, file) < unused_limit:
                    file.unlink(missing_ok=True)
                    deleted.append(name)
            if not any(day.iterdir()):
                shutil.rmtree(day, ignore_errors=True)
        return deleted


def _taken_at(date, file):
    """When the photo was taken: from folder (date) and file name (HHMMSS_…), otherwise file time."""
    try:
        return datetime.datetime.combine(date, datetime.datetime.strptime(file.name[:6], "%H%M%S").time())
    except ValueError:
        return datetime.datetime.fromtimestamp(file.stat().st_mtime)
