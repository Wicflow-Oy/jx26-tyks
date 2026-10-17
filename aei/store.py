"""Demo state in SQLite: approved alerts, heads-up drafts, order feedback, issued CDS cards and an append-only audit log.

Path: `config.STATE_DB` (ephemeral `/tmp/state.sqlite` in the container), overridable with `set_path()` for tests.
Dates are ISO strings (`YYYY-MM-DD`) so they compare lexicographically.

**Sessions** (CONTRACTS.md section 10): every row a visitor creates carries the browser's random `X-Demo-Session` id,
and reads return only that session's rows plus the seeds (`config.DEMO_ALERT_SEEDS`), which every session sees.
Revoking a seed only hides it for the revoking session. Each session may write at most `MAX_WRITES_PER_SESSION` rows.

**Replay** (section 2): an alert approved from the brief dated Monday `as_of + 1` has `approved_on = as_of + 1`; it is
visible at a replay date only if `approved_on <= as_of + 1 <= expires_on` and not revoked by then.

No user id, patient id, IP address or free-text comment is ever stored.
"""
import dataclasses
import datetime as dt
import json
import math
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C

ANONYMOUS = "anonymous"  # requests without a session header (e.g. a CDS client) share this bucket
SEED_SESSION = "seed"
SESSION_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
ORDER_OUTCOMES = ("shown", "keep", "change", "details")
_TABLES = ("alerts", "revocations", "heads_up", "feedback", "cards", "audit", "session_writes")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, session TEXT NOT NULL, signal_id TEXT, as_of TEXT NOT NULL, approved_on TEXT NOT NULL,
    wards TEXT NOT NULL, drugs TEXT NOT NULL, organism TEXT, specimen TEXT, message TEXT NOT NULL,
    approved_by_role TEXT NOT NULL, expires_on TEXT NOT NULL, seed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS revocations (
    alert_id TEXT NOT NULL, session TEXT NOT NULL, revoked_on TEXT NOT NULL, by_role TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY (alert_id, session));
CREATE TABLE IF NOT EXISTS heads_up (
    id TEXT PRIMARY KEY, session TEXT NOT NULL, signal_id TEXT NOT NULL, as_of TEXT NOT NULL, audience TEXT NOT NULL,
    to_units TEXT NOT NULL, language TEXT NOT NULL, text TEXT NOT NULL, provider TEXT, validated INTEGER,
    fallback_reason TEXT, status TEXT NOT NULL DEFAULT 'draft', approved_by_role TEXT, approved_at TEXT,
    created_at TEXT NOT NULL);
-- Cards issued by the CDS Hooks service, so feedback (which carries only the card uuid) can name its source.
CREATE TABLE IF NOT EXISTS cards (
    card_uuid TEXT PRIMARY KEY, source_kind TEXT, source_id TEXT, state TEXT, unit TEXT, drug TEXT, indication TEXT,
    as_of TEXT, service_id TEXT, first_issued_at TEXT NOT NULL);
-- Order-card outcomes from the doctor's view and from CDS Hooks feedback (accepted -> change, overridden -> keep).
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, channel TEXT NOT NULL, card_key TEXT NOT NULL,
    source_kind TEXT, source_id TEXT, state TEXT, outcome TEXT NOT NULL, reason TEXT, changed_to TEXT,
    unit TEXT, drug TEXT, indication TEXT, as_of TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS feedback_session ON feedback (session, card_key, outcome);
