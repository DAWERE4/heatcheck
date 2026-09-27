# HeatCheck

**HeatCheck calls seniors who can't run AC when it gets dangerously hot, and gets a neighbor to their door if they don't answer.**

Built solo at HackGT 13 for *A Marina's Mission* (presented by Aramco).

<!-- Add your links: -->
<!-- Demo video: https://youtu.be/... · Devpost: https://devpost.com/software/... -->

```
indoor sensor, or live outdoor weather if there's no sensor
   → heat index (National Weather Service formula) reaches 90°F twice in a row
   → phone call in a natural voice, in English or Spanish: "Press 1 if you're okay, 2 if you need help"
        okay           → cooling tips + nearest cooling center open right now; calls again in 30 min if still hot
        help / no answer / voicemail → urgent alert to a neighbor's phone with the address and directions
```

- **Works with just a phone number.** No sensor? It uses live local weather, and the call says it's the heat *outside*.
- **Natural voice** from ElevenLabs, with automatic fallback to Twilio's voice.
- **English and Spanish,** switchable per resident from the dashboard.
- **Knows which cooling centers are open right now**, not just where they are.
- **Live dashboard** with every home, the outdoor forecast peak, and a timeline of every call.

---

## Quick start (2 minutes, no accounts)

Requires Python 3.10 or newer. There's nothing to install.

```bash
git clone https://github.com/DAWERE4/heatcheck.git
cd heatcheck
cp .env.example .env        # Windows: copy .env.example .env
python3 server.py           # Windows: py server.py
```

Open **http://localhost:8000/dashboard** and **http://localhost:8000/sensor**.

On the sensor page, tap **Heat wave**. About 10 seconds later the dashboard turns red and starts a (simulated) check-in call. Click **No answer** and the status changes to **Neighbor alerted**.

---

## Going live

Each part is optional and works on its own. After editing `.env`, restart the server.

### 1. Neighbor alerts (ntfy, free)
1. Install the **ntfy** app and subscribe to a hard-to-guess topic. Anyone who knows the name can read it.
2. In `.env`: `NTFY_TOPIC=your-topic-name`

### 2. Natural voice (ElevenLabs, free plan works)
1. Create an API key at elevenlabs.io with **Text to Speech** allowed.
2. In `.env`: `ELEVENLABS_API_KEY=...`
3. Click **▶ Hear the call** on the dashboard to check it. This works without Twilio.

