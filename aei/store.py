"""Demo state in SQLite (`config.STATE_DB`): approved alerts, heads-up drafts, CDS Hooks feedback, order-card feedback
and an append-only audit log. CONTRACTS.md sections 7, 7b and 10.

Sessions: the browser sends a random `X-Demo-Session` id. Reads return that session's rows plus the demo seeds, which
every session sees, so judges never see each other's clicks; a reader without the header (session None) sees the seeds
only. Alerts, revocations and heads-ups need a browser session. CDS Hooks clients send no header: their shown cards
and feedback are appended under `ANONYMOUS`, which can never approve or revoke anything. Every write also appends one
audit row, which makes the audit log the per-session write counter behind `MAX_WRITES_PER_SESSION`.

Replay: an alert approved from the brief dated Monday `as_of + 1` is stored with `approved_on = as_of + 1`. At a replay
date it is active only if it was approved by that Monday, has not expired and was not revoked by then, so a later
approval or revocation never changes an earlier date. Read at a date, an alert shows only what was known by that Monday.

No user id, patient id or IP address is stored. Free text is limited to alert messages and heads-up drafts.
"""

import datetime as dt
import json
import re
import sqlite3
import unicodedata
import uuid
from collections import Counter
from collections.abc import Sequence
from contextlib import closing, contextmanager
from pathlib import Path

from . import config as C

ANONYMOUS = "cds-hooks:anonymous"  # the colon is outside the session-id alphabet, so no browser can claim this bucket
SEED = "seed"
APPROVER = C.ROLES["infection_control"]  # CONTRACTS.md section 7: alerts are "Flagged by infection control"
MAX_ALERT_DAYS = 90  # an alert lapses within a quarter unless approved again, so none stays on order screens for good
ORDER_OUTCOMES = ("shown", "keep", "edit", "change", "details")  # edit: back to the order; change: drug changed
CARD_STATES = ("info", "warning")  # only displayed cards are logged
CDS_OUTCOMES = {"accepted": "change", "overridden": "keep"}  # CDS Hooks feedback outcome -> order-card outcome
NOT_SENT = "not sent (demo)"
_SESSION = re.compile(r"[A-Za-z0-9_-]{8,64}")
_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")  # card keys, source ids, reason codes, suggestion ids
_HIDDEN = {"Cc", "Cf", "Cs"}  # Unicode control, format (U+202E, zero-width marks) and surrogate characters
_SCHEMA_VERSION = 3  # bump on any table change (2 added alerts.resistant_to; 3 indications, marker, profile)
_TABLES = ("alerts", "revocations", "heads_up", "feedback", "order_feedback", "audit")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, session TEXT NOT NULL, seed INTEGER NOT NULL, signal_id TEXT, approved_on TEXT NOT NULL,
    expires_on TEXT NOT NULL, wards TEXT NOT NULL, drugs TEXT NOT NULL, resistant_to TEXT NOT NULL,
    indications TEXT NOT NULL, organism TEXT, specimen TEXT, marker TEXT, profile TEXT, message TEXT NOT NULL,
    approved_by_role TEXT NOT NULL);
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
        super().__init__(
            f"This demo session reached its limit of {C.MAX_WRITES_PER_SESSION} changes. "
            "Open the demo in a new tab to start a fresh session."
        )


