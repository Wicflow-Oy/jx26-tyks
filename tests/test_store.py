"""Demo state: per-session isolation, shared seeds, the write cap, strict as-of visibility, revocation, alert input
checks, audit."""

import sqlite3

import pytest

from aei import config as C
from aei import store

A, B = "visitor-aaaa-0001", "visitor-bbbb-0002"


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE_DB", tmp_path / "state.sqlite")
    store.reset()
    store.seed_demo()
    return C.STATE_DB


def _approve(session, as_of="2026-03-08", **kw):
    args = {
        "signal_id": "phe-1a2b3c4d5e",
        "as_of": as_of,
        "wards": ["ICU"],
        "drugs": ["MEM"],
        "message": "Possible cluster, ICU. Typing advised.",
        **kw,
    }
    return store.approve_alert(session, **args)


def _audit_rows(db) -> int:
    with sqlite3.connect(db) as con:
        return con.execute("SELECT COUNT(*) FROM audit").fetchone()[0]


def test_seeds_are_visible_to_every_session_and_seeding_is_idempotent():
    store.seed_demo()
    seed_ids = [s["id"] for s in C.DEMO_ALERT_SEEDS]
    for session in (A, B, store.ANONYMOUS, None):
        assert [a["id"] for a in store.alerts(session)] == seed_ids
    assert all(a["seed"] and a["approved_by_role"] == "Infection control" for a in store.alerts(A))
    for seed, stored in zip(C.DEMO_ALERT_SEEDS, store.alerts(A), strict=True):
        assert set(stored["resistant_to"]) == set(seed["resistant_to"]) and set(stored["drugs"]) == set(seed["drugs"])
        assert {k: stored[k] for k in ("indications", "marker", "profile")} == {
            k: seed[k] for k in ("indications", "marker", "profile")
        }


def test_sessions_do_not_see_each_others_rows():
    mine = _approve(A)
    assert mine["approved_on"] == "2026-03-09" and mine["expires_on"] == "2026-03-23"
    assert mine["id"] in {a["id"] for a in store.alerts(A)}
    assert mine["id"] not in {a["id"] for a in store.alerts(B)}
    with pytest.raises(store.NotFound):
        store.revoke_alert(B, mine["id"], "2026-03-15")
    draft = store.draft_heads_up(A, signal_id="phe-1a2b3c4d5e", as_of="2026-03-08", text="Heads-up for the ED.")
    assert store.heads_ups(B, "2026-03-08") == []
    with pytest.raises(store.NotFound):
        store.approve_heads_up(B, draft["id"])


def _active(session, as_of) -> list[str]:
    return [a["id"] for a in store.alerts(session, as_of)]


def test_alerts_are_strictly_as_of():
    mine = _approve(A)["id"]  # from the brief of Mon 9 Mar 2026
    assert mine not in _active(A, "2026-03-01")  # approved after this brief: invisible
    assert mine in _active(A, "2026-03-08")
    assert mine in _active(A, "2026-03-22")  # brief of 23 Mar, the expiry day
    assert mine not in _active(A, "2026-03-29")
    assert _active(B, "2025-06-15") == ["seed-uro-esbl-2025"]
    assert _active(B, "2025-06-01") == [] and _active(B, "2025-06-29") == []
    assert _active(B, "2026-03-15") == ["seed-icu-mrsa-2026"]


def test_revoking_a_seed_hides_it_for_that_session_from_that_brief_on():
    revoked = store.revoke_alert(A, "seed-icu-mrsa-2026", "2026-03-15")
    assert revoked["revoked_on"] == "2026-03-16"
    assert _active(A, "2026-03-15") == []
    assert _active(A, "2026-03-08") == ["seed-icu-mrsa-2026"]  # earlier dates unchanged
    assert _active(B, "2026-03-15") == ["seed-icu-mrsa-2026"]  # other sessions unchanged
    assert store.revoke_alert(A, "seed-icu-mrsa-2026", "2026-03-22")["revoked_on"] == "2026-03-16"  # idempotent
    # going back in the replay and revoking from an earlier brief moves the revocation forward
    assert store.revoke_alert(A, "seed-icu-mrsa-2026", "2026-03-08")["revoked_on"] == "2026-03-09"
    assert _active(A, "2026-03-08") == []


