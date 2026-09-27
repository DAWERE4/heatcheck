"""Settings, read from environment variables (and a local .env file)."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path=None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (without overriding)."""
    path = Path(path) if path else ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif value.startswith("#"):
            value = ""  # "KEY=   # comment" means empty
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # allow trailing comments
        os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


def _env_bool(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    port: int
    public_base_url: str
    twilio_sid: str
    twilio_token: str
    twilio_from: str
    twilio_api_base: str
    ntfy_server: str
    ntfy_topic: str
    alert_heat_index_f: float
    alert_consecutive: int
    recheck_minutes: float
    device_key: str
    force_simulate: bool
    sample_homes: bool
    weather_enabled: bool = True
    weather_api_base: str = "https://api.open-meteo.com"
    weather_refresh_minutes: float = 10.0
    sensor_stale_minutes: float = 5.0
    elevenlabs_key: str = ""
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"   # "George", a default ElevenLabs voice
    elevenlabs_voice_id_es: str = ""                    # optional separate voice for Spanish calls
    elevenlabs_model: str = "eleven_flash_v2_5"         # fast, cheap, speaks English and Spanish
    elevenlabs_speed: str = ""                          # e.g. 0.9 to speak a little slower
    elevenlabs_api_base: str = "https://api.elevenlabs.io"
    audio_dir: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            port=int(_env_float("PORT", 8000)),
            public_base_url=_env("PUBLIC_BASE_URL").rstrip("/"),
            twilio_sid=_env("TWILIO_ACCOUNT_SID"),
            twilio_token=_env("TWILIO_AUTH_TOKEN"),
            twilio_from=_env("TWILIO_FROM_NUMBER"),
            twilio_api_base=_env("TWILIO_API_BASE", "https://api.twilio.com").rstrip("/"),
            ntfy_server=_env("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
            ntfy_topic=_env("NTFY_TOPIC"),
            alert_heat_index_f=_env_float("ALERT_HEAT_INDEX_F", 90.0),
            alert_consecutive=max(1, int(_env_float("ALERT_CONSECUTIVE_READINGS", 2))),
            recheck_minutes=_env_float("RECHECK_MINUTES", 30.0),
            device_key=_env("DEVICE_KEY"),
            force_simulate=_env_bool("SIMULATE_CALLS"),
            sample_homes=_env("SAMPLE_HOMES", "true").lower() not in {"0", "false", "no", "off"},
            weather_enabled=_env("WEATHER", "true").lower() not in {"0", "false", "no", "off"},
            weather_api_base=_env("WEATHER_API_BASE", "https://api.open-meteo.com").rstrip("/"),
            weather_refresh_minutes=max(1.0, _env_float("WEATHER_REFRESH_MINUTES", 10.0)),
            sensor_stale_minutes=_env_float("SENSOR_STALE_MINUTES", 5.0),
            elevenlabs_key=_env("ELEVENLABS_API_KEY"),
            elevenlabs_voice_id=_env("ELEVENLABS_VOICE_ID") or "JBFqnCBsd6RMkjVDRZzb",
            elevenlabs_voice_id_es=_env("ELEVENLABS_VOICE_ID_ES"),
            elevenlabs_model=_env("ELEVENLABS_MODEL") or "eleven_flash_v2_5",
            elevenlabs_speed=_env("ELEVENLABS_SPEED"),
            elevenlabs_api_base=_env("ELEVENLABS_API_BASE", "https://api.elevenlabs.io").rstrip("/"),
        )

    @property
    def twilio_ready(self) -> bool:
        return bool(self.twilio_sid and self.twilio_token and self.twilio_from and self.public_base_url)

    @property
    def live_calls(self) -> bool:
        """True when real phone calls will be placed through Twilio."""
        return self.twilio_ready and not self.force_simulate

    def missing_for_live(self) -> list:
        missing = []
        for label, value in [
            ("TWILIO_ACCOUNT_SID", self.twilio_sid),
            ("TWILIO_AUTH_TOKEN", self.twilio_token),
            ("TWILIO_FROM_NUMBER", self.twilio_from),
            ("PUBLIC_BASE_URL", self.public_base_url),
        ]:
            if not value:
                missing.append(label)
        return missing
