"""The check-in logic: when to call, what to say, and when to alert a neighbor.

Status flow for a home:

    normal --(heat index over threshold N readings in a row)--> calling
    calling --(pressed 1 / said yes)--> ok
    calling --(pressed 2, no answer, voicemail, busy, hung up)--> escalated
    ok --(still hot after RECHECK_MINUTES)--> calling again
    ok / escalated --(cooled down for a few readings)--> normal

Where readings come from:
    - an indoor sensor (ESP32, or the virtual sensor page) when one is sending, or
    - live outdoor weather (Open-Meteo) when no sensor has reported for
      SENSOR_STALE_MINUTES. Outdoor heat is only a rough guide to indoor heat,
      so the call script and alerts say "outside" when that's the source.
"""

import random
import re
import threading
import time
import urllib.parse

from . import twiml
from .cooling import local_now, nearest_open
from .heat import category, heat_index_f
from .services import ServiceError, ntfy_publish, twilio_create_call
from .voice import Voice
from .weather import WeatherError, fetch_weather

LANGUAGE_NAMES = {"en": "English", "es": "Español"}
CALL_WATCHDOG_SECONDS = 120  # if a call never reports back, escalate anyway
COOL_DOWN_MARGIN_F = 4.0     # must drop this far below the threshold to reset
COOL_DOWN_READINGS = 3

HELP_WORDS = [
    r"help", r"ayuda", r"emergenc", r"dizzy", r"sick", r"not ok", r"not okay",
    r"not good", r"not fine", r"bad", r"can'?t breathe", r"maread", r"no estoy bien",
    r"me siento mal", r"hurt",
]
OK_WORDS = [
    r"yes", r"yeah", r"yep", r"okay", r"ok", r"fine", r"good", r"alright",
    r"all right", r"s[ií]", r"bien", r"estoy bien",
]


def classify_reply(digits: str, speech: str) -> str:
    """Return "ok", "help" or "unclear".

    Stretch goal: replace the keyword matching below with an LLM call that
    reads `speech` and returns one of the three labels.
    """
    digits = (digits or "").strip()
    if digits == "1":
        return "ok"
    if digits == "2":
        return "help"
    text = (speech or "").lower()
    if not text:
        return "unclear"
    if any(re.search(rf"\b{w}", text) for w in HELP_WORDS):
        return "help"
    if any(re.search(rf"\b{w}\b", text) for w in OK_WORDS):
        return "ok"
    return "unclear"


def maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"