CREATE TABLE IF NOT EXISTS session_writes (session TEXT PRIMARY KEY, writes INTEGER NOT NULL, first_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, session TEXT, event TEXT NOT NULL, entity TEXT,
    entity_id TEXT, detail TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""

_path_override: Path | None = None
_initialised: set[str] = set()
_seeded: set[str] = set()
_lock = threading.RLock()


class NotFound(KeyError):
    pass


class Conflict(ValueError):
    pass


class WriteCapExceeded(RuntimeError):
    """The session reached `MAX_WRITES_PER_SESSION` (the API answers 429 with a friendly message)."""


# --------------------------------------------------------------------------- paths and connections
def db_path() -> Path:
    return _path_override if _path_override is not None else Path(C.STATE_DB)


def set_path(path) -> None:
    """Point the store at another file (tests use tmp_path). `None` restores `config.STATE_DB`."""
    global _path_override
    _path_override = None if path is None else Path(path)


def _key() -> str:
    return str(db_path().resolve())


@contextmanager
def _conn():
    path = db_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            if _key() not in _initialised or not _has_schema(con):
                con.executescript(_SCHEMA)
                _initialised.add(_key())
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()


def _has_schema(con) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alerts'").fetchone() is not None


def init() -> Path:
    """Create the tables if needed and return the database path."""
    with _conn():
        pass
    return db_path()


def reset() -> None:
    """Drop this module's tables (the audit log included) and recreate them. Tests and demo resets only.
    Other modules' tables in the same file (the narrator's spend counter) are left alone."""
    path = db_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=10)
        try:
            for t in _TABLES:
                con.execute(f"DROP TABLE IF EXISTS {t}")
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()
        _initialised.add(_key())
        _seeded.discard(_key())
    audit("store_reset")


def session_id(raw: str | None) -> str:
    """Validate a session header value. Missing -> the shared anonymous bucket; malformed -> ValueError."""
    if raw is None or raw == "":
        return ANONYMOUS
    if not SESSION_RE.fullmatch(raw):
        raise ValueError("session id must be 8-64 letters, digits, '-' or '_'")
    return raw


def _count_write(con, session: str) -> None:
    if session == SEED_SESSION:
        return
    r = con.execute("SELECT writes FROM session_writes WHERE session = ?", (session,)).fetchone()
    writes = 0 if r is None else r["writes"]
    if writes >= C.MAX_WRITES_PER_SESSION:
        raise WriteCapExceeded(session)
    con.execute("INSERT INTO session_writes (session, writes, first_at) VALUES (?, 1, ?) "
                "ON CONFLICT(session) DO UPDATE SET writes = writes + 1", (session, _now()))


def writes_used(session: str) -> int:
    with _conn() as con:
        r = con.execute("SELECT writes FROM session_writes WHERE session = ?", (session,)).fetchone()
    return 0 if r is None else int(r["writes"])


# --------------------------------------------------------------------------- helpers
def to_jsonable(o):
    """Make numpy/pandas values JSON-safe: NaN -> None, numpy scalars -> Python, dates -> ISO strings."""
    if o is None or isinstance(o, (str, bool)):
        return o
    if o is pd.NaT or o is pd.NA:
        return None
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (set, frozenset)):
        return [to_jsonable(v) for v in sorted(o, key=str)]
    if isinstance(o, (list, tuple)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, pd.Timestamp):
        return o.date().isoformat() if o == o.normalize() else o.isoformat()
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if isinstance(o, np.ndarray):
        return to_jsonable(o.tolist())
    if isinstance(o, pd.DataFrame):
        return to_jsonable(o.to_dict(orient="records"))
    if isinstance(o, pd.Series):
        return to_jsonable(o.to_dict())
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return to_jsonable(dataclasses.asdict(o))
    try:
        if pd.isna(o):
            return None
    except (TypeError, ValueError):
        pass
    return str(o)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _day(x) -> str:
    return pd.Timestamp(str(x)[:10]).date().isoformat()


def _monday(as_of) -> str:
    return (pd.Timestamp(str(as_of)[:10]) + pd.Timedelta(days=1)).date().isoformat()


def _role_key(role: str | None) -> str:
    """Accept a role key ("infection_control") or its label ("Infection control")."""
    if role in C.ROLES:
        return role
    return next((k for k, v in C.ROLES.items() if v == role), role or "infection_control")


def audit(event: str, entity: str | None = None, entity_id: str | None = None, detail: dict | None = None,
          session: str | None = None) -> None:
    """Append one audit row. Callers never pass user, patient or IP identifiers."""
    with _conn() as con:
        con.execute("INSERT INTO audit (ts, session, event, entity, entity_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
                    (_now(), session, event, entity, entity_id, json.dumps(to_jsonable(detail or {}), sort_keys=True)))


