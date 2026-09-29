"""Sign-in, race director and spectators: real web server, real HTTP requests."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import webserver
from config import Config
from database import Database
from photos import Photos
from race import RaceController
from sounds import Library


class RolesTest(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        config = Config(base / "config.json")
        self.db = Database(str(base / "test.db"))
        self.addCleanup(self.db.close)
        self.app = webserver.App(config, self.db, RaceController(self.db), Photos(base / "photos"),
                                 Library(base / "sounds"))
        self.app.local_is_race_director = False  # the tests themselves run "from the Pi"
        self.server = webserver.start(self.app, 0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def request(self, path, data=None, cookie=None, raw=False, language=None):
        """(status, answer, cookie from Set-Cookie)"""
        req = urllib.request.Request(self.base + path)
        if data is not None:
            req.data = json.dumps(data).encode()
            req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", cookie)
        if language:
            req.add_header("X-Language", language)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                content = r.read()
                set_cookie = r.headers.get("Set-Cookie")
                return (r.status, content if raw else json.loads(content or b"{}"),
                        set_cookie.split(";")[0] if set_cookie else None)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}"), None

    def spectator(self):
        return self.request("/api/spectator", {})[2]

    def race_director(self):
        self.app.access.set_pin("4711")
        return self.request("/api/sign_in", {"pin": "4711"})[2]

    def test_without_sign_in_only_the_login_page(self):
        self.assertEqual(self.request("/", raw=True)[0], 200)            # the page itself: yes
        self.assertEqual(self.request("/app.js", raw=True)[0], 200)
        self.assertEqual(self.request("/api/session")[1], {"role": None, "pin_set": False})
        status, answer, _ = self.request("/api/state")                   # data: no
        self.assertEqual((status, answer["sign_in"]), (401, True))
        self.assertEqual(self.request("/api/pilots")[0], 401)
        self.assertEqual(self.request("/api/pilots", {"name": "Hacker"})[0], 401)
        self.assertEqual(self.request("/api/pin", {"pin": "1234"})[0], 401)  # no getting in first

    def test_spectator(self):
        cookie = self.spectator()
        self.assertTrue(cookie.startswith("laptimer="))
        status, state, _ = self.request("/api/state", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertFalse(state["role"]["admin"])
        self.assertEqual(self.request("/api/pilots", cookie=cookie)[0], 200)
        self.assertEqual(self.request("/api/pilots", {"name": "Hacker"}, cookie=cookie)[0], 403)
        self.assertEqual(self.request("/api/race/abort", {}, cookie=cookie)[0], 403)
        self.assertEqual(self.request("/api/system/shutdown", {}, cookie=cookie)[0], 403)
        self.assertEqual(self.request("/api/pin", {"pin": "1234"}, cookie=cookie)[0], 403)
        self.assertEqual(self.request("/api/camera/presets", cookie=cookie)[0], 403)
        self.assertEqual(self.request("/api/races", cookie=cookie)[0], 403)      # no race history
        self.assertEqual(self.request("/api/tracks", cookie=cookie)[0], 200)

    def test_race_director(self):
        status, answer, _ = self.request("/api/sign_in", {"pin": "4711"})
        self.assertEqual(status, 400)
        self.assertIn("pin.py", answer["error"])              # no PIN yet: hint
        cookie = self.race_director()
        self.assertEqual(self.request("/api/sign_in", {"pin": "0000"})[0], 400)
        self.assertTrue(self.request("/api/state", cookie=cookie)[1]["role"]["admin"])
        self.assertEqual(self.request("/api/pilots", {"name": "Anna"}, cookie=cookie)[0], 200)
        self.assertEqual(self.request("/api/session", cookie=cookie)[1]["role"], "race_director")

    def test_errors_in_the_language_of_the_device(self):
        self.race_director()
        self.assertEqual(self.request("/api/sign_in", {"pin": "0000"})[1]["error"], "Wrong PIN.")
        self.assertEqual(self.request("/api/sign_in", {"pin": "0000"}, language="de")[1]["error"], "Falsche PIN.")
        self.assertEqual(self.request("/api/state", language="de")[1]["error"], "Bitte anmelden.")

    def test_delete_pilot_only_with_pin(self):
        cookie = self.race_director()
        pilot = self.app.db.add_pilot("Gone")
        path = f"/api/pilots/{pilot}/delete"
        self.assertEqual(self.request(path, {}, cookie=cookie)[0], 400)               # without PIN
        status, answer, _ = self.request(path, {"pin": "0000"}, cookie=cookie)       # wrong PIN
        self.assertEqual((status, answer["error"]), (400, "Wrong PIN."))
        self.assertEqual(self.request(path, {"pin": "4711"}, cookie=self.spectator())[0], 403)
        self.assertIn("Gone", [p["name"] for p in self.app.db.pilots()])              # still there
        self.assertEqual(self.request(path, {"pin": "4711"}, cookie=cookie)[0], 200)
        self.assertNotIn("Gone", [p["name"] for p in self.app.db.pilots(include_archived=True)])

    def test_race_over_the_api(self):
        cookie = self.race_director()
        anna = self.app.db.add_pilot("Anna")
        quad = self.app.db.quads(pilot_id=anna)[0]["id"]
        self.assertEqual(self.request("/api/race/start", {"participants": [{"pilot_id": anna, "quad_id": quad}],
                                                          "format": "practice", "settings": {}}, cookie=cookie)[0], 200)
        state = self.request("/api/state", cookie=cookie)[1]
        self.assertEqual(state["race"]["status"], "running")
        self.assertEqual(state["selection"]["participants"], [{"pilot_id": anna, "quad_id": quad}])
        self.assertEqual(self.request("/api/race/end_practice", {}, cookie=cookie)[0], 200)
        self.assertEqual(self.request("/api/state", cookie=cookie)[1]["race"]["status"], "ready")

    def test_race_history_with_ranking(self):
        cookie = self.race_director()
        anna, ben = self.app.db.add_pilot("Anna"), self.app.db.add_pilot("Ben")
        race = self.app.db.save_race("laps", {"laps": 2}, None, "2026-09-28T12:00:00", "2026-09-28T12:01:00")
        self.app.db.save_pilot_race(anna, None, "laps", {"laps": 2}, "2026-09-28T12:00:00", "2026-09-28T12:01:00",
                                    [1.0, 9.0], race_id=race)                        # not finished
        self.app.db.save_pilot_race(ben, None, "laps", {"laps": 2}, "2026-09-28T12:00:00", "2026-09-28T12:01:00",
                                    [2.0, 8.0, 13.0], race_id=race)                  # 13 s
        detail = self.request(f"/api/races/{race}", cookie=cookie)[1]
        ranking = [(r["pilot"], r["rank"], r["best_lap"], r["holeshot_s"]) for r in detail["pilot_races"]]
        self.assertEqual(sorted(ranking, key=lambda x: x[1]), [("Ben", 1, 5.0, 2.0), ("Anna", 2, 8.0, 1.0)])

    def test_statistics_of_the_pop_up_course(self):
        cookie = self.race_director()
        anna = self.app.db.add_pilot("Anna")
        self.app.db.save_pilot_race(anna, None, "laps", {"laps": 1}, "2026-09-28T12:00:00", "2026-09-28T12:01:00",
                                    [1.0, 9.0])
        board = self.request("/api/stats/leaderboard?track=none&quad=&category=laps:1", cookie=cookie)[1]
        self.assertEqual([(e["pilot"], e["time_s"]) for e in board], [("Anna", 9.0)])

    def test_commands_that_ignore_the_data_sent_along_still_answer(self):
        """The server must read what the browser sends, even when a command doesn't need it –
        otherwise closing the connection resets it and the browser gets an error instead of the answer."""
        cookie = self.race_director()
        # the connection reset only hits now and then (about 1 in 100 before the fix), so try many times
        for _ in range(300):
            status, _, _ = self.request("/api/race/abort", {}, cookie=cookie)
            self.assertEqual(status, 200)

    def test_hotspot_password_only_for_the_race_director(self):
        self.assertEqual(self.request("/api/hotspot/password", {"password": "longenough"},
                                      cookie=self.spectator())[0], 403)
        cookie = self.race_director()
        status, answer, _ = self.request("/api/hotspot/password", {"password": "short"}, cookie=cookie)
        self.assertEqual(status, 400)
        self.assertIn("8 to 63", answer["error"])

    def test_sign_out(self):
        cookie = self.race_director()
        _, _, deleted = self.request("/api/sign_out", {}, cookie=cookie)
        self.assertEqual(deleted, "laptimer=")
        self.assertEqual(self.request("/api/state", cookie=cookie)[0], 401)

    def test_pin_only_from_the_pi_itself(self):
        self.app.local_is_race_director = True    # like pin.py via SSH on the Pi
        self.assertEqual(self.request("/api/pin", {"pin": "2468"})[0], 200)
        self.app.local_is_race_director = False
        self.assertEqual(self.request("/api/sign_in", {"pin": "2468"})[0], 200)


class CaptivePortalTest(RolesTest):
    """Phones that do their internet check after connecting end up at the lap timer."""

    def raw(self, path, host="127.0.0.1"):
        import http.client
        port = self.server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        self.addCleanup(connection.close)
        connection.request("GET", path, headers={"Host": host})
        answer = connection.getresponse()
        answer.read()
        return answer.status, answer.getheader("Location"), port

    def test_android_check_is_redirected(self):
        status, target, port = self.raw("/generate_204", host="connectivitycheck.gstatic.com")
        self.assertEqual(status, 302)
        self.assertEqual(target, f"http://127.0.0.1:{port}/")

    def test_apple_check_is_redirected(self):
        status, _, _ = self.raw("/hotspot-detect.html", host="captive.apple.com")
        self.assertEqual(status, 302)
        status, _, _ = self.raw("/anything", host="captive.apple.com")
        self.assertEqual(status, 302)

    def test_normal_pages_stay(self):
        self.assertEqual(self.raw("/")[0], 200)
        self.assertEqual(self.raw("/", host="laptimer.local")[0], 200)


if __name__ == "__main__":
    unittest.main()