### 3. Real phone calls (Twilio + Cloudflare Tunnel)
1. Upgrade your Twilio account (trial accounts can't use custom call scripts) and buy a US number with **Voice**.
2. Install cloudflared (Windows: `winget install --id Cloudflare.cloudflared`, Mac: `brew install cloudflared`) and run:
   ```bash
   cloudflared tunnel --url http://127.0.0.1:8000
   ```
   Keep it open. Use `http://127.0.0.1`, not `localhost` or `https`. The URL changes each time you restart it.
3. In `.env`:
   ```
   PUBLIC_BASE_URL=https://your-tunnel.trycloudflare.com
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=+14045551234
   RESIDENT_PHONE=+1...        # the phone that gets the check-in
   NEIGHBOR_PHONE=             # optional: also call the neighbor
   ```
4. Restart. The server should print **Calls: LIVE**. Click **Start check-in now** to test.

**Demoing with one phone:** leave `NEIGHBOR_PHONE` blank. Save the Twilio number as a contact, and turn off Focus / Do Not Disturb and "Silence Unknown Callers," or the call goes straight to voicemail.

---

## Using it

| Dashboard control | What it does |
|---|---|
| **Start check-in now** | Calls the resident immediately |
| **▶ Hear the call** | Plays the opening line in your browser |
| **Call language** | Switches the resident's calls between English and Español |
| **Open virtual sensor** | A phone-friendly slider page that sends readings like a real sensor |
| **Reset** | Clears the alert and returns to Normal |
| **Pressed 1 / Pressed 2 / No answer** | Shown during simulated calls (when Twilio isn't set up) |

**Real sensors** can send readings with:
```bash
curl -X POST http://localhost:8000/api/readings -H "Content-Type: application/json" \
  -d '{"home_id": "demo", "temp_f": 91, "humidity": 55}'
```
(`temp_c` also works. If `DEVICE_KEY` is set, include `"device_key"`.) If no sensor reports for 5 minutes, HeatCheck switches to live outdoor weather.

**Residents** are in `data/homes.json` (phone numbers come from `.env`). **Cooling centers and their hours** are in `data/cooling_spots.json`. "Ms. Johnson" is a made-up demo persona.

---

## Configuration (`.env`)

| Setting | Default | What it does |
|---|---|---|
| `NTFY_TOPIC` | none | ntfy topic for neighbor alerts |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `PUBLIC_BASE_URL` | none | All four are needed for real calls |
| `RESIDENT_PHONE`, `NEIGHBOR_PHONE`, `NEIGHBOR_NAME` | none | Who gets called |
| `RESIDENT_LANGUAGE` | `en` | Starting call language (`en` or `es`) |
| `ELEVENLABS_API_KEY` | none | Turns on the natural voice |
| `ELEVENLABS_VOICE_ID` / `ELEVENLABS_VOICE_ID_ES` | George / same | Voice for English / Spanish calls |
| `ELEVENLABS_SPEED` | normal | e.g. `0.9` to speak slower |
| `ALERT_HEAT_INDEX_F` | `90` | Heat index that triggers a check-in |
| `ALERT_CONSECUTIVE_READINGS` | `2` | Hot readings in a row before calling |
| `RECHECK_MINUTES` | `30` | Call again this long after "I'm okay" if still hot |
| `WEATHER` | `true` | Live outdoor weather (Open-Meteo) |
| `SENSOR_STALE_MINUTES` | `5` | Minutes without a sensor reading before switching to weather |
| `SIMULATE_CALLS` | `false` | Never place real calls, even if Twilio is set up |
| `SAMPLE_HOMES` | `true` | Show the sample homes in the sidebar |
| `PORT` | `8000` | Server port |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Tunnel URL shows **Bad Gateway** | Start the server in its own terminal, and start the tunnel with `http://127.0.0.1:8000` |
| Call says "an application error has occurred" | `PUBLIC_BASE_URL` is out of date. Check the cloudflared window and Twilio Console → Monitor → Logs |
| Phone never rings | Twilio account not upgraded, number lacks Voice, or phone not in `+1XXXXXXXXXX` format. The dashboard timeline shows Twilio's error |
| Badge says **ElevenLabs voice (failing)** | Hover it for the reason, usually the key or its Text to Speech permission. Calls still work with Twilio's voice |
| "Weather update failed" | Check your internet connection. Everything else keeps working |
| `python3` not found on Windows | Use `py server.py` |

---

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
35 tests, including the full call flow against fake Twilio, weather and ElevenLabs servers.

## Project structure

```
server.py                 web server (run this)
app/engine.py             check-in logic: when to call, what to say, when to alert
app/heat.py               NWS heat index
app/weather.py            live weather + forecast peak (Open-Meteo)
app/voice.py              ElevenLabs voice with caching and fallback
app/cooling.py            which cooling center is open and closest
app/services.py           Twilio calls + ntfy alerts
app/twiml.py              phone call instructions (TwiML)
app/static/               dashboard + virtual sensor pages
data/                     residents and cooling centers
tests/                    automated tests
```

## Limitations and what's next

- Without a sensor it only knows the outdoor heat index, and a house without AC can be hotter inside, especially at night. Next step: a cheap Wi-Fi temperature sensor per home.
- One alert threshold for everyone. For older adults with health problems, even 80°F can be dangerous, so per-person thresholds are next.
- State is in memory (a restart clears it), and Twilio webhook signatures aren't verified yet. Both are needed before real use.
- Next: a pilot with a senior center, more languages checked by native speakers, and morning calls when the forecast is dangerous.

## Built with

Python · Twilio Voice · ElevenLabs · Open-Meteo · ntfy · Cloudflare Tunnel · HTML/CSS/JavaScript

Built with help from Claude (an AI coding assistant), which wrote much of the code under my direction. I chose the problem and features, did the research, set up the services, and tested everything on real phones.

Weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0). Call voice by [ElevenLabs](https://elevenlabs.io/).

## Sources

- NASA, Europe's Scorching Summer (Aug 2026): https://science.nasa.gov/earth/europes-scorching-summer/
- BC Coroners Service heat dome review, via CBC: https://www.cbc.ca/news/canada/british-columbia/bc-heat-dome-coroners-report-1.6480026
- ACEEE, Georgia energy burden: https://www.aceee.org/sites/default/files/pdf/fact-sheet/ses-georgia-100917.pdf
- AJC, Atlanta City Council extreme heat plan (Aug 2026): https://www.ajc.com/news/2026/08/under-fire-city-council-tells-mayors-office-to-craft-extreme-heat-plan/
- City of Atlanta, cooling center hours (June 2026): https://www.atlantaga.gov/Home/Components/News/News/15758
- NWS heat index equation: https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
