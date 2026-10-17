"""Demo state in SQLite (`config.STATE_DB`): approved alerts, heads-up drafts, CDS Hooks feedback, order-card feedback
and an append-only audit log. CONTRACTS.md sections 7, 7b and 10.

Sessions: every write carries the browser's random `X-Demo-Session` id, and reads return that session's rows plus the
demo seeds, which every session sees, so judges never see each other's clicks. Every write also appends one audit row,
which makes the audit log the per-session write counter behind `MAX_WRITES_PER_SESSION`.

Replay: an alert approved from the brief dated Monday `as_of + 1` is stored with `approved_on = as_of + 1`. At a replay
date it is active only if it was approved by that Monday, has not expired and was not revoked by then, so a later
approval or revocation never changes an earlier date.

No user id, patient id or IP address is stored. Free text is limited to alert messages and heads-up drafts.
"""
import datetime as dt
import json
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Sequence
from contextlib import closing, contextmanager
from pathlib import Path

from . import config as C

ANONYMOUS = "anonymous"  # requests without a session header (a CDS Hooks client) share this bucket
SEED = "seed"
ORDER_OUTCOMES = ("shown", "keep", "change", "details")
CARD_STATES = ("info", "warning")  # only displayed cards are logged
CDS_OUTCOMES = {"accepted": "change", "overridden": "keep"}  # CDS Hooks feedback outcome -> order-card outcome
NOT_SENT = "not sent (demo)"
_SESSION = re.compile(r"[A-Za-z0-9_-]{8,64}")
_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")  # card keys, source ids, reason codes, suggestion ids
_TABLES = ("alerts", "revocations", "heads_up", "feedback", "order_feedback", "audit")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, session TEXT NOT NULL, seed INTEGER NOT NULL, signal_id TEXT, approved_on TEXT NOT NULL,
    expires_on TEXT NOT NULL, wards TEXT NOT NULL, drugs TEXT NOT NULL, organism TEXT, specimen TEXT,
    message TEXT NOT NULL, approved_by_role TEXT NOT NULL);
-- A revocation belongs to the session that made it, so revoking a shared seed hides it for that session only.
CREATE TABLE IF NOT EXISTS revocations (
    alert_id TEXT NOT NULL, session TEXT NOT NULL, revoked_on TEXT NOT NULL, PRIMARY KEY (alert_id, session));
CREATE TABLE IF NOT EXISTS heads_up (
    id TEXT PRIMARY KEY, session TEXT NOT NULL, signal_id TEXT NOT NULL, as_of TEXT NOT NULL, audience TEXT NOT NULL,
    text TEXT NOT NULL, provider TEXT, status TEXT NOT NULL, approved_by_role TEXT);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY, session TEXT NOT NULL, service_id TEXT NOT NULL, card_uuid TEXT NOT NULL, source_id TEXT,
    as_of TEXT, outcome TEXT NOT NULL, override_reason TEXT, accepted_suggestions TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_feedback (
    id INTEGER PRIMARY KEY, session TEXT NOT NULL, card_key TEXT NOT NULL, source_id TEXT, state TEXT NOT NULL,
    outcome TEXT NOT NULL, reason TEXT, changed_to TEXT, as_of TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, at TEXT NOT NULL, session TEXT NOT NULL, event TEXT NOT NULL, ref TEXT);
CREATE INDEX IF NOT EXISTS audit_by_session ON audit (session);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
"""


class NotFound(LookupError):
    """No such row for this session (the API answers 404)."""


class WriteLimitReached(RuntimeError):
    """The session used up `MAX_WRITES_PER_SESSION` (the API answers 429 with this message)."""

    def __init__(self):
        super().__init__(f"This demo session reached its limit of {C.MAX_WRITES_PER_SESSION} changes. "
                         "Open the demo in a new tab to start a fresh session.")


# --------------------------------------------------------------------------- connections, sessions, audit
def _connect() -> sqlite3.Connection:
    path = Path(C.STATE_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


@contextmanager
def _transaction():
    """BEGIN IMMEDIATE takes the write lock up front, so a session's write-cap check and its insert cannot interleave
    with another request (FastAPI runs sync endpoints on a thread pool)."""
    with closing(_connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")


def _write(con, session: str, event: str, ref: str) -> None:
    """Enforce the session's write cap, then append the audit row that counts this write."""
    if session != SEED:
        used = con.execute("SELECT COUNT(*) FROM audit WHERE session = ?", (session,)).fetchone()[0]
        if used >= C.MAX_WRITES_PER_SESSION:
            raise WriteLimitReached()
    con.execute("INSERT INTO audit (at, session, event, ref) VALUES (?, ?, ?, ?)", (_now(), session, event, ref))


