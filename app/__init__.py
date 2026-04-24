from flask import Flask, g, session

from app.config import AppConfig
from app.repositories.market_repository import MarketRepository
from app.repositories.user_repository import UserRepository
from app.services.alert_service import AlertService
from app.services.auth_service import AuthService
from app.services.eddn_poller import EDDNPoller
from app.services.ops_service import OpsService
from app.services.station_service import StationService
from app.services.telegram_poller import TelegramPoller
from app.services.telegram_update_service import TelegramUpdateService
from app.services.trade_service import TradeService
from app.web.routes import web_bp


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(AppConfig())
    app.secret_key = app.config["SECRET_KEY"]

    market_repository = MarketRepository(
        storage_dir=app.config["STORAGE_DIR"],
        max_history_entries=app.config["MAX_HISTORY_ENTRIES"],
        alert_expiry_seconds=app.config["ALERT_EXPIRY_SECONDS"],
    )
    user_repository = UserRepository(
        storage_dir=app.config["STORAGE_DIR"],
        alert_expiry_seconds=app.config["ALERT_EXPIRY_SECONDS"],
    )
    station_service = StationService(
        edsm_system_url=app.config["EDSM_SYSTEM_URL"],
        edsm_station_url=app.config["EDSM_STATION_URL"],
        inara_api_url=app.config["INARA_API_URL"],
        inara_api_key=app.config["INARA_API_KEY"],
        edsm_failure_cooldown_seconds=app.config["EDSM_FAILURE_COOLDOWN_SECONDS"],
        market_repository=market_repository,
    )
    alert_service = AlertService(
        bot_token=app.config["BOT_TOKEN"],
        chat_id=app.config["CHAT_ID"],
        bot_username=app.config["TELEGRAM_BOT_USERNAME"],
    )
    telegram_update_service = TelegramUpdateService(
        user_repository=user_repository,
        alert_service=alert_service,
    )
    auth_service = AuthService(user_repository=user_repository)
    ops_service = OpsService(
        storage_dir=app.config["STORAGE_DIR"],
        project_dir=str(__import__("pathlib").Path(app.root_path).parent),
    )
    trade_service = TradeService(
        market_repository=market_repository,
        user_repository=user_repository,
        station_service=station_service,
        alert_service=alert_service,
        default_filters=app.config["DEFAULT_FILTERS"],
    )
    poller = EDDNPoller(
        repository=market_repository,
        trade_service=trade_service,
        eddn_listener_url=app.config["EDDN_LISTENER_URL"],
        alert_process_interval_seconds=app.config["ALERT_PROCESS_INTERVAL_SECONDS"],
    )
    telegram_poller = TelegramPoller(
        bot_token=app.config["BOT_TOKEN"],
        update_service=telegram_update_service,
        mode=app.config["TELEGRAM_UPDATE_MODE"],
        poll_interval_seconds=app.config["TELEGRAM_POLL_INTERVAL_SECONDS"],
    )

    app.extensions["market_repository"] = market_repository
    app.extensions["user_repository"] = user_repository
    app.extensions["station_service"] = station_service
    app.extensions["auth_service"] = auth_service
    app.extensions["alert_service"] = alert_service
    app.extensions["ops_service"] = ops_service
    app.extensions["trade_service"] = trade_service
    app.extensions["eddn_poller"] = poller
    app.extensions["telegram_update_service"] = telegram_update_service
    app.extensions["telegram_poller"] = telegram_poller

    @app.before_request
    def load_current_user() -> None:
        user_id = session.get("user_id")
        g.current_user = user_repository.get_user_by_id(user_id) if user_id else None

    @app.context_processor
    def inject_template_globals() -> dict:
        return {
            "current_user": g.get("current_user"),
            "telegram_bot_username": app.config["TELEGRAM_BOT_USERNAME"],
        }

    app.register_blueprint(web_bp)

    poller.start()
    telegram_poller.start()

    return app
