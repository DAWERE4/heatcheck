"""HeatCheck web server. Run it with:   python3 server.py

Uses only the Python standard library, so there is nothing to install.
"""

import json
import re
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.config import Settings, load_dotenv
from app.cooling import load_spots
from app.engine import Engine
from app.store import Store

STATIC = Path(__file__).resolve().parent / "app" / "static"
PAGES = {"/": "dashboard.html", "/dashboard": "dashboard.html", "/sensor": "sensor.html"}
HOME_ACTION = re.compile(r"^/api/homes/([\w-]+)/(reset|simulate|checkin)$")
QUIET_PATHS = {"/api/state", "/api/readings"}


def make_handler(engine: Engine):
    settings = engine.settings
    store = engine.store

    class Handler(BaseHTTPRequestHandler):
        server_version = "HeatCheck/1.0"

        # ----- plumbing -----
        def log_message(self, fmt, *args):
            if urllib.parse.urlparse(self.path).path not in QUIET_PATHS:
                super().log_message(fmt, *args)

        def _send(self, code: int, body: bytes, content_type: str):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, data, code: int = 200):
            self._send(code, json.dumps(data).encode("utf-8"), "application/json")

        def send_xml(self, xml: str):
            self._send(200, xml.encode("utf-8"), "text/xml; charset=utf-8")

        def body_bytes(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def body_json(self) -> dict:
            raw = self.body_bytes()
            if not raw:
                return {}
            try:
                data = json.loads(raw.decode("utf-8"))
                return data if isinstance(data, dict) else {}
            except (ValueError, UnicodeDecodeError):
                return {}

        def body_form(self) -> dict:
            parsed = urllib.parse.parse_qs(self.body_bytes().decode("utf-8"), keep_blank_values=True)
            return {k: v[0] for k, v in parsed.items()}

        def route(self):
            parsed = urllib.parse.urlparse(self.path)
            query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            return parsed.path, query

        # ----- GET -----
        def do_GET(self):
            path, _ = self.route()
            if path in PAGES:
                page = (STATIC / PAGES[path]).read_bytes()
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/api/state":
                return self.send_json(engine.state())
            if path == "/health":
                return self.send_json({"ok": True, "mode": engine.state()["mode"]})
            self.send_json({"error": "not found"}, 404)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Device-Key")
            self.end_headers()

        # ----- POST -----
        def do_POST(self):
            path, query = self.route()
            if path == "/api/readings":
                return self.post_reading()
            match = HOME_ACTION.match(path)
            if match:
                return self.post_home_action(match.group(1), match.group(2))
            if path.startswith("/twilio/"):
                return self.post_twilio(path, query)
            self.send_json({"error": "not found"}, 404)

        def post_reading(self):
            data = self.body_json()
            if settings.device_key:
                given = data.get("device_key") or self.headers.get("X-Device-Key", "")
                if given != settings.device_key:
                    return self.send_json({"error": "wrong device_key"}, 401)
            home = store.get(str(data.get("home_id") or "demo"))
            if not home or home.sample:
                return self.send_json({"error": "unknown home_id"}, 404)
            try:
                if data.get("temp_f") is not None:
                    temp_f = float(data["temp_f"])
                elif data.get("temp_c") is not None:
                    temp_f = float(data["temp_c"]) * 9.0 / 5.0 + 32.0
                else:
                    raise ValueError("send temp_f or temp_c")
                humidity = float(data["humidity"])
            except (KeyError, TypeError, ValueError) as err:
                return self.send_json({"error": f"bad reading: {err}"}, 400)
            if not (-40 <= temp_f <= 160 and 0 <= humidity <= 100):
                return self.send_json({"error": "reading out of range"}, 400)
            reading = engine.add_reading(home, temp_f, humidity, source=str(data.get("source") or "sensor"))
            self.send_json({"ok": True, "heat_index_f": reading["hi"], "category": reading["category"],
                            "status": home.status})

        def post_home_action(self, home_id: str, action: str):
            home = store.get(home_id)
            if not home:
                return self.send_json({"error": "unknown home"}, 404)
            if action == "reset":
                engine.reset(home)
            elif action == "checkin":
                engine.start_checkin(home, "Manual check-in from the dashboard")
            elif action == "simulate":
                outcome = self.body_json().get("outcome", "")
                if not engine.simulate(home, outcome):
                    return self.send_json({"error": "only works while a call is in progress"}, 409)
            self.send_json({"ok": True, "status": home.status})

        def post_twilio(self, path: str, query: dict):
            params = self.body_form()
            home = store.get(query.get("home_id", ""))
            if not home:
                from app import twiml
                return self.send_xml(twiml.response(twiml.say("Sorry, something went wrong."), twiml.hangup()))
            try:
                attempt = int(query.get("attempt", "1"))
            except ValueError:
                attempt = 1
            if path == "/twilio/voice":
                return self.send_xml(engine.voice_twiml(home, params, attempt))
            if path == "/twilio/gather":
                return self.send_xml(engine.gather_twiml(home, params, attempt))
            if path == "/twilio/no-input":
                return self.send_xml(engine.no_input_twiml(home, attempt))
            if path == "/twilio/neighbor":
                return self.send_xml(engine.neighbor_twiml(home))
            if path == "/twilio/status":
                engine.status_callback(home, params, query.get("leg", "resident"))
                return self._send(204, b"", "text/plain")
            self.send_json({"error": "not found"}, 404)

    return Handler


def build(settings: Settings = None, run_async: bool = True):
    settings = settings or Settings.from_env()
    store = Store(include_samples=settings.sample_homes)
    engine = Engine(settings, store, load_spots(), run_async=run_async)
    server = ThreadingHTTPServer(("0.0.0.0", settings.port), make_handler(engine))
    server.daemon_threads = True
    return server, engine


def start_ticker(engine: Engine, every: float = 5.0) -> None:
    def loop():
        while True:
            try:
                engine.tick()
            except Exception as err:  # keep ticking no matter what
                print(f"tick error: {err}", flush=True)
            time.sleep(every)

    threading.Thread(target=loop, daemon=True).start()


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no packets are sent
            return s.getsockname()[0]
    except OSError:
        return "your-laptop-ip"


def main():
    try:
        sys.stdout.reconfigure(errors="replace")  # old Windows consoles can't print every symbol
    except AttributeError:
        pass
    load_dotenv()
    server, engine = build()
    s = engine.settings
    start_ticker(engine)
    port = s.port
    print("\n  HeatCheck is running")
    print(f"  Dashboard:      http://localhost:{port}/dashboard")
    print(f"  Virtual sensor: http://localhost:{port}/sensor   (phone on same Wi-Fi: http://{lan_ip()}:{port}/sensor)")
    if s.live_calls:
        print(f"  Calls: LIVE through Twilio, webhooks at {s.public_base_url}")
    else:
        missing = ", ".join(s.missing_for_live()) or "SIMULATE_CALLS=true"
        print(f"  Calls: SIMULATED (missing: {missing})")
    print(f"  Push alerts: {'ntfy topic ' + s.ntfy_topic if s.ntfy_topic else 'OFF (set NTFY_TOPIC in .env)'}")
    print(f"  Alert when heat index >= {s.alert_heat_index_f:.0f}°F for {s.alert_consecutive} readings in a row\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
