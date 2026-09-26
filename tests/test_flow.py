"""End-to-end test of the whole call flow against fake Twilio and ntfy servers.

Run with:  python3 -m unittest discover -s tests -v
"""

import json
import os
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["RESIDENT_PHONE"] = "+14045550101"
os.environ["NEIGHBOR_PHONE"] = "+14045550102"

from app.config import Settings  # noqa: E402
from server import build  # noqa: E402


class FakeCloud:
    """Pretends to be both Twilio's REST API and ntfy.sh, and records requests."""

    def __init__(self):
        self.calls, self.pushes = [], []
        cloud = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                if self.path.endswith("/Calls.json"):
                    cloud.calls.append({k: v[0] for k, v in urllib.parse.parse_qs(body).items()})
                    payload = json.dumps({"sid": f"CA{len(cloud.calls):032d}"}).encode()
                    self.send_response(201)
                else:
                    cloud.pushes.append(json.loads(body))
                    payload = b"{}"
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def settings_for(cloud, simulate=False, device_key=""):
    return Settings(
        port=0,
        public_base_url="https://example.trycloudflare.com",
        twilio_sid="AC_test",
        twilio_token="token",
        twilio_from="+14045550100",
        twilio_api_base=cloud.base,
        ntfy_server=cloud.base,
        ntfy_topic="heatcheck-test",
        alert_heat_index_f=90.0,
        alert_consecutive=2,
        recheck_minutes=30.0,
        device_key=device_key,
        force_simulate=simulate,
        sample_homes=True,
    )


class AppClient:
    def __init__(self, settings):
        self.server, self.engine = build(settings, run_async=False)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def _open(self, request):
        try:
            with urllib.request.urlopen(request, timeout=10) as res:
                return res.status, res.read().decode()
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode()

    def get(self, path):
        return self._open(urllib.request.Request(self.base + path))

    def post_json(self, path, data=None):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(data or {}).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        status, body = self._open(req)
        return status, (json.loads(body) if body else {})

    def post_form(self, path, data=None):
        req = urllib.request.Request(
            self.base + path, data=urllib.parse.urlencode(data or {}).encode(), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return self._open(req)

    def reading(self, temp_f, humidity):
        return self.post_json("/api/readings", {"home_id": "demo", "temp_f": temp_f, "humidity": humidity})

    @property
    def home(self):
        return self.engine.store.get("demo")


class LiveCallFlowTests(unittest.TestCase):
    def setUp(self):
        self.cloud = FakeCloud()
        self.app = AppClient(settings_for(self.cloud))

    def tearDown(self):
        self.app.stop()
        self.cloud.stop()

    def heat_up(self):
        self.app.reading(76, 50)
        self.assertEqual(self.app.home.status, "normal")
        self.app.reading(94, 55)
        self.assertEqual(self.app.home.status, "normal", "needs 2 hot readings in a row")
        status, data = self.app.reading(94, 55)
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "Danger")
        self.assertEqual(self.app.home.status, "calling")

    def test_pages_and_state(self):
        status, html = self.app.get("/dashboard")
        self.assertEqual(status, 200)
        self.assertIn("HeatCheck", html)
        status, html = self.app.get("/sensor")
        self.assertEqual(status, 200)
        status, body = self.app.get("/api/state")
        state = json.loads(body)
        self.assertEqual(state["mode"], "live")
        demo = next(h for h in state["homes"] if h["id"] == "demo")
        self.assertEqual(demo["resident_phone"], "•••0101", "phone numbers are masked")

    def test_resident_answers_ok(self):
        self.heat_up()
        self.assertEqual(len(self.cloud.calls), 1)
        call = self.cloud.calls[0]
        self.assertEqual(call["To"], "+14045550101")
        self.assertEqual(call["From"], "+14045550100")
        self.assertIn("https://example.trycloudflare.com/twilio/voice?home_id=demo&attempt=1", call["Url"])
        self.assertEqual(call["MachineDetection"], "Enable")

        status, xml = self.app.post_form("/twilio/voice?home_id=demo&attempt=1", {"AnsweredBy": "human"})
        self.assertEqual(status, 200)
        self.assertIn("<Gather", xml)
        self.assertIn("dangerously hot", xml)
        self.assertIn("home_id=demo&amp;attempt=1", xml, "URLs are XML-escaped")
        self.assertIn("/twilio/no-input", xml)

        status, xml = self.app.post_form("/twilio/gather?home_id=demo&attempt=1", {"Digits": "1"})
        self.assertIn("Thank you", xml)
        self.assertIn("<Hangup/>", xml)
        self.assertEqual(self.app.home.status, "ok")

        self.app.post_form("/twilio/status?home_id=demo&leg=resident", {"CallStatus": "completed"})
        self.assertEqual(self.app.home.status, "ok", "a finished call after 'OK' is not an escalation")
        self.assertEqual(self.cloud.pushes, [])

        for _ in range(3):
            self.app.reading(75, 45)
        self.assertEqual(self.app.home.status, "normal")

    def test_no_answer_alerts_neighbor(self):
        self.heat_up()
        self.app.post_form("/twilio/status?home_id=demo&leg=resident", {"CallStatus": "no-answer"})
        self.assertEqual(self.app.home.status, "escalated")

        self.assertEqual(len(self.cloud.pushes), 1)
        push = self.cloud.pushes[0]
        self.assertEqual(push["topic"], "heatcheck-test")
        self.assertIn("check on Ms. Johnson", push["title"])
        self.assertIn("didn't pick up", push["message"])
        self.assertEqual(push["priority"], 5)

        self.assertEqual(len(self.cloud.calls), 2)
        neighbor_call = self.cloud.calls[1]
        self.assertEqual(neighbor_call["To"], "+14045550102")
        self.assertIn("/twilio/neighbor", neighbor_call["Url"])

        status, xml = self.app.post_form("/twilio/neighbor?home_id=demo")
        self.assertIn("Please go check on them now", xml)

    def test_resident_says_help(self):
        self.heat_up()
        status, xml = self.app.post_form(
            "/twilio/gather?home_id=demo&attempt=1", {"SpeechResult": "I need help", "Confidence": "0.9"}
        )
        self.assertIn("call 9 1 1", xml)
        self.assertEqual(self.app.home.status, "escalated")
        self.assertEqual(len(self.cloud.pushes), 1)

    def test_silence_reprompts_then_escalates(self):
        self.heat_up()
        status, xml = self.app.post_form("/twilio/no-input?home_id=demo&attempt=1")
        self.assertIn("attempt=2", xml)
        self.assertEqual(self.app.home.status, "calling")
        status, xml = self.app.post_form("/twilio/voice?home_id=demo&attempt=2", {"AnsweredBy": "human"})
        self.assertIn("didn't catch that", xml)
        status, xml = self.app.post_form("/twilio/no-input?home_id=demo&attempt=2")
        self.assertEqual(self.app.home.status, "escalated")

    def test_voicemail_escalates(self):
        self.heat_up()
        status, xml = self.app.post_form("/twilio/voice?home_id=demo&attempt=1", {"AnsweredBy": "machine_start"})
        self.assertNotIn("<Gather", xml)
        self.assertEqual(self.app.home.status, "escalated")

    def test_bad_reading_rejected(self):
        status, data = self.app.post_json("/api/readings", {"home_id": "demo", "temp_f": "hot"})
        self.assertEqual(status, 400)
        status, data = self.app.post_json("/api/readings", {"home_id": "nope", "temp_f": 80, "humidity": 40})
        self.assertEqual(status, 404)

    def test_celsius_readings_from_esp32(self):
        status, data = self.app.post_json(
            "/api/readings", {"home_id": "demo", "temp_c": 34.4, "humidity": 55, "source": "esp32"}
        )
        self.assertEqual(status, 200)
        self.assertAlmostEqual(self.app.home.last["temp_f"], 93.9, delta=0.2)