class Engine:
    def __init__(self, settings, store, spots, now_fn=local_now, run_async=True):
        self.settings = settings
        self.store = store
        self.spots = spots
        self.now_fn = now_fn
        self.run_async = run_async
        self.weather_fetch = fetch_weather  # swapped out in tests
        self.weather_checked_at = 0.0
        self.voice = Voice(settings)
        self._voice_error_logged = ""

    # ---------- helpers ----------

    def _bg(self, fn, *args):
        if self.run_async:
            threading.Thread(target=fn, args=args, daemon=True).start()
        else:
            fn(*args)

    def url(self, path: str, **params) -> str:
        query = urllib.parse.urlencode(params)
        return f"{self.settings.public_base_url}{path}" + (f"?{query}" if query else "")

    def calls_live(self, home) -> bool:
        return self.settings.live_calls and home.live and bool(home.resident_phone)

    def last_hi(self, home) -> int:
        last = home.last
        return int(round(last["hi"])) if last else 0

    def spot_for(self, home) -> dict:
        return nearest_open(home.lat, home.lon, self.spots, self.now_fn())

    def speak(self, home, text: str, lang: str = None) -> str:
        """TwiML for saying `text`: the ElevenLabs clip if we have one, else Twilio's voice."""
        lang = lang or home.language
        clip = self.voice.get(text, lang=lang)
        if clip:
            return twiml.play(self.url(f"/audio/{clip}.mp3"))
        if self.voice.enabled and self.voice.last_error and self.voice.last_error != self._voice_error_logged:
            self._voice_error_logged = self.voice.last_error
            self.store.add_event(home, f"ElevenLabs voice failed, using the backup voice. {self.voice.last_error}", "error")
        return twiml.say(text, lang)

    def prefetch_voice(self, home) -> None:
        """Make the opening line's audio while the phone is ringing, so there's no pause."""
        if self.voice.enabled:
            self._bg(lambda: self.voice.get(self.prompt_text(home, 1), lang=home.language))

    # ---------- readings ----------

    def add_reading(self, home, temp_f: float, humidity: float, source: str = "sensor") -> dict:
        hi = heat_index_f(temp_f, humidity)
        cat = category(hi)
        reading = {
            "t": time.time(),
            "temp_f": round(float(temp_f), 1),
            "humidity": round(float(humidity), 1),
            "hi": round(hi, 1),
            "category": cat["label"],
            "css": cat["css"],
        }
        threshold = self.settings.alert_heat_index_f
        action = None
        with self.store.lock:
            home.readings.append(reading)
            home.last_source = source
            if source != "weather":
                home.last_sensor_at = reading["t"]
            if home.sample:
                return reading
            if hi >= threshold:
                home.over_count += 1
                home.under_count = 0
            elif hi < threshold - COOL_DOWN_MARGIN_F:
                home.under_count += 1
                home.over_count = 0
            else:
                home.over_count = 0

            waited = time.time() - home.status_since
            if home.status == "normal" and home.over_count >= self.settings.alert_consecutive:
                action = "checkin"
            elif home.status == "ok" and hi >= threshold and waited >= self.settings.recheck_minutes * 60:
                action = "checkin"
            elif home.status in ("ok", "escalated") and home.under_count >= COOL_DOWN_READINGS:
                action = "cooled"

        if action == "checkin":
            where = "Outdoor heat index (no indoor sensor)" if source == "weather" else "Heat index"
            self.start_checkin(home, f"{where} hit {hi:.0f}°F ({cat['label']})")
        elif action == "cooled":
            self.store.set_status(home, "normal")
            self.store.add_event(home, f"Cooled down to {hi:.0f}°F. Back to normal.", "good")
        return reading

    # ---------- check-in call ----------

    def start_checkin(self, home, trigger: str) -> None:
        with self.store.lock:
            if home.status == "calling":
                return
            home.checkins += 1
            home.over_count = 0
            home.call_sid = ""
            self.store.set_status(home, "calling", trigger)
        self.store.add_event(home, f"{trigger}. Calling {home.name} to check in.", "alert")
        if self.calls_live(home):
            self.prefetch_voice(home)
            self._bg(self._place_resident_call, home)
        else:
            why = "no Twilio set up" if not self.settings.live_calls else "no RESIDENT_PHONE set"
            self.store.add_event(
                home, f"Simulated call ({why}). Use the dashboard buttons to choose what happens.", "info"
            )

    def _place_resident_call(self, home) -> None:
        try:
            sid = twilio_create_call(
                self.settings,
                to=home.resident_phone,
                url=self.url("/twilio/voice", home_id=home.id, attempt=1),
                status_callback=self.url("/twilio/status", home_id=home.id, leg="resident"),
            )
            home.call_sid = sid
            self.store.add_event(home, "Phone is ringing.", "info")
        except ServiceError as err:
            self.store.add_event(home, f"Couldn't place the call. {err}", "error")
            self.escalate(home, "couldn't be reached because the check-in call failed")

    def heat_sentence(self, home, hi: int = None) -> str:
        """One sentence about how hot it is, honest about whether we measured inside."""
        hi = self.last_hi(home) if hi is None else hi
        if home.language == "es":
            if home.using_weather:
                return (
                    f"Hoy hace un calor peligroso afuera, un índice de calor de unos {hi} grados. "
                    "Una casa sin aire acondicionado puede estar aún más caliente por dentro."
                )
            return f"Está haciendo un calor peligroso dentro de su casa, unos {hi} grados."
        if home.using_weather:
            return (
                f"It is dangerously hot outside today, a heat index of about {hi} degrees. "
                "A home without air conditioning can get even hotter inside."
            )
        return f"It is getting dangerously hot inside your home, about {hi} degrees."

    def prompt_text(self, home, attempt: int, hi: int = None) -> str:
        if home.language == "es":
            if attempt > 1:
                return "Perdón, no le entendí. Si está bien, oprima 1. Si necesita ayuda, oprima 2."
            return (
                f"Hola, {home.name}. Le habla HeatCheck, su llamada de seguridad por el calor. "
                f"{self.heat_sentence(home, hi)} "
                "Si está bien, oprima 1 o diga sí. Si necesita ayuda, oprima 2 o diga ayuda."
            )
        if attempt > 1:
            return "Sorry, I didn't catch that. If you are okay, press 1. If you need help, press 2."
        return (
            f"Hello, {home.name}. This is HeatCheck, your heat safety check. "
            f"{self.heat_sentence(home, hi)} "
            "If you are okay, press 1 or say yes. If you need help, press 2 or say help."
        )

    def ok_text(self, home) -> str:
        spot = self.spot_for(home)
        minutes = int(self.settings.recheck_minutes)
        if home.language == "es":
            place = (
                f"El centro de enfriamiento abierto más cercano es {spot['name']}, en {spot['address']}."
                if spot["found"]
                else "No hay un centro de enfriamiento abierto ahora. Si se siente confundido o mareado, o deja de sudar, llame al 9 1 1."
            )
            return (
                "Gracias. Tome agua, quédese en el cuarto más fresco y use un ventilador o un paño húmedo y fresco. "
                f"{place} Le volveremos a llamar en {minutes} minutos si sigue haciendo calor. Adiós."
            )
        place = (
            f"The nearest cooling center open right now is {spot['say']}."
            if spot["found"]
            else spot["say"]
        )
        return (
            "Thank you. Please drink water, stay in the coolest room, and use a fan or a cool, wet cloth. "
            f"{place} We will call again in {minutes} minutes if it stays hot. Goodbye."
        )

    def help_text(self, home) -> str:
        if home.language == "es":
            return (
                f"Entendido. Estamos avisando a {home.neighbor_name} ahora mismo para que venga a verle. "
                "Si se siente confundido o mareado, o deja de sudar, cuelgue y llame al 9 1 1."
            )
        return (
            f"Okay. We are contacting {home.neighbor_name} right now to check on you. "
            "If you feel confused or dizzy, or you stop sweating, hang up and call 9 1 1."
        )

    def voicemail_text(self, home) -> str:
        if home.language == "es":
            return (
                f"Hola, {home.name}. Le habla HeatCheck. {self.heat_sentence(home)} "
                "Tome agua y busque un lugar fresco. Vamos a pedirle a alguien que venga a verle."
            )
        return (
            f"Hello, {home.name}. This is HeatCheck. {self.heat_sentence(home)} "
            "Please drink water and get somewhere cool. We are asking someone to come check on you."
        )

    def goodbye_text(self, home) -> str:
        if home.language == "es":
            return "Vamos a pedirle a alguien que venga a verle. Adiós."
        return "We'll ask someone to come check on you. Goodbye."

    # ---------- Twilio webhooks (each returns TwiML) ----------

    def voice_twiml(self, home, params: dict, attempt: int) -> str:
        answered_by = params.get("AnsweredBy", "")
        if answered_by.startswith("machine") or answered_by == "fax":
            self.store.add_event(home, "Voicemail picked up.", "info")
            self.escalate(home, "didn't pick up (the call went to voicemail)")
            return twiml.response(self.speak(home, self.voicemail_text(home)), twiml.hangup())
        prompt = self.prompt_text(home, attempt)
        return twiml.response(
            twiml.gather(
                prompt,
                self.url("/twilio/gather", home_id=home.id, attempt=attempt),
                home.language,
                inner=self.speak(home, prompt),
            ),
            twiml.redirect(self.url("/twilio/no-input", home_id=home.id, attempt=attempt)),
        )

    def gather_twiml(self, home, params: dict, attempt: int) -> str:
        digits = params.get("Digits", "")
        speech = params.get("SpeechResult", "")
        result = classify_reply(digits, speech)
        heard = f"pressed {digits}" if digits else (f'said "{speech}"' if speech else "said nothing")
        self.store.add_event(home, f"{home.name} {heard}.", "info")

        if result == "ok":
            self.mark_ok(home)
            return twiml.response(self.speak(home, self.ok_text(home)), twiml.hangup())
        if result == "help":
            self.escalate(home, "asked for help on the check-in call")
            return twiml.response(self.speak(home, self.help_text(home)), twiml.hangup())
        if attempt < 2:
            return twiml.response(twiml.redirect(self.url("/twilio/voice", home_id=home.id, attempt=2)))
        self.escalate(home, "gave an unclear answer twice")
        return twiml.response(self.speak(home, self.goodbye_text(home)), twiml.hangup())

    def no_input_twiml(self, home, attempt: int) -> str:
        if attempt < 2:
            return twiml.response(twiml.redirect(self.url("/twilio/voice", home_id=home.id, attempt=2)))
        self.escalate(home, "didn't respond on the check-in call")
        return twiml.response(self.speak(home, self.goodbye_text(home)), twiml.hangup())

    def status_callback(self, home, params: dict, leg: str) -> None:
        status = params.get("CallStatus", "")
        if leg == "neighbor":
            self.store.add_event(home, f"Call to {home.neighbor_name}: {status}.", "info")
            return
        reasons = {
            "no-answer": "didn't pick up the check-in call",
            "busy": "didn't pick up (line busy)",
            "failed": "couldn't be reached (call failed)",
            "canceled": "couldn't be reached (call canceled)",
            "completed": "hung up before answering the check-in",
        }
        if home.status == "calling" and status in reasons:
            self.escalate(home, reasons[status])

    def neighbor_twiml(self, home) -> str:
        hi = self.last_hi(home)
        where = "outside" if home.using_weather else "inside their home"
        message = (
            f"This is HeatCheck. {home.name}, at {home.address}, {home.reason}. "
            f"The heat index {where} is about {hi} degrees. "
            "Please go check on them now. If they are confused or not sweating, call 9 1 1. "
            "Details were sent to your phone."
        )
        spoken = self.speak(home, message, "en")
        return twiml.response(spoken, twiml.pause(1), spoken, twiml.hangup())

    # ---------- outcomes ----------

    def mark_ok(self, home) -> None:
        self.store.set_status(home, "ok", "Answered the check-in")
        self.store.add_event(
            home,
            f"{home.name} is OK. Gave cooling tips and the nearest open cooling spot. "
            f"Will call again in {int(self.settings.recheck_minutes)} min if it stays hot.",
            "good",
        )

    def escalate(self, home, reason: str) -> None:
        with self.store.lock:
            if home.status == "escalated":
                return
            self.store.set_status(home, "escalated", reason)
        self.store.add_event(home, f"{home.name} {reason}. Alerting {home.neighbor_name}.", "alert")
        self._bg(self._notify_neighbor, home, reason)

    def _notify_neighbor(self, home, reason: str) -> None:
        hi = self.last_hi(home)
        cat = category(hi)["label"]
        spot = self.spot_for(home)
        spot_line = (
            f"Nearest open cooling spot: {spot['name']} ({spot['miles']} mi)."
            if spot["found"]
            else f"No cooling center open right now ({spot['closed']} closed)."
        )
        if self.settings.ntfy_topic:
            try:
                link = maps_link(home.lat, home.lon)
                ntfy_publish(
                    self.settings,
                    topic=self.settings.ntfy_topic,
                    title=f"HeatCheck: please check on {home.name} now",
                    message=(
                        f"{home.name} ({home.address}) {reason}.\n"
                        f"{'Outdoor heat index (no indoor sensor)' if home.using_weather else 'Indoor heat index'}: "
                        f"{hi}°F ({cat}).\n{spot_line}\n"
                        "If they're confused, dizzy or not sweating, call 911."
                    ),
                    priority=5,
                    tags=["warning", "thermometer"],
                    click=link,
                    actions=[{"action": "view", "label": "Directions", "url": link}],
                )
                self.store.add_event(home, f"Push alert sent to {home.neighbor_name}.", "info")
            except ServiceError as err:
                self.store.add_event(home, f"Push alert failed. {err}", "error")
        else:
            self.store.add_event(home, "No NTFY_TOPIC set, so no push alert was sent.", "error")

        if self.settings.live_calls and home.neighbor_phone:
            try:
                twilio_create_call(
                    self.settings,
                    to=home.neighbor_phone,
                    url=self.url("/twilio/neighbor", home_id=home.id),
                    status_callback=self.url("/twilio/status", home_id=home.id, leg="neighbor"),
                    machine_detection=False,
                )
                self.store.add_event(home, f"Calling {home.neighbor_name}.", "info")
            except ServiceError as err:
                self.store.add_event(home, f"Couldn't call {home.neighbor_name}. {err}", "error")

    # ---------- dashboard actions ----------

    def set_language(self, home, lang: str) -> bool:
        """Switch which language this resident is called in (English or Spanish)."""
        if lang not in twiml.VOICES:
            return False
        if lang != home.language:
            home.language = lang
            self.store.add_event(home, f"Calls will now be in {LANGUAGE_NAMES.get(lang, lang)}.", "info")
        return True

    def preview(self, home) -> dict:
        """The opening line of the call as audio, so the dashboard can play it.
        If it isn't hot right now, preview with a July-style heat index of 104°F."""
        hi = self.last_hi(home)
        if hi < self.settings.alert_heat_index_f:
            hi = 104
        text = self.prompt_text(home, 1, hi=hi)
        if not self.voice.enabled:
            return {"ok": False, "text": text,
                    "error": "Add ELEVENLABS_API_KEY to .env and restart the server to hear the ElevenLabs voice."}
        clip = self.voice.get(text, timeout=15, lang=home.language)
        if not clip:
            return {"ok": False, "text": text, "error": f"ElevenLabs didn't work: {self.voice.last_error}"}
        return {"ok": True, "text": text, "url": f"/audio/{clip}.mp3"}

    def reset(self, home) -> None:
        with self.store.lock:
            home.over_count = 0
            home.under_count = 0
            self.store.set_status(home, "normal")
        self.store.add_event(home, "Reset from the dashboard.", "info")

    def simulate(self, home, outcome: str) -> bool:
        if home.status != "calling":
            return False
        if outcome == "ok":
            self.store.add_event(home, f"(Simulated) {home.name} pressed 1.", "info")
            self.mark_ok(home)
        elif outcome == "help":
            self.store.add_event(home, f"(Simulated) {home.name} pressed 2.", "info")
            self.escalate(home, "asked for help on the check-in call")
        elif outcome == "no_answer":
            self.store.add_event(home, "(Simulated) The phone rang with no answer.", "info")
            self.escalate(home, "didn't pick up the check-in call")
        else:
            return False
        return True

    # ---------- outdoor weather ----------

    def sensor_is_stale(self, home, now: float = None) -> bool:
        now = now or time.time()
        return now - home.last_sensor_at > self.settings.sensor_stale_minutes * 60

    def refresh_weather(self) -> None:
        """Fetch outdoor weather for each home. Homes with no recent sensor reading
        get the outdoor heat index as their reading, which can trigger a check-in."""
        if not self.settings.weather_enabled:
            return
        self.weather_checked_at = time.time()
        cache = {}
        for home in list(self.store.homes.values()):
            if home.sample:
                continue
            key = (round(home.lat, 2), round(home.lon, 2))
            if key not in cache:
                try:
                    cache[key] = self.weather_fetch(self.settings, home.lat, home.lon)
                except WeatherError as err:
                    cache[key] = err
            result = cache[key]
            if isinstance(result, WeatherError):
                if home.weather_error != str(result):
                    self.store.add_event(home, f"Weather update failed. {result}", "error")
                home.weather_error = str(result)
                continue
            if home.weather_error:
                self.store.add_event(home, "Weather updates are working again.", "info")
            home.weather_error = ""
            home.weather = result
            if self.sensor_is_stale(home):
                self.add_reading(home, result["temp_f"], result["humidity"], source="weather")

    # ---------- background tick ----------

    def tick(self) -> None:
        """Runs every few seconds: moves sample homes and catches stuck calls."""
        now = time.time()
        for home in list(self.store.homes.values()):
            if home.sample:
                temp = home.sample_temp_f + random.uniform(-0.6, 0.6)
                rh = home.sample_humidity + random.uniform(-1.5, 1.5)
                self.add_reading(home, temp, rh, source="sample")
            elif home.status == "calling" and now - home.status_since > CALL_WATCHDOG_SECONDS:
                self.store.add_event(home, "The check-in never finished.", "error")
                self.escalate(home, "didn't complete the check-in call")

    # ---------- dashboard state ----------

    def state(self) -> dict:
        s = self.settings
        with self.store.lock:
            homes = [
                self.store.public_home(h, {"cooling": self.spot_for(h), "calls_live": self.calls_live(h)})
                for h in self.store.homes.values()
            ]
        return {
            "mode": "live" if s.live_calls else "simulate",
            "missing_for_live": s.missing_for_live(),
            "threshold_f": s.alert_heat_index_f,
            "recheck_minutes": s.recheck_minutes,
            "push_alerts": bool(s.ntfy_topic),
            "voice": {"elevenlabs": self.voice.enabled, "error": self.voice.last_error},
            "languages": LANGUAGE_NAMES,
            "weather_enabled": s.weather_enabled,
            "weather_refresh_minutes": s.weather_refresh_minutes,
            "sensor_stale_minutes": s.sensor_stale_minutes,
            "now": time.time(),
            "homes": homes,
        }
