"""SQLite database operations for WNSM Data Store."""
import logging
from typing import Optional

import aiosqlite

_LOGGER = logging.getLogger(__name__)

# Module-level connection, set by init_db
_db: Optional[aiosqlite.Connection] = None


async def init_db(db_path: str) -> aiosqlite.Connection:
    """Initialize the SQLite database and create tables."""
    global _db
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript("""
        CREATE TABLE IF NOT EXISTS consumption (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            zaehlpunkt       TEXT    NOT NULL,
            interval_start   TEXT    NOT NULL,
            interval_end     TEXT    NOT NULL,
            kwh              REAL    NOT NULL,
            estimated        INTEGER DEFAULT 0,
            imported_at      TEXT    DEFAULT (datetime('now')),
            UNIQUE(zaehlpunkt, interval_start)
        );

        CREATE INDEX IF NOT EXISTS idx_consumption_zp_start
            ON consumption(zaehlpunkt, interval_start);

        CREATE TABLE IF NOT EXISTS fetch_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at    TEXT    DEFAULT (datetime('now')),
            status        TEXT,
            message       TEXT,
            records_added INTEGER DEFAULT 0
        );
    """)
    await _db.commit()
    _LOGGER.info("Database initialized at %s", db_path)
    return _db


async def get_db() -> aiosqlite.Connection:
    return _db


async def upsert_consumption_records(db: aiosqlite.Connection, records: list) -> int:
    """Insert records, ignoring duplicates. Returns count of newly inserted rows."""
    inserted = 0
    for r in records:
        cursor = await db.execute(
            """INSERT OR IGNORE INTO consumption
               (zaehlpunkt, interval_start, interval_end, kwh, estimated)
               VALUES (?, ?, ?, ?, ?)""",
            (
                r["zaehlpunkt"],
                r["interval_start"],
                r["interval_end"],
                r["kwh"],
                r.get("estimated", 0),
            ),
        )
        inserted += cursor.rowcount
    await db.commit()
    return inserted


async def log_fetch(db: aiosqlite.Connection, status: str, message: str, records_added: int = 0):
    await db.execute(
        "INSERT INTO fetch_log (status, message, records_added) VALUES (?, ?, ?)",
        (status, message, records_added),
    )
    await db.commit()


async def get_last_fetch(db: aiosqlite.Connection) -> Optional[dict]:
    async with db.execute(
        "SELECT * FROM fetch_log ORDER BY id DESC LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_cumulative_kwh(db: aiosqlite.Connection, zaehlpunkt: Optional[str] = None) -> float:
    if zaehlpunkt:
        async with db.execute(
            "SELECT SUM(kwh) as total FROM consumption WHERE zaehlpunkt = ?",
            (zaehlpunkt,),
        ) as cursor:
            row = await cursor.fetchone()
    else:
        async with db.execute(
            "SELECT SUM(kwh) as total FROM consumption"
        ) as cursor:
            row = await cursor.fetchone()
    return float(row["total"]) if row and row["total"] is not None else 0.0


async def get_latest_record(db: aiosqlite.Connection, zaehlpunkt: Optional[str] = None) -> Optional[dict]:
    if zaehlpunkt:
        async with db.execute(
            "SELECT * FROM consumption WHERE zaehlpunkt = ? ORDER BY interval_start DESC LIMIT 1",
            (zaehlpunkt,),
        ) as cursor:
            row = await cursor.fetchone()
    else:
        async with db.execute(
            "SELECT * FROM consumption ORDER BY interval_start DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


async def get_last_timestamp(db: aiosqlite.Connection, zaehlpunkt: str) -> Optional[str]:
    """Return the most recent interval_start for a zaehlpunkt."""
    async with db.execute(
        "SELECT MAX(interval_start) as last_ts FROM consumption WHERE zaehlpunkt = ?",
        (zaehlpunkt,),
    ) as cursor:
        row = await cursor.fetchone()
    return row["last_ts"] if row and row["last_ts"] else None


async def get_consumption_history(
    db: aiosqlite.Connection,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    zaehlpunkt: Optional[str] = None,
) -> list:
    """Return 15-min records filtered by time range and/or zaehlpunkt."""
    conditions = []
    params = []
    if zaehlpunkt:
        conditions.append("zaehlpunkt = ?")
        params.append(zaehlpunkt)
    if from_ts:
        conditions.append("interval_start >= ?")
        params.append(from_ts)
    if to_ts:
        conditions.append("interval_start <= ?")
        params.append(to_ts)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    async with db.execute(
        f"SELECT zaehlpunkt, interval_start, interval_end, kwh, estimated "
        f"FROM consumption {where} ORDER BY interval_start ASC",
        params,
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_consumption_day(
    db: aiosqlite.Connection, date_str: str, zaehlpunkt: Optional[str] = None
) -> list:
    """Return all 15-min records for a given date (YYYY-MM-DD)."""
    return await get_consumption_history(
        db,
        from_ts=f"{date_str}T00:00:00",
        to_ts=f"{date_str}T23:59:59",
        zaehlpunkt=zaehlpunkt,
    )


async def has_any_data(db: aiosqlite.Connection) -> bool:
    async with db.execute("SELECT COUNT(*) as cnt FROM consumption") as cursor:
        row = await cursor.fetchone()
    return bool(row["cnt"]) if row else False


async def get_zaehlpunkte_list(db: aiosqlite.Connection) -> list:
    """Return distinct zaehlpunkt IDs stored in the DB."""
    async with db.execute(
        "SELECT DISTINCT zaehlpunkt FROM consumption ORDER BY zaehlpunkt"
    ) as cursor:
        rows = await cursor.fetchall()
    return [r["zaehlpunkt"] for r in rows]


async def get_hourly_aggregated(db: aiosqlite.Connection, zaehlpunkt: str) -> list:
    """Return hourly aggregated consumption for a zaehlpunkt, ordered ASC.

    Each entry: {hour_start: ISO8601 UTC str, kwh: float, cumsum: float}
    where cumsum is the running total from the first ever recorded interval.
    """
    from datetime import datetime, timezone

    async with db.execute(
        "SELECT interval_start, kwh FROM consumption WHERE zaehlpunkt = ? ORDER BY interval_start ASC",
        (zaehlpunkt,),
    ) as cursor:
        rows = await cursor.fetchall()

    hourly: dict = {}
    for row in rows:
        ts = datetime.fromisoformat(row["interval_start"])
        hour_utc = ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        hourly[hour_utc] = hourly.get(hour_utc, 0.0) + row["kwh"]

    result = []
    cumsum = 0.0
    for hour in sorted(hourly):
        kwh = hourly[hour]
        cumsum += kwh
        result.append({
            "hour_start": hour.isoformat(),
            "kwh": round(kwh, 6),
            "cumsum": round(cumsum, 6),
        })
    return result
