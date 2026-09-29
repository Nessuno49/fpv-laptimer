"""Sound library: your own sound files in the folder sounds/ (upload, list, delete).

Which file plays for which event is stored in config.json under "sound_mapping".
"""
import re
from pathlib import Path

from i18n import UserError

EXTENSIONS = (".mp3", ".wav", ".ogg")
MAX_BYTES = 5 * 1024 * 1024   # 5 MB per file


class Library:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)

    def list(self):
        return sorted((p.name for p in self.folder.iterdir()
                       if p.is_file() and p.suffix.lower() in EXTENSIONS), key=str.lower)

    def path(self, name):
        path = (self.folder / name).resolve()
        if path.parent != self.folder or path.suffix.lower() not in EXTENSIONS or not path.is_file():
            raise UserError("sound_not_found")
        return path

    def save(self, name, data):
        """Stores an uploaded file. Returns the (cleaned) file name."""
        name = Path(name).name                        # only the file name, no folders
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)  # only harmless characters
        if Path(name).suffix.lower() not in EXTENSIONS:
            raise UserError("sound_type")
        if not data:
            raise UserError("sound_empty")
        if len(data) > MAX_BYTES:
            raise UserError("sound_too_big", mb=MAX_BYTES // (1024 * 1024))
        (self.folder / name).write_bytes(data)
        return name

    def delete(self, name):
        self.path(name).unlink()
