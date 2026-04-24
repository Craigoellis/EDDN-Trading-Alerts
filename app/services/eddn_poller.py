from __future__ import annotations

import json
import re
import threading
import zlib
from datetime import datetime, timezone
from time import time

try:
    import zmq
except ImportError:  # pragma: no cover - exercised in runtime environments without pyzmq
    zmq = None


class EDDNPoller:
    FC_CODE_RE = re.compile(r"\b[A-Z0-9]{3}-[A-Z0-9]{3}\b", re.IGNORECASE)

    def __init__(
        self,
        repository,
        trade_service,
        station_service,
        eddn_listener_url: str,
        alert_process_interval_seconds: int = 20,
        station_refresh_interval_seconds: int = 2,
        station_refresh_batch_size: int = 1,
    ) -> None:
        self._repository = repository
        self._trade_service = trade_service
        self._station_service = station_service
        self._eddn_listener_url = self._normalize_listener_url(eddn_listener_url)
        self._alert_process_interval_seconds = alert_process_interval_seconds
        self._station_refresh_interval_seconds = station_refresh_interval_seconds
        self._station_refresh_batch_size = max(station_refresh_batch_size, 1)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._message_count = 0
        self._last_alert_processing_epoch = 0.0
        self._last_station_refresh_epoch = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.listen_forever, name="eddn-listener", daemon=True)
        self._thread.start()

    def listen_forever(self) -> None:
        if zmq is None:
            print("EDDN listener could not start because pyzmq is not installed.")
            return

        context = zmq.Context.instance()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        socket.setsockopt(zmq.RCVTIMEO, 5000)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(self._eddn_listener_url)
        print(f"Listening to EDDN relay at {self._eddn_listener_url}")

        try:
            while not self._stop_event.is_set():
                try:
                    raw_frame = socket.recv()
                except zmq.error.Again:
                    self._process_background_refreshes()
                    continue
                except Exception as exc:
                    print(f"EDDN listener receive error: {exc}")
                    self._process_background_refreshes()
                    continue

                raw_message = self._decode_message(raw_frame)
                if not raw_message:
                    self._process_background_refreshes()
                    continue

                self._process_message(raw_message)
                self._process_background_refreshes()
        finally:
            socket.close()

    def stop(self) -> None:
        self._stop_event.set()

    def _process_message(self, raw_message: dict) -> None:
        schema_ref = raw_message.get("$schemaRef", "")
        if "fsssignaldiscovered" in schema_ref.lower():
            self._process_fsssignal_message(raw_message)
            return
        if "commodity" not in schema_ref:
            return

        message = raw_message.get("message", {})
        system_name = message.get("systemName")
        station_name = message.get("stationName")
        station_type = message.get("stationType", "Unknown")
        commodities = message.get("commodities", [])
        if not system_name or not station_name:
            return

        market_updates = []
        updated_at = datetime.now(timezone.utc)
        for commodity in commodities:
            commodity_name = commodity.get("name", "").lower()
            if not commodity_name:
                continue

            buy_price = commodity.get("buyPrice", 0)
            sell_price = commodity.get("sellPrice", 0)
            if buy_price == 0 and sell_price == 0:
                continue

            market_updates.append(
                (
                    commodity_name,
                    {
                    "station": station_name,
                    "system": system_name,
                    "stationType": station_type,
                    "buy": buy_price,
                    "sell": sell_price,
                    "stock": commodity.get("stock", 0),
                    "demand": commodity.get("demand", 0),
                    "updated": updated_at,
                    },
                )
            )

        if not market_updates:
            return

        self._repository.upsert_market_batch(market_updates)
        self._station_service.queue_station_refresh(system_name)

        self._message_count += 1
        self._repository.set_last_poll()
        if self._message_count % 25 == 0:
            print("Processed 25 EDDN commodity messages.")

        now_epoch = time()
        if now_epoch - self._last_alert_processing_epoch >= self._alert_process_interval_seconds:
            self._last_alert_processing_epoch = now_epoch
            self._trade_service.process_trade_alerts()

    def _process_fsssignal_message(self, raw_message: dict) -> None:
        message = raw_message.get("message", {})
        system_name = message.get("systemName")
        signals = message.get("signals", [])
        stored_count = 0

        for signal in signals:
            signal_type = str(signal.get("SignalType", "")).lower()
            if signal_type != "fleetcarrier":
                continue

            signal_name = signal.get("SignalName") or ""
            parsed = self._extract_carrier_name_and_code(signal_name)
            if not parsed:
                continue

            carrier_name, carrier_code = parsed
            self._repository.upsert_carrier_name(
                carrier_code=carrier_code,
                carrier_name=carrier_name,
                system_name=system_name,
            )
            stored_count += 1

        if stored_count:
            self._repository.set_last_poll()
            if system_name:
                self._station_service.queue_station_refresh(system_name)

    def _extract_carrier_name_and_code(self, signal_name: str) -> tuple[str, str] | None:
        match = self.FC_CODE_RE.search(signal_name or "")
        if not match:
            return None

        carrier_code = match.group(0).upper()
        carrier_name = signal_name.replace(carrier_code, "").strip(" -()")
        if not carrier_name:
            carrier_name = carrier_code
        return carrier_name, carrier_code

    @staticmethod
    def _decode_message(raw_frame: bytes) -> dict | None:
        candidate_payloads = [raw_frame]
        try:
            candidate_payloads.append(zlib.decompress(raw_frame))
        except zlib.error:
            pass

        for payload in candidate_payloads:
            try:
                return json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

        return None

    @staticmethod
    def _normalize_listener_url(listener_url: str) -> str:
        return listener_url.rstrip("/")

    def _process_background_refreshes(self) -> None:
        now_epoch = time()
        if now_epoch - self._last_station_refresh_epoch < self._station_refresh_interval_seconds:
            return
        self._last_station_refresh_epoch = now_epoch
        self._station_service.refresh_pending_station_metadata(max_systems=self._station_refresh_batch_size)
