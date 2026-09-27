"""Live outdoor weather from Open-Meteo (free, no API key).

Used two ways:
  1. Shown on the dashboard as "Outside now" plus the peak heat index coming up.
  2. For a home with no working indoor sensor, the outdoor heat index becomes the
     trigger for a check-in call. It's only a rough guide: a house without AC can
     stay hotter than outside, especially at night. That's why the sensor is the upgrade.

Weather data by Open-Meteo.com (CC BY 4.0).
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from .heat import category, heat_index_f

FORECAST_HOURS = 18


class WeatherError(RuntimeError):
    pass


def _hour_label(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    h12 = dt.hour % 12 or 12
    return f"{h12} {'AM' if dt.hour < 12 else 'PM'}"


def parse_open_meteo(data: dict) -> dict:
    """Turn an Open-Meteo response into the numbers HeatCheck needs."""
    try:
        current = data["current"]
        temp_f = float(current["temperature_2m"])
        humidity = float(current["relative_humidity_2m"])
        now_iso = str(current.get("time", ""))
    except (KeyError, TypeError, ValueError) as err:
        raise WeatherError(f"Unexpected weather data (missing {err})") from err

    hi = heat_index_f(temp_f, humidity)
    result = {
        "temp_f": round(temp_f, 1),
        "humidity": round(humidity),
        "hi": round(hi, 1),
        "category": category(hi)["label"],
        "css": category(hi)["css"],
        "observed_at": now_iso,
        "fetched_at": time.time(),
        "peak": None,
        "source": "Open-Meteo",
    }

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    hums = hourly.get("relative_humidity_2m") or []
    this_hour = now_iso[:13]  # "YYYY-MM-DDTHH"
    upcoming = []
    for t, tf, rh in zip(times, temps, hums):
        if tf is None or rh is None or str(t)[:13] < this_hour:
            continue
        upcoming.append((heat_index_f(tf, rh), str(t)))
        if len(upcoming) >= FORECAST_HOURS:
            break
    if upcoming:
        peak_hi, peak_time = max(upcoming, key=lambda item: item[0])
        label = _hour_label(peak_time)
        if hi >= peak_hi:  # it's already as hot as it's going to get
            peak_hi, peak_time, label = hi, now_iso, "now"
        result["peak"] = {
            "hi": round(peak_hi, 1),
            "time": peak_time,
            "label": label,
            "category": category(peak_hi)["label"],
            "css": category(peak_hi)["css"],
            "hours": len(upcoming),
        }
    return result


def fetch_weather(settings, lat: float, lon: float) -> dict:
    params = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,relative_humidity_2m",
        "hourly": "temperature_2m,relative_humidity_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
        "forecast_days": "2",
    })
    url = f"{settings.weather_api_base}/v1/forecast?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "HeatCheck hackathon demo"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raise WeatherError(f"Weather service said HTTP {err.code}") from err
    except urllib.error.URLError as err:
        raise WeatherError(f"Couldn't reach the weather service: {err.reason}") from err
    except ValueError as err:
        raise WeatherError("Weather service sent something that isn't JSON") from err
    return parse_open_meteo(data)
