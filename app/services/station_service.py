from __future__ import annotations

import math
import re
from time import time

import requests


class StationService:
    FC_CODE_RE = re.compile(r"\b[A-Z0-9]{3}-[A-Z0-9]{3}\b", re.IGNORECASE)
    PAD_RANK = {"Small": 1, "Medium": 2, "Large": 3, "Unknown": 0}
    PAD_MAP = {
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

    def __init__(
        self,
        edsm_system_url: str,
        edsm_station_url: str,
        inara_api_url: str,
        inara_api_key: str,
        edsm_failure_cooldown_seconds: int = 300,
        market_repository=None,
    ) -> None:
        self._edsm_system_url = edsm_system_url
        self._edsm_station_url = edsm_station_url
        self._inara_api_url = inara_api_url
        self._inara_api_key = inara_api_key
        self._edsm_failure_cooldown_seconds = edsm_failure_cooldown_seconds
        self._market_repository = market_repository
        self._session = requests.Session()
        self._system_cache: dict[str, dict | None] = {}
        self._station_cache: dict[str, dict] = {}
        self._system_station_payload_cache: dict[str, list[dict]] = {}
        self._system_failure_cache: dict[str, float] = {}
        self._station_failure_cache: dict[str, float] = {}
        self._carrier_name_cache: dict[str, str | None] = {}
        self._distance_cache: dict[tuple[str, str], float | None] = {}

    def get_system_coords(self, system_name: str) -> dict | None:
        if system_name in self._system_cache:
            return self._system_cache[system_name]
        if self._is_failure_cooled_down(self._system_failure_cache, system_name):
            return None

        try:
            response = self._session.get(
                self._edsm_system_url,
                params={"systemName": system_name, "showCoordinates": 1},
                timeout=10,
            )
            if response.status_code != 200:
                self._record_failure(self._system_failure_cache, system_name)
                return None
            payload = response.json()
            coords = payload.get("coords")
            self._system_cache[system_name] = coords
            self._clear_failure(self._system_failure_cache, system_name)
            return coords
        except requests.RequestException as exc:
            self._record_failure(self._system_failure_cache, system_name)
            print(f"EDSM system lookup failed for {system_name}: {exc}")
            return None

    def calc_distance_ly(self, source_system: str, destination_system: str) -> float | None:
        if source_system.lower() == destination_system.lower():
            return 0.0

        cache_key = tuple(sorted((source_system.lower(), destination_system.lower())))
        if cache_key in self._distance_cache:
            return self._distance_cache[cache_key]

        source_coords = self.get_system_coords(source_system)
        destination_coords = self.get_system_coords(destination_system)
        if not source_coords or not destination_coords:
            self._distance_cache[cache_key] = None
            return None

        try:
            dx = source_coords["x"] - destination_coords["x"]
            dy = source_coords["y"] - destination_coords["y"]
            dz = source_coords["z"] - destination_coords["z"]
            distance = round(math.sqrt(dx * dx + dy * dy + dz * dz), 2)
            self._distance_cache[cache_key] = distance
            return distance
        except (KeyError, TypeError):
            self._distance_cache[cache_key] = None
            return None

    def get_station_data(self, system_name: str, station_name: str) -> dict:
        cache_key = self._station_cache_key(system_name, station_name)
        cached = self._station_cache.get(cache_key)
        if cached is not None:
            return self._normalize_station_record(cached)
        if self._is_failure_cooled_down(self._station_failure_cache, cache_key):
            return self._default_station_record()

        stations = self._get_system_station_payload(system_name)
        if stations is None:
            self._record_failure(self._station_failure_cache, cache_key)
            return self._default_station_record()

        exact_match = None
        partial_match = None
        station_name_lower = station_name.lower()
        for station in stations:
            candidate_name = str(station.get("name", ""))
            candidate_name_lower = candidate_name.lower()
            if candidate_name_lower == station_name_lower:
                exact_match = station
                break
            if partial_match is None and station_name_lower in candidate_name_lower:
                partial_match = station

        matched_station = exact_match or partial_match
        if matched_station:
            station_info = self._station_info_from_payload(matched_station)
            self._station_cache[cache_key] = station_info
            self._clear_failure(self._station_failure_cache, cache_key)
            return self._normalize_station_record(station_info)

        default_station = self._default_station_record()
        self._station_cache[cache_key] = default_station
        self._clear_failure(self._station_failure_cache, cache_key)
        return default_station

    def prettify_station_name(self, station_name: str, station_type: str) -> str:
        station_type = station_type or "Unknown"
        if "fleet carrier" not in station_type.lower():
            return station_name

        if "(" in station_name and ")" in station_name and self.FC_CODE_RE.search(station_name):
            return station_name

        callsign = self.extract_carrier_callsign(station_name) or station_name.strip().upper()
        if self._market_repository is not None:
            mapped_name = self._market_repository.get_carrier_name(callsign)
            if mapped_name:
                return f"{mapped_name} ({callsign})"
        full_name = self._get_carrier_fullname_from_inara(callsign)
        return f"{full_name} ({callsign})" if full_name else callsign

    def extract_carrier_callsign(self, station_name: str) -> str | None:
        match = self.FC_CODE_RE.search(station_name or "")
        return match.group(0).upper() if match else None

    def supports_pad_size(self, station_pad_size: str, required_pad_size: str) -> bool:
        if required_pad_size == "Any":
            return True
        station_rank = self.PAD_RANK.get(station_pad_size, 0)
        required_rank = self.PAD_RANK.get(required_pad_size, 0)
        if station_rank <= 0 or required_rank <= 0:
            return False
        return station_rank >= required_rank

    def _normalize_station_record(self, station_record: dict) -> dict:
        station_type = station_record.get("type") or "Unknown"
        return {
            "type": station_type,
            "pad": station_record.get("pad") or self.PAD_MAP.get(station_type, "Unknown"),
            "distance": station_record.get("distance"),
        }

    def _get_system_station_payload(self, system_name: str) -> list[dict] | None:
        if system_name in self._system_station_payload_cache:
            return self._system_station_payload_cache[system_name]
        if self._is_failure_cooled_down(self._system_failure_cache, system_name):
            return None

        try:
            response = self._session.get(
                self._edsm_station_url,
                params={"systemName": system_name},
                timeout=10,
            )
            if response.status_code != 200:
                self._record_failure(self._system_failure_cache, system_name)
                return None

            payload = response.json()
            stations = payload.get("stations", []) if isinstance(payload, dict) else []
            self._system_station_payload_cache[system_name] = stations
            for station in stations:
                station_name = station.get("name")
                if not station_name:
                    continue
                self._station_cache[self._station_cache_key(system_name, station_name)] = self._station_info_from_payload(station)
            self._clear_failure(self._system_failure_cache, system_name)
            return stations
        except requests.RequestException as exc:
            self._record_failure(self._system_failure_cache, system_name)
            print(f"EDSM station lookup failed for system {system_name}: {exc}")
            return None

    def _station_info_from_payload(self, station: dict) -> dict:
        station_type = station.get("type") or "Unknown"
        return self._normalize_station_record(
            {
                "type": station_type,
                "pad": self.PAD_MAP.get(station_type, "Unknown"),
                "distance": station.get("distanceToArrival"),
            }
        )

    @staticmethod
    def _default_station_record() -> dict:
        return {"type": "Unknown", "pad": "Unknown", "distance": None}

    @staticmethod
    def _station_cache_key(system_name: str, station_name: str) -> str:
        return f"{system_name}|{station_name}".lower()

    def _get_carrier_fullname_from_inara(self, callsign: str) -> str | None:
        normalized = callsign.upper()
        if normalized in self._carrier_name_cache:
            return self._carrier_name_cache[normalized]

        try:
            payload = {
                "header": {
                    "appName": "EDDNTradeAlerts",
                    "appVersion": "2.0",
                    "APIkey": self._inara_api_key,
                },
                "events": [{"eventName": "getFleetCarrier", "eventData": {"searchName": normalized}}],
            }
            response = self._session.post(self._inara_api_url, json=payload, timeout=12)
            data = response.json()
            events = data.get("events", []) if isinstance(data, dict) else []
            event_data = events[0].get("eventData", {}) if events else {}
            full_name = (
                event_data.get("name")
                or event_data.get("carrierName")
                or event_data.get("fleetCarrierName")
            )
            self._carrier_name_cache[normalized] = full_name
            return full_name
        except requests.RequestException as exc:
            print(f"Inara fleet carrier lookup failed for {normalized}: {exc}")
            self._carrier_name_cache[normalized] = None
            return None

    def _is_failure_cooled_down(self, failure_cache: dict[str, float], key: str) -> bool:
        failed_at = failure_cache.get(key)
        if failed_at is None:
            return False
        return (time() - failed_at) < self._edsm_failure_cooldown_seconds

    @staticmethod
    def _record_failure(failure_cache: dict[str, float], key: str) -> None:
        failure_cache[key] = time()

    @staticmethod
    def _clear_failure(failure_cache: dict[str, float], key: str) -> None:
        failure_cache.pop(key, None)
