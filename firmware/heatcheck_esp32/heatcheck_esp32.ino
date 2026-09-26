/*
  HeatCheck sensor: ESP32 + DHT22 (or DHT11) temperature/humidity sensor.

  Wiring (DHT22 module with 3 pins):
    + / VCC  -> 3V3
    - / GND  -> GND
    OUT/DATA -> GPIO 4
  (Bare 4-pin DHT22: add a 10k resistor between DATA and 3V3.)

  Arduino IDE setup:
    1. Boards Manager: install "esp32" by Espressif. Pick your board (e.g. "ESP32 Dev Module").
    2. Library Manager: install "DHT sensor library" by Adafruit
       (say yes when it asks to install "Adafruit Unified Sensor" too).
    3. Fill in the settings below, then Upload. Open Serial Monitor at 115200 baud.

  Wi-Fi: campus Wi-Fi like eduroam needs a login the ESP32 can't do easily.
  Turn on your phone's hotspot and put its name and password below.
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "DHT.h"

// ---------- settings: change these ----------
const char* WIFI_SSID  = "your-phone-hotspot";
const char* WIFI_PASS  = "hotspot-password";
// Your cloudflared URL (https://....trycloudflare.com), or http://<laptop-ip>:8000
// if the laptop is on the same hotspot. No trailing slash.
const char* SERVER_URL = "https://your-tunnel.trycloudflare.com";
const char* HOME_ID    = "demo";
const char* DEVICE_KEY = "";          // match DEVICE_KEY in .env (leave "" if unset)
const unsigned long SEND_EVERY_MS = 3000;

#define DHTPIN 4
#define DHTTYPE DHT22                 // change to DHT11 if that's what you have
// --------------------------------------------

#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

DHT dht(DHTPIN, DHTTYPE);
unsigned long lastSend = 0;

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Connecting to Wi-Fi \"%s\"", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nConnected. IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\nWi-Fi failed. Check the hotspot name/password (2.4 GHz only).");
  }
}

int postReading(float tempC, float humidity) {
  String url = String(SERVER_URL) + "/api/readings";
  String body = String("{\"home_id\":\"") + HOME_ID +
                "\",\"temp_c\":" + String(tempC, 2) +
                ",\"humidity\":" + String(humidity, 1) +
                ",\"source\":\"esp32\",\"device_key\":\"" + DEVICE_KEY + "\"}";

  HTTPClient http;
  int code = -1;
  if (url.startsWith("https")) {
    WiFiClientSecure client;
    client.setInsecure();  // fine for a hackathon demo; don't ship this
    if (http.begin(client, url)) {
      http.addHeader("Content-Type", "application/json");
      code = http.POST(body);
      http.end();
    }
  } else {
    WiFiClient client;
    if (http.begin(client, url)) {
      http.addHeader("Content-Type", "application/json");
      code = http.POST(body);
      http.end();
    }
  }
  return code;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  dht.begin();
  delay(1500);
  connectWifi();
}

void loop() {
  if (millis() - lastSend < SEND_EVERY_MS) return;
  lastSend = millis();

  float humidity = dht.readHumidity();
  float tempC = dht.readTemperature();
  if (isnan(humidity) || isnan(tempC)) {
    Serial.println("Sensor read failed. Check wiring and DHTTYPE.");
    return;
  }

  connectWifi();
  if (WiFi.status() != WL_CONNECTED) return;

  digitalWrite(LED_BUILTIN, HIGH);
  int code = postReading(tempC, humidity);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.printf("%.1f C (%.1f F), %.0f%% RH -> HTTP %d\n", tempC, tempC * 9.0 / 5.0 + 32.0, humidity, code);
}
