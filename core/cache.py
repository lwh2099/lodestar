"""SQLite-backed cache with a three-stage fetch strategy.

Every remote fetch in the app goes through :func:`fetch_with_cache`:

1. Read the cached row; if it is fresh (within its TTL) serve it.
2. If missing or expired, call the fetcher and persist the result.
3. If the fetcher raises, fall back to the expired row (marked stale) so a
   broken free API degrades to "last updated at HH:MM (cached)" instead of
   taking the page down.

Payloads may be pandas DataFrames, JSON scalars, or any nesting of dicts /
lists containing the two. Everything is serialised into a single JSON column
so the whole store stays portable: one file, ``data/cache.db``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DB_PATH = DATA_DIR / "cache.db"

_LOCK = threading.Lock()
# In-process memo so Streamlit reruns don't hit SQLite + JSON parsing on
# every widget interaction. Keyed by (source, key).
_MEMO: dict[tuple[str, str], tuple[Any, datetime, float]] = {}
_MEMO_TTL = 300.0  # seconds


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS series_cache (
            source     TEXT NOT NULL,
            key        TEXT NOT NULL,
            value_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (source, key)
        )
        """
    )
    return conn


# --------------------------------------------------------------------------
# Payload (de)serialisation
# --------------------------------------------------------------------------

def _encode(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return {"__type__": "dataframe",
                "data": obj.to_json(orient="split", date_format="iso")}
    if isinstance(obj, pd.Series):
        frame = obj.to_frame(obj.name if obj.name is not None else "value")
        return {"__type__": "series",
                "data": frame.to_json(orient="split", date_format="iso")}
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v) for v in obj]
    return obj


def _restore_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    if len(df.index) and not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except (ValueError, TypeError):
            pass
    return df


def _decode(obj: Any) -> Any:
    if isinstance(obj, dict):
        kind = obj.get("__type__")
        if kind in ("dataframe", "series"):
            df = _restore_datetime_index(
                pd.read_json(StringIO(obj["data"]), orient="split"))
            return df.iloc[:, 0] if kind == "series" else df
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


# --------------------------------------------------------------------------
# Cache primitives
# --------------------------------------------------------------------------

def read(source: str, key: str) -> tuple[Any, Optional[datetime]]:
    """Return (payload, fetched_at) or (None, None) when absent."""
    memo = _MEMO.get((source, key))
    if memo is not None and (time.monotonic() - memo[2]) < _MEMO_TTL:
        return memo[0], memo[1]
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT value_json, fetched_at FROM series_cache "
            "WHERE source = ? AND key = ?", (source, key)).fetchone()
    if row is None:
        return None, None
    payload = _decode(json.loads(row[0]))
    fetched_at = datetime.fromisoformat(row[1])
    _MEMO[(source, key)] = (payload, fetched_at, time.monotonic())
    return payload, fetched_at


def write(source: str, key: str, payload: Any) -> datetime:
    fetched_at = datetime.now(timezone.utc)
    blob = json.dumps(_encode(payload))
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO series_cache "
            "(source, key, value_json, fetched_at) VALUES (?, ?, ?, ?)",
            (source, key, blob, fetched_at.isoformat()))
    _MEMO[(source, key)] = (payload, fetched_at, time.monotonic())
    return fetched_at


def clear(source: Optional[str] = None) -> int:
    """Drop cached rows (all sources by default). Returns rows removed."""
    _MEMO.clear()
    with _LOCK, _connect() as conn:
        if source is None:
            cur = conn.execute("DELETE FROM series_cache")
        else:
            cur = conn.execute(
                "DELETE FROM series_cache WHERE source = ?", (source,))
    return cur.rowcount


# --------------------------------------------------------------------------
# Three-stage fetch
# --------------------------------------------------------------------------

@dataclass
class CacheResult:
    data: Any
    fetched_at: Optional[datetime]
    from_cache: bool
    is_stale: bool  # True when the source failed and an expired copy was served
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.data is not None

    @property
    def age_text(self) -> str:
        if self.fetched_at is None:
            return "never"
        local = self.fetched_at.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")


def _is_empty(payload: Any) -> bool:
    if payload is None:
        return True
    if isinstance(payload, (pd.DataFrame, pd.Series)):
        return payload.empty
    if isinstance(payload, (dict, list)):
        return len(payload) == 0
    return False


def fetch_with_cache(source: str, key: str, ttl_seconds: float,
                     fetcher: Callable[[], Any],
                     force_refresh: bool = False) -> CacheResult:
    cached, fetched_at = read(source, key)
    if cached is not None and fetched_at is not None and not force_refresh:
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < ttl_seconds:
            return CacheResult(cached, fetched_at, True, False)

    try:
        fresh = fetcher()
        if _is_empty(fresh):
            raise ValueError("fetcher returned no data")
    except Exception as exc:  # noqa: BLE001 - any source failure falls back
        if cached is not None:
            return CacheResult(cached, fetched_at, True, True, str(exc))
        return CacheResult(None, None, False, True, str(exc))

    stamp = write(source, key, fresh)
    return CacheResult(fresh, stamp, False, False)


def retry(fn: Callable[[], Any], attempts: int = 3, delay: float = 1.0) -> Any:
    """Call ``fn`` up to ``attempts`` times with a linear backoff."""
    last_exc: Optional[Exception] = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if i < attempts - 1:
                time.sleep(delay * (i + 1))
    raise last_exc  # type: ignore[misc]
