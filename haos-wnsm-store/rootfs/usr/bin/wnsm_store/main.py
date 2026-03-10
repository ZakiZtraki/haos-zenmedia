#!/usr/bin/env python3
"""WNSM Data Store — main entry point.

Reads /data/options.json (written by HA Supervisor), initialises the SQLite
database, starts the daily scheduler and launches the aiohttp REST API.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from aiohttp import web

# Ensure the wnsm_store package directory is on the path so sibling modules
# (db, fetcher, scheduler, api, wnsm_api.*) are importable when the script
# is launched directly via `python3 /usr/bin/wnsm_store/main.py`.
sys.path.insert(0, str(Path(__file__).parent))

from api import create_app
from db import init_db
from scheduler import Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stdout,
)
_LOGGER = logging.getLogger(__name__)

OPTIONS_PATH = Path("/data/options.json")
DB_PATH = Path("/data/wnsm.db")


def load_options() -> dict:
    """Load addon options written by the HA Supervisor."""
    with open(OPTIONS_PATH) as fh:
        return json.load(fh)


async def main():
    _LOGGER.info("=== WNSM Data Store starting ===")

    options = load_options()
    _LOGGER.info(
        "Config: update_hour=%s  history_days=%s  api_port=%s",
        options.get("update_hour", 4),
        options.get("history_days", 730),
        options.get("api_port", 8099),
    )

    # Initialise SQLite database
    db = await init_db(str(DB_PATH))

    # Create scheduler
    scheduler = Scheduler(db=db, options=options)

    # Build aiohttp app
    app = create_app(db=db, scheduler=scheduler, options=options)

    port = int(options.get("api_port", 8099))

    # Start the daily scheduler loop in the background
    asyncio.create_task(scheduler.run())

    # Trigger initial history fetch if the DB is empty (runs in background)
    asyncio.create_task(scheduler.maybe_initial_fetch())

    # Start HTTP server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    _LOGGER.info("REST API listening on 0.0.0.0:%d", port)

    # Block forever (s6-overlay will restart if we exit)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
