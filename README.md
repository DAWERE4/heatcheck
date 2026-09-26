# HeatCheck

**HeatCheck watches the indoor heat in the homes of seniors who can't run AC, calls them when it gets dangerous, and gets a neighbor to their door if they don't answer.**

Built at HackGT 13 for *A Marina's Mission* (presented by Aramco).

```
sensor (ESP32 or phone slider)
   → server computes the heat index (National Weather Service formula)
   → heat index over 90°F twice in a row → phone call: "Press 1 if you're OK, 2 if you need help"
        pressed 1 / said "yes"   → cooling tips + nearest cooling spot open right now, call again in 30 min
        pressed 2 / no answer / voicemail / hung up → push alert (and call) to a neighbor
   → dashboard shows every home live
```

No Python packages to install. It only uses the standard library.

```
heatcheck/
├── server.py                  ← run this
├── app/
│   ├── engine.py              ← the check-in logic (start reading here)
│   ├── heat.py                ← NWS heat index + categories
│   ├── cooling.py             ← which cooling spot is open now, and closest
│   ├── services.py            ← Twilio calls + ntfy push alerts
│   ├── twiml.py               ← what the phone call says
│   ├── store.py, config.py
│   └── static/dashboard.html, sensor.html
├── data/homes.json            ← residents (phones come from .env)
├── data/cooling_spots.json    ← cooling centers + hours
├── firmware/heatcheck_esp32/  ← Arduino sketch for ESP32 + DHT22
└── tests/                     ← 17 tests, including the full call flow against fake Twilio
```

---

## Step 1: Put it on GitHub (5 min)

1. On github.com, create an **empty public** repo called `heatcheck` (no README).
2. Unzip this folder, open a terminal in it, and run:

   ```bash
   git init
   git add -A
   git commit -m "HeatCheck starter: server, dashboard, virtual sensor, ESP32 sketch"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/heatcheck.git
   git push -u origin main
   ```

   If it asks for a password, GitHub wants a token, not your password. Easiest fixes: install the GitHub CLI and run `gh auth login`, or use GitHub Desktop (File → Add local repository).

3. Commit every time something works (`git add -A && git commit -m "..."` then `git push`). HackGT doesn't allow past projects, and a commit history from this weekend shows you built it here.

---

## Step 2: Run it with simulated calls (5 min, no accounts)

```bash
cp .env.example .env        # Windows: copy .env.example .env
python3 server.py           # Windows: py server.py
```

Open **http://localhost:8000/dashboard** and, in another tab, **http://localhost:8000/sensor**.

On the sensor page, tap **Heat wave**. In about 10 seconds the dashboard turns red and says **Calling now**. Click **No answer**, and the status changes to **Neighbor alerted**. Tap **Cool down** and after a few readings it goes back to **Normal**.

Check the tests pass: `python3 -m unittest discover -s tests -t . -v`

**Commit.**

---

## Step 3: Push alerts to a phone (5 min)

1. Install the **ntfy** app and subscribe to a hard-to-guess topic, like `heatcheck-yourname-7391`. Anyone who knows the topic name can read it, so don't use your real name alone.
2. Put the same topic in `.env`: `NTFY_TOPIC=heatcheck-yourname-7391`
3. Restart the server (Ctrl+C, then `python3 server.py`) and repeat the Heat wave → No answer test. Your phone gets an urgent notification with the address, heat index and nearest open cooling spot.

We use ntfy instead of text messages because US carriers block texts from unregistered Twilio numbers, and registration takes days.

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

## Step 5: ESP32 sensor (optional, 30–60 min)

You need an ESP32 dev board, a DHT22 (or DHT11) sensor, 3 jumper wires and a USB cable.

1. Wire it: sensor **+** → 3V3, **−** → GND, **OUT** → GPIO 4.
2. In the Arduino IDE:
   - Boards Manager: install **esp32** by Espressif.
   - Library Manager: install **DHT sensor library** by Adafruit (and **Adafruit Unified Sensor** when it asks).
3. Open `firmware/heatcheck_esp32/heatcheck_esp32.ino` and set:
   - `WIFI_SSID` / `WIFI_PASS`: use your **phone's hotspot**, because the ESP32 can't log in to eduroam. On iPhone, turn on *Maximize Compatibility* so it's 2.4 GHz.
   - `SERVER_URL`: your trycloudflare URL.
4. Upload, then open the Serial Monitor at 115200 baud. You should see `-> HTTP 200` every 3 seconds, and the dashboard shows "from ESP32 sensor".
5. **Demo:** warm the sensor gently with a hairdryer from about a foot away. Hot air is dry, so the heat index climbs a bit slower than the temperature. If it won't cross 90, set `ALERT_HEAT_INDEX_F=85` for the demo.

---

## Demo script (about 2.5 minutes)

1. **Open with one sentence:** "HeatCheck watches the indoor heat in the homes of seniors who can't run AC, calls them when it gets dangerous, and gets a neighbor to their door if they don't answer."
2. **The problem (about 30 seconds):**
   - In August, Atlanta City Council told the mayor's office to plan heat outreach to seniors and people without AC, including robocalls. This is that.
   - During July's heat wave, the city's cooling center was open weekdays 11am to 6pm only.
   - Half of Atlanta's low-income households spend more than 10.2% of their income on energy, so many ration their AC.
3. **Live demo:**
   - Hairdryer on the sensor (or Heat wave on the slider), and the dashboard turns red.
   - Hand the judge the "resident" phone. It rings, and they hear the check-in.
   - Ask them not to press anything. The neighbor's phone buzzes with the address and the nearest open cooling spot.
4. **Name a limitation before they ask:** "It's not a medical device, and it only works with the resident's consent and a real network of neighbors. Our next step is a pilot with a senior center."

Ms. Johnson is a composite demo persona, not a real person.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python3` not found on Windows | Use `py server.py` |
| Mac: `CERTIFICATE_VERIFY_FAILED` on push or calls | You have the python.org Python. Run *Install Certificates.command* in `/Applications/Python 3.x/` |
| The call says "an application error has occurred" | `PUBLIC_BASE_URL` is wrong or out of date, or the server isn't running. Check the cloudflared terminal and Twilio Console → Monitor → Logs |
| The phone never rings | Account not upgraded, number lacks Voice, or phone number isn't in `+1XXXXXXXXXX` format. The dashboard timeline shows Twilio's error message |
| ESP32 prints `HTTP -1` | Wrong `SERVER_URL` or Wi-Fi. The hotspot must be 2.4 GHz |
| Port already in use | Set `PORT=8001` in `.env` |
| Sample homes are distracting | Set `SAMPLE_HOMES=false` |

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

## Stretch goals

- Swap `classify_reply` for an LLM so "I feel a little dizzy" counts as help.
- Call in the morning when the National Weather Service forecast says tonight won't cool down.
- Spanish calls: set `RESIDENT_LANGUAGE=es`.
- More residents: add entries to `data/homes.json`.

## Sources

- City of Atlanta cooling center hours, June 30 2026: https://www.atlantaga.gov/Home/Components/News/News/15758
- AJC, City Council extreme heat plan (Aug 2026): https://www.ajc.com/news/2026/08/under-fire-city-council-tells-mayors-office-to-craft-extreme-heat-plan/
- ACEEE, Georgia energy burden: https://www.aceee.org/sites/default/files/pdf/fact-sheet/ses-georgia-100917.pdf
- NWS heat index equation: https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
