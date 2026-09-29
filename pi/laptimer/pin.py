#!/usr/bin/env python3
"""Set or reset the race director PIN – only directly on the Pi (via SSH).

Usage (the lap timer must be running):
    python3 ~/laptimer/pin.py

This deliberately does not work over the Wi-Fi: otherwise someone could get in first and set
a PIN before you do. If you forgot the PIN, simply set a new one here.
Afterwards all race director devices are signed out and sign in again with the new PIN.
"""
import getpass
import json
import sys
import urllib.error
import urllib.request

ADDRESS = "http://127.0.0.1:8080"


def main():
    pin = getpass.getpass("New race director PIN (4–8 digits, not shown): ").strip()
    if getpass.getpass("Once more to be sure: ").strip() != pin:
        sys.exit("The two entries differ – nothing changed.")
    request = urllib.request.Request(ADDRESS + "/api/pin", data=json.dumps({"pin": pin}).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except urllib.error.HTTPError as e:
        with e:
            sys.exit("Error: " + json.loads(e.read() or b"{}").get("error", str(e)))
    except urllib.error.URLError:
        sys.exit("The lap timer does not answer. Is it running? (systemctl --user status laptimer)")
    print("✓ PIN saved. Sign in as race director in the browser with the new PIN.")


if __name__ == "__main__":
    main()
