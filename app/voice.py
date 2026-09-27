"""A warm, natural voice for the check-in call, from ElevenLabs text-to-speech.

How it works:
  - Each sentence HeatCheck says is turned into an MP3 once and saved in
    data/audio_cache/. The same sentence is never paid for twice.
  - The phone call plays that MP3 (TwiML <Play>) instead of Twilio's built-in voice.
  - If there's no ELEVENLABS_API_KEY, or ElevenLabs is slow or down, the call
    falls back to Twilio's voice (<Say>). The call never breaks because of this.

Voice by ElevenLabs (elevenlabs.io).
"""

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .config import ROOT

CLIP_ID_LENGTH = 16


class Voice:
    def __init__(self, settings):
        self.settings = settings
        self.dir = Path(settings.audio_dir) if settings.audio_dir else ROOT / "data" / "audio_cache"
        self.last_error = ""
        self.requests_made = 0
        self._lock = threading.Lock()
        self._inflight = {}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.elevenlabs_key)

    def voice_id(self, lang: str = "en") -> str:
        if lang == "es" and self.settings.elevenlabs_voice_id_es:
            return self.settings.elevenlabs_voice_id_es
        return self.settings.elevenlabs_voice_id

    def clip_id(self, text: str, lang: str = "en") -> str:
        key = "|".join([self.voice_id(lang), self.settings.elevenlabs_model,
                        self.settings.elevenlabs_speed or "", text])
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:CLIP_ID_LENGTH]

    def path(self, clip_id: str) -> Path:
        return self.dir / f"{clip_id}.mp3"

    def cached(self, text: str, lang: str = "en"):
        cid = self.clip_id(text, lang)
        return cid if self.path(cid).exists() else None

    def get(self, text: str, timeout: float = 8.0, lang: str = "en"):
        """Return a clip id for `text`, making it if needed. None means "use the backup voice"."""
        if not self.enabled:
            return None
        cid = self.clip_id(text, lang)
        if self.path(cid).exists():
            return cid

        with self._lock:
            event = self._inflight.get(cid)
            owner = event is None
            if owner:
                event = self._inflight[cid] = threading.Event()
        if not owner:  # someone else is already making this clip
            event.wait(timeout)
            return cid if self.path(cid).exists() else None

        try:
            audio = self._synthesize(text, timeout, self.voice_id(lang))
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path(cid).with_suffix(".tmp")
            tmp.write_bytes(audio)
            os.replace(tmp, self.path(cid))
            self.last_error = ""
            return cid
        except VoiceError as err:
            self.last_error = str(err)
            return None
        finally:
            with self._lock:
                self._inflight.pop(cid, None)
            event.set()

    def _synthesize(self, text: str, timeout: float, voice_id: str) -> bytes:
        s = self.settings
        body = {"text": text, "model_id": s.elevenlabs_model}
        if s.elevenlabs_speed:
            try:
                body["voice_settings"] = {"speed": float(s.elevenlabs_speed)}
            except ValueError:
                pass
        url = (f"{s.elevenlabs_api_base}/v1/text-to-speech/{voice_id}"
               "?output_format=mp3_44100_128")
        request = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"xi-api-key": s.elevenlabs_key, "Content-Type": "application/json",
                     "Accept": "audio/mpeg"},
        )
        self.requests_made += 1
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                audio = response.read()
        except urllib.error.HTTPError as err:
            raise VoiceError(f"ElevenLabs said HTTP {err.code}: {_error_detail(err)}") from err
        except urllib.error.URLError as err:
            raise VoiceError(f"Couldn't reach ElevenLabs: {err.reason}") from err
        except TimeoutError as err:
            raise VoiceError("ElevenLabs took too long") from err
        if len(audio) < 100:
            raise VoiceError("ElevenLabs sent back an empty clip")
        return audio


class VoiceError(RuntimeError):
    pass


def _error_detail(err) -> str:
    try:
        data = json.loads(err.read().decode("utf-8", "replace"))
        detail = data.get("detail", data)
        if isinstance(detail, dict):
            return detail.get("message") or detail.get("status") or json.dumps(detail)[:200]
        return str(detail)[:200]
    except Exception:
        return err.reason if hasattr(err, "reason") else "unknown error"