def reset() -> None:
    """Drop and recreate this module's tables (tests and demo resets). Other tables in the same file, such as the
    narrator's `llm_spend`, are left alone."""
    with closing(_connect()) as con:
        con.executescript("".join(f"DROP TABLE IF EXISTS {t};" for t in _TABLES) + _SCHEMA)


def session_id(header: str | None) -> str:
    """The validated `X-Demo-Session` header; a missing header falls back to the shared anonymous bucket."""
    if not header:
        return ANONYMOUS
    if not _SESSION.fullmatch(header):
        raise ValueError("X-Demo-Session must be 8-64 letters, digits, '-' or '_'")
    return header


# --------------------------------------------------------------------------- small helpers
def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _day(value, days: int = 0) -> str:
    return (dt.date.fromisoformat(str(value)[:10]) + dt.timedelta(days=days)).isoformat()


def _monday(as_of) -> str:
    """The brief's date: the day after the last data day."""
    return _day(as_of, 1)


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _role(role: str) -> str:
    """Accept a role key ("infection_control") or its label; store the label."""
    label = C.ROLES.get(role, role)
    _require(label in C.ROLES.values(), f"unknown role {role!r}")
    return label


def _code(value: str | None, name: str) -> str | None:
    _require(value is None or bool(_CODE.fullmatch(str(value))), f"{name} must be a short code")
    return value


# --------------------------------------------------------------------------- alerts
def is_active(alert: dict, as_of) -> bool:
    """Active at the brief's Monday (`as_of + 1`): approved by then, not expired, and not revoked by then."""
    monday = _monday(as_of)
    revoked = alert.get("revoked_on")
    return alert["approved_on"] <= monday <= alert["expires_on"] and (revoked is None or revoked > monday)


def seed_demo() -> None:
    """Insert `config.DEMO_ALERT_SEEDS` if missing (idempotent). Seeds belong to no session; every session sees them."""
    with _transaction() as con:
        for s in C.DEMO_ALERT_SEEDS:
            added = con.execute(
                "INSERT OR IGNORE INTO alerts VALUES (?, ?, 1, NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s["id"], SEED, _day(s["approved_on"]), _day(s["expires_on"]), json.dumps(s["wards"]),
                 json.dumps(s["drugs"]), s["organism"], s["specimen"], s["message"], _role(s["approved_by_role"]))).rowcount
            if added:
                _write(con, SEED, "alert_seeded", s["id"])


def approve_alert(session: str, *, signal_id: str | None, as_of, wards: list[str], drugs: list[str], message: str,
                  approved_by_role: str = "infection_control", expires_on=None, organism: str | None = None,
                  specimen: str | None = None) -> dict:
    """Approve an alert from the brief dated `as_of + 1`. It expires after `ALERT_DEFAULT_EXPIRY_DAYS` unless given."""
    approved_on = _monday(as_of)
    expires_on = _day(expires_on) if expires_on else _day(approved_on, C.ALERT_DEFAULT_EXPIRY_DAYS)
    _require(bool(wards) and set(wards) <= set(C.WARD_LABELS), "wards must be known ward codes")
    _require(set(drugs) <= set(C.DRUGS), "drugs must be known drug codes")
    _require(bool(message.strip()), "message is empty")
    _require(expires_on >= approved_on, "expires_on is before the approval date")
    alert_id = f"alr-{uuid.uuid4().hex[:12]}"
    with _transaction() as con:
        _write(con, session, "alert_approved", alert_id)
        con.execute("INSERT INTO alerts VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (alert_id, session, _code(signal_id, "signal_id"), approved_on, expires_on, json.dumps(list(wards)),
                     json.dumps(list(drugs)), organism, specimen, message.strip(), _role(approved_by_role)))
    return get_alert(session, alert_id)


_ALERTS_SQL = """SELECT a.*, r.revoked_on FROM alerts a
    LEFT JOIN revocations r ON r.alert_id = a.id AND r.session = :session
    WHERE (a.seed = 1 OR a.session = :session)"""