def audit_log(limit: int = 200, session: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM audit", []
    if session is not None:
        q, args = q + " WHERE session = ?", [session]
    with _conn() as con:
        rows = con.execute(q + " ORDER BY id DESC LIMIT ?", (*args, int(limit))).fetchall()
    return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


# --------------------------------------------------------------------------- alerts
def _alert_row(r: sqlite3.Row, revoked: dict | None = None) -> dict:
    d = dict(r)
    d["wards"], d["drugs"] = json.loads(d["wards"]), json.loads(d["drugs"])
    d["seed"] = bool(d["seed"])
    d["approved_by"] = C.ROLES.get(d["approved_by_role"], d["approved_by_role"])
    d["status"] = "revoked" if revoked else "approved"
    d["revoked_on"] = revoked["revoked_on"] if revoked else None
    return d


def demo_seed_alerts() -> list[dict]:
    """`config.DEMO_ALERT_SEEDS` as store-shaped alert dicts (no database needed; tests use these directly)."""
    out = []
    for s in C.DEMO_ALERT_SEEDS:
        approved = _day(s["approved_on"])
        out.append({"id": s["id"], "session": SEED_SESSION, "signal_id": s.get("signal_id"),
                    "as_of": (pd.Timestamp(approved) - pd.Timedelta(days=1)).date().isoformat(), "approved_on": approved,
                    "wards": list(s["wards"]), "drugs": list(s.get("drugs") or []), "organism": s.get("organism"),
                    "specimen": s.get("specimen"), "message": s["message"],
                    "approved_by_role": _role_key(s.get("approved_by_role")),
                    "approved_by": C.ROLES.get(_role_key(s.get("approved_by_role")), s.get("approved_by_role")),
                    "expires_on": _day(s["expires_on"]), "status": "approved", "revoked_on": None, "seed": True})
    return out


def create_alert(signal_id: str | None, as_of, wards: list[str], drugs: list[str], message: str,
                 approved_by_role: str, expires_on=None, *, session: str = ANONYMOUS, organism: str | None = None,
                 specimen: str | None = None, seed: bool = False, alert_id: str | None = None) -> dict:
    """Store an approved alert. `as_of` is the brief's data day; the approval is dated the Monday after it."""
    approved_on = _monday(as_of)
    if expires_on is None:
        expires_on = (pd.Timestamp(approved_on) + pd.Timedelta(days=C.ALERT_DEFAULT_EXPIRY_DAYS)).date().isoformat()
    aid = alert_id or f"alr-{uuid.uuid4().hex[:12]}"
    role = _role_key(approved_by_role)
    with _conn() as con:
        _count_write(con, session)
        con.execute("INSERT INTO alerts (id, session, signal_id, as_of, approved_on, wards, drugs, organism, specimen, "
                    "message, approved_by_role, expires_on, seed, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, session, signal_id, _day(as_of), approved_on, json.dumps(list(wards)), json.dumps(list(drugs)),
                     organism, specimen, message, role, _day(expires_on), int(seed), _now()))
    audit("alert_approved", "alert", aid, {"signal_id": signal_id, "wards": list(wards), "drugs": list(drugs),
                                            "approved_on": approved_on, "expires_on": _day(expires_on), "role": role,
                                            "seed": seed}, session=session)
    return get_alert(aid, session)


def seed_demo() -> list[dict]:
    """Insert every `config.DEMO_ALERT_SEEDS` alert that is missing (idempotent). Seeds are visible to all sessions."""
    with _conn() as con:
        have = {r["id"] for r in con.execute("SELECT id FROM alerts WHERE seed = 1")}
    for s in demo_seed_alerts():
        if s["id"] not in have:
            create_alert(s["signal_id"], s["as_of"], s["wards"], s["drugs"], s["message"], s["approved_by_role"],
                         s["expires_on"], session=SEED_SESSION, organism=s["organism"], specimen=s["specimen"],
                         seed=True, alert_id=s["id"])
    _seeded.add(_key())
    return [get_alert(s["id"]) for s in demo_seed_alerts()]


