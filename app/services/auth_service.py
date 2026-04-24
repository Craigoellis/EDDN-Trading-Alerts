from __future__ import annotations

from zoneinfo import ZoneInfo

from werkzeug.security import check_password_hash, generate_password_hash


class AuthService:
    def __init__(self, user_repository) -> None:
        self._user_repository = user_repository

    def register_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        telegram_contact: str,
        timezone_name: str,
    ) -> tuple[dict | None, str | None]:
        username = username.strip()
        email = email.strip().lower()
        telegram_contact = telegram_contact.strip()
        timezone_name = timezone_name.strip() or "UTC"

        if not username or not email or not password:
            return None, "Username, email, and password are required."
        if len(password) < 8:
            return None, "Password must be at least 8 characters."
        if self._user_repository.get_user_by_username(username):
            return None, "That username is already taken."
        if self._user_repository.get_user_by_email(email):
            return None, "That email address is already registered."
        try:
            ZoneInfo(timezone_name)
        except Exception:
            return None, "Please choose a valid timezone."

        user = self._user_repository.create_user(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            telegram_contact=telegram_contact,
            timezone_name=timezone_name,
        )
        return user, None

    def authenticate(self, *, email: str, password: str) -> tuple[dict | None, str | None]:
        user = self._user_repository.get_user_by_email(email.strip().lower())
        if not user or not check_password_hash(user["password_hash"], password):
            return None, "Invalid email or password."
        return user, None
