"""Daily async scheduler for WNSM data fetching."""
import asyncio
import logging
from datetime import datetime, timedelta

import aiosqlite

from db import has_any_data
from fetcher import fetch_consumption
from ha_statistics import push_statistics

_LOGGER = logging.getLogger(__name__)

# Global lock so that only one fetch runs at a time
_fetch_lock = asyncio.Lock()


class Scheduler:
    def __init__(self, db: aiosqlite.Connection, options: dict):
        self.db = db
        self.options = options
        self.update_hour = int(options.get("update_hour", 4))
        self._is_fetching = False

    @property
    def is_fetching(self) -> bool:
        return self._is_fetching

    async def maybe_initial_fetch(self):
        """Trigger an initial history fetch if the database is empty.

        If data already exists, skip the fetch but still push statistics to HA
        so that historical data is visible in the Energy Dashboard immediately.
        """
        if not await has_any_data(self.db):
            _LOGGER.info("Database is empty — triggering initial history fetch ...")
            await self.trigger_fetch()  # trigger_fetch also calls push_statistics
        else:
            _LOGGER.info("Database already contains data, skipping initial fetch.")
            _LOGGER.info("Pushing existing data as HA statistics ...")
            try:
                await push_statistics(self.db, self.options)
            except Exception as exc:
                _LOGGER.error("Statistics push on startup failed: %s", exc)

    async def trigger_fetch(self) -> dict:
        """Trigger a data fetch immediately (thread-safe). Returns a status dict."""
        if _fetch_lock.locked():
            _LOGGER.info("Fetch already in progress, skipping duplicate trigger.")
            return {"status": "already_running"}

        async with _fetch_lock:
            self._is_fetching = True
            try:
                count = await fetch_consumption(self.db, self.options)
                fetch_result = {"status": "ok", "records_added": count}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}
            finally:
                self._is_fetching = False

        # Push updated statistics after a successful fetch (non-critical)
        try:
            await push_statistics(self.db, self.options)
        except Exception as exc:
            _LOGGER.error("Statistics push after fetch failed: %s", exc)

        return fetch_result

    async def run(self):
        """Scheduler loop: fires once daily at the configured update_hour."""
        _LOGGER.info(
            "Scheduler started — daily fetch will run at %02d:00", self.update_hour
        )
        while True:
            now = datetime.now()
            next_run = now.replace(
                hour=self.update_hour,
                minute=0,
                second=0,
                microsecond=0,
            )
            # If the scheduled time has already passed today, roll forward to tomorrow
            if next_run <= now:
                next_run += timedelta(days=1)

            wait_seconds = (next_run - now).total_seconds()
            _LOGGER.info(
                "Next scheduled fetch at %s (in %.0f minutes)",
                next_run.strftime("%Y-%m-%d %H:%M"),
                wait_seconds / 60,
            )

            await asyncio.sleep(wait_seconds)

            _LOGGER.info("Scheduled daily fetch triggered")
            await self.trigger_fetch()
