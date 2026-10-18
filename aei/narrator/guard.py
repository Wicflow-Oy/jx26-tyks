"""Guards on live model calls (CONTRACTS.md section 9): a daily spend cap and per-IP rate limits.

- Spend: each response's `usage` tokens times PRICES (USD per million tokens) are added to today's UTC total in the
  `llm_spend` table of config.STATE_DB. Once the total reaches config.DAILY_SPEND_USD, no live call starts that day.
  Env AEI_PRICE_TABLE overrides prices as JSON, e.g. {"claude-haiku-5-5": [0.10, 0.50]}.
- Rate: at most config.LLM_RATE_LIMIT_PER_MIN live calls per client IP in any 60 seconds and LLM_RATE_LIMIT_PER_DAY
  per UTC day. Counted in memory only, so no IP address is written to disk. Calls without an IP (the precompute CLI)
  count toward the spend cap only.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import threading
import time
from collections import Counter, defaultdict, deque
from contextlib import contextmanager

from .. import config

log = logging.getLogger(__name__)

# Anthropic first-party list prices (Bedrock and Vertex bill partner prices, so the total is an estimate there).
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}
UNKNOWN_MODEL_PRICE = (10.00, 50.00)  # deliberately high, so an unpriced model reaches the cap early


def load_prices() -> dict[str, tuple[float, float]]:
    raw = config.env("AEI_PRICE_TABLE")
    if raw is None:
        return dict(PRICES)
    try:
        overrides = {str(model): (float(pair[0]), float(pair[1])) for model, pair in json.loads(raw).items()}
    except (ValueError, TypeError, AttributeError, IndexError, KeyError):
        raise ValueError('AEI_PRICE_TABLE must be JSON like {"claude-haiku-5-5": [0.10, 0.50]}') from None
    return {**PRICES, **overrides}


def _utc_day(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).date().isoformat()


class Guard:
    def __init__(
        self,
        *,
        cap_usd: float | None = None,
        per_min: int | None = None,
        per_day: int | None = None,
        prices: dict | None = None,
        clock=time.time,
    ):
        self.cap_usd = config.DAILY_SPEND_USD if cap_usd is None else cap_usd
        self.per_min = config.LLM_RATE_LIMIT_PER_MIN if per_min is None else per_min
        self.per_day = config.LLM_RATE_LIMIT_PER_DAY if per_day is None else per_day
        self.prices = load_prices() if prices is None else prices
        self.clock = clock
        self._lock = threading.Lock()
        self._day = ""
        self._recent: defaultdict[str, deque[float]] = defaultdict(deque)  # IP -> call times in the last minute
        self._today: Counter[str] = Counter()  # IP -> calls this UTC day

    def check(self, client_ip: str | None) -> str | None:
        """None if a live call may start (and counts it), else the fallback reason "spend_cap" or "rate_limit"."""
        try:
            if self.spend_today() >= self.cap_usd:
                return "spend_cap"
        except (sqlite3.Error, OSError) as e:  # an unreadable counter must stop spending, not allow it
            log.warning("spend counter unreadable (%s); live calls stop", type(e).__name__)
            return "spend_cap"
        if client_ip is None:
            return None
        now = self.clock()
        with self._lock:
            if _utc_day(now) != self._day:
                self._day, self._recent, self._today = _utc_day(now), defaultdict(deque), Counter()
            recent = self._recent[client_ip]
            while recent and now - recent[0] >= 60:
                recent.popleft()
            if len(recent) >= self.per_min or self._today[client_ip] >= self.per_day:
                return "rate_limit"
            recent.append(now)
            self._today[client_ip] += 1
        return None

    def cost(self, model: str, usage) -> float:
        price_in, price_out = self.prices.get(model, UNKNOWN_MODEL_PRICE)
        return (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000

    def record(self, model: str, usage) -> float:
        """Add one response's estimated cost to today's total; returns the estimate in USD."""
        usd = self.cost(model, usage)
        try:
            with self._db() as con:
                con.execute(
                    "INSERT INTO llm_spend (day, usd) VALUES (?, ?) "
                    "ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd",
                    (_utc_day(self.clock()), usd),
                )
        except (sqlite3.Error, OSError) as e:  # check() then fails closed on the same database
            log.warning("spend not recorded (%s)", type(e).__name__)
        return usd

    def spend_today(self) -> float:
        with self._db() as con:
            row = con.execute("SELECT usd FROM llm_spend WHERE day = ?", (_utc_day(self.clock()),)).fetchone()
        return row[0] if row else 0.0

    def status(self) -> dict:
        try:
            spend = round(self.spend_today(), 4)
        except (sqlite3.Error, OSError):
            spend = None
        return {"spend_today_usd": spend, "cap_usd": self.cap_usd}

    @contextmanager
    def _db(self):
        """One transaction on the state DB. The path is read at call time, so tests and the container can point
        config.STATE_DB elsewhere; store.py owns the other tables in the same file."""
        config.STATE_DB.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(config.STATE_DB, timeout=5)
        try:
            with con:
                con.execute("CREATE TABLE IF NOT EXISTS llm_spend (day TEXT PRIMARY KEY, usd REAL NOT NULL)")
                yield con
        finally:
            con.close()


GUARD = Guard()  # one per process, so the rate limits hold across requests
