import json
import requests
import threading
import math
import re
from datetime import datetime, timezone
from time import time, sleep
from flask import Flask

# === Flask setup (for Render + UptimeRobot) ===
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ EDDN Trading Alerts is running (HTTPS polling mode)!"

# === Telegram setup ===
BOT_TOKEN = "8082600371:AAFYY9g-RW2TFovgnrX7JfncCWVHxY4XzYs"
CHAT_ID = "-1003296190277"

# === Inara API (for Fleet Carrier full names) ===
INARA_API_URL = "https://inara.cz/inapi/v1/"
INARA_API_KEY = "4k2e3fepus8w8skc0kw0csgw4s4ww08oo4c8wcc"

# === Trade filters ===
PROFIT_THRESHOLD = 40000
SUPPLY_THRESHOLD = 5000
DEMAND_THRESHOLD = 5000
MAX_DISTANCE_LY = 1490
MAX_SELL_DISTANCE = 120  # Max LY between systems for alert
POLL_INTERVAL = 15  # seconds between HTTPS checks

# === Cache & duplicate management ===
markets = {}
sent_alerts = set()
alert_timestamps = {}
station_cache = {}
system_cache = {}
carrier_name_cache = {}
ALERT_EXPIRY = 3 * 60 * 60  # 3 hours

# === Fleet Carrier pattern ===
FC_CODE_RE = re.compile(r"\b[A-Z0-9]{3}-[A-Z0-9]{3}\b", re.IGNORECASE)


# === EDSM System Distance Lookup ===
def get_system_coords(system_name):
    if system_name in system_cache:
        return system_cache[system_name]
    try:
        url = f"https://www.edsm.net/api-v1/system?systemName={system_name}&showCoordinates=1"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if "coords" in data:
            coords = data["coords"]
            system_cache[system_name] = coords
            return coords
    except Exception as e:
        print(f"⚠️ EDSM system lookup failed for {system_name}: {e}")
    return None


def calc_distance_ly(sys1, sys2):
    if sys1.lower() == sys2.lower():
        return 0.0
    c1 = get_system_coords(sys1)
    c2 = get_system_coords(sys2)
    if not c1 or not c2:
        return None
    try:
        dx = c1["x"] - c2["x"]
        dy = c1["y"] - c2["y"]
        dz = c1["z"] - c2["z"]
        return round(math.sqrt(dx * dx + dy * dy + dz * dz), 2)
    except Exception:
        return None


# === EDSM Station Lookup ===
def get_station_data(system_name, station_name):
    key = f"{system_name}|{station_name}"
    if key in station_cache:
        return station_cache[key]

    try:
        url = f"https://www.edsm.net/api-system-v1/stations?systemName={system_name}"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return {"type": "Unknown", "pad": "Unknown", "distance": "N/A"}

        data = r.json()
        for station in data.get("stations", []):
            if station_name.lower() in station.get("name", "").lower():
                stype = station.get("type", "Unknown")
                distance = station.get("distanceToArrival", "N/A")

                pad_map = {
                    "Coriolis Starport": "Large",
                    "Orbis Starport": "Large",
                    "Ocellus Starport": "Large",
                    "Outpost": "Medium",
                    "Planetary Port": "Large",
                    "Planetary Base": "Large",
                    "Odyssey Settlement": "Small",
                    "Surface Settlement": "Small",
                    "Mega Ship": "Large",
                    "Fleet Carrier": "Large",
                }
                pad_size = pad_map.get(stype, "Unknown")

                info = {"type": stype, "pad": pad_size, "distance": distance}
                station_cache[key] = info
                return info

        station_cache[key] = {"type": "Unknown", "pad": "Unknown", "distance": "N/A"}
        return station_cache[key]

    except Exception as e:
        print(f"⚠️ EDSM lookup failed for {station_name} in {system_name}: {e}")
        return {"type": "Unknown", "pad": "Unknown", "distance": "N/A"}


# === Inara: Resolve Fleet Carrier callsign ===
def get_carrier_fullname_from_inara(callsign: str):
    key = callsign.upper()
    if key in carrier_name_cache:
        return carrier_name_cache[key]
    try:
        payload = {
            "header": {"appName": "EDDNTradeAlerts", "appVersion": "1.0", "APIkey": INARA_API_KEY},
            "events": [{"eventName": "getFleetCarrier", "eventData": {"searchName": callsign}}],
        }
        resp = requests.post(INARA_API_URL, json=payload, timeout=12)
        data = resp.json()

        full_name = None
        if isinstance(data, dict) and "events" in data and data["events"]:
            ev = data["events"][0]
            ed = ev.get("eventData", {}) if isinstance(ev, dict) else {}
            full_name = ed.get("name") or ed.get("carrierName") or ed.get("fleetCarrierName")

        if full_name:
            carrier_name_cache[key] = full_name
            return full_name
    except Exception as e:
        print(f"⚠️ Inara lookup failed for {callsign}: {e}")

    carrier_name_cache[key] = None
    return None


def prettify_station_name_with_fc_fullname(station_name: str, station_type: str) -> str:
    if "fleet carrier" not in station_type.lower():
        return station_name
    if "(" in station_name and ")" in station_name and FC_CODE_RE.search(station_name):
        return station_name
    m = FC_CODE_RE.search(station_name)
    callsign = m.group(0).upper() if m else station_name.strip().upper()
    full = get_carrier_fullname_from_inara(callsign)
    if full:
        return f"{full} ({callsign})"
    return callsign


