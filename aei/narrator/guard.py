"""Spend and rate guards for live model calls (CONTRACTS.md section 10).

- **Daily spend cap** (`config.DAILY_SPEND_USD`, default $20 per UTC day). Cost is estimated from the response's
  `usage` tokens times `PRICE_TABLE` (USD per million tokens; override with env `AEI_PRICE_TABLE`, a JSON object
  `{"model": [input, output]}`). The running total per UTC day lives in the SQLite table `llm_spend` in
  `config.STATE_DB`, created if missing. If the table cannot be read, `allow` fails closed ("guard_unavailable").
- **Per-key token bucket** for live calls: `config.LLM_RATE_LIMIT_PER_MIN` (burst capacity, refilled evenly over a
  minute) and `config.LLM_RATE_LIMIT_PER_DAY` per key and UTC day. The key is the caller's IP in the API. Keys are kept
  in memory only; no IP address is ever written to disk.

The estimate uses Anthropic first-party list prices (cached 2026-10-06). Bedrock and Vertex bill at partner prices,
so treat the total as an estimate. An unknown model is priced at `UNKNOWN_MODEL_PRICE`, which is deliberately high.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)

PRICE_TABLE = {  # USD per million tokens: (input, output). Prompts up to 100K tokens for Haiku 5.5.
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
UNKNOWN_MODEL_PRICE = (10.00, 50.00)
CACHE_WRITE_MULTIPLIER = 1.25  # cache_creation_input_tokens, relative to the input price
CACHE_READ_MULTIPLIER = 0.10   # cache_read_input_tokens
TABLE = "llm_spend"
LOCAL_KEY = "local"            # used when a caller passes no key: all such calls share one bucket
MAX_KEY_CHARS = 64
MAX_TRACKED_KEYS = 10_000

_BATCH = ContextVar("aei_llm_batch", default=False)


@contextmanager
def batch():
    """Precompute runs: skip the per-key buckets, keep the spend cap. A context variable, so HTTP input cannot set it."""
    token = _BATCH.set(True)
    try:
        yield
    finally:
        _BATCH.reset(token)


def price_table() -> dict[str, tuple[float, float]]:
    prices = dict(PRICE_TABLE)
    raw = config.env("AEI_PRICE_TABLE")
    if raw:
        try:
            for model, pair in json.loads(raw).items():
                inp, out = (float(x) for x in pair)
                if inp < 0 or out < 0:
                    raise ValueError("negative price")
                prices[str(model)] = (inp, out)
        except (ValueError, TypeError, AttributeError):
            log.warning("AEI_PRICE_TABLE ignored: expected a JSON object {model: [input, output]}")
    return prices


def _model_family(model: str | None) -> str:
    """'eu.anthropic.claude-haiku-5-5' or 'claude-haiku-5-5@x' -> 'claude-haiku-5-5'."""
    m = (model or "").strip()
    i = m.find("claude-")
    if i >= 0:
        m = m[i:]
    return m.split("@")[0]


def _usage_field(usage, name: str) -> int:
    v = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    try:
        return max(int(v or 0), 0)
    except (TypeError, ValueError):
        return 0


def estimate_cost(model: str | None, usage, prices: dict | None = None) -> float:
    prices = price_table() if prices is None else prices
    inp, out = prices.get(model or "", prices.get(_model_family(model), UNKNOWN_MODEL_PRICE))
    tokens_in = (_usage_field(usage, "input_tokens")
                 + CACHE_WRITE_MULTIPLIER * _usage_field(usage, "cache_creation_input_tokens")
                 + CACHE_READ_MULTIPLIER * _usage_field(usage, "cache_read_input_tokens"))
    return (tokens_in * inp + _usage_field(usage, "output_tokens") * out) / 1_000_000


class Guard:
    def __init__(self, *, db_path=None, cap_usd: float | None = None, per_min: int | None = None,
                 per_day: int | None = None, clock=time.time, prices: dict | None = None):
        self.db_path = Path(db_path if db_path is not None else config.STATE_DB)
        self.cap_usd = float(config.DAILY_SPEND_USD if cap_usd is None else cap_usd)
        self.per_min = int(config.LLM_RATE_LIMIT_PER_MIN if per_min is None else per_min)
        self.per_day = int(config.LLM_RATE_LIMIT_PER_DAY if per_day is None else per_day)
        self.clock = clock
        self.prices = prices
        self._lock = threading.Lock()
        self._buckets: dict[str, list[float]] = {}   # key -> [tokens, last refill time]
        self._daily: dict[tuple[str, str], int] = {}  # (utc day, key) -> calls

    # --- persistence -------------------------------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} (day TEXT PRIMARY KEY, usd REAL NOT NULL DEFAULT 0, "
                     "calls INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0, "
                     "output_tokens INTEGER NOT NULL DEFAULT 0)")
        return conn

    def today(self) -> str:
        return _dt.datetime.fromtimestamp(self.clock(), tz=_dt.UTC).date().isoformat()

    def spend_today(self) -> float:
        """USD estimated so far this UTC day. Raises sqlite3.Error if the state DB is unusable."""
        conn = self._connect()
        try:
            row = conn.execute(f"SELECT usd FROM {TABLE} WHERE day = ?", (self.today(),)).fetchone()
        finally:
            conn.close()
        return float(row[0]) if row else 0.0

    def record(self, model: str | None, usage) -> float:
        """Add one call's estimated cost to today's total. Returns the estimate (USD)."""
        cost = estimate_cost(model, usage, self.prices)
        try:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(f"INSERT INTO {TABLE} (day, usd, calls, input_tokens, output_tokens) VALUES (?, ?, 1, ?, ?) "
                                 "ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd, calls = calls + 1, "
                                 "input_tokens = input_tokens + excluded.input_tokens, "
                                 "output_tokens = output_tokens + excluded.output_tokens",
                                 (self.today(), cost, _usage_field(usage, "input_tokens"),
                                  _usage_field(usage, "output_tokens")))
            finally:
                conn.close()
        except sqlite3.Error as e:
            log.warning("llm spend not recorded (%s)", type(e).__name__)
        return cost

    # --- decisions ---------------------------------------------------------------------------------------------
    def allow(self, key: str | None) -> tuple[bool, str | None]:
        """(True, None) and one token consumed, or (False, "spend_cap" | "rate_limited" | "guard_unavailable")."""
        try:
            if self.spend_today() >= self.cap_usd:
                return False, "spend_cap"
        except sqlite3.Error as e:
            log.warning("llm guard unavailable (%s)", type(e).__name__)
            return False, "guard_unavailable"
        if _BATCH.get():
            return True, None
        key = (str(key) if key else LOCAL_KEY)[:MAX_KEY_CHARS]
        now, day = self.clock(), self.today()
        with self._lock:
            self._prune(now, day)
            if self.per_min <= 0 or self._daily.get((day, key), 0) >= self.per_day:
                return False, "rate_limited"
            tokens, last = self._buckets.get(key, [float(self.per_min), now])
            tokens = min(float(self.per_min), tokens + (now - last) * self.per_min / 60.0)
            if tokens < 1.0:
                self._buckets[key] = [tokens, now]
                return False, "rate_limited"
            self._buckets[key] = [tokens - 1.0, now]
            self._daily[(day, key)] = self._daily.get((day, key), 0) + 1
        return True, None

    def _prune(self, now: float, day: str) -> None:
        for k in [k for k in self._daily if k[0] != day]:
            del self._daily[k]
        if len(self._buckets) > MAX_TRACKED_KEYS:
            for k in [k for k, (_, last) in self._buckets.items() if now - last > 120]:
                del self._buckets[k]

    def status(self) -> dict:
        try:
            spend = round(self.spend_today(), 4)
        except sqlite3.Error:
            spend = None
        return {"spend_today_usd": spend, "cap_usd": self.cap_usd, "per_min": self.per_min, "per_day": self.per_day}


_default: Guard | None = None
_default_lock = threading.Lock()


def get_guard() -> Guard:
    global _default
    with _default_lock:
        if _default is None:
            _default = Guard()
        return _default


def set_guard(guard: Guard | None) -> None:
    """Replace the process-wide guard (tests, or the API at startup). None resets to a fresh default on next use."""
    global _default
    with _default_lock:
        _default = guard
