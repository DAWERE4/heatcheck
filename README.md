# HeatCheck

**HeatCheck calls seniors who can't run AC when it gets dangerously hot, and gets a neighbor to their door if they don't answer. It works from live weather with nothing but a phone number, and an indoor sensor makes it precise.**

```
indoor sensor (phone slider for now)            ─┐
live outdoor weather (Open-Meteo), used when     ├→ server computes the heat index (National Weather Service formula)
  no sensor has reported for 5 minutes          ─┘
   → heat index over 90°F twice in a row → phone call: "Press 1 if you're OK, 2 if you need help"
        pressed 1 / said "yes"   → cooling tips + nearest cooling spot open right now, call again in 30 min
        pressed 2 / no answer / voicemail / hung up → push alert (and call) to a neighbor
   → dashboard shows every home live
```
```
heatcheck/
├── server.py                  ← run this
├── app/
│   ├── engine.py              ← the check-in logic (start reading here)
│   ├── heat.py                ← NWS heat index + categories
│   ├── cooling.py             ← which cooling spot is open now, and closest
│   ├── weather.py             ← live outdoor weather + forecast peak (Open-Meteo)
│   ├── services.py            ← Twilio calls + ntfy push alerts
│   ├── twiml.py               ← what the phone call says
│   ├── store.py, config.py
│   └── static/dashboard.html, sensor.html
├── data/homes.json            ← residents (phones come from .env)
├── data/cooling_spots.json    ← cooling centers + hours
└── tests/                     ← 24 tests, including the full call flow against fake Twilio and fake weather
```

---

## Simulation:

```bash
cp .env.example .env        # Windows: copy .env.example .env
python3 server.py           # Windows: py server.py
```

Open **http://localhost:8000/dashboard** and, in another tab, **http://localhost:8000/sensor**.

On the sensor page, tap **Heat wave**. In about 10 seconds the dashboard turns red and says **Calling now**. Click **No answer**, and the status changes to **Neighbor alerted**. Tap **Cool down** and after a few readings it goes back to **Normal**.

Check the tests pass: `python3 -m unittest discover -s tests -t . -v`

**Commit.**

---

## Notification Simulation:

1. Install the **ntfy** app and subscribe to a hard-to-guess topic, like `heatcheck-dawere4-7391`.
2. Restart the server (Ctrl+C, then `python3 server.py`) and repeat the Heat wave → No answer test. Your phone gets an urgent notification with the address, heat index and nearest open cooling spot.

---

## Live outdoor weather

The dashboard's **Outside now** card shows the real heat index where the resident lives, from [Open-Meteo](https://open-meteo.com/) (free, no key), plus the hottest hour coming up in the next 18 hours. It refreshes every 10 minutes (or click **Refresh**).

If no indoor sensor has sent a reading for 5 minutes, check-ins use this outdoor heat index instead. The call and the neighbor alert then say it's the heat *outside*, because a house without AC can be hotter than that. As soon as the sensor page sends again, the indoor reading takes over.

Settings in `.env`: `WEATHER=false` turns it off, `WEATHER_REFRESH_MINUTES` and `SENSOR_STALE_MINUTES` change the timing.

---

## Step 4: Real phone calls (20–30 min)