def _alert(row: sqlite3.Row) -> dict:
    a = dict(row)
    a.update(wards=json.loads(a["wards"]), drugs=json.loads(a["drugs"]), seed=bool(a["seed"]))
    del a["session"]
    return a


def alerts(session: str, as_of=None) -> list[dict]:
    """The seeds plus this session's alerts, oldest first; with `as_of`, only those active at `as_of + 1`."""
    with closing(_connect()) as con:
        rows = con.execute(_ALERTS_SQL + " ORDER BY a.approved_on, a.id", {"session": session}).fetchall()
    found = [_alert(r) for r in rows]
    return found if as_of is None else [a for a in found if is_active(a, as_of)]


def get_alert(session: str, alert_id: str) -> dict:
    with closing(_connect()) as con:
        row = con.execute(_ALERTS_SQL + " AND a.id = :id", {"session": session, "id": alert_id}).fetchone()
    if row is None:
        raise NotFound(f"alert {alert_id} not found")
    return _alert(row)


def revoke_alert(session: str, alert_id: str, as_of) -> dict:
    """Revoke from the brief dated `as_of + 1` on, for this session only. Earlier replay dates still show the alert."""
    if get_alert(session, alert_id)["revoked_on"] is None:
        with _transaction() as con:
            _write(con, session, "alert_revoked", alert_id)
            con.execute("INSERT OR IGNORE INTO revocations VALUES (?, ?, ?)", (alert_id, session, _monday(as_of)))
    return get_alert(session, alert_id)


# --------------------------------------------------------------------------- heads-up drafts (never sent)
def _heads_up(row: sqlite3.Row) -> dict:
    h = dict(row)
    del h["session"]
    return {**h, "delivery": NOT_SENT}


def draft_heads_up(session: str, *, signal_id: str, as_of, text: str, audience: str = "ed",
                   provider: str | None = None) -> dict:
    """Store a narrated heads-up as a draft for the brief dated `as_of + 1`."""
    _require(bool(text.strip()), "text is empty")
    heads_up_id = f"hu-{uuid.uuid4().hex[:12]}"
    with _transaction() as con:
        _write(con, session, "heads_up_drafted", heads_up_id)
        con.execute("INSERT INTO heads_up VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', NULL)",
                    (heads_up_id, session, _code(signal_id, "signal_id"), _day(as_of), _code(audience, "audience"),
                     text.strip(), provider))
    return get_heads_up(session, heads_up_id)


def get_heads_up(session: str, heads_up_id: str) -> dict:
    with closing(_connect()) as con:
        row = con.execute("SELECT * FROM heads_up WHERE id = ? AND session = ?", (heads_up_id, session)).fetchone()
    if row is None:
        raise NotFound(f"heads-up {heads_up_id} not found")
    return _heads_up(row)


def approve_heads_up(session: str, heads_up_id: str, approved_by_role: str = "infection_control") -> dict:
    """Mark a draft approved (idempotent). Nothing is ever sent from this demo."""
    if get_heads_up(session, heads_up_id)["status"] == "draft":
        with _transaction() as con:
            _write(con, session, "heads_up_approved", heads_up_id)
            con.execute("UPDATE heads_up SET status = 'approved', approved_by_role = ? WHERE id = ?",
                        (_role(approved_by_role), heads_up_id))
    return get_heads_up(session, heads_up_id)


def heads_ups(session: str, as_of, signal_id: str | None = None) -> list[dict]:
    """This session's heads-ups drafted for briefs up to `as_of` (strict as-of), newest first."""
    query, args = "SELECT * FROM heads_up WHERE session = ? AND as_of <= ?", [session, _day(as_of)]
    if signal_id is not None:
        query, args = query + " AND signal_id = ?", [*args, signal_id]
    with closing(_connect()) as con:
        rows = con.execute(query + " ORDER BY as_of DESC, rowid DESC", args).fetchall()
    return [_heads_up(r) for r in rows]