# === Telegram send function ===
def send_alert(buy_station, buy_system, buy_type,
               sell_station, sell_system, sell_type,
               commodity, buy_price, sell_price, profit,
               supply, demand, last_update):
    
    buy_info = get_station_data(buy_system, buy_station)
    sell_info = get_station_data(sell_system, sell_station)

    # Skip unwanted locations
    if "fleet carrier" in buy_info["type"].lower():
        return
    if "planetary outpost" in buy_info["type"].lower() or "planetary outpost" in sell_info["type"].lower():
        return

    ly_distance = calc_distance_ly(buy_system, sell_system)
    if ly_distance is None or ly_distance > MAX_SELL_DISTANCE:
        return

    buy_display = prettify_station_name_with_fc_fullname(buy_station, buy_info["type"])
    sell_display = prettify_station_name_with_fc_fullname(sell_station, sell_info["type"])

    message = (
        f"🚀 <b>Trade Alert</b>\n\n"
        f"💰 <b>{commodity.title()}</b>\n"
        f"📈 Profit: +{profit:,} Cr/ton\n"
        f"📏 Distance: {ly_distance:.2f} LY\n\n"
        f"🛒 <b>BUY FROM</b>\n"
        f"🏙️ {buy_display} ({buy_info['type']})\n"
        f"📍 {buy_system}\n"
        f"💵 {buy_price:,} Cr | 📦 {supply:,}\n\n"
        f"💼 <b>SELL TO</b>\n"
        f"🏙️ {sell_display} ({sell_info['type']})\n"
        f"📍 {sell_system}\n"
        f"💵 {sell_price:,} Cr | 📦 {demand:,}\n\n"
        f"🕒 {last_update.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
        print(f"✅ Sent trade alert for {commodity} — {profit:,} Cr/ton, {ly_distance:.1f} LY")
    except Exception as e:
        print("⚠️ Telegram send error:", e)


# === HTTPS polling fallback listener ===
def start_eddn_listener():
    print("🛰️ HTTPS polling mode active — listening for trades every 15s...")
    last_seen = None

    while True:
        try:
            # Pull a sample from an EDDN mirror (example mirror API)
            r = requests.get("https://eddbapi-python.vercel.app/eddn/latest", timeout=10)
            if r.status_code != 200:
                sleep(POLL_INTERVAL)
                continue

            data = r.json()
            for json_data in data:
                schema = json_data.get("$schemaRef", "")
                if "commodity" not in schema:
                    continue

                msg = json_data["message"]
                system = msg.get("systemName")
                station = msg.get("stationName")
                station_type = msg.get("stationType", "Unknown")
                commodities = msg.get("commodities", [])

                for c in commodities:
                    name = c.get("name", "").lower()
                    buy = c.get("buyPrice", 0)
                    sell = c.get("sellPrice", 0)
                    stock = c.get("stock", 0)
                    demand = c.get("demand", 0)
                    timestamp = datetime.now(timezone.utc)

                    if buy == 0 and sell == 0:
                        continue

                    if name not in markets:
                        markets[name] = []

                    updated = False
                    for entry in markets[name]:
                        if entry["station"] == station and entry["system"] == system:
                            entry.update({
                                "stationType": station_type,
                                "buy": buy,
                                "sell": sell,
                                "stock": stock,
                                "demand": demand,
                                "updated": timestamp
                            })
                            updated = True
                            break
                    if not updated:
                        markets[name].append({
                            "station": station,
                            "system": system,
                            "stationType": station_type,
                            "buy": buy,
                            "sell": sell,
                            "stock": stock,
                            "demand": demand,
                            "updated": timestamp
                        })

                    for entry in markets[name]:
                        if entry["station"] == station and entry["system"] == system:
                            continue

                        profit_buy = entry["sell"] - buy
                        profit_sell = sell - entry["buy"]

                        key_buy = f"{name}|{station}|{entry['station']}"
                        key_sell = f"{name}|{entry['station']}|{station}"

                        if (profit_buy > PROFIT_THRESHOLD and
                            stock > SUPPLY_THRESHOLD and
                            entry["demand"] > DEMAND_THRESHOLD and
                            key_buy not in sent_alerts):
                            send_alert(
                                buy_station=station, buy_system=system, buy_type=station_type,
                                sell_station=entry["station"], sell_system=entry["system"], sell_type=entry["stationType"],
                                commodity=name, buy_price=buy, sell_price=entry["sell"], profit=profit_buy,
                                supply=stock, demand=entry["demand"], last_update=timestamp
                            )
                            sent_alerts.add(key_buy)
                            alert_timestamps[key_buy] = time()

                        if (profit_sell > PROFIT_THRESHOLD and
                            entry["stock"] > SUPPLY_THRESHOLD and
                            demand > DEMAND_THRESHOLD and
                            key_sell not in sent_alerts):
                            send_alert(
                                buy_station=entry["station"], buy_system=entry["system"], buy_type=entry["stationType"],
                                sell_station=station, sell_system=system, sell_type=station_type,
                                commodity=name, buy_price=entry["buy"], sell_price=sell, profit=profit_sell,
                                supply=entry["stock"], demand=demand, last_update=timestamp
                            )
                            sent_alerts.add(key_sell)
                            alert_timestamps[key_sell] = time()

            sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"⚠️ HTTPS listener error: {e}")
            sleep(POLL_INTERVAL)


# === MAIN ENTRY ===
if __name__ == "__main__":
    t = threading.Thread(target=start_eddn_listener, daemon=True)
    t.start()
    print("✅ Background listener started (Render-safe).")
    app.run(host="0.0.0.0", port=10000, debug=False, use_reloader=False)