def ensure_seeded() -> None:
    """Run `seed_demo()` once per database file per process (the container's state DB is ephemeral)."""
    if _key() not in _seeded:
        seed_demo()


def link_signal(alert_id: str, signal_id: str) -> None:
    """Attach a signal id to an alert that has none yet (seeds are created before any signal exists)."""
    with _conn() as con:
        changed = con.execute("UPDATE alerts SET signal_id = ? WHERE id = ? AND signal_id IS NULL",
                              (signal_id, alert_id)).rowcount
    if changed:
        audit("alert_linked", "alert", alert_id, {"signal_id": signal_id})


def _revocations(con, session: str) -> dict[str, dict]:
    return {r["alert_id"]: dict(r) for r in con.execute("SELECT * FROM revocations WHERE session = ?", (session,))}


def get_alert(alert_id: str, session: str | None = None) -> dict:
    """One alert as `session` sees it (None = owner view, no session filter)."""
    with _conn() as con:
        r = con.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if r is None or (session is not None and not r["seed"] and r["session"] != session):
            raise NotFound(alert_id)
        rev = _revocations(con, session if session is not None else r["session"]).get(alert_id)
    return _alert_row(r, rev)


def all_alerts(session: str | None = None) -> list[dict]:
    """Seeds plus the session's own alerts (every alert when session is None)."""
    with _conn() as con:
        if session is None:
            rows, revs = con.execute("SELECT * FROM alerts ORDER BY approved_on, id").fetchall(), {}
        else:
            rows = con.execute("SELECT * FROM alerts WHERE seed = 1 OR session = ? ORDER BY approved_on, id",
                               (session,)).fetchall()
            revs = _revocations(con, session)
    return [_alert_row(r, revs.get(r["id"])) for r in rows]


def visible_alerts(as_of, session: str | None = None) -> list[dict]:
    """Every alert approved on or before `as_of + 1` (active or not), each with an `active` flag for that date."""
    from .cds import alert_active
    monday = _monday(as_of)
    return [{**a, "active": alert_active(a, as_of)} for a in all_alerts(session) if a["approved_on"] <= monday]


def active_alerts(as_of, unit: str | None = None, session: str | None = None) -> list[dict]:
    """Alerts active at `as_of + 1` for this session, optionally only those covering `unit`."""
    return [a for a in visible_alerts(as_of, session) if a["active"] and (unit is None or unit in a["wards"])]


def alerts_for_signal(signal_id: str, as_of, session: str | None = None) -> list[dict]:
    return [a for a in visible_alerts(as_of, session) if a["signal_id"] == signal_id]


def revoke_alert(alert_id: str, as_of=None, by_role: str = "infection_control", *, session: str = ANONYMOUS) -> dict:
    """Revoke for this session from `as_of + 1` onwards; without `as_of`, at every replay date."""
    a = get_alert(alert_id, session)
    if a["status"] == "revoked":
        raise Conflict(f"alert {alert_id} is already revoked")
    revoked_on = _monday(as_of) if as_of is not None else a["approved_on"]
    with _conn() as con:
        _count_write(con, session)
        con.execute("INSERT INTO revocations (alert_id, session, revoked_on, by_role, created_at) VALUES (?,?,?,?,?)",
                    (alert_id, session, revoked_on, _role_key(by_role), _now()))
    audit("alert_revoked", "alert", alert_id, {"revoked_on": revoked_on, "role": _role_key(by_role)}, session=session)
    return get_alert(alert_id, session)


# --------------------------------------------------------------------------- heads-up drafts (never sent)
def _hu_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["to_units"] = json.loads(d["to_units"])
    d["validated"] = None if d["validated"] is None else bool(d["validated"])
    return d


