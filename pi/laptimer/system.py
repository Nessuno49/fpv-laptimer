"""Shut down or restart the Pi (buttons in the settings).

The lap timer runs as a normal user. To switch off it needs permission:
the first user of Raspberry Pi OS may usually run "sudo" without a password – that is tried first.
Otherwise a permission for just these two commands in /etc/sudoers.d/laptimer helps.
"""
import subprocess
import threading

from i18n import UserError

COMMANDS = {"shutdown": "poweroff", "reboot": "reboot"}
DELAY_S = 1.5  # answer first, then switch off – otherwise the browser waits in vain


def run(action, start=subprocess.run, delay=DELAY_S):
    if action not in COMMANDS:
        raise ValueError(f"Unknown action: {action}")
    command = COMMANDS[action]
    try:  # may sudo run this command without a password? (-n: never ask, -l: only check)
        sudo_ok = start(["sudo", "-n", "-l", "systemctl", command], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        sudo_ok = False
    if sudo_ok:
        threading.Timer(delay, start, args=(["sudo", "-n", "systemctl", command],)).start()
        return
    try:  # without sudo: only works if the system allows it to the user
        r = start(["systemctl", command], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"Could not {action} the Pi: {e}") from e
    if r.returncode != 0:
        raise UserError("no_permission_shutdown")


# ---------------------------------------------------------------- hotspot password

HOTSPOT_PASSWORD_HELPER = "/usr/local/bin/laptimer-hotspot-password"   # pi/network/laptimer-hotspot-password


def set_hotspot_password(password, start=subprocess.run):
    """New password for the hotspot "Laptimer" (WPA2: 8–63 printable ASCII characters).

    Needs root, so it goes through a small helper that may be run with sudo (see README).
    If the hotspot is running, it restarts – connected phones have to reconnect.
    """
    password = str(password or "")
    if not 8 <= len(password) <= 63 or not all(" " <= c <= "~" for c in password):
        raise UserError("hotspot_password_format")
    try:
        r = start(["sudo", "-n", HOTSPOT_PASSWORD_HELPER], input=password + "\n",
                  capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise UserError("no_permission_hotspot") from None
    if r.returncode == 0:
        return
    if "sudo:" in (r.stderr or ""):   # not allowed, or the helper is not installed
        raise UserError("no_permission_hotspot")
    raise UserError("hotspot_not_set_up" if r.returncode == 3 else "hotspot_password_failed")