# --------------------------------------------------------------------------- connections, sessions, audit
def _connect() -> sqlite3.Connection:
    """A connection to the state DB. Demo state is disposable, so a file written by an older schema starts fresh."""
    path = Path(C.STATE_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    if con.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION:
        _recreate(con)
    return con


def _recreate(con: sqlite3.Connection) -> None:
    con.executescript(
        "".join(f"DROP TABLE IF EXISTS {t};" for t in _TABLES) + _SCHEMA + f"PRAGMA user_version = {_SCHEMA_VERSION};"
    )


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
        _recreate(con)


def session_id(header: str | None) -> str | None:
    """The validated `X-Demo-Session` header; None when it is missing."""
    if not header:
        return None
    _require(bool(_SESSION.fullmatch(header)), f"{C.SESSION_HEADER} must be 8-64 letters, digits, '-' or '_'")
    return header


def require_session(session: str | None) -> str:
    """The browser session a change belongs to. A caller without one (None, or ANONYMOUS for CDS Hooks) can only
    append to the feedback logs, never approve or revoke."""
    _require(session not in (None, ANONYMOUS), f"Changes need the {C.SESSION_HEADER} header (one random id per tab).")
    return session


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


def _approver(role: str) -> str:
    """Accept the role key ("infection_control") or its label; store the label."""
    _require(C.ROLES.get(role, role) == APPROVER, f"only {APPROVER.lower()} approves alerts and heads-ups")
    return APPROVER


def _code(value: str | None, name: str) -> str | None:
    _require(value is None or bool(_CODE.fullmatch(str(value))), f"{name} must be a short code")
    return value


def _drugs(codes: Sequence[str], name: str) -> list[str]:
    """Known drug codes, each once, in panel order."""
    given = set(codes)
    _require(given <= set(C.DRUGS), f"{name} must be known drug codes")
    return [d for d in C.DRUGS if d in given]


def _indications(keys: Sequence[str]) -> list[str]:
    """Known indication keys, each once, in config order; empty means every indication."""
    _require(set(keys) <= set(C.INDICATIONS), f"indications must be among {tuple(C.INDICATIONS)}")
    return [i for i in C.INDICATIONS if i in set(keys)]


def _plain_text(value: str, name: str) -> str:
    """Typed text as one line (line breaks and runs of spaces become one space). Hidden characters such as NUL or a
    right-to-left override make text display differently from what it says, so they are refused."""
    text = " ".join(value.split())
    _require(bool(text), f"{name} is empty")
    _require(
        not any(unicodedata.category(ch) in _HIDDEN for ch in text), f"{name} contains control or formatting characters"
    )
    return text


# --------------------------------------------------------------------------- alerts
def is_active(alert: dict, as_of) -> bool:
    """Active at the brief's Monday (`as_of + 1`): approved by then, not expired, and not revoked by then."""
    monday = _monday(as_of)
    revoked = alert.get("revoked_on")
    return alert["approved_on"] <= monday <= alert["expires_on"] and (revoked is None or revoked > monday)


_LISTS = ("wards", "drugs", "resistant_to", "indications")  # stored as JSON


def _insert_alert(con, alert: dict) -> bool:
    """Insert one alert; False when its id exists."""
    return (
        con.execute(
            "INSERT OR IGNORE INTO alerts VALUES (:id, :session, :seed, :signal_id, :approved_on, :expires_on, :wards, "
            ":drugs, :resistant_to, :indications, :organism, :specimen, :marker, :profile, :message, :approved_by_role)",
            alert | {k: json.dumps(alert[k]) for k in _LISTS},
        ).rowcount
        == 1
    )


def seed_demo() -> None:
    """Insert `config.DEMO_ALERT_SEEDS` if missing (idempotent). Seeds belong to no session; every session sees them."""
    with _transaction() as con:
        for s in C.DEMO_ALERT_SEEDS:
            seed = s | {
                "session": SEED,
                "seed": 1,
                "signal_id": None,
                "approved_on": _day(s["approved_on"]),
                "expires_on": _day(s["expires_on"]),
                "drugs": _drugs(s["drugs"], "drugs"),
                "resistant_to": _drugs(s["resistant_to"], "resistant_to"),
                "indications": _indications(s["indications"]),
                "approved_by_role": _approver(s["approved_by_role"]),
            }
            if _insert_alert(con, seed):
                _write(con, SEED, "alert_seeded", s["id"])


def approve_alert(
    session: str,
    *,
    signal_id: str | None,
    as_of,
    wards: list[str],
    drugs: list[str],
    message: str,
    resistant_to: Sequence[str] = (),
    indications: Sequence[str] = (),
    approved_by_role: str = "infection_control",
    expires_on=None,
    organism: str | None = None,
    specimen: str | None = None,
    marker: str | None = None,
    profile: str | None = None,
) -> dict:
    """Approve an alert from the brief dated `as_of + 1`. It expires after `ALERT_DEFAULT_EXPIRY_DAYS`, or on
    `expires_on`, at most `MAX_ALERT_DAYS` later. It warns at signing for `drugs`, on orders for `indications` (empty:
    every indication). `profile` is the flagged antibiogram, `marker` its resistance marker, and `resistant_to` what
    that antibiogram is R to; the order screen quotes them and names no other drug."""
    require_session(session)
    approved_on = _monday(as_of)
    expires_on = _day(expires_on) if expires_on else _day(approved_on, C.ALERT_DEFAULT_EXPIRY_DAYS)
    last_day = _day(approved_on, MAX_ALERT_DAYS)
    wards = list(dict.fromkeys(wards))
    _require(bool(wards) and set(wards) <= set(C.WARD_LABELS), "wards must be known ward codes")
    _require(approved_on <= expires_on <= last_day, f"expires_on must be from {approved_on} to {last_day}")
    alert = {
        "id": f"alr-{uuid.uuid4().hex[:12]}",
        "session": session,
        "seed": 0,
        "signal_id": _code(signal_id, "signal_id"),
        "approved_on": approved_on,
        "expires_on": expires_on,
        "wards": wards,
        "drugs": _drugs(drugs, "drugs"),
        "resistant_to": _drugs(resistant_to, "resistant_to"),
        "indications": _indications(indications),
        "organism": organism,
        "specimen": specimen,
        "marker": _code(marker, "marker"),
        "profile": profile,
        "message": _plain_text(message, "message"),
        "approved_by_role": _approver(approved_by_role),
    }
    with _transaction() as con:
        _write(con, session, "alert_approved", alert["id"])
        _insert_alert(con, alert)
    return get_alert(session, alert["id"])


_ALERTS_SQL = """SELECT a.*, r.revoked_on FROM alerts a
    LEFT JOIN revocations r ON r.alert_id = a.id AND r.session = :session
    WHERE (a.seed = 1 OR a.session = :session)"""  # session None matches no row: the seeds only


def _alert(row: sqlite3.Row) -> dict:
    a = dict(row)
    a.update({k: json.loads(a[k]) for k in _LISTS}, seed=bool(a["seed"]))
    del a["session"]
    return a


def _seen_at(alert: dict, as_of) -> dict:
    """The alert as the brief dated `as_of + 1` knew it: a revocation made at a later replay date is not shown yet, and
    `expired` says whether it lapsed by then."""
    monday = _monday(as_of)
    revoked = alert["revoked_on"] if alert["revoked_on"] and alert["revoked_on"] <= monday else None
    return {**alert, "revoked_on": revoked, "expired": alert["expires_on"] < monday}


def alerts(session: str | None, as_of=None, *, include_expired: bool = False) -> list[dict]:
    """The seeds plus this session's alerts, oldest first. With `as_of`, the alerts approved by `as_of + 1` as known
    then: only the active ones, or with `include_expired` also those expired or revoked by then (a case timeline)."""
    with closing(_connect()) as con:
        rows = con.execute(_ALERTS_SQL + " ORDER BY a.approved_on, a.id", {"session": session}).fetchall()
    found = [_alert(r) for r in rows]
    if as_of is None:
        return found
    seen = [_seen_at(a, as_of) for a in found if a["approved_on"] <= _monday(as_of)]
    return seen if include_expired else [a for a in seen if is_active(a, as_of)]


def get_alert(session: str | None, alert_id: str) -> dict:
    with closing(_connect()) as con:
        row = con.execute(_ALERTS_SQL + " AND a.id = :id", {"session": session, "id": alert_id}).fetchone()
    if row is None:
        raise NotFound(f"alert {alert_id} not found")
    return _alert(row)


def revoke_alert(session: str, alert_id: str, as_of) -> dict:
    """Revoke from the brief dated `as_of + 1` on, for this session only; earlier replay dates still show the alert.
    Revoking again changes nothing. An alert that is not active at that brief cannot be revoked from it."""
    require_session(session)
    alert, monday = get_alert(session, alert_id), _monday(as_of)
    if alert["revoked_on"] is not None and alert["revoked_on"] <= monday:
        return alert
    _require(is_active(alert, as_of), f"alert {alert_id} is not active in the brief of {monday}")
    with _transaction() as con:
        _write(con, session, "alert_revoked", alert_id)
        # replaces a revocation made at a later replay date, which this one precedes
        con.execute("INSERT OR REPLACE INTO revocations VALUES (?, ?, ?)", (alert_id, session, monday))
    return get_alert(session, alert_id)


# --------------------------------------------------------------------------- heads-up drafts (never sent)
def _heads_up(row: sqlite3.Row) -> dict:
    h = dict(row)
    del h["session"]
    return {**h, "delivery": NOT_SENT}


def draft_heads_up(
    session: str, *, signal_id: str, as_of, text: str, audience: str = "ed", provider: str | None = None
) -> dict:
    """Store a narrated heads-up as a draft for the brief dated `as_of + 1`."""
    require_session(session)
    _require(bool(text.strip()), "text is empty")
    heads_up_id = f"hu-{uuid.uuid4().hex[:12]}"
    with _transaction() as con:
        _write(con, session, "heads_up_drafted", heads_up_id)
        con.execute(
            "INSERT INTO heads_up VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', NULL)",
            (
                heads_up_id,
                session,
                _code(signal_id, "signal_id"),
                _day(as_of),
                _code(audience, "audience"),
                text.strip(),
                provider,
            ),
        )
    return get_heads_up(session, heads_up_id)


def get_heads_up(session: str | None, heads_up_id: str) -> dict:
    with closing(_connect()) as con:
        row = con.execute("SELECT * FROM heads_up WHERE id = ? AND session = ?", (heads_up_id, session)).fetchone()
    if row is None:
        raise NotFound(f"heads-up {heads_up_id} not found")
    return _heads_up(row)


def approve_heads_up(session: str, heads_up_id: str, approved_by_role: str = "infection_control") -> dict:
    """Mark a draft approved (idempotent). Nothing is ever sent from this demo."""
    require_session(session)
    role = _approver(approved_by_role)
    if get_heads_up(session, heads_up_id)["status"] == "draft":
        with _transaction() as con:
            _write(con, session, "heads_up_approved", heads_up_id)
            con.execute(
                "UPDATE heads_up SET status = 'approved', approved_by_role = ? WHERE id = ?", (role, heads_up_id)
            )
    return get_heads_up(session, heads_up_id)


def heads_ups(session: str | None, as_of, signal_id: str | None = None) -> list[dict]:
    """This session's heads-ups drafted for briefs up to `as_of` (strict as-of), newest first."""
    query, args = "SELECT * FROM heads_up WHERE session = ? AND as_of <= ?", [session, _day(as_of)]
    if signal_id is not None:
        query, args = query + " AND signal_id = ?", [*args, signal_id]
    with closing(_connect()) as con:
        rows = con.execute(query + " ORDER BY as_of DESC, rowid DESC", args).fetchall()
    return [_heads_up(r) for r in rows]


# --------------------------------------------------------------------------- order-card and CDS Hooks feedback
def log_order_feedback(
    session: str,
    *,
    card_key: str,
    source_id: str | None,
    state: str,
    outcome: str,
    as_of,
    reason: str | None = None,
    changed_to: str | None = None,
) -> dict:
    """One order-card event from the doctor's view. `shown` is logged once per session and card, i.e. once per order
    draft; a repeat is not stored and returns `logged: False`. Keep reasons come from `config.KEEP_REASONS` only."""
    _require(outcome in ORDER_OUTCOMES, f"outcome must be one of {ORDER_OUTCOMES}")
    _require(state in CARD_STATES, f"state must be one of {CARD_STATES}")
    _require(reason is None or (outcome == "keep" and reason in C.KEEP_REASONS), "reason must be a listed keep reason")
    _require(changed_to is None or (outcome == "change" and changed_to in C.DRUGS), "changed_to must be a drug code")
    _code(card_key, "card_key")
    _code(source_id, "source_id")
    with _transaction() as con:
        if (
            outcome == "shown"
            and con.execute(
                "SELECT 1 FROM order_feedback WHERE session = ? AND card_key = ? AND outcome = 'shown'",
                (session, card_key),
            ).fetchone()
        ):
            return {"card_key": card_key, "outcome": outcome, "logged": False}
        _write(con, session, f"order_{outcome}", card_key)
        con.execute(
            "INSERT INTO order_feedback (session, card_key, source_id, state, outcome, reason, changed_to, "
            "as_of, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session, card_key, source_id, state, outcome, reason, changed_to, _day(as_of), _now()),
        )
    return {"card_key": card_key, "outcome": outcome, "logged": True}


def log_cds_feedback(
    session: str,
    *,
    service_id: str,
    card_uuid: str,
    outcome: str,
    override_reason: str | None = None,
    accepted_suggestions: Sequence[str] = (),
) -> dict:
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
        shown = con.execute(
            "SELECT source_id, as_of FROM order_feedback WHERE card_key = ? AND outcome = 'shown' LIMIT 1", (card_uuid,)
        ).fetchone()
        source_id, as_of = (shown["source_id"], shown["as_of"]) if shown else (None, None)
        _write(con, session, f"cds_{outcome}", card_uuid)
        con.execute(
            "INSERT INTO feedback (session, service_id, card_uuid, source_id, as_of, outcome, override_reason, "
            "accepted_suggestions, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session,
                service_id,
                card_uuid,
                source_id,
                as_of,
                outcome,
                override_reason,
                json.dumps(list(accepted_suggestions)),
                _now(),
            ),
        )
    return {"card_uuid": card_uuid, "outcome": outcome, "logged": True}


