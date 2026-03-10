"""WNSM data fetch logic.

Uses the Smartmeter client synchronously wrapped in asyncio.to_thread()
so it doesn't block the event loop.
"""
import asyncio
import logging
from datetime import datetime, timedelta, date
from typing import Optional

import aiosqlite

from db import get_last_timestamp, has_any_data, upsert_consumption_records, log_fetch

_LOGGER = logging.getLogger(__name__)


async def fetch_consumption(db: aiosqlite.Connection, options: dict) -> int:
    """Fetch WNSM consumption data and persist it. Returns count of new records."""
    username = options["username"]
    password = options["password"]
    configured_zaehlpunkte = [z for z in (options.get("zaehlpunkte") or []) if z]
    history_days = int(options.get("history_days", 730))

    try:
        from wnsm_api.client import Smartmeter
        from wnsm_api.constants import ValueType

        smartmeter = Smartmeter(username, password)

        _LOGGER.info("Logging in to WNSM API as %s ...", username)
        await asyncio.to_thread(smartmeter.login)
        _LOGGER.info("Login successful")

        # Auto-discover zaehlpunkte if not explicitly configured
        if not configured_zaehlpunkte:
            _LOGGER.info("No zaehlpunkte configured — discovering from account ...")
            contracts = await asyncio.to_thread(smartmeter.zaehlpunkte)
            zaehlpunkte_list = []
            for contract in contracts:
                for zp in contract.get("zaehlpunkte", []):
                    zp_num = zp.get("zaehlpunktnummer")
                    if zp_num:
                        zaehlpunkte_list.append(zp_num)
            _LOGGER.info("Discovered %d zaehlpunkt(e): %s", len(zaehlpunkte_list), zaehlpunkte_list)
        else:
            zaehlpunkte_list = configured_zaehlpunkte
            _LOGGER.info("Using configured zaehlpunkte: %s", zaehlpunkte_list)

        if not zaehlpunkte_list:
            msg = "No zaehlpunkte found — check your account or configuration."
            _LOGGER.warning(msg)
            await log_fetch(db, "error", msg, 0)
            return 0

        total_added = 0
        for zp in zaehlpunkte_list:
            added = await _fetch_zaehlpunkt(
                db, smartmeter, zp, history_days, ValueType
            )
            total_added += added

        summary = f"Fetched {total_added} new records for {len(zaehlpunkte_list)} zaehlpunkt(e)"
        _LOGGER.info(summary)
        await log_fetch(db, "ok", summary, total_added)
        return total_added

    except Exception as exc:
        msg = f"Fetch failed: {exc}"
        _LOGGER.exception(msg)
        await log_fetch(db, "error", msg, 0)
        raise


async def _fetch_zaehlpunkt(
    db: aiosqlite.Connection,
    smartmeter,
    zp: str,
    history_days: int,
    ValueType,
) -> int:
    """Fetch data for a single zaehlpunkt and store it. Returns new record count."""
    today = date.today()

    last_ts_str = await get_last_timestamp(db, zp)
    if last_ts_str:
        # Incremental: continue from the day after the last stored interval
        try:
            # Normalize ISO string — strip trailing Z or offset for date parsing
            ts_clean = last_ts_str.replace("Z", "+00:00")
            last_dt = datetime.fromisoformat(ts_clean)
            date_from = (last_dt + timedelta(days=1)).date()
        except (ValueError, TypeError):
            _LOGGER.warning("Could not parse last timestamp '%s', using 7-day fallback", last_ts_str)
            date_from = today - timedelta(days=7)
        _LOGGER.info("[%s] Incremental fetch from %s", zp, date_from)
    else:
        # Initial full history load
        date_from = today - timedelta(days=history_days)
        _LOGGER.info("[%s] Initial fetch: %d days of history from %s", zp, history_days, date_from)

    # WNSM only publishes yesterday's data at best, so stop at today (exclusive)
    date_until = today

    if date_from >= date_until:
        _LOGGER.info("[%s] Already up to date (last fetch was today)", zp)
        return 0

    _LOGGER.info("[%s] Querying bewegungsdaten %s → %s", zp, date_from, date_until)
    raw = await asyncio.to_thread(
        smartmeter.bewegungsdaten,
        zp,
        date_from,
        date_until,
        ValueType.QUARTER_HOUR,
    )

    descriptor = raw.get("descriptor", {})
    unit = descriptor.get("einheit", "WH").upper()
    factor = 1e-3 if unit == "WH" else 1.0

    values = raw.get("values", [])
    if not values:
        _LOGGER.info("[%s] No values returned for %s → %s", zp, date_from, date_until)
        return 0

    records = []
    skipped = 0
    for v in values:
        ts_str = v.get("zeitpunktVon")
        wert = v.get("wert")

        if ts_str is None or wert is None:
            skipped += 1
            continue

        kwh = float(wert) * factor

        try:
            ts_start = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            # Fallback: parse without timezone
            ts_start = datetime.fromisoformat(ts_str[:19])

        ts_end = ts_start + timedelta(minutes=15)

        records.append(
            {
                "zaehlpunkt": zp,
                "interval_start": ts_start.isoformat(),
                "interval_end": ts_end.isoformat(),
                "kwh": kwh,
                "estimated": 1 if v.get("geschaetzt", False) else 0,
            }
        )

    if skipped:
        _LOGGER.debug("[%s] Skipped %d null/incomplete values from API", zp, skipped)

    added = await upsert_consumption_records(db, records)
    _LOGGER.info(
        "[%s] Stored %d new records (out of %d fetched, %d already existed)",
        zp,
        added,
        len(records),
        len(records) - added,
    )
    return added
