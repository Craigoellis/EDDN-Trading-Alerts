from __future__ import annotations

import hashlib


class TradeService:
    def __init__(self, market_repository, user_repository, station_service, alert_service, default_filters: dict) -> None:
        self._market_repository = market_repository
        self._user_repository = user_repository
        self._station_service = station_service
        self._alert_service = alert_service
        self._default_filters = default_filters

    def build_dashboard_payload(self, filter_values: dict | None = None) -> dict:
        filters = self.parse_filters(filter_values or {})
        opportunities = self.get_trade_opportunities(filters)

        total_profit = sum(opportunity["profit_per_ton"] for opportunity in opportunities)
        max_profit = max((opportunity["profit_per_ton"] for opportunity in opportunities), default=0)
        shortest_route = min((opportunity["distance_ly"] for opportunity in opportunities), default=0)

        return {
            "filters": filters,
            "summary": {
                "opportunity_count": len(opportunities),
                "average_profit_per_ton": int(total_profit / len(opportunities)) if opportunities else 0,
                "best_profit_per_ton": max_profit,
                "shortest_route_ly": shortest_route,
                "last_poll_epoch": self._market_repository.get_last_poll_epoch(),
            },
            "opportunities": opportunities,
        }

    def build_station_browser_payload(self, params: dict | None = None) -> dict:
        params = params or {}
        filters = self.parse_station_browser_filters(params)
        markets = self._market_repository.get_markets_snapshot()
        stations = {}

        for commodity_name, entries in markets.items():
            for entry in entries:
                station = self._station_service.get_station_data(
                    entry["system"],
                    entry["station"],
                    allow_live_lookup=False,
                )
                station_type = station.get("type") or entry.get("stationType") or "Unknown"
                pad_size = station.get("pad") or "Unknown"
                arrival_distance_ls = self._normalize_station_distance(station.get("distance"))

                if not self._matches_station_browser_filters(
                    station_type=station_type,
                    pad_size=pad_size,
                    arrival_distance_ls=arrival_distance_ls,
                    system_name=entry["system"],
                    station_name=entry["station"],
                    filters=filters,
                ):
                    continue

                key = (entry["system"], entry["station"])
                station_entry = stations.setdefault(
                    key,
                    {
                        "station_name": self._station_service.prettify_station_name(
                            entry["station"],
                            station_type,
                            allow_live_lookup=False,
                        ),
                        "raw_station_name": entry["station"],
                        "system": entry["system"],
                        "station_type": station_type,
                        "pad_size": pad_size,
                        "arrival_distance_ls": arrival_distance_ls,
                        "commodity_count": 0,
                        "updated_at": entry["updated"].isoformat(),
                    },
                )
                station_entry["commodity_count"] += 1
                station_entry["updated_at"] = max(station_entry["updated_at"], entry["updated"].isoformat())

        station_rows = sorted(
            stations.values(),
            key=lambda item: (
                item["system"],
                item["station_name"],
            ),
        )

        return {
            "filters": filters,
            "summary": {
                "station_count": len(station_rows),
                "last_poll_epoch": self._market_repository.get_last_poll_epoch(),
            },
            "stations": station_rows,
        }

    def build_station_payload(self, system_name: str, station_name: str, params: dict | None = None) -> dict:
        params = params or {}
        station_rows = self._market_repository.get_station_snapshot(system_name, station_name)
        station_info = self._station_service.get_station_data(system_name, station_name, allow_live_lookup=False)
        station_type = station_info.get("type") or "Unknown"
        station_pad = station_info.get("pad") or "Unknown"
        station_distance_ls = self._normalize_station_distance(station_info.get("distance"))

        commodities = [
            {
                "commodity": row["commodity"],
                "commodity_display": row["commodity"].replace("-", " ").title(),
                "buy_price": row["buy"],
                "sell_price": row["sell"],
                "stock": row["stock"],
                "demand": row["demand"],
                "updated_at": row["updated"].isoformat(),
            }
            for row in station_rows
        ]

        history = self._decorate_history_rows(
            self._market_repository.get_recent_history(
                system_name=system_name,
                station_name=station_name,
                limit=150,
            )
        )

        sort_by = params.get("sort_by", "commodity")
        sort_order = params.get("sort_order", "asc")
        commodities = self._sort_station_commodities(commodities, sort_by, sort_order)

        return {
            "station": {
                "name": self._station_service.prettify_station_name(
                    station_name,
                    station_type,
                    allow_live_lookup=False,
                ),
                "raw_name": station_name,
                "system": system_name,
                "type": station_type,
                "pad_size": station_pad,
                "arrival_distance_ls": station_distance_ls,
                "commodity_count": len(commodities),
                "last_poll_epoch": self._market_repository.get_last_poll_epoch(),
            },
            "sorting": {
                "sort_by": sort_by,
                "sort_order": sort_order,
            },
            "commodities": commodities,
            "history": history,
        }

    def build_system_payload(self, system_name: str) -> dict:
        rows = self._market_repository.get_system_snapshot(system_name)
        stations = {}
        for row in rows:
            station_key = (row["system"], row["station"])
            station_info = self._station_service.get_station_data(
                row["system"],
                row["station"],
                allow_live_lookup=False,
            )
            station_type = station_info.get("type") or "Unknown"
            station_pad = station_info.get("pad") or "Unknown"
            station_distance_ls = self._normalize_station_distance(station_info.get("distance"))

            station_entry = stations.setdefault(
                station_key,
                {
                    "station_name": self._station_service.prettify_station_name(
                        row["station"],
                        station_type,
                        allow_live_lookup=False,
                    ),
                    "raw_station_name": row["station"],
                    "system": row["system"],
                    "station_type": station_type,
                    "pad_size": station_pad,
                    "arrival_distance_ls": station_distance_ls,
                    "commodity_count": 0,
                    "latest_update_at": row["updated"].isoformat(),
                },
            )
            station_entry["commodity_count"] += 1
            station_entry["latest_update_at"] = max(station_entry["latest_update_at"], row["updated"].isoformat())

        history = self._decorate_history_rows(
            self._market_repository.get_recent_history(system_name=system_name, limit=150)
        )

        station_list = sorted(
            stations.values(),
            key=lambda item: (item["station_name"], item["arrival_distance_ls"] or 0),
        )

        return {
            "system": {
                "name": system_name,
                "station_count": len(station_list),
                "commodity_rows": len(rows),
                "last_poll_epoch": self._market_repository.get_last_poll_epoch(),
            },
            "stations": station_list,
            "history": history,
        }

    def build_commodity_payload(self, commodity_name: str) -> dict:
        rows = self._market_repository.get_commodity_snapshot(commodity_name)
        market_rows = []
        for row in rows:
            station_info = self._station_service.get_station_data(
                row["system"],
                row["station"],
                allow_live_lookup=False,
            )
            station_type = station_info.get("type") or "Unknown"
            market_rows.append(
                {
                    "commodity": commodity_name,
                    "commodity_display": commodity_name.replace("-", " ").title(),
                    "station_name": self._station_service.prettify_station_name(
                        row["station"],
                        station_type,
                        allow_live_lookup=False,
                    ),
                    "raw_station_name": row["station"],
                    "system": row["system"],
                    "station_type": station_type,
                    "pad_size": station_info.get("pad") or "Unknown",
                    "arrival_distance_ls": self._normalize_station_distance(station_info.get("distance")),
                    "buy_price": row["buy"],
                    "sell_price": row["sell"],
                    "stock": row["stock"],
                    "demand": row["demand"],
                    "updated_at": row["updated"].isoformat(),
                }
            )

        market_rows.sort(key=lambda item: (-item["sell_price"], item["station_name"]))
        history = self._decorate_history_rows(
            self._market_repository.get_recent_history(commodity_name=commodity_name, limit=150)
        )

        return {
            "commodity": {
                "name": commodity_name,
                "display_name": commodity_name.replace("-", " ").title(),
                "listing_count": len(market_rows),
                "best_sell_price": max((row["sell_price"] for row in market_rows), default=0),
                "lowest_buy_price": min((row["buy_price"] for row in market_rows if row["buy_price"] > 0), default=0),
                "last_poll_epoch": self._market_repository.get_last_poll_epoch(),
            },
            "markets": market_rows,
            "history": history,
        }

    def build_search_payload(self, query: str) -> dict:
        matches = self._market_repository.search_entities(query)
        stations = [
            {
                "station_name": match["station"],
                "system": match["system"],
            }
            for match in matches["stations"]
        ]
        systems = [{"name": system_name} for system_name in matches["systems"]]
        commodities = [
            {"name": commodity_name, "display_name": commodity_name.replace("-", " ").title()}
            for commodity_name in matches["commodities"]
        ]
        return {
            "query": query,
            "stations": stations,
            "systems": systems,
            "commodities": commodities,
        }

    def suggest_systems(self, query: str, limit: int = 8) -> list[str]:
        return self._market_repository.search_system_names(query, limit=limit)

    def suggest_commodities(self, query: str, limit: int = 8) -> list[str]:
        return self._market_repository.search_commodity_names(query, limit=limit)

    def build_commodity_finder_payload(self, params: dict | None = None) -> dict:
        params = params or {}
        filters = self.parse_commodity_finder_filters(params)
        commodity_name = filters["commodity"]

        if not commodity_name:
            return {
                "filters": filters,
                "summary": {
                    "commodity_selected": False,
                    "buy_listing_count": 0,
                    "sell_listing_count": 0,
                    "best_buy_price": 0,
                    "best_sell_price": 0,
                    "last_poll_epoch": self._market_repository.get_last_poll_epoch(),
                },
                "buy_listings": [],
                "sell_listings": [],
            }

        rows = self._market_repository.get_commodity_snapshot(commodity_name)
        buy_listings = []
        sell_listings = []
        buy_distance_cache = {}
        sell_distance_cache = {}

        for row in rows:
            station_info = self._station_service.get_station_data(
                row["system"],
                row["station"],
                allow_live_lookup=False,
            )
            station_type = station_info.get("type") or "Unknown"
            pad_size = station_info.get("pad") or "Unknown"
            arrival_distance_ls = self._normalize_station_distance(station_info.get("distance"))
            station_name = self._station_service.prettify_station_name(
                row["station"],
                station_type,
                allow_live_lookup=False,
            )

            base_listing = {
                "commodity": commodity_name,
                "commodity_display": commodity_name.replace("-", " ").title(),
                "station_name": station_name,
                "raw_station_name": row["station"],
                "system": row["system"],
                "station_type": station_type,
                "pad_size": pad_size,
                "arrival_distance_ls": arrival_distance_ls,
                "buy_price": row["buy"],
                "sell_price": row["sell"],
                "stock": row["stock"],
                "demand": row["demand"],
                "updated_at": row["updated"].isoformat(),
            }

            buy_origin_system = filters["buy_origin_system"]
            if buy_origin_system:
                buy_distance_ly = buy_distance_cache.get(row["system"].lower())
                if buy_distance_ly is None and row["system"].lower() not in buy_distance_cache:
                    buy_distance_cache[row["system"].lower()] = self._station_service.calc_distance_ly(
                        buy_origin_system,
                        row["system"],
                    )
                buy_distance_ly = buy_distance_cache.get(row["system"].lower())
            else:
                buy_distance_ly = None

            sell_origin_system = filters["sell_origin_system"]
            sell_distance_key = row["system"].lower()
            if sell_origin_system:
                sell_distance_ly = sell_distance_cache.get(sell_distance_key)
                if sell_distance_ly is None and sell_distance_key not in sell_distance_cache:
                    sell_distance_cache[sell_distance_key] = self._station_service.calc_distance_ly(
                        sell_origin_system,
                        row["system"],
                    )
                sell_distance_ly = sell_distance_cache.get(sell_distance_key)
            else:
                sell_distance_ly = None

            if self._matches_commodity_station_filters(
                price=row["buy"],
                quantity=row["stock"],
                distance_ly=buy_distance_ly,
                arrival_distance_ls=arrival_distance_ls,
                max_distance_ly=filters["buy_max_distance_ly"],
                max_station_distance_ls=filters["buy_max_station_distance_ls"],
            ):
                buy_listings.append(
                    {
                        **base_listing,
                        "distance_origin_system": buy_origin_system,
                        "distance_from_origin_ly": buy_distance_ly,
                    }
                )

            if self._matches_commodity_station_filters(
                price=row["sell"],
                quantity=row["demand"],
                distance_ly=sell_distance_ly,
                arrival_distance_ls=arrival_distance_ls,
                max_distance_ly=filters["sell_max_distance_ly"],
                max_station_distance_ls=filters["sell_max_station_distance_ls"],
            ):
                sell_listings.append(
                    {
                        **base_listing,
                        "distance_origin_system": sell_origin_system,
                        "distance_from_origin_ly": sell_distance_ly,
                    }
                )

        buy_listings.sort(
            key=lambda item: (
                item["buy_price"] if item["buy_price"] > 0 else float("inf"),
                item["distance_from_origin_ly"] if item["distance_from_origin_ly"] is not None else float("inf"),
                item["arrival_distance_ls"] if item["arrival_distance_ls"] is not None else float("inf"),
                item["station_name"],
            )
        )
        sell_listings.sort(
            key=lambda item: (
                -(item["sell_price"] or 0),
                item["distance_from_origin_ly"] if item["distance_from_origin_ly"] is not None else float("inf"),
                item["arrival_distance_ls"] if item["arrival_distance_ls"] is not None else float("inf"),
                item["station_name"],
            )
        )

        return {
            "filters": filters,
            "summary": {
                "commodity_selected": True,
                "buy_listing_count": len(buy_listings),
                "sell_listing_count": len(sell_listings),
                "best_buy_price": min((item["buy_price"] for item in buy_listings), default=0),
                "best_sell_price": max((item["sell_price"] for item in sell_listings), default=0),
                "last_poll_epoch": self._market_repository.get_last_poll_epoch(),
            },
            "buy_listings": buy_listings[:150],
            "sell_listings": sell_listings[:150],
        }

    def process_trade_alerts(self) -> None:
        self._market_repository.cleanup_alerts()
        self._user_repository.cleanup_alert_history()

        opportunities = self.get_trade_opportunities(self._default_filters)
        for trade in opportunities:
            if self._market_repository.has_sent_alert(trade["alert_key"]):
                continue
            self._alert_service.send_trade_alert(trade)
            self._market_repository.mark_alert_sent(trade["alert_key"])

        all_filters = self._user_repository.list_all_filters()
        for filter_record in all_filters:
            user = self._user_repository.get_user_by_id(filter_record["user_id"])
            if not user or not user.get("telegram_verified") or not user.get("telegram_chat_id"):
                continue

            filter_values = self._filter_record_to_trade_filters(filter_record)
            user_opportunities = self.get_trade_opportunities(filter_values)
            active_keys = set()
            existing_deliveries = self._user_repository.list_alert_deliveries(
                user_id=user["id"],
                filter_id=filter_record["id"],
            )
            active_group_owners = self._build_active_route_group_owners(
                existing_deliveries
            )
            for trade in user_opportunities:
                user_alert_key = trade.get("user_alert_key", trade["alert_key"])
                route_group_keys = self._build_route_group_keys(trade)
                existing_delivery = self._find_exact_alert_delivery(
                    deliveries=existing_deliveries,
                    alert_key=user_alert_key,
                )
                delivery_alert_key = (existing_delivery or {}).get("alert_key", user_alert_key)

                if delivery_alert_key in active_keys:
                    continue

                if not filter_record.get("is_enabled") and not (
                    (existing_delivery or {}).get("status", "active") == "active"
                    and (existing_delivery or {}).get("message_id") is not None
                ):
                    continue

                if self._has_conflicting_group_owner(active_group_owners, route_group_keys, delivery_alert_key):
                    continue

                active_keys.add(delivery_alert_key)

                alert_result = self._alert_service.send_trade_alert_to_chat(
                    chat_id=str(user["telegram_chat_id"]),
                    trade=trade,
                    filter_name=filter_record["name"],
                    existing_message_id=(
                        (existing_delivery or {}).get("message_id")
                        if (existing_delivery or {}).get("status", "active") == "active"
                        else None
                    ),
                    status_label=(
                        "♻️ Trade Still Active"
                        if (existing_delivery or {}).get("status", "active") == "active"
                        and (existing_delivery or {}).get("message_id") is not None
                        else None
                    ),
                    timezone_name=user.get("timezone", "UTC"),
                )
                self._assign_route_group_owners(active_group_owners, route_group_keys, delivery_alert_key)
                self._user_repository.upsert_alert_delivery(
                    user_id=user["id"],
                    filter_id=filter_record["id"],
                    alert_key=delivery_alert_key,
                    message_id=alert_result.get("message_id"),
                    payload_hash=alert_result.get("payload_hash", ""),
                    status="active",
                    terminal_reason=None,
                    trade_snapshot=self._build_trade_snapshot(trade),
                )

            self._lock_stale_trade_alerts(
                user=user,
                filter_record=filter_record,
                active_alert_keys=active_keys,
            )

    def process_filter_alerts(self, filter_record: dict, user: dict | None = None) -> int:
        user = user or self._user_repository.get_user_by_id(filter_record["user_id"])
        if not user or not user.get("telegram_verified") or not user.get("telegram_chat_id"):
            return 0

        filter_values = self._filter_record_to_trade_filters(filter_record)
        user_opportunities = self.get_trade_opportunities(filter_values)
        delivered_count = 0
        existing_deliveries = self._user_repository.list_alert_deliveries(
            user_id=user["id"],
            filter_id=filter_record["id"],
        )
        active_group_owners = self._build_active_route_group_owners(
            existing_deliveries
        )
        processed_alert_keys = set()
        for trade in user_opportunities:
            user_alert_key = trade.get("user_alert_key", trade["alert_key"])
            route_group_keys = self._build_route_group_keys(trade)
            existing_delivery = self._find_exact_alert_delivery(
                deliveries=existing_deliveries,
                alert_key=user_alert_key,
            )
            delivery_alert_key = (existing_delivery or {}).get("alert_key", user_alert_key)

            if delivery_alert_key in processed_alert_keys:
                continue

            if not filter_record.get("is_enabled") and not (
                (existing_delivery or {}).get("status", "active") == "active"
                and (existing_delivery or {}).get("message_id") is not None
            ):
                continue

            if self._has_conflicting_group_owner(active_group_owners, route_group_keys, delivery_alert_key):
                continue

            alert_result = self._alert_service.send_trade_alert_to_chat(
                chat_id=str(user["telegram_chat_id"]),
                trade=trade,
                filter_name=filter_record["name"],
                existing_message_id=(
                    (existing_delivery or {}).get("message_id")
                    if (existing_delivery or {}).get("status", "active") == "active"
                    else None
                ),
                status_label=(
                    "♻️ Trade Still Active"
                    if (existing_delivery or {}).get("status", "active") == "active"
                    and (existing_delivery or {}).get("message_id") is not None
                    else None
                ),
                timezone_name=user.get("timezone", "UTC"),
            )
            self._user_repository.upsert_alert_delivery(
                user_id=user["id"],
                filter_id=filter_record["id"],
                alert_key=delivery_alert_key,
                message_id=alert_result.get("message_id"),
                payload_hash=alert_result.get("payload_hash", ""),
                status="active",
                terminal_reason=None,
                trade_snapshot=self._build_trade_snapshot(trade),
            )
            self._assign_route_group_owners(active_group_owners, route_group_keys, delivery_alert_key)
            processed_alert_keys.add(delivery_alert_key)
            delivered_count += 1
        return delivered_count

    def get_trade_opportunities(self, filters: dict) -> list[dict]:
        markets = self._market_repository.get_markets_snapshot()
        results = []
        seen_keys = set()
        station_context_cache = {}
        route_distance_cache = {}
        origin_distance_cache = {}
        required_pad_size = filters["landing_pad_size"]
        max_station_distance_ls = filters["max_station_distance_ls"]
        max_origin_distance_ly = filters["max_origin_distance_ly"]
        max_route_distance_ly = filters["max_route_distance_ly"]
        profit_min = filters["profit_min"]
        supply_min = filters["supply_min"]
        demand_min = filters["demand_min"]
        origin_system = filters["distance_origin_system"]
        fleet_carrier_mode = filters["fleet_carrier_mode"]
        exclude_buy_fleet_carriers = filters["exclude_buy_fleet_carriers"]
        surface_station_mode = filters["surface_station_mode"]

        for commodity_name, entries in markets.items():
            source_entries = [
                entry for entry in entries
                if entry["buy"] > 0 and entry["stock"] >= supply_min
            ]
            destination_entries = [
                entry for entry in entries
                if entry["sell"] > 0 and entry["demand"] >= demand_min
            ]
            if not source_entries or not destination_entries:
                continue

            max_sell_price = max(destination_entry["sell"] for destination_entry in destination_entries)

            for source_entry in source_entries:
                if source_entry["buy"] + profit_min > max_sell_price:
                    continue

                origin_distance_key = source_entry["system"].lower()
                if origin_distance_key not in origin_distance_cache:
                    origin_distance_cache[origin_distance_key] = self._station_service.calc_distance_ly(
                        origin_system,
                        source_entry["system"],
                    )
                distance_from_origin_ly = origin_distance_cache[origin_distance_key]
                if distance_from_origin_ly is None or distance_from_origin_ly > max_origin_distance_ly:
                    continue

                source_context = self._get_station_context(source_entry, station_context_cache)
                if source_context["skip_buy_always"]:
                    continue
                if exclude_buy_fleet_carriers and source_context["is_fleet_carrier"]:
                    continue
                if surface_station_mode == "exclude" and source_context["is_surface_station"]:
                    continue
                if source_context["distance_ls"] is not None and source_context["distance_ls"] > max_station_distance_ls:
                    continue
                if not self._station_service.supports_pad_size(source_context["pad_size"], required_pad_size):
                    continue

                min_sell_price = source_entry["buy"] + profit_min
                for destination_entry in destination_entries:
                    if self._is_same_market(source_entry, destination_entry):
                        continue
                    if destination_entry["sell"] < min_sell_price:
                        continue

                    destination_context = self._get_station_context(destination_entry, station_context_cache)
                    if destination_context["skip_sell"]:
                        continue
                    if surface_station_mode == "exclude" and destination_context["is_surface_station"]:
                        continue
                    if destination_context["distance_ls"] is not None and destination_context["distance_ls"] > max_station_distance_ls:
                        continue
                    if not self._station_service.supports_pad_size(destination_context["pad_size"], required_pad_size):
                        continue

                    distance_cache_key = (
                        source_entry["system"].lower(),
                        destination_entry["system"].lower(),
                    )
                    if distance_cache_key not in route_distance_cache:
                        route_distance_cache[distance_cache_key] = self._station_service.calc_distance_ly(
                            source_entry["system"],
                            destination_entry["system"],
                        )
                    distance_ly = route_distance_cache[distance_cache_key]
                    if distance_ly is None:
                        continue
                    if distance_ly > max_route_distance_ly:
                        continue
                    if not self._matches_trade_fleet_carrier_mode(
                        station_type=destination_context["station_type"],
                        fleet_carrier_mode=fleet_carrier_mode,
                    ):
                        continue

                    opportunity = self._build_trade_opportunity(
                        commodity_name=commodity_name,
                        source_entry=source_entry,
                        destination_entry=destination_entry,
                        distance_ly=distance_ly,
                        buy_station=source_context["station"],
                        sell_station=destination_context["station"],
                        buy_station_type=source_context["station_type"],
                        sell_station_type=destination_context["station_type"],
                        exclude_buy_fleet_carriers=exclude_buy_fleet_carriers,
                        surface_station_mode=surface_station_mode,
                    )
                    if not opportunity:
                        continue
                    opportunity["distance_origin_system"] = origin_system
                    opportunity["distance_from_origin_ly"] = distance_from_origin_ly
                    if opportunity["trade_key"] in seen_keys:
                        continue

                    seen_keys.add(opportunity["trade_key"])
                    results.append(opportunity)

        results.sort(
            key=lambda item: (
                -item["profit_per_ton"],
                item["distance_ly"],
                -item["demand"],
            )
        )
        return results[:100]

    def _get_station_context(self, entry: dict, cache: dict) -> dict:
        cache_key = (entry["system"], entry["station"])
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        station = self._station_service.get_station_data(entry["system"], entry["station"])
        station_type = station.get("type") or entry.get("stationType") or "Unknown"
        distance_ls = self._normalize_station_distance(station.get("distance"))
        context = {
            "station": station,
            "station_type": station_type,
            "pad_size": station.get("pad") or "Unknown",
            "distance_ls": distance_ls,
            "is_fleet_carrier": self._is_fleet_carrier_endpoint(
                station_name=entry["station"],
                station_type=station_type,
            ),
            "is_surface_station": self._is_surface_station_type(station_type),
            "skip_buy_always": False,
            "skip_sell": False,
        }
        cache[cache_key] = context
        return context

    def _lock_stale_trade_alerts(self, *, user: dict, filter_record: dict, active_alert_keys: set[str]) -> None:
        existing_deliveries = self._user_repository.list_alert_deliveries(
            user_id=user["id"],
            filter_id=filter_record["id"],
        )
        for delivery in existing_deliveries:
            if delivery["status"] != "active":
                continue
            if delivery["alert_key"] in active_alert_keys:
                continue

            trade_snapshot = delivery.get("trade_snapshot") or {}
            status_label, terminal_reason = self._determine_terminal_alert_state(trade_snapshot)
            if delivery.get("message_id") and trade_snapshot:
                alert_result = self._alert_service.send_trade_alert_to_chat(
                    chat_id=str(user["telegram_chat_id"]),
                    trade=trade_snapshot,
                    filter_name=filter_record["name"],
                    existing_message_id=delivery["message_id"],
                    status_label=status_label,
                    timezone_name=user.get("timezone", "UTC"),
                )
                message_id = alert_result.get("message_id") or delivery.get("message_id")
                payload_hash = alert_result.get("payload_hash", delivery.get("payload_hash", ""))
            else:
                message_id = delivery.get("message_id")
                payload_hash = delivery.get("payload_hash", "")

            self._user_repository.upsert_alert_delivery(
                user_id=user["id"],
                filter_id=filter_record["id"],
                alert_key=delivery["alert_key"],
                message_id=message_id,
                payload_hash=payload_hash,
                status="locked",
                terminal_reason=terminal_reason,
                trade_snapshot=trade_snapshot,
            )

    @staticmethod
    def _build_route_group_keys(trade: dict) -> list[str]:
        keys = []
        commodity = str(trade.get("commodity") or "")
        buy_endpoint_identity = str(trade.get("buy_endpoint_identity") or "")
        sell_endpoint_identity = str(trade.get("sell_endpoint_identity") or "")
        if commodity and buy_endpoint_identity:
            keys.append("|".join([commodity, "buy", buy_endpoint_identity]))
        if commodity and sell_endpoint_identity:
            keys.append("|".join([commodity, "sell", sell_endpoint_identity]))
        return keys

    def _build_active_route_group_owners(self, deliveries: list[dict]) -> dict[str, str]:
        owners = {}
        for delivery in deliveries:
            if delivery.get("status") != "active":
                continue
            trade_snapshot = delivery.get("trade_snapshot") or {}
            for route_group_key in self._build_route_group_keys(trade_snapshot):
                if not route_group_key.strip("|"):
                    continue
                owners.setdefault(route_group_key, delivery["alert_key"])
        return owners

    @staticmethod
    def _find_exact_alert_delivery(*, deliveries: list[dict], alert_key: str) -> dict | None:
        for delivery in deliveries:
            if delivery.get("alert_key") == alert_key:
                return delivery
        return None

    @staticmethod
    def _has_conflicting_group_owner(active_group_owners: dict[str, str], route_group_keys: list[str], delivery_alert_key: str) -> bool:
        for route_group_key in route_group_keys:
            group_owner_key = active_group_owners.get(route_group_key)
            if group_owner_key and group_owner_key != delivery_alert_key:
                return True
        return False

    @staticmethod
    def _assign_route_group_owners(active_group_owners: dict[str, str], route_group_keys: list[str], delivery_alert_key: str) -> None:
        for route_group_key in route_group_keys:
            active_group_owners[route_group_key] = delivery_alert_key

    def get_market_activity(self, filters: dict) -> list[dict]:
        markets = self._market_repository.get_markets_snapshot()
        rows = []

        for commodity_name, entries in markets.items():
            for entry in entries:
                station = self._station_service.get_station_data(entry["system"], entry["station"])
                station_type = station.get("type") or "Unknown"
                station_pad = station.get("pad") or "Unknown"
                station_distance_ls = self._normalize_station_distance(station.get("distance"))

                if station_distance_ls is not None and station_distance_ls > filters["max_station_distance_ls"]:
                    continue
                if not self._station_service.supports_pad_size(station_pad, filters["landing_pad_size"]):
                    continue

                rows.append(
                    {
                        "commodity": commodity_name,
                        "commodity_display": commodity_name.replace("-", " ").title(),
                        "station_name": self._station_service.prettify_station_name(entry["station"], station_type),
                        "raw_station_name": entry["station"],
                        "station_type": station_type,
                        "system": entry["system"],
                        "pad_size": station_pad,
                        "station_distance_ls": station_distance_ls,
                        "buy_price": entry["buy"],
                        "sell_price": entry["sell"],
                        "stock": entry["stock"],
                        "demand": entry["demand"],
                        "updated_at": entry["updated"].isoformat(),
                    }
                )

        rows.sort(
            key=lambda item: (
                item["commodity_display"],
                item["system"],
                item["station_name"],
            )
        )
        return rows[:250]

    def parse_station_browser_filters(self, params: dict) -> dict:
        filters = {
            "query": str(params.get("query", "")).strip(),
            "landing_pad_size": str(params.get("landing_pad_size", "Any")).title(),
            "fleet_carrier_mode": str(params.get("fleet_carrier_mode", "exclude")).lower(),
            "max_station_distance_ls": self._coerce_int(params.get("max_station_distance_ls"), 20000, minimum=0),
        }
        if filters["landing_pad_size"] not in {"Any", "Small", "Medium", "Large"}:
            filters["landing_pad_size"] = "Any"
        if filters["fleet_carrier_mode"] not in {"exclude", "only", "include"}:
            filters["fleet_carrier_mode"] = "exclude"
        return filters

    def parse_commodity_finder_filters(self, params: dict) -> dict:
        return {
            "commodity": str(params.get("commodity", "")).strip().lower(),
            "buy_origin_system": str(params.get("buy_origin_system", "Sol")).strip() or "Sol",
            "buy_max_distance_ly": self._coerce_float(params.get("buy_max_distance_ly"), 120, minimum=0),
            "buy_max_station_distance_ls": self._coerce_int(
                params.get("buy_max_station_distance_ls"),
                20000,
                minimum=0,
            ),
            "sell_origin_system": str(params.get("sell_origin_system", "Sol")).strip() or "Sol",
            "sell_max_distance_ly": self._coerce_float(params.get("sell_max_distance_ly"), 120, minimum=0),
            "sell_max_station_distance_ls": self._coerce_int(
                params.get("sell_max_station_distance_ls"),
                20000,
                minimum=0,
            ),
        }

    def parse_filters(self, params: dict) -> dict:
        filters = dict(self._default_filters)
        filters["profit_min"] = self._coerce_int(params.get("profit_min"), filters["profit_min"], minimum=0)
        filters["supply_min"] = self._coerce_int(params.get("supply_min"), filters["supply_min"], minimum=0)
        filters["demand_min"] = self._coerce_int(params.get("demand_min"), filters["demand_min"], minimum=0)
        filters["max_origin_distance_ly"] = self._coerce_float(
            params.get("max_origin_distance_ly"),
            filters["max_origin_distance_ly"],
            minimum=0,
        )
        filters["max_route_distance_ly"] = self._coerce_float(
            params.get("max_route_distance_ly"),
            filters["max_route_distance_ly"],
            minimum=0,
        )
        distance_origin_system = str(
            params.get("distance_origin_system", filters.get("distance_origin_system", "Sol"))
        ).strip()
        filters["distance_origin_system"] = distance_origin_system or "Sol"
        filters["max_station_distance_ls"] = self._coerce_int(
            params.get("max_station_distance_ls"),
            filters["max_station_distance_ls"],
            minimum=0,
        )

        landing_pad_size = str(params.get("landing_pad_size", filters["landing_pad_size"])).title()
        if landing_pad_size not in {"Any", "Small", "Medium", "Large"}:
            landing_pad_size = filters["landing_pad_size"]
        filters["landing_pad_size"] = landing_pad_size
        filters["fleet_carrier_mode"] = str(
            params.get("fleet_carrier_mode", filters.get("fleet_carrier_mode", "include"))
        ).lower()
        if filters["fleet_carrier_mode"] not in {"exclude", "only", "include"}:
            filters["fleet_carrier_mode"] = "include"
        filters["exclude_buy_fleet_carriers"] = self._coerce_bool(
            params.get("exclude_buy_fleet_carriers"),
            filters.get("exclude_buy_fleet_carriers", True),
        )
        filters["surface_station_mode"] = str(
            params.get("surface_station_mode", filters.get("surface_station_mode", "include"))
        ).lower()
        if filters["surface_station_mode"] not in {"exclude", "include"}:
            filters["surface_station_mode"] = "include"
        return filters

    def _build_trade_opportunity(
        self,
        commodity_name: str,
        source_entry: dict,
        destination_entry: dict,
        *,
        distance_ly: float | None = None,
        buy_station: dict | None = None,
        sell_station: dict | None = None,
        buy_station_type: str | None = None,
        sell_station_type: str | None = None,
        exclude_buy_fleet_carriers: bool = True,
        surface_station_mode: str = "include",
    ) -> dict | None:
        buy_price = source_entry["buy"]
        sell_price = destination_entry["sell"]
        if buy_price <= 0 or sell_price <= 0:
            return None

        profit_per_ton = sell_price - buy_price
        if profit_per_ton <= 0:
            return None

        if distance_ly is None:
            distance_ly = self._station_service.calc_distance_ly(source_entry["system"], destination_entry["system"])
        if distance_ly is None:
            return None

        buy_station = buy_station or self._station_service.get_station_data(source_entry["system"], source_entry["station"])
        sell_station = sell_station or self._station_service.get_station_data(destination_entry["system"], destination_entry["station"])
        buy_station_type = buy_station_type or buy_station.get("type") or "Unknown"
        sell_station_type = sell_station_type or sell_station.get("type") or "Unknown"

        if exclude_buy_fleet_carriers and self._is_fleet_carrier_endpoint(
            station_name=source_entry["station"],
            station_type=buy_station_type,
        ):
            return None
        if surface_station_mode == "exclude" and (
            self._is_surface_station_type(buy_station_type)
            or self._is_surface_station_type(sell_station_type)
        ):
            return None

        updated_at = max(source_entry["updated"], destination_entry["updated"])
        buy_station_name = self._station_service.prettify_station_name(source_entry["station"], buy_station_type)
        sell_station_name = self._station_service.prettify_station_name(destination_entry["station"], sell_station_type)
        buy_station_distance_ls = self._normalize_station_distance(buy_station["distance"])
        sell_station_distance_ls = self._normalize_station_distance(sell_station["distance"])
        trade_key = "|".join(
            [
                commodity_name,
                source_entry["system"],
                source_entry["station"],
                destination_entry["system"],
                destination_entry["station"],
            ]
        )
        user_alert_key = "|".join(
            [
                commodity_name,
                self._build_endpoint_identity(destination_entry["system"], destination_entry["station"], sell_station_type),
            ]
        )

        return {
            "trade_key": trade_key,
            "alert_key": trade_key,
            "user_alert_key": user_alert_key,
            "buy_endpoint_identity": self._build_endpoint_identity(
                source_entry["system"],
                source_entry["station"],
                buy_station_type,
            ),
            "sell_endpoint_identity": self._build_endpoint_identity(
                destination_entry["system"],
                destination_entry["station"],
                sell_station_type,
            ),
            "commodity": commodity_name,
            "commodity_display": commodity_name.replace("-", " ").title(),
            "buy_station_name": buy_station_name,
            "buy_raw_station_name": source_entry["station"],
            "buy_station_type": buy_station_type,
            "buy_system": source_entry["system"],
            "buy_pad_size": buy_station.get("pad") or "Unknown",
            "buy_station_distance_ls": buy_station_distance_ls,
            "buy_price": buy_price,
            "supply": source_entry["stock"],
            "buy_updated_at": source_entry["updated"].isoformat(),
            "sell_station_name": sell_station_name,
            "sell_raw_station_name": destination_entry["station"],
            "sell_station_type": sell_station_type,
            "sell_system": destination_entry["system"],
            "sell_pad_size": sell_station.get("pad") or "Unknown",
            "sell_station_distance_ls": sell_station_distance_ls,
            "sell_price": sell_price,
            "demand": destination_entry["demand"],
            "sell_updated_at": destination_entry["updated"].isoformat(),
            "profit_per_ton": profit_per_ton,
            "distance_ly": distance_ly,
            "updated_at": updated_at.isoformat(),
        }

    def _matches_filters(self, opportunity: dict, filters: dict) -> bool:
        if opportunity["profit_per_ton"] < filters["profit_min"]:
            return False
        if opportunity["supply"] < filters["supply_min"]:
            return False
        if opportunity["demand"] < filters["demand_min"]:
            return False
        if opportunity["distance_from_origin_ly"] > filters["max_origin_distance_ly"]:
            return False
        if opportunity["distance_ly"] > filters["max_route_distance_ly"]:
            return False
        if opportunity["buy_station_distance_ls"] is not None and opportunity["buy_station_distance_ls"] > filters["max_station_distance_ls"]:
            return False
        if opportunity["sell_station_distance_ls"] is not None and opportunity["sell_station_distance_ls"] > filters["max_station_distance_ls"]:
            return False
        required_pad = filters["landing_pad_size"]
        if not self._station_service.supports_pad_size(opportunity["buy_pad_size"], required_pad):
            return False
        if not self._station_service.supports_pad_size(opportunity["sell_pad_size"], required_pad):
            return False
        return True

    def _matches_station_browser_filters(
        self,
        *,
        station_type: str,
        pad_size: str,
        arrival_distance_ls: int | None,
        system_name: str,
        station_name: str,
        filters: dict,
    ) -> bool:
        station_type_normalized = station_type.lower()
        is_fleet_carrier = "fleet carrier" in station_type_normalized
        carrier_mode = filters["fleet_carrier_mode"]

        if carrier_mode == "exclude" and is_fleet_carrier:
            return False
        if carrier_mode == "only" and not is_fleet_carrier:
            return False
        if filters["landing_pad_size"] != "Any" and not self._station_service.supports_pad_size(pad_size, filters["landing_pad_size"]):
            return False
        if arrival_distance_ls is not None and arrival_distance_ls > filters["max_station_distance_ls"]:
            return False

        query = filters["query"].lower()
        if query and query not in system_name.lower() and query not in station_name.lower():
            return False
        return True

    @staticmethod
    def _matches_commodity_station_filters(
        *,
        price: int,
        quantity: int,
        distance_ly: float | None,
        arrival_distance_ls: int | None,
        max_distance_ly: float,
        max_station_distance_ls: int,
    ) -> bool:
        if price <= 0 or quantity <= 0:
            return False
        if distance_ly is None or distance_ly > max_distance_ly:
            return False
        if arrival_distance_ls is not None and arrival_distance_ls > max_station_distance_ls:
            return False
        return True

    @staticmethod
    def _matches_trade_fleet_carrier_mode(*, station_type: str, fleet_carrier_mode: str) -> bool:
        station_type_normalized = station_type.lower()
        is_fleet_carrier = "fleet carrier" in station_type_normalized
        if fleet_carrier_mode == "exclude" and is_fleet_carrier:
            return False
        if fleet_carrier_mode == "only" and not is_fleet_carrier:
            return False
        return True

    @staticmethod
    def _filter_record_to_trade_filters(filter_record: dict) -> dict:
        return {
            "profit_min": filter_record["profit_min"],
            "supply_min": filter_record["supply_min"],
            "demand_min": filter_record["demand_min"],
            "max_origin_distance_ly": filter_record["max_origin_distance_ly"],
            "max_route_distance_ly": filter_record["max_route_distance_ly"],
            "distance_origin_system": filter_record.get("distance_origin_system") or "Sol",
            "max_station_distance_ls": filter_record["max_station_distance_ls"],
            "landing_pad_size": filter_record["landing_pad_size"],
            "fleet_carrier_mode": filter_record.get("fleet_carrier_mode") or "include",
            "exclude_buy_fleet_carriers": filter_record.get("exclude_buy_fleet_carriers", True),
            "surface_station_mode": filter_record.get("surface_station_mode") or "include",
        }

    def _is_fleet_carrier_endpoint(self, *, station_name: str, station_type: str) -> bool:
        return (
            "fleet carrier" in (station_type or "").lower()
            or self._station_service.extract_carrier_callsign(station_name) is not None
        )

    @staticmethod
    def _is_surface_station_type(station_type: str) -> bool:
        station_type_normalized = (station_type or "").lower()
        return any(
            surface_type in station_type_normalized
            for surface_type in (
                "planetary port",
                "planetary outpost",
                "planetary base",
                "surface port",
                "surface settlement",
                "odyssey settlement",
            )
        )

    @staticmethod
    def _sort_station_commodities(rows: list[dict], sort_by: str, sort_order: str) -> list[dict]:
        key_map = {
            "commodity": lambda item: item["commodity_display"],
            "buy": lambda item: item["buy_price"],
            "sell": lambda item: item["sell_price"],
            "supply": lambda item: item["stock"],
            "demand": lambda item: item["demand"],
            "updated": lambda item: item["updated_at"],
        }
        key_func = key_map.get(sort_by, key_map["commodity"])
        return sorted(rows, key=key_func, reverse=(sort_order == "desc"))

    def _decorate_history_rows(self, rows: list[dict]) -> list[dict]:
        decorated = []
        for row in rows:
            decorated.append(
                {
                    "commodity": row["commodity"],
                    "commodity_display": row["commodity"].replace("-", " ").title(),
                    "station": row["station"],
                    "system": row["system"],
                    "buy_price": row["buy"],
                    "sell_price": row["sell"],
                    "stock": row["stock"],
                    "demand": row["demand"],
                    "updated_at": row["updated"],
                }
            )
        return decorated

    def _build_endpoint_identity(self, system_name: str, station_name: str, station_type: str) -> str:
        if self._is_fleet_carrier_endpoint(station_name=station_name, station_type=station_type):
            callsign = self._station_service.extract_carrier_callsign(station_name)
            if callsign:
                return f"fc:{callsign}"
        return f"st:{system_name}|{station_name}"

    def _build_trade_snapshot(self, trade: dict) -> dict:
        snapshot_keys = [
            "commodity",
            "commodity_display",
            "buy_station_name",
            "buy_raw_station_name",
            "buy_station_type",
            "buy_system",
            "buy_pad_size",
            "buy_station_distance_ls",
            "buy_price",
            "supply",
            "buy_updated_at",
            "sell_station_name",
            "sell_raw_station_name",
            "sell_station_type",
            "sell_system",
            "sell_pad_size",
            "sell_station_distance_ls",
            "sell_price",
            "demand",
            "sell_updated_at",
            "profit_per_ton",
            "distance_ly",
            "distance_origin_system",
            "distance_from_origin_ly",
            "updated_at",
            "buy_endpoint_identity",
            "sell_endpoint_identity",
        ]
        return {key: trade.get(key) for key in snapshot_keys}

    def _determine_terminal_alert_state(self, trade_snapshot: dict) -> tuple[str, str]:
        commodity_entries = self._market_repository.get_markets_snapshot().get(trade_snapshot.get("commodity"), [])
        buy_entry = self._find_exact_market_entry(
            commodity_entries,
            system_name=trade_snapshot.get("buy_system"),
            station_name=trade_snapshot.get("buy_raw_station_name"),
        )
        sell_entry = self._find_exact_market_entry(
            commodity_entries,
            system_name=trade_snapshot.get("sell_system"),
            station_name=trade_snapshot.get("sell_raw_station_name"),
        )

        if (buy_entry and buy_entry.get("stock", 0) <= 0) or (sell_entry and sell_entry.get("demand", 0) <= 0):
            return "✅ Trade Complete", "trade_complete"

        buy_endpoint_identity = trade_snapshot.get("buy_endpoint_identity") or ""
        sell_endpoint_identity = trade_snapshot.get("sell_endpoint_identity") or ""
        if (
            self._endpoint_has_moved(commodity_entries, buy_endpoint_identity, trade_snapshot.get("buy_system"))
            or self._endpoint_has_moved(commodity_entries, sell_endpoint_identity, trade_snapshot.get("sell_system"))
        ):
            return "❌ Fleet Carrier Moved", "fleet_carrier_moved"

        return "❌ Trade No Longer Available", "trade_unavailable"

    def _endpoint_has_moved(self, commodity_entries: list[dict], endpoint_identity: str, previous_system: str | None) -> bool:
        if not endpoint_identity.startswith("fc:"):
            return False
        for entry in commodity_entries:
            station_type = entry.get("stationType") or "Unknown"
            current_identity = self._build_endpoint_identity(entry["system"], entry["station"], station_type)
            if current_identity == endpoint_identity and entry["system"] != previous_system:
                return True
        return False

    @staticmethod
    def _find_exact_market_entry(commodity_entries: list[dict], *, system_name: str | None, station_name: str | None) -> dict | None:
        for entry in commodity_entries:
            if entry["system"] == system_name and entry["station"] == station_name:
                return entry
        return None

    @staticmethod
    def _is_same_market(source_entry: dict, destination_entry: dict) -> bool:
        return (
            source_entry["station"] == destination_entry["station"]
            and source_entry["system"] == destination_entry["system"]
        )

    @staticmethod
    def _normalize_station_distance(distance_value) -> int | None:
        if distance_value in (None, "", "N/A"):
            return None
        try:
            return int(float(distance_value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_int(value, default: int, minimum: int = 0) -> int:
        try:
            return max(int(value), minimum)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float(value, default: float, minimum: float = 0) -> float:
        try:
            return max(float(value), minimum)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_bool(value, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