1. **Twilio:** upgrade your account (trial accounts can only use Twilio's sample call scripts and can only call verified numbers). Buy one US number with **Voice**. Copy the Account SID, Auth Token and the number.
2. **Tunnel:** in a second terminal, run:

   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```

   Copy the `https://something.trycloudflare.com` URL it prints. Leave this terminal open all day. The URL changes every time you restart cloudflared, so if you restart it, update `.env` and restart the server.
3. Fill in `.env`:

   ```
   PUBLIC_BASE_URL=https://something.trycloudflare.com
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=+14045551234
   RESIDENT_PHONE=+1YOURCELL
   NEIGHBOR_PHONE=            # optional second phone
   ```

4. Restart the server. The banner should say **Calls: LIVE**.
5. On the dashboard, click **Start check-in now**. Your phone rings. Press 1 and the status changes to "Said they're OK". Try again and don't answer; the neighbor gets alerted.

You don't need to set a webhook on the number in the Twilio console. Each call carries its own URLs.

**Commit.**

---

## Hardware (future work)

We didn't have an ESP32 at HackGT, so there's no firmware in this repo. The server already accepts readings from any sensor: `POST /api/readings` with `{"home_id": "demo", "temp_f": 91, "humidity": 55}`. Next step is a cheap Wi-Fi temperature/humidity sensor posting there every few seconds.

---

## Demo script (about 2.5 minutes)

1. **Open with one sentence:** "HeatCheck calls seniors who can't run AC when it gets dangerously hot, and gets a neighbor to their door if they don't answer."
2. **The problem (about 30 seconds):**
   - In the 2021 British Columbia heat dome, 98% of the 619 heat deaths happened indoors, 56% of the people lived alone, and two-thirds were 70 or older (BC Coroners Service review).
   - In August, Atlanta City Council told the mayor's office to plan heat outreach to seniors and people without AC, including robocalls. This is that.
   - Half of Atlanta's low-income households spend more than 10.2% of their income on energy, so many ration their AC.
3. **Live demo:**
   - Point at **Outside now**: that's today's real Atlanta weather. "With no sensor, this alone triggers the call."
   - "It isn't dangerous today, so here's a July afternoon." Let the judge click **Heat wave** on the sensor page.
   - Hand the judge your phone. It rings with the check-in. Ask them not to press anything.
   - About 25 seconds later the call gives up, and the neighbor alert pops up (keep ntfy.sh open in a laptop tab too, so everyone sees it).
4. **Name a limitation before they ask:** "Outdoor weather is only a rough guide, because a house without AC can stay hotter than outside, which is why a sensor is the upgrade. It's not a medical device, and it needs the resident's consent and a real neighbor. Next step: a pilot with a senior center."

**One phone?** Leave `NEIGHBOR_PHONE` blank so the no-answer only sends the push alert, not a second call to you.

Ms. Johnson is a composite demo persona, not a real person.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python3` not found on Windows | Use `py server.py` |
| Mac: `CERTIFICATE_VERIFY_FAILED` on push or calls | You have the python.org Python. Run *Install Certificates.command* in `/Applications/Python 3.x/` |
| The call says "an application error has occurred" | `PUBLIC_BASE_URL` is wrong or out of date, or the server isn't running. Check the cloudflared terminal and Twilio Console → Monitor → Logs |
| The phone never rings | Account not upgraded, number lacks Voice, or phone number isn't in `+1XXXXXXXXXX` format. The dashboard timeline shows Twilio's error message |
| Port already in use | Set `PORT=8001` in `.env` |
| Sample homes are distracting | Set `SAMPLE_HOMES=false` |
| "Weather update failed" on the dashboard | Check the laptop's internet. Everything else keeps working; `WEATHER=false` hides it |
| The big number flips back to outdoor weather | The sensor page stopped sending for 5 minutes (closed tab or sleeping phone). Reopen it |

---

## How the check-in works

| Status | Meaning | What changes it |
|---|---|---|
| Normal | Nothing to do | Heat index ≥ threshold for 2 readings → **Calling** |
| Calling now | Phone is ringing | 1 / "yes" → **OK**. 2 / "help", no answer, voicemail, busy, hang-up, or silence twice → **Neighbor alerted** |
| Said they're OK | They answered | Still hot after 30 min → **Calling** again. Cooled down → **Normal** |
| Neighbor alerted | Push alert (and call) sent | Cooled down → **Normal**, or Reset on the dashboard |

Heat index bands (National Weather Service): Caution 80–90°F, Extreme caution 90–103°F, Danger 103–124°F, Extreme danger 125°F+.

## Known limitations (good answers for "what breaks first?")

- State is in memory, so restarting the server clears it. A real version needs a database.
- Twilio webhook signatures aren't verified yet. Add that before any real use.
- Speech replies use simple keyword matching (`classify_reply` in `app/engine.py`).
- Cooling spot data is hand-entered. Verify the coordinates and add more places in `data/cooling_spots.json`.
- Without a sensor, HeatCheck only knows the outdoor heat index. A house without AC can stay hotter than outside, especially at night.

## Stretch goals

- Swap `classify_reply` for an LLM so "I feel a little dizzy" counts as help.
- Call in the morning when the forecast peak (already on the dashboard) will be dangerous.
- Spanish calls: set `RESIDENT_LANGUAGE=es`.
- More residents: add entries to `data/homes.json`.

## Sources

- City of Atlanta cooling center hours, June 30 2026: https://www.atlantaga.gov/Home/Components/News/News/15758
- AJC, City Council extreme heat plan (Aug 2026): https://www.ajc.com/news/2026/08/under-fire-city-council-tells-mayors-office-to-craft-extreme-heat-plan/
- ACEEE, Georgia energy burden: https://www.aceee.org/sites/default/files/pdf/fact-sheet/ses-georgia-100917.pdf
- NWS heat index equation: https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
- CBC on the BC Coroners Service heat dome review: https://www.cbc.ca/news/canada/british-columbia/bc-heat-dome-coroners-report-1.6480026
- Weather data by Open-Meteo.com (CC BY 4.0): https://open-meteo.com/
