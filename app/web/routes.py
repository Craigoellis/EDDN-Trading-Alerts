from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo, available_timezones

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)


web_bp = Blueprint("web", __name__)


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not g.get("current_user"):
            flash("Please sign in to access your account.", "warning")
            return redirect(url_for("web.sign_in"))
        return view_func(*args, **kwargs)

    return wrapped_view


@web_bp.route("/")
def dashboard():
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_dashboard_payload(request.args.to_dict())
    return render_template("dashboard.html", initial_data=payload)


@web_bp.route("/sign-up", methods=["GET", "POST"])
def sign_up():
    auth_service = current_app.extensions["auth_service"]
    if request.method == "POST":
        user, error = auth_service.register_user(
            username=request.form.get("username", ""),
            email=request.form.get("email", ""),
            password=request.form.get("password", ""),
            telegram_contact=request.form.get("telegram_contact", ""),
            timezone_name=request.form.get("timezone", "UTC"),
        )
        if error:
            flash(error, "error")
        else:
            session["user_id"] = user["id"]
            flash("Your account has been created.", "success")
            return redirect(url_for("web.alerts"))

    return render_template("sign_up.html")


@web_bp.route("/sign-in", methods=["GET", "POST"])
def sign_in():
    auth_service = current_app.extensions["auth_service"]
    if request.method == "POST":
        user, error = auth_service.authenticate(
            email=request.form.get("email", ""),
            password=request.form.get("password", ""),
        )
        if error:
            flash(error, "error")
        else:
            session["user_id"] = user["id"]
            flash("Signed in successfully.", "success")
            return redirect(url_for("web.alerts"))

    return render_template("sign_in.html")


@web_bp.route("/sign-out", methods=["POST"])
def sign_out():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("web.dashboard"))


@web_bp.route("/account")
@login_required
def account():
    return redirect(url_for("web.alerts"))


@web_bp.route("/alerts")
@login_required
def alerts():
    user_repository = current_app.extensions["user_repository"]
    user = g.current_user
    filters = user_repository.list_filters_for_user(user["id"])

    return render_template(
        "alerts.html",
        alerts_data={
            "user": user,
            "filters": filters,
        },
    )


@web_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_repository = current_app.extensions["user_repository"]
    alert_service = current_app.extensions["alert_service"]
    user = dict(g.current_user)
    active_link = user_repository.get_active_link_for_user(user["id"])
    if not user.get("telegram_verified") and not active_link:
        active_link = user_repository.create_telegram_link_code(user["id"])
    telegram_link = alert_service.build_telegram_start_link(active_link["code"]) if active_link else None

    if request.method == "POST":
        telegram_contact = request.form.get("telegram_contact", "").strip()
        timezone_name = request.form.get("timezone", "UTC").strip() or "UTC"
        try:
            ZoneInfo(timezone_name)
        except Exception:
            flash("Please choose a valid timezone.", "error")
        else:
            user["telegram_contact"] = telegram_contact
            user["timezone"] = timezone_name
            user_repository.update_user(user)
            session["user_id"] = user["id"]
            flash("Profile updated.", "success")
            return redirect(url_for("web.profile"))

    return render_template(
        "profile.html",
        profile_data={
            "user": user,
            "timezone_options": sorted(available_timezones()),
            "active_link": active_link,
            "telegram_link": telegram_link,
        },
    )


@web_bp.route("/account/filters", methods=["POST"])
@login_required
def create_account_filter():
    user_repository = current_app.extensions["user_repository"]
    trade_service = current_app.extensions["trade_service"]
    filter_payload = trade_service.parse_filters(request.form.to_dict())

    name = request.form.get("name", "").strip() or "My Alert Filter"
    created_filter = user_repository.create_filter(
        user_id=g.current_user["id"],
        filter_data={
            "name": name,
            "profit_min": filter_payload["profit_min"],
            "supply_min": filter_payload["supply_min"],
            "demand_min": filter_payload["demand_min"],
            "max_origin_distance_ly": filter_payload["max_origin_distance_ly"],
            "max_route_distance_ly": filter_payload["max_route_distance_ly"],
            "distance_origin_system": filter_payload["distance_origin_system"],
            "max_station_distance_ls": filter_payload["max_station_distance_ls"],
            "landing_pad_size": filter_payload["landing_pad_size"],
            "fleet_carrier_mode": filter_payload["fleet_carrier_mode"],
            "is_enabled": request.form.get("is_enabled", "on") == "on",
        },
    )
    immediate_matches = trade_service.process_filter_alerts(created_filter, user=g.current_user)
    if immediate_matches:
        flash(
            f"Alert filter saved. {immediate_matches} current trade opportunit{'y' if immediate_matches == 1 else 'ies'} matched immediately.",
            "success",
        )
    else:
        flash("Alert filter saved.", "success")
    return redirect(url_for("web.alerts"))


@web_bp.route("/account/filters/<int:filter_id>/delete", methods=["POST"])
@login_required
def delete_account_filter(filter_id: int):
    user_repository = current_app.extensions["user_repository"]
    deleted = user_repository.delete_filter(user_id=g.current_user["id"], filter_id=filter_id)
    flash("Alert filter deleted." if deleted else "Filter not found.", "success" if deleted else "warning")
    return redirect(url_for("web.alerts"))


