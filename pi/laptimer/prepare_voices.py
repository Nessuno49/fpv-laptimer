#!/usr/bin/env python3
"""Prepares all Pi voices at once (instead of clicking each one in the settings).

Run on the Pi (the lap timer must be running):
    python3 ~/laptimer/prepare_voices.py

For voices with several speakers all speakers are prepared if there are at most
MAX_SPEAKERS (e.g. Thorsten emotional). With very many (e.g. mls) only the first –
you then pick further ones in the settings.
Cancel with Ctrl+C: the preparation on the Pi keeps running anyway.
"""
import json
import time
import urllib.parse
import urllib.request

ADDRESS = "http://localhost:8080"
MAX_SPEAKERS = 10


def api(path, data=None):
    request = urllib.request.Request(ADDRESS + path)
    if data is not None:
        request.data = json.dumps(data).encode()
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as answer:
        return json.load(answer)


def speaker_name(speaker):
    return speaker["name"] or f"speaker {speaker['nr']}"


def voice_ids():
    ids = []
    for v in api("/api/voices")["voices"]:
        speakers = v.get("speakers")
        if not speakers:
            ids.append((v["id"], v["name"]))
        elif len(speakers) <= MAX_SPEAKERS:
            ids += [(f"{v['id']}:{s['nr']}", f"{v['name']} – {speaker_name(s)}") for s in speakers]
        else:
            ids.append((f"{v['id']}:{speakers[0]['nr']}", f"{v['name']} – {speaker_name(speakers[0])}"))
            print(f"Note: {v['name']} has {len(speakers)} speakers – only the first is prepared.")
    return ids


def main():
    ids = voice_ids()
    if not ids:
        print("No Pi voices found. Is the lap timer running? Is Piper installed, are there voices in the voices folder?")
        return
    print(f"Preparing {len(ids)} voices one after the other.\n")
    for nr, (id, name) in enumerate(ids, 1):
        api("/api/voices/prepare", {"voice": id})
        start = time.monotonic()
        while True:
            s = api("/api/voices/status?voice=" + urllib.parse.quote(id))
            print(f"\r[{nr}/{len(ids)}] {name}: {s['done']}/{s['total']}   ", end="", flush=True)
            if s["done"] >= s["total"]:
                break
            time.sleep(1)
        duration = time.monotonic() - start
        print(f"✓ ({duration:.0f} s)" if not s["error"] else f"⚠ {s['error']}")
    print("\nDone – all voices are prepared.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled (preparation already started keeps running on the Pi).")
