#!/usr/bin/env python3
"""Lap timer – lap timing by camera for up to 8 pilots.

Starts camera, detector, race controller and web server.
Open in the browser:  http://laptimer.local
Stop with Ctrl+C (or systemctl --user stop laptimer).
"""
import threading
import time
from pathlib import Path

import camera
import embedding
import speech
import webserver
from config import Config
from database import Database
from detector import Detector
from photos import Photos
from race import RaceController
from sounds import Library

HERE = Path(__file__).resolve().parent
WEB_PORTS = (80, 8080)  # 80 = default (address without ":8080"), 8080 as before
# Folders of the German version -> new names (renamed once at the start)
OLD_FOLDERS = {"bilder": "photos", "sprachcache": "voice_cache"}


def rename_old_folders(base):
    for old, new in OLD_FOLDERS.items():
        if (base / old).is_dir() and not (base / new).exists():
            (base / old).rename(base / new)
            print(f"Folder {old}/ renamed to {new}/", flush=True)
    for marker in (base / "voice_cache").glob("*/stimme.txt"):
        marker.rename(marker.with_name("voice.txt"))


def ticker(race):
    """Drives the countdown and the time limit."""
    while True:
        race.tick()
        time.sleep(0.05)


def cleaner(photos, db, config):
    """Deletes expired photos once an hour."""
    while True:
        try:
            with config.lock:
                months = config.data["photo_months"]
            deleted = photos.clean_up(db, months)
            if deleted:
                print(f"{len(deleted)} old photos deleted", flush=True)
        except Exception as e:
            print(f"Error cleaning up photos: {e!r}", flush=True)
        time.sleep(3600)


def main():
    rename_old_folders(HERE)
    config = Config(HERE / "config.json")
    db = Database(str(HERE / "laptimer.db"))
    photos = Photos(HERE / "photos")

    def min_lap():
        with config.lock:
            return config.data["min_lap_s"]

    race = RaceController(db, min_lap=min_lap)
    with config.lock:
        v = dict(config.data["voice"])
    worker = speech.Worker(Path(v["python"]).expanduser(), HERE / "speech_worker.py")
    voice_output = speech.Speech(HERE / "voice_cache", Path(v["voices_dir"]).expanduser(), worker,
                                 names=lambda: [p["name"] for p in db.pilots()])
    app = webserver.App(config, db, race, photos, Library(HERE / "sounds"), voice_output)

    with config.lock:
        cam = camera.open_camera(config.data)
    app.camera = cam
    net = embedding.load(HERE / "models" / "mobilenetv2-12.onnx")
    app.detector = Detector(config, app.crossing, photos, net,
                            to_card=lambda: race.status == "running")  # race or practice
    threading.Thread(target=app.detector.run, args=(cam,), daemon=True).start()
    threading.Thread(target=ticker, args=(race,), daemon=True).start()
    threading.Thread(target=cleaner, args=(photos, db, config), daemon=True).start()

    server = webserver.start(app, WEB_PORTS[1])
    try:  # port 80 needs the permission from pi/network/99-laptimer-port80.conf
        server80 = webserver.start(app, WEB_PORTS[0])
        threading.Thread(target=server80.serve_forever, daemon=True).start()
        print("Lap timer running. Open in the browser: http://laptimer.local", flush=True)
    except OSError as e:
        print(f"Port 80 not available ({e.strerror}) – only http://laptimer.local:{WEB_PORTS[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        cam.close()


if __name__ == "__main__":
    main()
