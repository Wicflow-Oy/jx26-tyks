"""The HTTP API end to end (offline): as-of handling, the brief and case file, per-session alerts and heads-ups, the
order screen and CDS Hooks, write and rate limits, and the public-demo headers."""
import pytest
from fastapi.testclient import TestClient

from aei import api, brief, cds, data, precompute, store
from aei import config as C

A, B = "judge-aaaa-0001", "judge-bbbb-0002"
ICU_CLUSTER = "phe-7972cb3f12"  # ICU MRSA 2026, pattern FOX:R VAN:S CLI:R, first sample 3 Mar 2026
AS_B = {C.SESSION_HEADER: B}
SCENARIOS = {s["key"]: s for s in C.DEMO_SCENARIOS}


@pytest.fixture(scope="module")
def cache_dir(tmp_path_factory, ds):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "CACHE_DIR", tmp_path_factory.mktemp("cache"))
        yield C.CACHE_DIR


@pytest.fixture
def client(cache_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setattr(C, "PUBLIC", False)  # the template narrator: no key, no replay cache
    for name in ("AEI_NARRATOR", "ANTHROPIC_API_KEY", "JEV_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    api.LIMITER.hits.clear()
    with TestClient(api.app, headers={C.SESSION_HEADER: A}) as c:
        yield c


def items(brief_json):
    return {i["id"]: i for s in brief_json["sections"] for i in s["items"]}


def approve(client, headers=None, **body):
    payload = {"signal_id": ICU_CLUSTER, "as_of": "2026-03-29", "wards": ["ICU"], "drugs": ["CXM", "CRO"],
               "message": "Possible MRSA cluster, ICU. Typing advised.", **body}
    return client.post("/api/alerts", json=payload, headers=headers)


def order(client, headers=None, **body):
    payload = {"as_of": "2026-03-29", "unit": "ICU", "indication": "wound", "drug": "CXM", "stage": "sign", **body}
    return client.post("/api/order-context", json=payload, headers=headers)


# --------------------------------------------------------------------------- meta, health, headers
def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["app_name"] == C.APP_NAME and m["synthetic"] is True
    assert m["replay"] == {"first": "2024-10-27", "last": C.DATA_END}
    assert m["demo_mondays"] == C.DEMO_MONDAYS and m["second_opinion"] == "not_configured"
    assert {w["code"] for w in m["wards"]} == set(C.WARD_LABELS) and m["narrator"] == "template"


def test_health_never_contains_a_key(client, monkeypatch):
    secret = "sk-ant-test-not-a-real-key-0123456789"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    r = client.get("/api/health")
    assert r.json() | {"spend_today_usd": 0} == {"ok": True, "app_name": C.APP_NAME, "data_loaded": True,
                                                 "narrator": "template", "key_set": True, "spend_today_usd": 0,
                                                 "cap_usd": C.DAILY_SPEND_USD}
    for path in ("/api/health", "/api/meta"):
        assert secret not in client.get(path).text


def test_server_starts_without_data(cache_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE_DB", tmp_path / "state.sqlite")

    def missing(*_):
        raise FileNotFoundError("isolates.csv")

    monkeypatch.setattr(data, "load", missing)
    with TestClient(api.app) as c:
        assert c.get("/api/health").json()["data_loaded"] is False
        r = c.get("/api/brief")
        assert r.status_code == 503 and "not loaded" in r.json()["message"]
        assert c.get("/api/meta").status_code == 200


def test_noindex_everywhere_and_robots_txt(client):
    for path in ("/", "/api/meta", "/robots.txt", "/api/signals/nope", "/no-such-page"):
        assert client.get(path).headers["x-robots-tag"] == "noindex, nofollow"
    assert '<meta name="robots" content="noindex">' in client.get("/").text
    assert client.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"


def test_no_cors(client):
    r = client.get("/api/meta", headers={"Origin": "https://elsewhere.example"})
    assert "access-control-allow-origin" not in r.headers


def test_rate_limit_per_forwarded_ip(client, monkeypatch):
    monkeypatch.setattr(C, "RATE_LIMIT_PER_MIN", 2)
    judge = {"X-Forwarded-For": "198.51.100.7, 203.0.113.9"}  # the proxy appended the last entry
    assert [client.get("/api/meta", headers=judge).status_code for _ in range(2)] == [200, 200]
    r = client.get("/api/meta", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited" and r.headers["x-robots-tag"]
    assert client.get("/api/meta", headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200
    assert client.get("/").status_code == 200  # the static UI is not counted


def test_bad_session_header(client):
    r = client.get("/api/alerts", headers={C.SESSION_HEADER: "x"})
    assert r.status_code == 400 and "X-Demo-Session" in r.json()["message"]


@pytest.mark.parametrize("query, message", [
    ("as_of=2026-03-25", "must be a Sunday"),
    ("as_of=yesterday", "must be a date"),
    ("monday=2026-03-08", "must be a Monday"),
    ("as_of=2024-10-20", "replay range"),
    ("as_of=2026-10-04", "replay range"),
    ("as_of=2026-03-29&monday=2026-03-30", "not both"),
])
def test_bad_as_of_is_a_clear_400(client, query, message):
    r = client.get(f"/api/brief?{query}")
    assert r.status_code == 400 and message in r.json()["message"]


# --------------------------------------------------------------------------- brief, replay, case file, feed
def test_brief_has_the_icu_mrsa_p1(client):
    b = client.get("/api/brief?as_of=2026-03-29").json()
    assert b["as_of"] == "2026-03-29" and b["monday"] == "2026-03-30" and b["counts"]["P1"] == 1
    p1 = items(b)[ICU_CLUSTER]
    assert (p1["priority"], p1["ward"], p1["kind"]) == ("P1", "ICU", "phenotype_cluster")
    assert all("alert" in i and "heads_up" in i for i in items(b).values())
    assert client.get("/api/brief?monday=2026-03-30").json()["counts"] == b["counts"]


def test_demo_monday_brief_links_the_seeded_alert(client):
    b = items(client.get("/api/brief?monday=2026-03-09").json())
    assert b[ICU_CLUSTER]["alert"]["id"] == "seed-icu-mrsa-2026"
    assert all(i["alert"] is None for k, i in b.items() if k != ICU_CLUSTER and i["kind"] == "phenotype_cluster")


def test_my_ward_icu_has_banners_and_signals(client):
    w = client.get("/api/my-ward?as_of=2026-03-15&ward=ICU").json()
    assert w["filters"]["ward"] == "ICU" and w["rows"]
    assert [b["id"] for b in w["banners"]] == ["seed-icu-mrsa-2026"]
    assert ICU_CLUSTER in [s["id"] for s in w["signals"]]
    assert client.get("/api/my-ward?as_of=2026-03-15&ward=NOPE").status_code == 400


def test_replay_weeks_cover_the_range_and_use_precomputed_counts(client, ds):
    weeks = client.get("/api/replay/weeks").json()
    assert (weeks[0]["as_of"], weeks[-1]["as_of"]) == ("2024-10-27", C.DATA_END) and len(weeks) == 101
    assert weeks[0]["monday"] == "2024-10-28" and weeks[0]["n_p1"] is None  # not precomputed yet
    precompute.warm_signals(ds, ["2026-03-29"])
    tick = next(w for w in client.get("/api/replay/weeks").json() if w["as_of"] == "2026-03-29")
    assert tick["n_p1"] == 1 and tick["n_signals"] >= 1


def test_case_file(client):
    f = client.get(f"/api/signals/{ICU_CLUSTER}?as_of=2026-03-29").json()
    assert f["signal"]["id"] == ICU_CLUSTER and f["line_list"]["n"] == 13
    row = f["line_list"]["rows"][0]
    assert set(row) == {"isolate_id", "date", "ward", "care_day", "specimen", "organism", "profile"}
    assert all(r["date"] <= "2026-03-29" and r["ward"] == "ICU" for r in f["line_list"]["rows"])
    curve = f["epi_curve"]
    assert (curve[0]["date"], curve[-1]["date"], sum(d["n"] for d in curve)) == ("2026-03-03", "2026-03-29", 13)
    assert [s["kind"] for s in f["seen_before"]] == ["seen_before"]
    assert f["seen_before"][0]["slots"]["n_elsewhere"] == 11
    assert f["stepup"]["positive"] is True and f["alerts"] == [] and f["heads_ups"] == []


def test_case_file_is_strictly_as_of(client):
    assert client.get(f"/api/signals/{ICU_CLUSTER}?as_of=2026-03-01").status_code == 404  # first sample 3 Mar


def test_feed_counts_by_unit(client):
    f = client.get("/api/feed?as_of=2026-03-15").json()
    assert (f["from"], f["to"], f["refreshed"]) == ("2026-03-09", "2026-03-15", "nightly")
    assert [u["ward"] for u in f["units"]] == list(C.WARD_LABELS)
    assert f["totals"]["isolates"] == sum(u["isolates"] for u in f["units"]) > 0


# --------------------------------------------------------------------------- alerts and heads-ups per session
def test_approved_alert_reaches_brief_my_ward_and_orders_for_that_session_only(client):
    r = approve(client)
    assert r.status_code == 201
    alert = r.json()
    assert (alert["approved_on"], alert["organism"], alert["signal_id"]) == ("2026-03-30", "Staphylococcus aureus",
                                                                              ICU_CLUSTER)
    assert [a["id"] for a in client.get("/api/alerts?as_of=2026-03-29").json()] == [alert["id"]]
    assert client.get("/api/alerts?as_of=2026-03-29", headers=AS_B).json() == []
    assert client.get("/api/alerts?as_of=2026-03-22").json()[0]["id"] == "seed-icu-mrsa-2026"  # strict as-of

    assert items(client.get("/api/brief?as_of=2026-03-29").json())[ICU_CLUSTER]["alert"]["id"] == alert["id"]
    assert items(client.get("/api/brief?as_of=2026-03-29", headers=AS_B).json())[ICU_CLUSTER]["alert"] is None
    banners = client.get("/api/my-ward?as_of=2026-03-29&ward=ICU").json()["banners"]
    assert [b["id"] for b in banners] == [alert["id"]]

    mine = order(client).json()
    assert (mine["state"], mine["source"]["id"]) == ("warning", alert["id"])
    assert order(client, stage="select").json()["state"] == "info"
    assert order(client, headers=AS_B).json()["state"] != "warning"

    revoked = client.post(f"/api/alerts/{alert['id']}/revoke", json={"as_of": "2026-03-29"}).json()
    assert revoked["revoked_on"] == "2026-03-30"
    assert client.get("/api/alerts?as_of=2026-03-29").json() == []
    assert order(client).json()["state"] != "warning"


def test_alert_needs_a_signal_that_exists_then(client):
    assert approve(client, as_of="2026-03-01").status_code == 404
    assert approve(client, wards=["NOPE"]).status_code == 400
    assert client.post("/api/alerts/alr-unknown/revoke", json={"as_of": "2026-03-29"}).status_code == 404


def test_heads_up_is_drafted_approved_and_never_sent(client):
    r = client.post("/api/heads-up", json={"signal_id": ICU_CLUSTER, "as_of": "2026-03-29"})
    assert r.status_code == 201
    draft = r.json()
    assert (draft["status"], draft["audience"], draft["delivery"]) == ("draft", "ed", store.NOT_SENT)
    assert "ICU" in draft["text"] and draft["validated"] is True
    approved = client.post(f"/api/heads-up/{draft['id']}/approve").json()
    assert (approved["status"], approved["delivery"]) == ("approved", "not sent (demo)")
    assert items(client.get("/api/brief?as_of=2026-03-29").json())[ICU_CLUSTER]["heads_up"]["status"] == "approved"
    assert client.post(f"/api/heads-up/{draft['id']}/approve", headers=AS_B).status_code == 404


def test_write_cap_is_a_friendly_429(client, monkeypatch):
    monkeypatch.setattr(C, "MAX_WRITES_PER_SESSION", 1)
    assert approve(client).status_code == 201
    r = approve(client)
    assert r.status_code == 429 and r.json()["error"] == "write_limit" and "new tab" in r.json()["message"]
    other = approve(client, headers=AS_B, wards=[])
    assert other.status_code == 201 and other.json()["wards"] == ["ICU"]  # per session; wards default to the signal's


def test_narrate_and_validate(client):
    n = client.post("/api/narrate", json={"signal_id": ICU_CLUSTER, "as_of": "2026-03-29"}).json()
    assert n["provider"] == "template" and n["validated"] is True and n["text"]
    bad = client.post("/api/validate", json={"text": "13 patients, {n} share it", "slots": {"n": 12}}).json()
    assert bad["ok"] is False
    good = client.post("/api/validate", json={"text": "12 of 13", "slots": {"x": [12, 13]}, "mode": "rendered"})
    assert good.json()["ok"] is True


def test_second_opinion_is_not_configured(client):
    assert client.get(f"/api/second-opinion/{ICU_CLUSTER}?as_of=2026-03-29").json() == {"status": "not_configured"}


# --------------------------------------------------------------------------- the doctor's order view
@pytest.mark.parametrize("key", list(SCENARIOS))
def test_order_context_for_each_demo_scenario(client, key):
    s = SCENARIOS[key]
    body = {k: s[k] for k in ("as_of", "patient_id", "unit", "indication", "drug")}
    ctx = client.post("/api/order-context", json={**body, "stage": "sign"}).json()
    assert ctx["state"] == s["expect"]
    if s["expect"] == "warning":
        assert client.post("/api/order-context", json=body).json()["state"] == "info"  # select never interrupts


def test_demo_scenarios_carry_their_state(client):
    got = {s["key"]: s["state"] for s in client.get("/api/demo/scenarios").json()}
    assert got == {k: s["expect"] for k, s in SCENARIOS.items()}


def test_bad_orders_and_unknown_patients(client):
    assert order(client, drug="XYZ").status_code == 422
    assert client.get("/api/patients/P999999/history?as_of=2026-03-15").status_code == 404
    h = client.get("/api/patients/P008135/history?as_of=2026-03-15").json()
    assert h["previous_results"][0]["date"] == "2026-01-16"
    assert all(r["date"] <= "2026-03-15" for r in h["previous_results"])


def test_order_feedback_summary(client):
    shown = {"as_of": "2026-03-15", "card_key": "card-1", "source_id": "own_history", "state": "warning"}
    assert client.post("/api/order-feedback", json={**shown, "outcome": "shown"}).json()["logged"] is True
    assert client.post("/api/order-feedback", json={**shown, "outcome": "shown"}).json()["logged"] is False
    client.post("/api/order-feedback", json={**shown, "outcome": "change", "changed_to": "NIT"})
    summary = client.get("/api/order-feedback/summary?as_of=2026-03-15").json()
    assert summary[0]["text"] == "shown 1 time, changed 1"
    assert client.get("/api/feedback?as_of=2026-03-15").json() == summary
    assert client.get("/api/order-feedback/summary?as_of=2026-03-15", headers=AS_B).json() == []


# --------------------------------------------------------------------------- CDS Hooks
def hook_request(hook, scenario="ed-own-history"):
    s = SCENARIOS[scenario]
    atc = next(a for d, _, a in C.ORDER_DRUGS if d == s["drug"])
    medication = {"resourceType": "MedicationRequest", "id": "mr-1", "status": "draft", "intent": "order",
                  "medicationCodeableConcept": {"coding": [{"system": cds.ATC_SYSTEM, "code": atc}]}}
    return {"hookInstance": "d1577c69-dfbe-44ad-ba6d-3e05e953b2ea", "hook": hook,
            "context": {"userId": "Practitioner/1", "patientId": s["patient_id"], "encounterId": "Encounter/1",
                        "selections": ["MedicationRequest/mr-1"],
                        "draftOrders": {"resourceType": "Bundle", "entry": [{"resource": medication}]},
                        "extension": {f"{cds.SLUG}.unit": s["unit"], f"{cds.SLUG}.indication": s["indication"],
                                      f"{cds.SLUG}.as_of": s["as_of"]}}}


def test_cds_discovery_and_an_order_sign_warning(client):
    services = {s["hook"]: s["id"] for s in client.get("/cds-services").json()["services"]}
    assert set(services) == {"order-select", "order-sign"}
    cards = client.post(f"/cds-services/{services['order-sign']}", json=hook_request("order-sign")).json()["cards"]
    assert [c["indicator"] for c in cards] == ["warning"]
    assert all(link["url"].startswith("http://testserver/") for link in cards[0]["links"])
    select = client.post(f"/cds-services/{services['order-select']}", json=hook_request("order-select")).json()
    assert [c["indicator"] for c in select["cards"]] == ["info"]

    feedback = {"feedback": [{"card": cards[0]["uuid"], "outcome": "overridden",
                              "overrideReason": {"reason": {"code": "keep"}, "userComment": "free text, dropped"},
                              "outcomeTimestamp": "2026-03-15T10:00:00Z"}]}
    assert client.post(f"/cds-services/{services['order-sign']}/feedback", json=feedback).json() == {"logged": 1}
    summary = client.get("/api/order-feedback/summary?as_of=2026-03-15").json()
    own = next(s for s in summary if s["source_id"] == "own_history")
    assert (own["shown"], own["kept"]) == (2, 1)  # the select (info) and sign (warning) cards, one kept


def test_cds_errors(client):
    assert client.post("/cds-services/nope", json=hook_request("order-sign")).status_code == 404
    sign = next(s["id"] for s in cds.SERVICES if s["hook"] == "order-sign")
    assert client.post(f"/cds-services/{sign}", json=hook_request("order-select")).status_code == 422
    assert client.post(f"/cds-services/{sign}", json={"hook": "order-sign"}).status_code == 422


def test_brief_cache_is_used(client, cache_dir):
    client.get("/api/brief?as_of=2026-03-29")
    assert (cache_dir / "signals" / "2026-03-29.json").exists()
    brief.clear_memory_cache()
    assert client.get("/api/brief?as_of=2026-03-29").json()["counts"]["P1"] == 1
