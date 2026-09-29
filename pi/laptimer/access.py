"""Sign-in: race director (with PIN) and spectators (with a button).

Without signing in there is only the login page. Spectators see race and statistics,
the race director may do everything. The race director PIN is set for the first time on the Pi
itself (pin.py) – so nobody on the Wi-Fi can get in first and lock the race director out.

Signed-in devices get a token as a cookie:
  race director:  random; config.json only holds its hash (at most MAX_DEVICES)
  spectator:      the same for everyone, signed with a secret from config.json
The PIN is stored only as a hash (with salt) in config.json.
"""
import hashlib
import hmac
import secrets
import time

from i18n import UserError

PIN_LENGTH = (4, 8)
MAX_DEVICES = 20          # this many race director devices can be signed in (the oldest drops out)
MAX_FAILURES = 5          # then lock briefly, so nobody can try out the PIN
LOCK_S = 60
ITERATIONS = 50_000
RACE_DIRECTOR, SPECTATOR = "race_director", "spectator"


def _pin_hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), ITERATIONS).hex()


def _device_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Access:
    def __init__(self, config, clock=time.monotonic):
        self.config = config
        self.clock = clock
        self._failures = 0
        self._locked_until = 0.0

    def pin_set(self):
        with self.config.lock:
            return bool(self.config.data.get("admin_pin"))

    def _spectator_token(self):
        with self.config.lock:
            secret = self.config.data.get("spectator_secret")
            if not secret:
                secret = self.config.data["spectator_secret"] = secrets.token_hex(16)
                self.config.save()
        return "s." + hmac.new(bytes.fromhex(secret), b"spectator", "sha256").hexdigest()[:32]

    def role(self, token):
        """RACE_DIRECTOR, SPECTATOR or None (not signed in)."""
        if not token:
            return None
        if token.startswith("s."):
            return SPECTATOR if hmac.compare_digest(token, self._spectator_token()) else None
        h = _device_hash(token)
        with self.config.lock:
            if any(hmac.compare_digest(h, d) for d in self.config.data.get("admin_devices", [])):
                return RACE_DIRECTOR
        return None

    def spectator(self):
        """Token for a spectator device."""
        return self._spectator_token()

    def _new_device(self):
        token = secrets.token_urlsafe(24)
        devices = self.config.data.setdefault("admin_devices", [])
        devices.append(_device_hash(token))
        del devices[:-MAX_DEVICES]
        return token

    def set_pin(self, pin):
        """New race director PIN. All other race director devices are signed out.

        Returns the token for the device that set the PIN (it stays signed in).
        """
        pin = str(pin or "").strip()
        if not pin.isdigit() or not PIN_LENGTH[0] <= len(pin) <= PIN_LENGTH[1]:
            raise UserError("pin_format", min=PIN_LENGTH[0], max=PIN_LENGTH[1])
        with self.config.lock:
            data = self.config.data
            salt = secrets.token_hex(16)
            data["admin_pin"] = {"salt": salt, "hash": _pin_hash(pin, salt)}
            data["admin_devices"] = []
            token = self._new_device()
            self.config.save()
            return token

    def sign_in(self, pin):
        """Check the race director PIN. Returns the token for this device or raises UserError."""
        self.check_pin(pin)
        with self.config.lock:
            token = self._new_device()
            self.config.save()
            return token

    def check_pin(self, pin):
        """Check the race director PIN, e.g. before deleting for good. Raises UserError if it is wrong."""
        now = self.clock()
        if now < self._locked_until:
            raise UserError("pin_locked", s=int(self._locked_until - now) + 1)
        with self.config.lock:
            stored = self.config.data.get("admin_pin")
            if not stored:
                raise UserError("pin_not_set")
            right = hmac.compare_digest(_pin_hash(str(pin or "").strip(), stored["salt"]), stored["hash"])
            if right:
                self._failures = 0
                return
        self._failures += 1
        if self._failures >= MAX_FAILURES:
            self._failures = 0
            self._locked_until = now + LOCK_S
        raise UserError("pin_wrong")

    def sign_out(self, token):
        if not token or token.startswith("s."):
            return
        with self.config.lock:
            h = _device_hash(token)
            devices = self.config.data.get("admin_devices", [])
            if h in devices:
                devices.remove(h)
                self.config.save()
