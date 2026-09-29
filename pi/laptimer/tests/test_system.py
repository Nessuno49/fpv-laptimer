import subprocess
import threading
import unittest

import system


class FakeStart:
    """Instead of real commands: remembers the calls and returns given results."""

    def __init__(self, sudo_ok=True, systemctl_ok=True):
        self.calls = []
        self.sudo_ok, self.systemctl_ok = sudo_ok, systemctl_ok
        self.done = threading.Event()

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[:3] == ["sudo", "-n", "-l"]:
            ok = self.sudo_ok
        else:
            ok = self.systemctl_ok
            self.done.set()
        return subprocess.CompletedProcess(command, 0 if ok else 1, "", "")


class SystemTest(unittest.TestCase):
    def test_shutdown_with_sudo(self):
        s = FakeStart()
        system.run("shutdown", start=s, delay=0)
        self.assertTrue(s.done.wait(2))
        self.assertEqual(s.calls[-1], ["sudo", "-n", "systemctl", "poweroff"])

    def test_reboot_with_sudo(self):
        s = FakeStart()
        system.run("reboot", start=s, delay=0)
        self.assertTrue(s.done.wait(2))
        self.assertEqual(s.calls[-1], ["sudo", "-n", "systemctl", "reboot"])

    def test_without_sudo_directly(self):
        s = FakeStart(sudo_ok=False)
        system.run("shutdown", start=s)
        self.assertEqual(s.calls[-1], ["systemctl", "poweroff"])

    def test_no_permission(self):
        s = FakeStart(sudo_ok=False, systemctl_ok=False)
        with self.assertRaisesRegex(ValueError, "permission"):
            system.run("shutdown", start=s)

    def test_sudo_missing_entirely(self):
        def start(command, **kwargs):
            if command[0] == "sudo":
                raise FileNotFoundError("sudo")
            return subprocess.CompletedProcess(command, 0, "", "")
        system.run("reboot", start=start)  # falls back to systemctl, no error

    def test_unknown_action(self):
        with self.assertRaises(ValueError):
            system.run("rm -rf", start=FakeStart())


class HotspotPasswordTest(unittest.TestCase):
    def fake(self, returncode=0):
        calls = []

        def start(command, **kwargs):
            calls.append((command, kwargs.get("input")))
            return subprocess.CompletedProcess(command, returncode, "", "")
        return start, calls

    def test_password_goes_to_the_helper_via_stdin(self):
        start, calls = self.fake()
        system.set_hotspot_password("Neues Passwort 1", start=start)
        command, stdin = calls[0]
        self.assertEqual(command, ["sudo", "-n", system.HOTSPOT_PASSWORD_HELPER])
        self.assertEqual(stdin, "Neues Passwort 1\n")          # not on the command line

    def test_invalid_passwords(self):
        start, calls = self.fake()
        for bad in ("short", "x" * 64, "tab\there", "ümlaut12", ""):
            with self.assertRaises(ValueError):
                system.set_hotspot_password(bad, start=start)
        self.assertEqual(calls, [])

    def test_errors_of_the_helper(self):
        for returncode, key in ((1, "hotspot_password_failed"), (3, "hotspot_not_set_up")):
            start, _ = self.fake(returncode)
            with self.assertRaises(ValueError) as e:
                system.set_hotspot_password("longenough", start=start)
            self.assertEqual(e.exception.key, key)

    def test_helper_not_allowed(self):
        def start(command, **kwargs):  # sudo -n without permission: exit code 1 and a message
            return subprocess.CompletedProcess(command, 1, "", "sudo: a password is required")
        with self.assertRaises(ValueError) as e:
            system.set_hotspot_password("longenough", start=start)
        self.assertEqual(e.exception.key, "no_permission_hotspot")


if __name__ == "__main__":
    unittest.main()