def create_heads_up(signal_id: str, as_of, text: str, *, session: str = ANONYMOUS, audience: str = "ed",
                    to_units=("ED",), language: str = "en", provider: str | None = None, validated: bool | None = None,
                    fallback_reason: str | None = None) -> dict:
    hid = f"hu-{uuid.uuid4().hex[:12]}"
    with _conn() as con:
        _count_write(con, session)
        con.execute("INSERT INTO heads_up (id, session, signal_id, as_of, audience, to_units, language, text, provider, "
                    "validated, fallback_reason, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'draft', ?)",
                    (hid, session, signal_id, _day(as_of), audience, json.dumps(list(to_units)), language, text, provider,
                     None if validated is None else int(bool(validated)), fallback_reason, _now()))
    audit("heads_up_drafted", "heads_up", hid, {"signal_id": signal_id, "audience": audience, "provider": provider,
                                                "validated": validated, "fallback_reason": fallback_reason},
          session=session)
    return get_heads_up(hid, session)


def get_heads_up(hid: str, session: str | None = None) -> dict:
    with _conn() as con:
        r = con.execute("SELECT * FROM heads_up WHERE id = ?", (hid,)).fetchone()
    if r is None or (session is not None and r["session"] != session):
        raise NotFound(hid)
    return _hu_row(r)


def approve_heads_up(hid: str, by_role: str = "infection_control", *, session: str = ANONYMOUS) -> dict:
    """Mark a draft approved (idempotent). Nothing is ever sent from this demo."""
    h = get_heads_up(hid, session)
    if h["status"] == "approved":
        return h
    with _conn() as con:
        _count_write(con, session)
        con.execute("UPDATE heads_up SET status = 'approved', approved_by_role = ?, approved_at = ? WHERE id = ?",
                    (_role_key(by_role), _now(), hid))
    audit("heads_up_approved", "heads_up", hid, {"role": _role_key(by_role), "delivery": "not sent (demo)"},
          session=session)
    return get_heads_up(hid, session)


def heads_ups(signal_id: str | None = None, as_of=None, session: str | None = None) -> list[dict]:
    """The session's heads-ups drafted for a brief dated on or before `as_of` (strict as-of), newest first."""
    q, args = "SELECT * FROM heads_up WHERE 1=1", []
    if session is not None:
        q, args = q + " AND session = ?", [*args, session]
    if signal_id is not None:
        q, args = q + " AND signal_id = ?", [*args, signal_id]
    if as_of is not None:
        q, args = q + " AND as_of <= ?", [*args, _day(as_of)]
    with _conn() as con:
        rows = con.execute(q + " ORDER BY as_of DESC, created_at DESC, id DESC", args).fetchall()
    return [_hu_row(r) for r in rows]