class SimulatedFlowTests(unittest.TestCase):
    def setUp(self):
        self.cloud = FakeCloud()
        self.app = AppClient(settings_for(self.cloud, simulate=True, device_key="secret"))

    def tearDown(self):
        self.app.stop()
        self.cloud.stop()

    def test_simulated_call_and_device_key(self):
        status, _ = self.app.reading(94, 55)
        self.assertEqual(status, 401, "device key required when DEVICE_KEY is set")
        for _ in range(2):
            self.app.post_json("/api/readings", {"home_id": "demo", "temp_f": 94, "humidity": 55, "device_key": "secret"})
        self.assertEqual(self.app.home.status, "calling")
        self.assertEqual(self.cloud.calls, [], "no real call in simulate mode")

        status, data = self.app.post_json("/api/homes/demo/simulate", {"outcome": "no_answer"})
        self.assertEqual(status, 200)
        self.assertEqual(self.app.home.status, "escalated")
        self.assertEqual(len(self.cloud.pushes), 1, "push alerts still work without Twilio")

        status, data = self.app.post_json("/api/homes/demo/simulate", {"outcome": "ok"})
        self.assertEqual(status, 409)

        self.app.post_json("/api/homes/demo/reset")
        self.assertEqual(self.app.home.status, "normal")
        self.app.post_json("/api/homes/demo/checkin")
        self.assertEqual(self.app.home.status, "calling")
        self.app.post_json("/api/homes/demo/simulate", {"outcome": "ok"})
        self.assertEqual(self.app.home.status, "ok")


if __name__ == "__main__":
    unittest.main()
