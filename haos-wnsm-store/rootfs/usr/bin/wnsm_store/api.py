"""aiohttp REST API for the WNSM Data Store addon."""
import asyncio
import logging

from aiohttp import web

from db import (
    get_consumption_day,
    get_consumption_history,
    get_cumulative_kwh,
    get_last_fetch,
    get_latest_record,
    get_zaehlpunkte_list,
)
from ha_statistics import push_statistics

_LOGGER = logging.getLogger(__name__)

VERSION = "1.0.0"


def create_app(db, scheduler, options: dict) -> web.Application:
    app = web.Application()
    app["db"] = db
    app["scheduler"] = scheduler
    app["options"] = options

    app.router.add_get("/health", health_handler)
    app.router.add_get("/consumption/current", consumption_current_handler)
    app.router.add_get("/consumption/history", consumption_history_handler)
    app.router.add_get("/consumption/latest", consumption_latest_handler)
    app.router.add_get("/consumption/day", consumption_day_handler)
    app.router.add_get("/zaehlpunkte", zaehlpunkte_handler)
    app.router.add_post("/fetch/trigger", fetch_trigger_handler)
    app.router.add_get("/fetch/status", fetch_status_handler)
    app.router.add_post("/statistics/push", statistics_push_handler)

    return app


async def health_handler(request: web.Request) -> web.Response:
    db = request.app["db"]
    last_fetch = await get_last_fetch(db)
    return web.json_response(
        {
            "status": "ok",
            "version": VERSION,
            "last_fetch": last_fetch,
        }
    )


async def consumption_current_handler(request: web.Request) -> web.Response:
    """Return the cumulative kWh sum — use this for a total_increasing HA sensor."""
    db = request.app["db"]
    zaehlpunkt = request.query.get("zaehlpunkt") or None

    total_kwh = await get_cumulative_kwh(db, zaehlpunkt)
    latest = await get_latest_record(db, zaehlpunkt)

    return web.json_response(
        {
            "kwh": round(total_kwh, 6),
            "unit": "kWh",
            "zaehlpunkt": zaehlpunkt,
            "updated_at": latest["interval_end"] if latest else None,
        }
    )


async def consumption_history_handler(request: web.Request) -> web.Response:
    """Return 15-min records in a time window.

    Query params:
      from       ISO8601 start (inclusive), e.g. 2024-01-15T00:00:00
      to         ISO8601 end   (inclusive), e.g. 2024-01-15T23:45:00
      zaehlpunkt Filter by meter point ID
    """
    db = request.app["db"]
    from_ts = request.query.get("from") or None
    to_ts = request.query.get("to") or None
    zaehlpunkt = request.query.get("zaehlpunkt") or None

    records = await get_consumption_history(
        db, from_ts=from_ts, to_ts=to_ts, zaehlpunkt=zaehlpunkt
    )
    return web.json_response({"count": len(records), "records": records})


async def consumption_latest_handler(request: web.Request) -> web.Response:
    """Return the most recent 15-min record."""
    db = request.app["db"]
    zaehlpunkt = request.query.get("zaehlpunkt") or None
    record = await get_latest_record(db, zaehlpunkt)
    if record is None:
        return web.json_response({"error": "No data available yet"}, status=404)
    return web.json_response(record)


async def consumption_day_handler(request: web.Request) -> web.Response:
    """Return all 15-min records for a given date.

    Query params:
      date       YYYY-MM-DD (required)
      zaehlpunkt Filter by meter point ID
    """
    db = request.app["db"]
    date_str = request.query.get("date")
    zaehlpunkt = request.query.get("zaehlpunkt") or None

    if not date_str:
        return web.json_response(
            {"error": "Missing required query parameter: date (YYYY-MM-DD)"},
            status=400,
        )

    records = await get_consumption_day(db, date_str, zaehlpunkt)
    return web.json_response(
        {"date": date_str, "count": len(records), "records": records}
    )


async def zaehlpunkte_handler(request: web.Request) -> web.Response:
    """Return all zaehlpunkt IDs that have stored data."""
    db = request.app["db"]
    zp_list = await get_zaehlpunkte_list(db)
    return web.json_response({"zaehlpunkte": zp_list})


async def fetch_trigger_handler(request: web.Request) -> web.Response:
    """Manually trigger a WNSM data fetch (fire and forget)."""
    scheduler = request.app["scheduler"]
    if scheduler.is_fetching:
        return web.json_response({"status": "already_running"}, status=409)

    asyncio.create_task(scheduler.trigger_fetch())
    return web.json_response({"status": "triggered"})


async def fetch_status_handler(request: web.Request) -> web.Response:
    """Return the result of the last fetch attempt."""
    db = request.app["db"]
    last = await get_last_fetch(db)
    if last is None:
        return web.json_response({"status": "never_fetched"})
    return web.json_response(last)


async def statistics_push_handler(request: web.Request) -> web.Response:
    """Manually push all historical data as HA long-term statistics.

    Connects to the HA WebSocket API and calls recorder/import_statistics for
    each zaehlpunkt. Useful for backfilling after first install or to force a
    refresh of the Energy Dashboard data.

    Returns: {status, results: {zaehlpunkt -> hours_pushed}}
    """
    db = request.app["db"]
    options = request.app["options"]
    results = await push_statistics(db, options)
    total_hours = sum(results.values())
    return web.json_response(
        {
            "status": "ok",
            "zaehlpunkte_count": len(results),
            "total_hours_pushed": total_hours,
            "results": results,
        }
    )
