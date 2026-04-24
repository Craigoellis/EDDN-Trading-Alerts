from __future__ import annotations

import json
import threading
from time import sleep

import requests


class TelegramPoller:
    def __init__(
        self,
        *,
        bot_token: str,
        update_service,
        mode: str = "webhook",
        poll_interval_seconds: int = 3,
    ) -> None:
        self._bot_token = bot_token
        self._update_service = update_service
        self._mode = (mode or "webhook").lower()
        self._poll_interval_seconds = max(int(poll_interval_seconds), 1)
        self._session = requests.Session()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = None

    def start(self) -> None:
        if self._mode != "polling" or not self._bot_token:
            return
        if self._thread and self._thread.is_alive():
            return
        self._delete_webhook()
        self._thread = threading.Thread(target=self._listen_forever, name="telegram-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _listen_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                updates = self._get_updates()
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self._offset = update_id + 1
                    self._update_service.handle_update(update)
            except requests.RequestException as exc:
                print(f"Telegram polling failed: {exc}")
                sleep(self._poll_interval_seconds)
                continue
            except Exception as exc:  # pragma: no cover - runtime guard
                print(f"Telegram polling handler failed: {exc}")

            sleep(self._poll_interval_seconds)

    def _get_updates(self) -> list[dict]:
        params = {
            "timeout": 10,
            "allowed_updates": json.dumps(["message"]),
        }
        if self._offset is not None:
            params["offset"] = self._offset

        response = self._session.get(
            f"https://api.telegram.org/bot{self._bot_token}/getUpdates",
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("ok"):
            return []
        result = payload.get("result")
        return result if isinstance(result, list) else []

    def _delete_webhook(self) -> None:
        try:
            self._session.post(
                f"https://api.telegram.org/bot{self._bot_token}/deleteWebhook",
                json={"drop_pending_updates": False},
                timeout=10,
            )
        except requests.RequestException as exc:
            print(f"Telegram webhook delete failed before polling start: {exc}")
