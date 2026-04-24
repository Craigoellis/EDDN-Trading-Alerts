from __future__ import annotations


class TelegramUpdateService:
    def __init__(self, user_repository, alert_service) -> None:
        self._user_repository = user_repository
        self._alert_service = alert_service

    def handle_update(self, payload: dict) -> bool:
        message = payload.get("message", {})
        text = str(message.get("text", "")).strip()
        chat = message.get("chat", {})
        chat_id = chat.get("id")

        if not chat_id:
            return False

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                code = parts[1].strip()
                user = self._user_repository.consume_telegram_link_code(code, str(chat_id))
                if user:
                    self._alert_service.send_plain_message(
                        chat_id=str(chat_id),
                        message=f"Telegram linked successfully to {user['username']}. You will now receive alert messages here.",
                    )
                else:
                    self._alert_service.send_plain_message(
                        chat_id=str(chat_id),
                        message="That link code is invalid or has already been used.",
                    )
            else:
                self._alert_service.send_plain_message(
                    chat_id=str(chat_id),
                    message="Use the Telegram link button from your profile page to connect this chat.",
                )
            return True

        return False