def test_alerts_read_at_a_date_include_expired_ones_on_request_and_hide_later_revocations():
    mine = _approve(A, indications=["wound", "bloodstream"])  # from the brief of 9 Mar, expires 23 Mar
    assert mine["indications"] == ["bloodstream", "wound"]  # config order
    store.revoke_alert(A, mine["id"], "2026-03-15")  # from the brief of 16 Mar

    def seen(as_of, **kw):
        return {a["id"]: (a["expired"], a["revoked_on"]) for a in store.alerts(A, as_of, **kw)}

    assert seen("2026-03-08") == {"seed-icu-mrsa-2026": (False, None), mine["id"]: (False, None)}  # revoked later
    assert seen("2026-03-15") == {"seed-icu-mrsa-2026": (False, None)}
    assert seen("2026-03-29", include_expired=True) == {
        "seed-uro-esbl-2025": (True, None),
        "seed-icu-mrsa-2026": (True, None),
        mine["id"]: (True, "2026-03-16"),
    }
    assert seen("2025-06-01", include_expired=True) == {}  # nothing approved yet
    with pytest.raises(ValueError, match="indications"):
        _approve(A, indications=["pneumonia"])


def test_only_an_alert_active_at_that_brief_can_be_revoked():
    mine = _approve(A, as_of="2026-03-29")["id"]  # approved 30 Mar, expires 13 Apr
    for before_or_after in ("2026-03-08", "2026-04-26"):
        with pytest.raises(ValueError, match="not active"):
            store.revoke_alert(A, mine, before_or_after)
    assert mine in _active(A, "2026-03-29")


def test_write_cap_per_session(monkeypatch):
    monkeypatch.setattr(C, "MAX_WRITES_PER_SESSION", 3)
    for _ in range(3):
        _approve(A)
    with pytest.raises(store.WriteLimitReached, match="limit of 3"):
        _approve(A)
    assert len([a for a in store.alerts(A) if not a["seed"]]) == 3
    _approve(B)  # other sessions keep their own budget


def test_audit_log_is_append_only(db):
    before = _audit_rows(db)
    _approve(A)
    assert _audit_rows(db) == before + 1
    with sqlite3.connect(db) as con, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE audit SET event = 'edited'")
    with sqlite3.connect(db) as con, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM audit")


def test_reset_leaves_other_tables_alone(db):
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE llm_spend (day TEXT PRIMARY KEY, usd REAL)")
        con.execute("INSERT INTO llm_spend VALUES ('2026-10-17', 1.5)")
    _approve(A)
    store.reset()
    assert store.alerts(A) == []
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT usd FROM llm_spend").fetchone()[0] == 1.5


def test_heads_up_is_drafted_approved_and_never_sent():
    h = store.draft_heads_up(
        A, signal_id="phe-1a2b3c4d5e", as_of="2026-03-08", text="Heads-up for the ED.", provider="template"
    )
    assert h["status"] == "draft" and h["delivery"] == "not sent (demo)"
    approved = store.approve_heads_up(A, h["id"])
    assert approved["status"] == "approved" and approved["approved_by_role"] == "Infection control"
    assert approved["delivery"] == "not sent (demo)"
    assert store.heads_ups(A, "2026-03-01") == []  # drafted for a later brief: invisible
    assert [x["id"] for x in store.heads_ups(A, "2026-03-15", "phe-1a2b3c4d5e")] == [h["id"]]


def test_order_feedback_summary_counts_without_identifiers(db):
    card = {"card_key": "card-1", "source_id": "tmp_uti_women_20", "state": "info"}
    assert store.log_order_feedback(A, outcome="shown", as_of="2026-06-21", **card)["logged"]
    assert not store.log_order_feedback(A, outcome="shown", as_of="2026-06-21", **card)["logged"]  # once per draft
    store.log_order_feedback(A, outcome="edit", as_of="2026-06-21", **card)  # back to the order
    store.log_order_feedback(A, outcome="change", changed_to="MEC", as_of="2026-06-21", **card)  # the doctor's pick
    store.log_order_feedback(A, outcome="keep", reason="Patient-specific reason", as_of="2026-06-21", **card)
    with pytest.raises(ValueError):
        store.log_order_feedback(A, outcome="keep", reason="free text about Ms X", as_of="2026-06-21", **card)
    [row] = store.feedback_summary(A, "2026-06-21")
    assert row["text"] == "shown 1 time, changed 1"
    assert (row["edited"], row["kept"], row["keep_reasons"]) == (1, 1, {"Patient-specific reason": 1})
    assert store.feedback_summary(A, "2026-06-14") == []  # logged at a later replay date
    assert store.feedback_summary(B, "2026-06-21") == []
    with sqlite3.connect(db) as con:
        columns = {c[1] for t in ("feedback", "order_feedback") for c in con.execute(f"PRAGMA table_info({t})")}
    assert not any("user" in c or "patient" in c or c == "ip" for c in columns)


