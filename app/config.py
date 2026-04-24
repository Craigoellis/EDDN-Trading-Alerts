import os
import secrets


class AppConfig:
    def __init__(self) -> None:
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "")
        self.CHAT_ID = os.getenv("CHAT_ID", "")
        self.SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(24))
        self.TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "EliteDTBot")
        self.TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", secrets.token_urlsafe(24))
        self.TELEGRAM_UPDATE_MODE = os.getenv("TELEGRAM_UPDATE_MODE", "webhook").lower()
        self.TELEGRAM_POLL_INTERVAL_SECONDS = int(os.getenv("TELEGRAM_POLL_INTERVAL_SECONDS", "3"))
        self.INARA_API_URL = os.getenv("INARA_API_URL", "https://inara.cz/inapi/v1/")
        self.INARA_API_KEY = os.getenv("INARA_API_KEY", "4k2e3fepus8w8skc0kw0csgw4s4ww08oo4c8wcc")
        self.EDDN_LISTENER_URL = os.getenv("EDDN_LISTENER_URL", "tcp://eddn.edcd.io:9500")
        self.EDSM_SYSTEM_URL = os.getenv("EDSM_SYSTEM_URL", "https://www.edsm.net/api-v1/system")
        self.EDSM_STATION_URL = os.getenv("EDSM_STATION_URL", "https://www.edsm.net/api-system-v1/stations")
        self.EDSM_FAILURE_COOLDOWN_SECONDS = int(os.getenv("EDSM_FAILURE_COOLDOWN_SECONDS", "300"))
        self.STORAGE_DIR = os.getenv("STORAGE_DIR", os.path.join("data", "store"))
        self.MAX_HISTORY_ENTRIES = int(os.getenv("MAX_HISTORY_ENTRIES", "20000"))
        self.ALERT_EXPIRY_SECONDS = int(os.getenv("ALERT_EXPIRY_SECONDS", str(3 * 60 * 60)))
        self.ALERT_PROCESS_INTERVAL_SECONDS = int(os.getenv("ALERT_PROCESS_INTERVAL_SECONDS", "20"))
        self.PORT = int(os.getenv("PORT", "10000"))
        self.DEFAULT_FILTERS = {
            "profit_min": int(os.getenv("PROFIT_THRESHOLD", "40000")),
            "supply_min": int(os.getenv("SUPPLY_THRESHOLD", "5000")),
            "demand_min": int(os.getenv("DEMAND_THRESHOLD", "5000")),
            "max_distance_ly": float(os.getenv("MAX_DISTANCE_LY", "120")),
            "distance_origin_system": os.getenv("DISTANCE_ORIGIN_SYSTEM", "Sol"),
            "landing_pad_size": os.getenv("LANDING_PAD_SIZE", "Any"),
            "max_station_distance_ls": int(os.getenv("MAX_STATION_DISTANCE_LS", "20000")),
        }
