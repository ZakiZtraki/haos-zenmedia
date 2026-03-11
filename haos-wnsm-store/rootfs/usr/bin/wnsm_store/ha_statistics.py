"""Push hourly-aggregated WNSM consumption into HA's long-term statistics.

Uses the HA WebSocket API (recorder/import_statistics) via the Supervisor
network proxy. Requires homeassistant_api: true in config.yaml so that the
SUPERVISOR_TOKEN environment variable is injected and the supervisor network
route is available.

Statistics are stored as external statistics with IDs:
    wnsm_store:<zaehlpunktnummer>

These can be added directly to the Energy Dashboard under
Settings → Energy → Electricity grid → Add consumption →
"Use an existing statistic" → search for "wnsm_store:".
"""
import logging
import os

import aiohttp
import aiosqlite

from db import get_hourly_aggregated, get_zaehlpunkte_list

_LOGGER = logging.getLogger(__name__)

HA_WS_URL = "ws://supervisor/core/api/websocket"


async def push_statistics(db: aiosqlite.Connection, options: dict) -> dict:
    """Push all hourly-aggregated consumption data to HA's statistics database.

    Connects to the HA WebSocket API via the Supervisor proxy, authenticates
    with SUPERVISOR_TOKEN, and calls recorder/import_statistics for each
    zaehlpunkt found in the local SQLite database.

    Returns a dict mapping zaehlpunkt → number of hours pushed (0 on failure).
    """
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        _LOGGER.warning(
            "[statistics] SUPERVISOR_TOKEN not set — skipping statistics push. "
            "Make sure homeassistant_api: true is set in config.yaml."
        )
        return {}

    zaehlpunkte = await get_zaehlpunkte_list(db)
    if not zaehlpunkte:
        _LOGGER.info("[statistics] No zaehlpunkte in DB yet — skipping statistics push")
        return {}

    results = {}
    try:
        async with aiohttp.ClientSession() as session:
            # Pass the SUPERVISOR_TOKEN as an HTTP Authorization header during the
            # WebSocket upgrade. The Supervisor proxy validates this and handles HA
            # auth internally — the first WS message received is auth_ok directly.
            # (SUPERVISOR_TOKEN is NOT a valid HA user token in modern Supervisor
            # versions; it must be validated at the HTTP/proxy level, not in the
            # WebSocket auth message.)
            async with session.ws_connect(
                HA_WS_URL,
                headers={"Authorization": f"Bearer {token}"},
            ) as ws:
                # --- Authentication handshake ---
                msg = await ws.receive_json()

                if msg.get("type") == "auth_required":
                    # Older Supervisor or direct HA connection: send token inline.
                    # This path is a fallback and may still fail with modern HA if
                    # the user hasn't configured a long-lived access token.
                    _LOGGER.debug("[statistics] Received auth_required, sending token")
                    await ws.send_json({"type": "auth", "access_token": token})
                    msg = await ws.receive_json()

                if msg.get("type") != "auth_ok":
                    _LOGGER.error(
                        "[statistics] HA WebSocket authentication failed: %s — "
                        "make sure the add-on was fully reinstalled (not just "
                        "restarted) after adding homeassistant_api: true to config.yaml.",
                        msg,
                    )
                    return {}

                _LOGGER.info("[statistics] Authenticated with HA WebSocket API")

                # --- Push one statistic series per zaehlpunkt ---
                msg_id = 1
                for zp in zaehlpunkte:
                    hourly = await get_hourly_aggregated(db, zp)
                    if not hourly:
                        _LOGGER.info("[statistics] No hourly data for %s", zp)
                        results[zp] = 0
                        continue

                    stats_payload = [
                        {
                            "start": entry["hour_start"],
                            "state": entry["kwh"],
                            "sum": entry["cumsum"],
                        }
                        for entry in hourly
                    ]

                    await ws.send_json(
                        {
                            "id": msg_id,
                            "type": "recorder/import_statistics",
                            "metadata": {
                                "has_mean": False,
                                "has_sum": True,
                                "name": f"WNSM {zp[-8:]}",
                                "source": "wnsm_store",
                                "statistic_id": f"wnsm_store:{zp}",
                                "unit_of_measurement": "kWh",
                            },
                            "stats": stats_payload,
                        }
                    )

                    result = await ws.receive_json()
                    if result.get("success"):
                        hours = len(stats_payload)
                        _LOGGER.info(
                            "[statistics] Pushed %d hours for %s", hours, zp
                        )
                        results[zp] = hours
                    else:
                        _LOGGER.error(
                            "[statistics] Failed to push stats for %s: %s", zp, result
                        )
                        results[zp] = 0

                    msg_id += 1

    except aiohttp.ClientConnectorError as exc:
        _LOGGER.error(
            "[statistics] Cannot connect to HA WebSocket API at %s: %s. "
            "Is homeassistant_api: true set in config.yaml?",
            HA_WS_URL,
            exc,
        )
    except Exception as exc:
        _LOGGER.exception("[statistics] Unexpected error pushing statistics: %s", exc)

    return results
