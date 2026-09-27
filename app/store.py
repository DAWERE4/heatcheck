"""In-memory state for homes, readings and the alert timeline.

Everything lives in memory, which is fine for a demo. Restarting the
server resets it.
"""

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .config import ROOT

STATUSES = {
    "normal": "Normal",
    "calling": "Calling now",
    "ok": "Said they're OK",
    "escalated": "Neighbor alerted",
}


def resolve(value):
    """Turn "$VAR|default" into the environment value (or the default)."""
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    name, _, default = value[1:].partition("|")
    return os.environ.get(name, "").strip() or default


def mask_phone(phone: str) -> str:
    if not phone:
        return ""
    return "•••" + phone[-4:]


@dataclass
class Home:
    id: str
    name: str
    address: str
    lat: float
    lon: float
    neighborhood: str = ""
    language: str = "en"
    resident_phone: str = ""
    neighbor_name: str = "Neighbor"
    neighbor_phone: str = ""
    live: bool = False
    sample: bool = False
    sample_temp_f: float = 78.0
    sample_humidity: float = 50.0
    note: str = ""

    readings: deque = field(default_factory=lambda: deque(maxlen=240))
    events: deque = field(default_factory=lambda: deque(maxlen=40))
    status: str = "normal"
    status_since: float = field(default_factory=time.time)
    reason: str = ""
    over_count: int = 0
    under_count: int = 0
    call_sid: str = ""
    checkins: int = 0
    last_source: str = ""
    last_sensor_at: float = 0.0    # time of the last indoor (non-weather) reading
    weather: dict = None           # latest outdoor weather for this home's location
    weather_error: str = ""

    @property
    def first_name(self) -> str:
        return self.name

    @property
    def using_weather(self) -> bool:
        """True when the latest reading came from outdoor weather, not an indoor sensor."""
        return self.last_source == "weather"

    @property
    def last(self):
        return self.readings[-1] if self.readings else None


class Store:
    def __init__(self, homes_path=None, include_samples=True):
        self.lock = threading.RLock()
        self.homes = {}
        path = Path(homes_path) if homes_path else ROOT / "data" / "homes.json"
        for raw in json.loads(path.read_text(encoding="utf-8")):
            if raw.get("sample") and not include_samples:
                continue
            data = {k: resolve(v) for k, v in raw.items()}
            home = Home(**data)
            self.homes[home.id] = home

    def get(self, home_id: str):
        return self.homes.get(home_id)

    def add_event(self, home: Home, text: str, kind: str = "info") -> None:
        with self.lock:
            home.events.append({"t": time.time(), "text": text, "kind": kind})
        print(f"[{home.id}] {text}", flush=True)

    def set_status(self, home: Home, status: str, reason: str = "") -> None:
        with self.lock:
            home.status = status
            home.status_since = time.time()
            home.reason = reason

    def public_home(self, home: Home, extra: dict = None) -> dict:
        last = home.last
        out = {
            "id": home.id,
            "name": home.name,
            "neighborhood": home.neighborhood,
            "address": home.address,
            "lat": home.lat,
            "lon": home.lon,
            "language": home.language,
            "live": home.live,
            "sample": home.sample,
            "note": home.note,
            "resident_phone": mask_phone(home.resident_phone),
            "neighbor_name": home.neighbor_name,
            "neighbor_phone": mask_phone(home.neighbor_phone),
            "status": home.status,
            "status_label": STATUSES.get(home.status, home.status),
            "status_since": home.status_since,
            "reason": home.reason,
            "checkins": home.checkins,
            "last": last,
            "last_source": home.last_source,
            "using_weather": home.using_weather,
            "weather": home.weather,
            "weather_error": home.weather_error,
            "history": [round(r["hi"], 1) for r in list(home.readings)[-90:]],
            "events": list(home.events)[::-1],
        }
        if extra:
            out.update(extra)
        return out