def feedback_summary(session: str | None, as_of) -> list[dict]:
    """Per card source, for cards shown up to `as_of`: how often it was shown, edited, changed, kept or opened, with keep
    reasons. Combines the order screen and CDS Hooks feedback (accepted = changed, overridden = kept). Counts only."""
    day = _day(as_of)
    with closing(_connect()) as con:
        events = [
            (r["source_id"], r["outcome"], r["reason"])
            for r in con.execute(
                "SELECT source_id, outcome, reason FROM order_feedback WHERE session = ? AND as_of <= ?", (session, day)
            )
        ]
        events += [
            (r["source_id"], CDS_OUTCOMES[r["outcome"]], r["override_reason"])
            for r in con.execute(
                "SELECT source_id, outcome, override_reason FROM feedback WHERE session = ? AND as_of <= ?",
                (session, day),
            )
        ]
    out = []
    for source in sorted({e[0] for e in events}, key=str):
        mine = [e for e in events if e[0] == source]
        n = Counter(outcome for _, outcome, _ in mine)
        reasons = Counter(reason or "No reason given" for _, outcome, reason in mine if outcome == "keep")
        out.append(
            {
                "source_id": source,
                "shown": n["shown"],
                "edited": n["edit"],
                "changed": n["change"],
                "kept": n["keep"],
                "details": n["details"],
                "keep_reasons": dict(reasons),
                "text": f"shown {n['shown']} {'time' if n['shown'] == 1 else 'times'}, changed {n['change']}",
            }
        )
    return out
