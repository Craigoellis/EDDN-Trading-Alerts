from __future__ import annotations

from datetime import datetime
import hashlib
from zoneinfo import ZoneInfo

import requests


class AlertService:
    def __init__(self, bot_token: str, chat_id: str, bot_username: str = "") -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._bot_username = bot_username

    def send_trade_alert(self, trade: dict) -> None:
        if not self._bot_token or not self._chat_id:
            return
        self.send_trade_alert_to_chat(chat_id=self._chat_id, trade=trade)

    def send_trade_alert_to_chat(
        self,
        *,
        chat_id: str,
        trade: dict,
        filter_name: str | None = None,
        existing_message_id: int | None = None,
        status_label: str | None = None,
        timezone_name: str = "UTC",
    ) -> dict:
        if not self._bot_token or not chat_id:
            return {"message_id": existing_message_id, "payload_hash": "", "was_edited": False}

        message = self._build_trade_message(
            trade=trade,
            filter_name=filter_name,
            status_label=status_label,
            timezone_name=timezone_name,
        )
        payload_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()

        if existing_message_id is not None:
            edit_result = self._edit_message(chat_id=chat_id, message_id=existing_message_id, message=message)
            if edit_result["ok"]:
                return {"message_id": existing_message_id, "payload_hash": payload_hash, "was_edited": True}

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            return {
                "message_id": ((data.get("result") or {}).get("message_id") if isinstance(data, dict) else None),
                "payload_hash": payload_hash,
                "was_edited": False,
            }
        except requests.RequestException as exc:
            print(f"Telegram alert send failed: {exc}")
            return {"message_id": existing_message_id, "payload_hash": payload_hash, "was_edited": False}

    def send_plain_message(self, *, chat_id: str, message: str) -> None:
        if not self._bot_token or not chat_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=10,
            )
        except requests.RequestException as exc:
            print(f"Telegram message send failed: {exc}")

    def build_telegram_start_link(self, code: str) -> str | None:
        if not self._bot_username:
            return None
        return f"https://t.me/{self._bot_username}?start={code}"

    def _edit_message(self, *, chat_id: str, message_id: int, message: str) -> dict:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self._bot_token}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if isinstance(data, dict) and data.get("ok"):
                return {"ok": True}
            description = (data.get("description") or "").lower() if isinstance(data, dict) else ""
            if "message is not modified" in description:
                return {"ok": True}
            return {"ok": False}
        except requests.RequestException as exc:
            print(f"Telegram message edit failed: {exc}")
            return {"ok": False}

    def _build_trade_message(
        self,
        *,
        trade: dict,
        filter_name: str | None = None,
        status_label: str | None = None,
        timezone_name: str = "UTC",
    ) -> str:
        distance_origin_system = trade.get("distance_origin_system") or "Sol"
        distance_from_origin = trade.get("distance_from_origin_ly")
        filter_block = f"🎯 {filter_name}\n" if filter_name else ""
        status_block = f"{status_label}\n" if status_label else ""
        timezone_label = self._format_timezone_label(timezone_name)
        origin_block = (
            f"🌍 Distance from {distance_origin_system}: {distance_from_origin:.2f} LY\n\n"
            if distance_from_origin is not None
            else "\n"
        )

        return (
            f"{status_block}"
            f"🚀 <b>Trade Alert</b>\n\n"
            f"{filter_block}"
            f"💰 <b>{trade['commodity_display']}</b>\n"
            f"📈 Profit: +{trade['profit_per_ton']:,} Cr/ton\n"
            f"📏 Distance Between Systems: {trade['distance_ly']:.2f} LY\n"
            f"{origin_block}"
            f"🛒 <b>BUY FROM</b>\n"
            f"🏙️ {trade['buy_station_name']} ({trade['buy_station_type']})\n"
            f"📍 {trade['buy_system']}\n"
            f"🛬 Pad: {trade['buy_pad_size']}\n"
            f"☀️ Distance: {self._format_station_distance(trade['buy_station_distance_ls'])}\n"
            f"💵 Price: {trade['buy_price']:,} Cr\n"
            f"📦 Supply: {trade['supply']:,}\n"
            f"🕒 Updated at {self._format_timestamp(trade['buy_updated_at'], timezone_name)} {timezone_label}\n\n"
            f"💼 <b>SELL TO</b>\n"
            f"🏙️ {trade['sell_station_name']} ({trade['sell_station_type']})\n"
            f"📍 {trade['sell_system']}\n"
            f"🛬 Pad: {trade['sell_pad_size']}\n"
            f"☀️ Distance: {self._format_station_distance(trade['sell_station_distance_ls'])}\n"
            f"💵 Price: {trade['sell_price']:,} Cr\n"
            f"📦 Demand: {trade['demand']:,}\n"
            f"🕒 Updated at {self._format_timestamp(trade['sell_updated_at'], timezone_name)} {timezone_label}\n\n"
            f"🕒 Updated: {self._format_timestamp(trade['updated_at'], timezone_name)} {timezone_label}"
        )

    @staticmethod
    def _format_timestamp(timestamp: str | datetime, timezone_name: str = "UTC") -> str:
        target_timezone = AlertService._resolve_timezone(timezone_name)
        if isinstance(timestamp, datetime):
            datetime_value = timestamp
        else:
            try:
                datetime_value = datetime.fromisoformat(str(timestamp))
            except ValueError:
                return str(timestamp)

        if datetime_value.tzinfo is None:
            datetime_value = datetime_value.replace(tzinfo=ZoneInfo("UTC"))
        return datetime_value.astimezone(target_timezone).strftime("%d/%m/%Y %H:%M:%S")

    @staticmethod
    def _format_timezone_label(timezone_name: str) -> str:
        try:
            return datetime.now(AlertService._resolve_timezone(timezone_name)).strftime("%Z") or timezone_name
        except Exception:
            return timezone_name or "UTC"

    @staticmethod
    def _format_station_distance(distance_value) -> str:
        if distance_value is None:
            return "Unknown"
        return f"{distance_value} Ls"

    @staticmethod
    def _resolve_timezone(timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name or "UTC")
        except Exception:
            return ZoneInfo("UTC")
