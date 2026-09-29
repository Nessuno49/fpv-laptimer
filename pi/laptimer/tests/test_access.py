import tempfile
import unittest
from pathlib import Path

from access import LOCK_S, MAX_DEVICES, MAX_FAILURES, RACE_DIRECTOR, SPECTATOR, Access
from config import Config


class AccessTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "config.json"
        self.config = Config(self.path)
        self.t = 0.0
        self.a = Access(self.config, clock=lambda: self.t)

    def test_nothing_without_sign_in(self):
        self.assertIsNone(self.a.role(None))
        self.assertIsNone(self.a.role("guessed"))
        self.assertIsNone(self.a.role("s.guessed"))

    def test_spectator(self):
        token = self.a.spectator()
        self.assertEqual(self.a.role(token), SPECTATOR)
        self.assertEqual(Access(Config(self.path)).role(token), SPECTATOR)  # also after a restart

    def test_no_race_director_without_pin(self):
        self.assertFalse(self.a.pin_set())
        with self.assertRaisesRegex(ValueError, "pin.py"):
            self.a.sign_in("1234")

    def test_set_pin_and_sign_in(self):
        my_device = self.a.set_pin("1234")
        self.assertTrue(self.a.pin_set())
        self.assertEqual(self.a.role(my_device), RACE_DIRECTOR)  # whoever sets the PIN stays signed in
        phone = self.a.sign_in("1234")
        self.assertEqual(self.a.role(phone), RACE_DIRECTOR)
        self.assertNotIn("1234", self.path.read_text())  # the PIN is not in the file as plain text

    def test_sign_in_survives_restart(self):
        phone = self.a.set_pin("123456")
        self.assertEqual(Access(Config(self.path)).role(phone), RACE_DIRECTOR)

    def test_pin_from_german_config_still_works(self):
        self.a.set_pin("4711")
        data = self.config.data
        german = {"kamera": "csi", "admin_pin": {"salz": data["admin_pin"]["salt"], "hash": data["admin_pin"]["hash"]}}
        self.path.write_text(__import__("json").dumps(german), encoding="utf-8")
        Access(Config(self.path)).check_pin("4711")   # no error

    def test_wrong_pin_and_lock(self):
        self.a.set_pin("1234")
        for _ in range(MAX_FAILURES):
            with self.assertRaisesRegex(ValueError, "Wrong PIN"):
                self.a.sign_in("0000")
        with self.assertRaisesRegex(ValueError, "wait"):
            self.a.sign_in("1234")                      # locked, even with the right PIN
        self.t += LOCK_S + 1
        self.assertEqual(self.a.role(self.a.sign_in("1234")), RACE_DIRECTOR)

    def test_check_pin_without_new_sign_in(self):
        self.a.set_pin("1234")
        devices = list(self.config.data["admin_devices"])
        self.a.check_pin("1234")                                     # right: no error
        self.assertEqual(self.config.data["admin_devices"], devices)  # and no new device
        with self.assertRaisesRegex(ValueError, "Wrong PIN"):
            self.a.check_pin("0000")

    def test_invalid_pin(self):
        for pin in ("12", "123456789", "12ab", " ", None, ""):
            with self.assertRaises(ValueError):
                self.a.set_pin(pin)

    def test_sign_out(self):
        phone = self.a.set_pin("1234")
        self.a.sign_out(phone)
        self.assertIsNone(self.a.role(phone))

    def test_new_pin_signs_out_all_other_race_directors(self):
        old = self.a.set_pin("1234")
        phone = self.a.sign_in("1234")
        spectator = self.a.spectator()
        new = self.a.set_pin("9876")
        self.assertEqual(self.a.role(new), RACE_DIRECTOR)
        self.assertIsNone(self.a.role(old))
        self.assertIsNone(self.a.role(phone))
        self.assertEqual(self.a.role(spectator), SPECTATOR)  # spectators stay in

    def test_at_most_max_devices(self):
        first = self.a.set_pin("1234")
        for _ in range(MAX_DEVICES):
            self.a.sign_in("1234")
        self.assertIsNone(self.a.role(first))   # the oldest dropped out


if __name__ == "__main__":
    unittest.main()
