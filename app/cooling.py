"""Cooling spots: which ones are open right now, and which is closest."""

import json
import math
from datetime import datetime
from pathlib import Path

from .config import ROOT

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def local_now() -> datetime:
    """Current time in Atlanta. Falls back to the laptop's local clock."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:  # zoneinfo data missing (common on Windows without tzdata)
        return datetime.now()


def load_spots(path=None) -> list:
    path = Path(path) if path else ROOT / "data" / "cooling_spots.json"
    return json.loads(path.read_text(encoding="utf-8"))


def is_open(spot: dict, now: datetime) -> bool:
    if spot.get("always_open"):
        return True
    hours = spot.get("hours", {}).get(DAYS[now.weekday()])
    if not hours:
        return False
    start, end = hours
    current = now.strftime("%H:%M")
    return start <= current < end


def miles_between(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8  # Earth radius in miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def hours_text(spot: dict) -> str:
    if spot.get("always_open"):
        return "Open any time"
    hours = spot.get("hours", {})
    if not hours:
        return "Hours unknown"
    days = [d for d in DAYS if d in hours]
    if not days:
        return "Hours unknown"
    start, end = hours[days[0]]
    same = all(hours[d] == [start, end] for d in days)

    def fmt(hhmm):
        h, m = map(int, hhmm.split(":"))
        suffix = "am" if h < 12 else "pm"
        h12 = h % 12 or 12
        return f"{h12}{suffix}" if m == 0 else f"{h12}:{m:02d}{suffix}"

    span = f"{days[0].title()}–{days[-1].title()}" if len(days) > 1 else days[0].title()
    return f"{span} {fmt(start)}–{fmt(end)}" if same else "See schedule"


def nearest_open(lat: float, lon: float, spots: list, now: datetime = None) -> dict:
    """Pick the closest open cooling spot. Always returns something useful to say."""
    now = now or local_now()
    located = [s for s in spots if s.get("lat") is not None and s.get("lon") is not None]
    open_located = [s for s in located if is_open(s, now)]
    if open_located:
        best = min(open_located, key=lambda s: miles_between(lat, lon, s["lat"], s["lon"]))
        miles = miles_between(lat, lon, best["lat"], best["lon"])
        return {
            "found": True,
            "name": best["name"],
            "address": best.get("address", ""),
            "miles": round(miles, 1),
            "hours": hours_text(best),
            "say": f"{best['name']}, at {best.get('address', '')}, about {miles:.1f} miles away",
        }

    fallback = next((s for s in spots if s.get("fallback")), None)
    closed_names = ", ".join(s["name"] for s in located) or "none listed"
    return {
        "found": False,
        "name": fallback["name"] if fallback else "No cooling center open",
        "address": fallback.get("address", "") if fallback else "",
        "miles": None,
        "hours": hours_text(fallback) if fallback else "",
        "closed": closed_names,
        "say": (
            "No cooling center is open right now. "
            + (fallback.get("say", "") if fallback else "")
        ).strip(),
    }
