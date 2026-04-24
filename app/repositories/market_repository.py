from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import RLock
from time import time


class MarketRepository:
    def __init__(self, storage_dir: str, max_history_entries: int, alert_expiry_seconds: int) -> None:
        self._lock = RLock()
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._market_entries_path = self._storage_dir / "market_entries.json"
        self._history_path = self._storage_dir / "price_history.json"
        self._carrier_names_path = self._storage_dir / "carrier_names.json"
        self._alerts_path = self._storage_dir / "sent_alerts.json"
        self._metadata_path = self._storage_dir / "app_metadata.json"
        self._max_history_entries = max_history_entries
        self._alert_expiry_seconds = alert_expiry_seconds
        self._initialize_files()
        self._market_entries = self._deserialize_market_entries(self._read_json(self._market_entries_path, {}))
        self._history = self._deserialize_history(self._read_json(self._history_path, []))
        self._carrier_names = self._read_json(self._carrier_names_path, {})
        self._alerts = self._read_json(self._alerts_path, {})
        self._metadata = self._read_json(self._metadata_path, {})

    def upsert_market_entry(self, commodity_name: str, market_entry: dict) -> None:
        self.upsert_market_batch([(commodity_name, market_entry)])

    def upsert_market_batch(self, market_updates: list[tuple[str, dict]]) -> int:
        with self._lock:
            updated_count = 0
            entries_dirty = False
            history_dirty = False

            for commodity_name, market_entry in market_updates:
                commodity_entries = self._market_entries.setdefault(commodity_name, [])
                normalized_entry = {
                    "station": market_entry["station"],
                    "system": market_entry["system"],
                    "stationType": market_entry.get("stationType") or "Unknown",
                    "buy": market_entry["buy"],
                    "sell": market_entry["sell"],
                    "stock": market_entry["stock"],
                    "demand": market_entry["demand"],
                    "updated": self._ensure_datetime(market_entry["updated"]),
                }

                for existing_entry in commodity_entries:
                    if (
                        existing_entry["station"] == normalized_entry["station"]
                        and existing_entry["system"] == normalized_entry["system"]
                    ):
                        history_appended = self._append_history_if_changed(
                            history=self._history,
                            commodity_name=commodity_name,
                            current_entry=existing_entry,
                            next_entry=normalized_entry,
                        )
                        existing_entry.update(normalized_entry)
                        updated_count += 1
                        entries_dirty = True
                        history_dirty = history_dirty or history_appended
                        break
                else:
                    history_appended = self._append_history_if_changed(
                        history=self._history,
                        commodity_name=commodity_name,
                        current_entry=None,
                        next_entry=normalized_entry,
                    )
                    commodity_entries.append(normalized_entry)
                    updated_count += 1
                    entries_dirty = True
                    history_dirty = history_dirty or history_appended

            if history_dirty and len(self._history) > self._max_history_entries:
                self._history = self._history[-self._max_history_entries :]
            if entries_dirty:
                self._persist_market_entries()
            if history_dirty:
                self._persist_history()
            return updated_count

    def get_markets_snapshot(self) -> dict[str, list[dict]]:
        with self._lock:
            return {
                commodity: [dict(entry) for entry in entries]
                for commodity, entries in self._market_entries.items()
            }

    def get_station_snapshot(self, system_name: str, station_name: str) -> list[dict]:
        with self._lock:
            return [
                {"commodity": commodity, **dict(entry)}
                for commodity, entries in self._market_entries.items()
                for entry in entries
                if entry["system"] == system_name and entry["station"] == station_name
            ]

    def get_system_snapshot(self, system_name: str) -> list[dict]:
        with self._lock:
            return [
                {"commodity": commodity, **dict(entry)}
                for commodity, entries in self._market_entries.items()
                for entry in entries
                if entry["system"] == system_name
            ]

    def get_commodity_snapshot(self, commodity_name: str) -> list[dict]:
        with self._lock:
            return [
                {"commodity": commodity_name, **dict(entry)}
                for entry in self._market_entries.get(commodity_name, [])
            ]

    def get_recent_history(
        self,
        *,
        station_name: str | None = None,
        system_name: str | None = None,
        commodity_name: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        with self._lock:
            rows = []
            for entry in reversed(self._history):
                if station_name and entry["station"] != station_name:
                    continue
                if system_name and entry["system"] != system_name:
                    continue
                if commodity_name and entry["commodity"] != commodity_name:
                    continue
                rows.append(
                    {
                        "commodity": entry["commodity"],
                        "station": entry["station"],
                        "system": entry["system"],
                        "stationType": entry.get("stationType") or "Unknown",
                        "buy": entry["buy"],
                        "sell": entry["sell"],
                        "stock": entry["stock"],
                        "demand": entry["demand"],
                        "updated": entry["updated"].isoformat(),
                    }
                )
                if len(rows) >= limit:
                    break
            return rows

    def upsert_carrier_name(self, carrier_code: str, carrier_name: str, system_name: str | None = None) -> None:
        normalized_code = carrier_code.upper()
        with self._lock:
            self._carrier_names[normalized_code] = {
                "name": carrier_name,
                "system": system_name,
                "updated": self._to_isoformat(datetime.utcnow()),
            }
            self._persist_carrier_names()

    def get_carrier_name(self, carrier_code: str) -> str | None:
        normalized_code = carrier_code.upper()
        with self._lock:
            entry = self._carrier_names.get(normalized_code)
        if not isinstance(entry, dict):
            return None
        name = entry.get("name")
        return str(name) if name else None

    def search_entities(self, query: str, limit: int = 8) -> dict:
        query_normalized = query.strip().lower()
        if not query_normalized:
            return {"stations": [], "systems": [], "commodities": []}

        stations = {}
        systems = set()
        commodities = set()

        with self._lock:
            for commodity_name, entries in self._market_entries.items():
                if query_normalized in commodity_name.lower():
                    commodities.add(commodity_name)
                for entry in entries:
                    system_name = entry["system"]
                    station_name = entry["station"]
                    if query_normalized in system_name.lower():
                        systems.add(system_name)
                    if query_normalized in station_name.lower() or query_normalized in system_name.lower():
                        stations[(system_name, station_name)] = {
                            "system": system_name,
                            "station": station_name,
                        }

        return {
            "stations": sorted(stations.values(), key=lambda item: (item["system"], item["station"]))[:limit],
            "systems": sorted(systems)[:limit],
            "commodities": sorted(commodities)[:limit],
        }

    def search_system_names(self, query: str, limit: int = 8) -> list[str]:
        query_normalized = query.strip().lower()
        if not query_normalized:
            return []

        with self._lock:
            systems = {
                entry["system"]
                for entries in self._market_entries.values()
                for entry in entries
                if query_normalized in entry["system"].lower()
            }
        return sorted(systems)[:limit]

    def cleanup_alerts(self) -> None:
        cutoff = time() - self._alert_expiry_seconds
        with self._lock:
            active_alerts = {
                alert_key: sent_at_epoch
                for alert_key, sent_at_epoch in self._alerts.items()
                if sent_at_epoch >= cutoff
            }
            if len(active_alerts) != len(self._alerts):
                self._alerts = active_alerts
                self._persist_alerts()

    def has_sent_alert(self, alert_key: str) -> bool:
        with self._lock:
            return alert_key in self._alerts

    def mark_alert_sent(self, alert_key: str) -> None:
        with self._lock:
            self._alerts[alert_key] = time()
            self._persist_alerts()

    def set_last_poll(self) -> None:
        with self._lock:
            self._metadata["last_poll_epoch"] = time()
            self._persist_metadata()

    def get_last_poll_epoch(self) -> float | None:
        with self._lock:
            value = self._metadata.get("last_poll_epoch")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def get_storage_dir(self) -> str:
        return str(self._storage_dir)

    def _initialize_files(self) -> None:
        for path, default in (
            (self._market_entries_path, {}),
            (self._history_path, []),
            (self._carrier_names_path, {}),
            (self._alerts_path, {}),
            (self._metadata_path, {}),
        ):
            if not path.exists():
                self._write_json(path, default)

    def _append_history_if_changed(
        self,
        *,
        history: list[dict],
        commodity_name: str,
        current_entry: dict | None,
        next_entry: dict,
    ) -> bool:
        if current_entry is not None and all(
            current_entry.get(key) == next_entry.get(key)
            for key in ("buy", "sell", "stock", "demand", "stationType")
        ):
            return False

        history.append(
            {
                "commodity": commodity_name,
                "station": next_entry["station"],
                "system": next_entry["system"],
                "stationType": next_entry.get("stationType") or "Unknown",
                "buy": next_entry["buy"],
                "sell": next_entry["sell"],
                "stock": next_entry["stock"],
                "demand": next_entry["demand"],
                "updated": next_entry["updated"],
            }
        )
        return True

    def _persist_market_entries(self) -> None:
        self._write_json(self._market_entries_path, self._serialize_market_entries(self._market_entries))

    def _persist_history(self) -> None:
        self._write_json(self._history_path, self._serialize_history(self._history))

    def _persist_carrier_names(self) -> None:
        self._write_json(self._carrier_names_path, self._carrier_names)

    def _persist_alerts(self) -> None:
        self._write_json(self._alerts_path, self._alerts)

    def _persist_metadata(self) -> None:
        self._write_json(self._metadata_path, self._metadata)

    @staticmethod
    def _read_json(path: Path, default):
        try:
            if not path.exists():
                return default
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return default
            return json.loads(content)
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    @classmethod
    def _deserialize_market_entries(cls, payload: dict[str, list[dict]]) -> dict[str, list[dict]]:
        return {
            commodity: [cls._deserialize_entry(entry) for entry in entries]
            for commodity, entries in payload.items()
        }

    @classmethod
    def _deserialize_history(cls, payload: list[dict]) -> list[dict]:
        return [cls._deserialize_entry(entry) for entry in payload]

    @classmethod
    def _deserialize_entry(cls, entry: dict) -> dict:
        normalized = dict(entry)
        normalized["stationType"] = normalized.get("stationType") or "Unknown"
        normalized["updated"] = cls._ensure_datetime(normalized["updated"])
        return normalized

    @classmethod
    def _serialize_market_entries(cls, payload: dict[str, list[dict]]) -> dict[str, list[dict]]:
        return {
            commodity: [cls._serialize_entry(entry) for entry in entries]
            for commodity, entries in payload.items()
        }

    @classmethod
    def _serialize_history(cls, payload: list[dict]) -> list[dict]:
        return [cls._serialize_entry(entry) for entry in payload]

    @classmethod
    def _serialize_entry(cls, entry: dict) -> dict:
        normalized = dict(entry)
        normalized["updated"] = cls._to_isoformat(normalized["updated"])
        return normalized

    @staticmethod
    def _to_isoformat(value) -> str:
        return value.isoformat()

    @staticmethod
    def _ensure_datetime(value):
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)