# --------------------------------------------------------------------------- CDS cards and order feedback
def register_cards(cards: list[dict], *, service_id: str | None, as_of, unit: str | None,
                   indication: str | None = None) -> None:
    """Remember which source each issued CDS card came from. Stores no user, patient or encounter id."""
    rows = []
    for c in cards:
        ext = c.get("extension") or {}
        src = next((v for k, v in ext.items() if k.endswith(".source") and isinstance(v, dict)), {})
        state = next((v for k, v in ext.items() if k.endswith(".state")), None)
        rows.append((c["uuid"], src.get("kind"), src.get("id"), state, unit, src.get("drug"), indication, _day(as_of),
                     service_id, _now()))
    if rows:
        with _conn() as con:
            con.executemany("INSERT OR IGNORE INTO cards (card_uuid, source_kind, source_id, state, unit, drug, indication, "
                            "as_of, service_id, first_issued_at) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)


def card_info(card_uuid: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM cards WHERE card_uuid = ?", (card_uuid,)).fetchone()
    return None if r is None else dict(r)


def add_order_feedback(card_key: str, outcome: str, *, session: str = ANONYMOUS, channel: str = "order_view",
                       source_kind: str | None = None, source_id: str | None = None, state: str | None = None,
                       reason: str | None = None, changed_to: str | None = None, unit: str | None = None,
                       drug: str | None = None, indication: str | None = None, as_of=None) -> dict:
    """Log one outcome (shown | keep | change | details). `shown` is logged once per session and card key.
    No user or patient id is stored."""
    if outcome not in ORDER_OUTCOMES:
        raise ValueError(f"unknown outcome {outcome}")
    with _conn() as con:
        if outcome == "shown":
            dup = con.execute("SELECT id FROM feedback WHERE session = ? AND card_key = ? AND outcome = 'shown'",
                              (session, card_key)).fetchone()
            if dup is not None:
                return {"id": dup["id"], "card_key": card_key, "outcome": outcome, "duplicate": True}
        _count_write(con, session)
        fid = con.execute("INSERT INTO feedback (session, channel, card_key, source_kind, source_id, state, outcome, reason, "
                          "changed_to, unit, drug, indication, as_of, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (session, channel, card_key, source_kind, source_id, state, outcome, reason, changed_to, unit,
                           drug, indication, None if as_of is None else _day(as_of), _now())).lastrowid
    return {"id": fid, "card_key": card_key, "outcome": outcome, "duplicate": False, "source_kind": source_kind,
            "source_id": source_id}


def add_cds_feedback(card_uuid: str, outcome: str, *, session: str = ANONYMOUS, reason: str | None = None,
                     changed_to: str | None = None, service_id: str | None = None) -> dict:
    """CDS Hooks feedback: accepted -> change, overridden -> keep. The card's source comes from `cards`."""
    mapped = {"accepted": "change", "overridden": "keep"}.get(outcome)
    if mapped is None:
        raise ValueError(f"unknown CDS outcome {outcome}")
    info = card_info(card_uuid) or {}
    return add_order_feedback(card_uuid, mapped, session=session, channel=f"cds_hooks:{service_id or info.get('service_id')}",
                              source_kind=info.get("source_kind"), source_id=info.get("source_id"),
                              state=info.get("state"), reason=reason, changed_to=changed_to, unit=info.get("unit"),
                              drug=info.get("drug"), indication=info.get("indication"), as_of=info.get("as_of"))


def feedback_rows(session: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM feedback", []
    if session is not None:
        q, args = q + " WHERE session = ?", [session]
    with _conn() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY id", args).fetchall()]


def feedback_summary(as_of=None, session: str | None = None) -> dict:
    """Per source: shown / changed / kept / details counts, keep reasons and change targets. For cards issued at replay
    dates up to `as_of` (all when None). Infection-control view; counts only."""
    rows = feedback_rows(session)
    if as_of is not None:
        rows = [r for r in rows if r["as_of"] is None or r["as_of"] <= _day(as_of)]
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r["source_kind"], r["source_id"])
        g = groups.setdefault(key, {"source_kind": r["source_kind"], "source_id": r["source_id"], "shown": 0,
                                    "changed": 0, "kept": 0, "details": 0, "keep_reasons": {}, "changed_to": {},
                                    "units": set(), "drugs": set()})
        g[{"shown": "shown", "change": "changed", "keep": "kept", "details": "details"}[r["outcome"]]] += 1
        if r["outcome"] == "keep":
            reason = r["reason"] or "No reason given"
            g["keep_reasons"][reason] = g["keep_reasons"].get(reason, 0) + 1
        if r["outcome"] == "change" and r["changed_to"]:
            g["changed_to"][r["changed_to"]] = g["changed_to"].get(r["changed_to"], 0) + 1
        for k, col in (("units", "unit"), ("drugs", "drug")):
            if r[col]:
                g[k].add(r[col])
    items = []
    for g in sorted(groups.values(), key=lambda g: (str(g["source_kind"]), str(g["source_id"]))):
        g["units"], g["drugs"] = sorted(g["units"]), sorted(g["drugs"])
        g["text"] = f"shown {g['shown']} {'time' if g['shown'] == 1 else 'times'}, changed {g['changed']}"
        items.append(g)
    totals = {k: sum(g[k] for g in items) for k in ("shown", "changed", "kept", "details")}
    return {"as_of": None if as_of is None else _day(as_of), "items": items, "totals": totals,
            "note": "Counts only. No user or patient identifiers are stored."}