def test_cds_feedback_takes_its_source_from_the_shown_card():
    card = {"card_key": "6f2b6c1e-0000-5000-8000-000000000001", "source_id": "seed-uro-esbl-2025", "state": "warning"}
    store.log_order_feedback(store.ANONYMOUS, outcome="shown", as_of="2025-06-15", **card)
    store.log_cds_feedback(
        store.ANONYMOUS,
        service_id="strainwatch-order-sign",
        card_uuid=card["card_key"],
        outcome="overridden",
        override_reason="keep",
    )
    store.log_cds_feedback(
        store.ANONYMOUS,
        service_id="strainwatch-order-sign",
        card_uuid=card["card_key"],
        outcome="accepted",
        accepted_suggestions=["6f2b6c1e-0000-5000-8000-000000000002"],
    )
    [row] = store.feedback_summary(store.ANONYMOUS, "2025-06-15")
    assert (row["source_id"], row["shown"], row["kept"], row["changed"]) == ("seed-uro-esbl-2025", 1, 1, 1)
    with pytest.raises(ValueError):
        store.log_cds_feedback(store.ANONYMOUS, service_id="x", card_uuid=card["card_key"], outcome="ignored")


def test_session_header_validation():
    assert store.session_id(None) is None and store.session_id("") is None
    assert store.session_id(A) == A
    for bad in ("<script>", "short", store.ANONYMOUS):  # no header can claim the CDS Hooks bucket
        with pytest.raises(ValueError):
            store.session_id(bad)


def test_a_caller_without_a_session_reads_the_seeds_and_can_never_approve_or_revoke():
    _approve(A)
    store.log_cds_feedback(
        store.ANONYMOUS, service_id="strainwatch-order-sign", card_uuid="card-1", outcome="overridden"
    )
    assert [a["id"] for a in store.alerts(None)] == [s["id"] for s in C.DEMO_ALERT_SEEDS]
    assert store.feedback_summary(None, "2026-03-15") == [] and store.heads_ups(None, "2026-03-15") == []
    for nobody in (None, store.ANONYMOUS):
        with pytest.raises(ValueError, match=C.SESSION_HEADER):
            store.revoke_alert(nobody, "seed-uro-esbl-2025", "2025-06-08")
        with pytest.raises(ValueError, match=C.SESSION_HEADER):
            _approve(nobody)
        with pytest.raises(ValueError, match=C.SESSION_HEADER):
            store.draft_heads_up(nobody, signal_id="phe-1a2b3c4d5e", as_of="2026-03-08", text="Heads-up for the ED.")
    assert _active(A, "2025-06-08") == ["seed-uro-esbl-2025"]


def test_alert_input_checks():
    mine = _approve(
        A, wards=["ICU", "ICU"], drugs=["MEM", "CRO", "MEM"], resistant_to=["CLI", "FOX"], expires_on="2026-06-07"
    )  # 90 days after the brief of 9 Mar: the longest allowed
    assert (mine["wards"], mine["drugs"], mine["resistant_to"]) == (["ICU"], ["CRO", "MEM"], ["FOX", "CLI"])
    assert _approve(A, message=" Possible cluster, ICU.\n\tTyping advised. ")["message"] == (
        "Possible cluster, ICU. Typing advised."
    )
    bad = [
        ({"expires_on": "2026-06-08"}, "expires_on"),
        ({"expires_on": "9999-12-31"}, "expires_on"),
        ({"expires_on": "2026-03-08"}, "expires_on"),
        ({"approved_by_role": "ward_doctor"}, "infection control"),
        ({"message": "Typing advised.\u202e"}, "control"),
        ({"message": "MRSA\x00"}, "control"),
        ({"message": "   "}, "empty"),
        ({"resistant_to": ["XYZ"]}, "resistant_to"),
        ({"wards": []}, "wards"),
    ]
    for change, message in bad:
        with pytest.raises(ValueError, match=message):
            _approve(A, **change)


def test_a_state_file_from_an_older_schema_starts_fresh(db):
    with sqlite3.connect(db) as con:  # the alerts table as it was before resistant_to
        con.execute("DROP TABLE alerts")
        con.execute("CREATE TABLE alerts (id TEXT PRIMARY KEY, session TEXT NOT NULL)")
        con.execute("PRAGMA user_version = 0")
    store.seed_demo()
    assert [a["id"] for a in store.alerts(A)] == [s["id"] for s in C.DEMO_ALERT_SEEDS]