@web_bp.route("/account/filters/<int:filter_id>/toggle", methods=["POST"])
@login_required
def toggle_account_filter(filter_id: int):
    user_repository = current_app.extensions["user_repository"]
    desired_state = request.form.get("is_enabled", "false").lower() == "true"
    updated = user_repository.set_filter_enabled(
        user_id=g.current_user["id"],
        filter_id=filter_id,
        is_enabled=desired_state,
    )
    if updated:
        flash(
            "Alert filter enabled." if desired_state else "Alert filter paused. Existing alert messages can still update.",
            "success",
        )
    else:
        flash("Filter not found.", "warning")
    return redirect(url_for("web.alerts"))


@web_bp.route("/account/alerts/clear", methods=["POST"])
@login_required
def clear_account_alert_messages():
    user_repository = current_app.extensions["user_repository"]
    cleared_count = user_repository.clear_alert_history_for_user(user_id=g.current_user["id"])
    if cleared_count:
        flash(
            f"Cleared {cleared_count} stored alert message entr{'y' if cleared_count == 1 else 'ies'}. New alerts will be sent fresh.",
            "success",
        )
    else:
        flash("There were no stored alert messages to clear.", "warning")
    return redirect(url_for("web.alerts"))


@web_bp.route("/account/telegram/refresh", methods=["POST"])
@login_required
def refresh_telegram_link():
    user_repository = current_app.extensions["user_repository"]
    user_repository.create_telegram_link_code(g.current_user["id"])
    flash("A fresh Telegram link code has been generated.", "success")
    return redirect(url_for("web.profile"))


@web_bp.route("/telegram/webhook/<secret>", methods=["POST"])
def telegram_webhook(secret: str):
    if secret != current_app.config["TELEGRAM_WEBHOOK_SECRET"]:
        return jsonify({"ok": False}), 403

    payload = request.get_json(silent=True) or {}
    current_app.extensions["telegram_update_service"].handle_update(payload)
    return jsonify({"ok": True})


@web_bp.route("/api/trades")
def get_trades():
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_dashboard_payload(request.args.to_dict())
    return jsonify(payload)


@web_bp.route("/stations")
def station_detail():
    system_name = request.args.get("system", "")
    station_name = request.args.get("station", "")
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_station_payload(system_name, station_name, request.args.to_dict())
    return render_template("station_detail.html", station_data=payload)


@web_bp.route("/stations-browser")
def stations_browser():
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_station_browser_payload(request.args.to_dict())
    return render_template("stations_browser.html", station_browser_data=payload)


@web_bp.route("/api/stations")
def get_station_detail():
    system_name = request.args.get("system", "")
    station_name = request.args.get("station", "")
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_station_payload(system_name, station_name, request.args.to_dict())
    return jsonify(payload)


@web_bp.route("/api/stations-browser")
def get_stations_browser():
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_station_browser_payload(request.args.to_dict())
    return jsonify(payload)


@web_bp.route("/systems")
def system_detail():
    system_name = request.args.get("system", "")
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_system_payload(system_name)
    return render_template("system_detail.html", system_data=payload)


@web_bp.route("/api/systems")
def get_system_detail():
    system_name = request.args.get("system", "")
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_system_payload(system_name)
    return jsonify(payload)


@web_bp.route("/commodities")
def commodity_detail():
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_commodity_finder_payload(request.args.to_dict())
    return render_template("commodity_detail.html", commodity_data=payload)


@web_bp.route("/api/commodities")
def get_commodity_detail():
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_commodity_finder_payload(request.args.to_dict())
    return jsonify(payload)


@web_bp.route("/search")
def search():
    commodity_name = request.args.get("query", "").strip().lower()
    if commodity_name:
        return redirect(url_for("web.commodity_detail", commodity=commodity_name))
    return redirect(url_for("web.commodity_detail"))


@web_bp.route("/api/search")
def search_api():
    query = request.args.get("query", "")
    trade_service = current_app.extensions["trade_service"]
    payload = trade_service.build_search_payload(query)
    return jsonify(payload)


@web_bp.route("/api/system-suggestions")
def system_suggestions():
    query = request.args.get("query", "")
    trade_service = current_app.extensions["trade_service"]
    return jsonify({"systems": trade_service.suggest_systems(query)})


@web_bp.route("/api/commodity-suggestions")
def commodity_suggestions():
    query = request.args.get("query", "")
    trade_service = current_app.extensions["trade_service"]
    return jsonify({"commodities": trade_service.suggest_commodities(query)})


@web_bp.route("/api/health")
def health():
    last_poll_epoch = current_app.extensions["market_repository"].get_last_poll_epoch()
    last_poll_iso = None
    if last_poll_epoch:
        last_poll_iso = datetime.fromtimestamp(last_poll_epoch, tz=timezone.utc).isoformat()

    return jsonify(
        {
            "status": "ok",
            "last_poll_at": last_poll_iso,
            "eddn_listener_url": current_app.config["EDDN_LISTENER_URL"],
            "storage_dir": current_app.config["STORAGE_DIR"],
        }
    )


@web_bp.route("/ops")
@login_required
def ops_dashboard():
    metrics = current_app.extensions["ops_service"].get_metrics()
    return render_template("ops_dashboard.html", metrics_data=metrics)


@web_bp.route("/api/ops-metrics")
@login_required
def ops_metrics():
    return jsonify(current_app.extensions["ops_service"].get_metrics())
