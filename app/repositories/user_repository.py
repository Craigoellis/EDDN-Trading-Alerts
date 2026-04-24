from __future__ import annotations

import json
import secrets
from pathlib import Path
from threading import RLock
from time import time


class UserRepository:
    def __init__(self, storage_dir: str, alert_expiry_seconds: int) -> None:
        self._lock = RLock()
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._users_path = self._storage_dir / "users.json"
        self._filters_path = self._storage_dir / "user_filters.json"
        self._links_path = self._storage_dir / "telegram_links.json"
        self._alert_history_path = self._storage_dir / "user_alert_history.json"
        self._alert_expiry_seconds = alert_expiry_seconds
        self._initialize_files()

    def create_user(
        self,
        *,
        username: str,
        email: str,
        password_hash: str,
        telegram_contact: str,
        timezone_name: str,
    ) -> dict:
        with self._lock:
            users = self._read_json(self._users_path, [])
            user_id = self._next_id(users)
            user = {
                "id": user_id,
                "username": username,
                "email": email,
                "password_hash": password_hash,
                "telegram_contact": telegram_contact,
                "timezone": timezone_name or "UTC",
                "telegram_chat_id": None,
                "telegram_verified": False,
                "created_at": self._now_iso(),
            }
            users.append(user)
            self._write_json(self._users_path, users)
            return self._normalize_user(user)

    def list_users(self) -> list[dict]:
        with self._lock:
            users = self._read_json(self._users_path, [])
        return [self._normalize_user(user) for user in users]

    def get_user_by_id(self, user_id: int) -> dict | None:
        for user in self.list_users():
            if user["id"] == user_id:
                return user
        return None

    def get_user_by_email(self, email: str) -> dict | None:
        email_normalized = email.strip().lower()
        for user in self.list_users():
            if user["email"].lower() == email_normalized:
                return user
        return None

    def get_user_by_username(self, username: str) -> dict | None:
        username_normalized = username.strip().lower()
        for user in self.list_users():
            if user["username"].lower() == username_normalized:
                return user
        return None

    def update_user(self, updated_user: dict) -> None:
        with self._lock:
            users = self._read_json(self._users_path, [])
            for index, existing_user in enumerate(users):
                if existing_user["id"] == updated_user["id"]:
                    users[index] = updated_user
                    break
            self._write_json(self._users_path, users)

    def create_filter(self, *, user_id: int, filter_data: dict) -> dict:
        with self._lock:
            filters = self._read_json(self._filters_path, [])
            filter_record = {
                "id": self._next_id(filters),
                "user_id": user_id,
                "name": filter_data["name"],
                "profit_min": filter_data["profit_min"],
                "supply_min": filter_data["supply_min"],
                "demand_min": filter_data["demand_min"],
                "max_origin_distance_ly": filter_data["max_origin_distance_ly"],
                "max_route_distance_ly": filter_data["max_route_distance_ly"],
                "distance_origin_system": filter_data.get("distance_origin_system", "Sol"),
                "max_station_distance_ls": filter_data["max_station_distance_ls"],
                "landing_pad_size": filter_data["landing_pad_size"],
                "fleet_carrier_mode": filter_data["fleet_carrier_mode"],
                "is_enabled": filter_data["is_enabled"],
                "created_at": self._now_iso(),
            }
            filters.append(filter_record)
            self._write_json(self._filters_path, filters)
            return filter_record

    def list_filters_for_user(self, user_id: int) -> list[dict]:
        with self._lock:
            filters = self._read_json(self._filters_path, [])
        return [
            self._normalize_filter_record(filter_record)
            for filter_record in filters
            if filter_record["user_id"] == user_id
        ]

    def list_enabled_filters(self) -> list[dict]:
        with self._lock:
            filters = self._read_json(self._filters_path, [])
        return [
            self._normalize_filter_record(filter_record)
            for filter_record in filters
            if filter_record.get("is_enabled")
        ]

    def list_all_filters(self) -> list[dict]:
        with self._lock:
            filters = self._read_json(self._filters_path, [])
        return [self._normalize_filter_record(filter_record) for filter_record in filters]

    def set_filter_enabled(self, *, user_id: int, filter_id: int, is_enabled: bool) -> bool:
        with self._lock:
            filters = self._read_json(self._filters_path, [])
            updated = False
            for filter_record in filters:
                if filter_record["user_id"] == user_id and filter_record["id"] == filter_id:
                    filter_record["is_enabled"] = bool(is_enabled)
                    updated = True
                    break
            if updated:
                self._write_json(self._filters_path, filters)
            return updated

    def delete_filter(self, *, user_id: int, filter_id: int) -> bool:
        with self._lock:
            filters = self._read_json(self._filters_path, [])
            updated_filters = [
                filter_record
                for filter_record in filters
                if not (filter_record["user_id"] == user_id and filter_record["id"] == filter_id)
            ]
            deleted = len(updated_filters) != len(filters)
            if deleted:
                self._write_json(self._filters_path, updated_filters)
            return deleted

    def create_telegram_link_code(self, user_id: int) -> dict:
        with self._lock:
            links = self._read_json(self._links_path, [])
            link_code = secrets.token_urlsafe(16)
            record = {
                "code": link_code,
                "user_id": user_id,
                "created_at": self._now_iso(),
                "consumed_at": None,
            }
            links.append(record)
            self._write_json(self._links_path, links)
            return record

    def consume_telegram_link_code(self, code: str, chat_id: str) -> dict | None:
        with self._lock:
            links = self._read_json(self._links_path, [])
            users = self._read_json(self._users_path, [])
            matched_link = None
            for link in links:
                if link["code"] == code and not link.get("consumed_at"):
                    link["consumed_at"] = self._now_iso()
                    matched_link = link
                    break

            if not matched_link:
                return None

            linked_user = None
            for user in users:
                if user["id"] == matched_link["user_id"]:
                    user["telegram_chat_id"] = str(chat_id)
                    user["telegram_verified"] = True
                    linked_user = user
                    break

            self._write_json(self._links_path, links)
            self._write_json(self._users_path, users)
            return linked_user

    def get_active_link_for_user(self, user_id: int) -> dict | None:
        with self._lock:
            links = self._read_json(self._links_path, [])
        active_links = [
            link for link in links
            if link["user_id"] == user_id and not link.get("consumed_at")
        ]
        return active_links[-1] if active_links else None

    def cleanup_alert_history(self) -> None:
        cutoff = time() - self._alert_expiry_seconds
        with self._lock:
            history = self._read_json(self._alert_history_path, [])
            history = [item for item in history if item.get("sent_at_epoch", 0) >= cutoff]
            self._write_json(self._alert_history_path, history)

    def clear_alert_history_for_user(self, *, user_id: int) -> int:
        with self._lock:
            history = self._read_json(self._alert_history_path, [])
            remaining_history = [item for item in history if item["user_id"] != user_id]
            cleared_count = len(history) - len(remaining_history)
            if cleared_count:
                self._write_json(self._alert_history_path, remaining_history)
            return cleared_count

    def get_alert_delivery(self, *, user_id: int, filter_id: int, alert_key: str) -> dict | None:
        with self._lock:
            history = self._read_json(self._alert_history_path, [])
        for item in history:
            if item["user_id"] == user_id and item["filter_id"] == filter_id and item["alert_key"] == alert_key:
                return self._normalize_alert_delivery(item)
        return None

    def list_alert_deliveries(self, *, user_id: int, filter_id: int) -> list[dict]:
        with self._lock:
            history = self._read_json(self._alert_history_path, [])
        return [
            self._normalize_alert_delivery(item)
            for item in history
            if item["user_id"] == user_id and item["filter_id"] == filter_id
        ]

    def upsert_alert_delivery(
        self,
        *,
        user_id: int,
        filter_id: int,
        alert_key: str,
        message_id: int | None,
        payload_hash: str,
        status: str = "active",
        terminal_reason: str | None = None,
        trade_snapshot: dict | None = None,
    ) -> None:
        with self._lock:
            history = self._read_json(self._alert_history_path, [])
            updated = False
            for item in history:
                if item["user_id"] == user_id and item["filter_id"] == filter_id and item["alert_key"] == alert_key:
                    item["message_id"] = message_id
                    item["payload_hash"] = payload_hash
                    item["status"] = status
                    item["terminal_reason"] = terminal_reason
                    item["trade_snapshot"] = trade_snapshot
                    item["sent_at_epoch"] = time()
                    updated = True
                    break

            if not updated:
                history.append(
                    {
                        "user_id": user_id,
                        "filter_id": filter_id,
                        "alert_key": alert_key,
                        "message_id": message_id,
                        "payload_hash": payload_hash,
                        "status": status,
                        "terminal_reason": terminal_reason,
                        "trade_snapshot": trade_snapshot,
                        "sent_at_epoch": time(),
                    }
                )
            self._write_json(self._alert_history_path, history)

    def _initialize_files(self) -> None:
        for path, default in (
            (self._users_path, []),
            (self._filters_path, []),
            (self._links_path, []),
            (self._alert_history_path, []),
        ):
            if not path.exists():
                self._write_json(path, default)

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

    @staticmethod
    def _next_id(items: list[dict]) -> int:
        return (max((item["id"] for item in items), default=0) + 1) if items else 1

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_filter_record(filter_record: dict) -> dict:
        normalized = dict(filter_record)
        normalized["distance_origin_system"] = normalized.get("distance_origin_system") or "Sol"
        legacy_distance = normalized.get("max_distance_ly", 120)
        normalized["max_origin_distance_ly"] = normalized.get("max_origin_distance_ly", legacy_distance)
        normalized["max_route_distance_ly"] = normalized.get("max_route_distance_ly", legacy_distance)
        normalized["fleet_carrier_mode"] = normalized.get("fleet_carrier_mode") or "include"
        return normalized

    @staticmethod
    def _normalize_user(user: dict) -> dict:
        normalized = dict(user)
        normalized["timezone"] = normalized.get("timezone") or "UTC"
        return normalized

    @staticmethod
    def _normalize_alert_delivery(delivery: dict) -> dict:
        normalized = dict(delivery)
        normalized["status"] = normalized.get("status") or "active"
        normalized["terminal_reason"] = normalized.get("terminal_reason")
        normalized["trade_snapshot"] = normalized.get("trade_snapshot") or None
        return normalized