# --------------------------------------------------------------------------- order-card and CDS Hooks feedback
def log_order_feedback(session: str, *, card_key: str, source_id: str | None, state: str, outcome: str, as_of,
                       reason: str | None = None, changed_to: str | None = None) -> dict:
    """One order-card event from the doctor's view. `shown` is logged once per session and card, i.e. once per order
    draft; a repeat is not stored and returns `logged: False`. Keep reasons come from `config.KEEP_REASONS` only."""
    _require(outcome in ORDER_OUTCOMES, f"outcome must be one of {ORDER_OUTCOMES}")
    _require(state in CARD_STATES, f"state must be one of {CARD_STATES}")
    _require(reason is None or (outcome == "keep" and reason in C.KEEP_REASONS), "reason must be a listed keep reason")
    _require(changed_to is None or (outcome == "change" and changed_to in C.DRUGS), "changed_to must be a drug code")
    _code(card_key, "card_key")
    _code(source_id, "source_id")
    with _transaction() as con:
        if outcome == "shown" and con.execute("SELECT 1 FROM order_feedback WHERE session = ? AND card_key = ? AND "
                                              "outcome = 'shown'", (session, card_key)).fetchone():
            return {"card_key": card_key, "outcome": outcome, "logged": False}
        _write(con, session, f"order_{outcome}", card_key)
        con.execute("INSERT INTO order_feedback (session, card_key, source_id, state, outcome, reason, changed_to, "
                    "as_of, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (session, card_key, source_id, state, outcome, reason, changed_to, _day(as_of), _now()))
    return {"card_key": card_key, "outcome": outcome, "logged": True}


def log_cds_feedback(session: str, *, service_id: str, card_uuid: str, outcome: str,
                     override_reason: str | None = None, accepted_suggestions: Sequence[str] = ()) -> dict:
    """One CDS Hooks feedback item (outcome accepted | overridden). A feedback call carries only the card uuid, so the
    card's source and date are read from its `shown` row: the CDS endpoint logs every card it returns as shown.
    Feedback on a card never shown here has no date and stays out of the summary. Only the override reason code is
    stored, never the user's comment."""
    _require(outcome in CDS_OUTCOMES, f"outcome must be one of {tuple(CDS_OUTCOMES)}")
    _code(service_id, "service_id")
    _code(card_uuid, "card uuid")
    _code(override_reason, "override reason code")
    _require(len(accepted_suggestions) <= 10, "too many accepted suggestions")
    for s in accepted_suggestions:
        _code(s, "suggestion id")
    with _transaction() as con:
        shown = con.execute("SELECT source_id, as_of FROM order_feedback WHERE card_key = ? AND outcome = 'shown' "
                            "LIMIT 1", (card_uuid,)).fetchone()
        source_id, as_of = (shown["source_id"], shown["as_of"]) if shown else (None, None)
        _write(con, session, f"cds_{outcome}", card_uuid)
        con.execute("INSERT INTO feedback (session, service_id, card_uuid, source_id, as_of, outcome, override_reason, "
                    "accepted_suggestions, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (session, service_id, card_uuid, source_id, as_of, outcome,
                     override_reason, json.dumps(list(accepted_suggestions)), _now()))
    return {"card_uuid": card_uuid, "outcome": outcome, "logged": True}


def feedback_summary(session: str, as_of) -> list[dict]:
    """Per card source, for cards shown up to `as_of`: how often it was shown, changed, kept or opened, with keep
    reasons. Combines the order screen and CDS Hooks feedback (accepted = changed, overridden = kept). Counts only."""
    day = _day(as_of)
    with closing(_connect()) as con:
        events = [(r["source_id"], r["outcome"], r["reason"]) for r in con.execute(
            "SELECT source_id, outcome, reason FROM order_feedback WHERE session = ? AND as_of <= ?", (session, day))]
        events += [(r["source_id"], CDS_OUTCOMES[r["outcome"]], r["override_reason"]) for r in con.execute(
            "SELECT source_id, outcome, override_reason FROM feedback WHERE session = ? AND as_of <= ?", (session, day))]
    out = []
    for source in sorted({e[0] for e in events}, key=str):
        mine = [e for e in events if e[0] == source]
        n = Counter(outcome for _, outcome, _ in mine)
        reasons = Counter(reason or "No reason given" for _, outcome, reason in mine if outcome == "keep")
        out.append({"source_id": source, "shown": n["shown"], "changed": n["change"], "kept": n["keep"],
                    "details": n["details"], "keep_reasons": dict(reasons),
                    "text": f"shown {n['shown']} {'time' if n['shown'] == 1 else 'times'}, changed {n['change']}"})
    return out
