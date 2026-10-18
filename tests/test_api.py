"""The HTTP API end to end (offline): as-of handling, the brief and case file, per-session alerts and heads-ups, the
order screen and CDS Hooks, write and rate limits, and the public-demo headers."""

import pytest
from fastapi.testclient import TestClient

from aei import api, brief, cds, cds_hooks, data, i18n, precompute, store, views
from aei import config as C

A, B = "visitor-aaaa-0001", "visitor-bbbb-0002"
ICU_CLUSTER = "phe-7972cb3f12"  # ICU MRSA 2026, pattern FOX:R VAN:S CLI:R, first sample 3 Mar 2026
URO_CLUSTER = "phe-d06c1ec1c5"  # URO ESBL E. coli 2025, first sample 30 May 2025
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
    for name in ("AEI_NARRATOR", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    api.LIMITER.hits.clear()
    with TestClient(api.app, headers={C.SESSION_HEADER: A}) as c:
        yield c


def items(brief_json):
    return {i["id"]: i for s in brief_json["sections"] for i in s["items"]}


def approve(client, headers=None, **body):
    payload = {
        "signal_id": ICU_CLUSTER,
        "as_of": "2026-03-29",
        "wards": ["ICU"],
        "drugs": ["CXM", "CRO"],
        "message": "Possible MRSA cluster, ICU. Typing advised.",
        **body,
    }
    return client.post("/api/alerts", json=payload, headers=headers)


def order(client, headers=None, **body):
    payload = {"as_of": "2026-03-29", "unit": "ICU", "indication": "wound", "drug": "CXM", "stage": "sign", **body}
    return client.post("/api/order-context", json=payload, headers=headers)


# --------------------------------------------------------------------------- meta, health, headers
def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["app_name"] == C.APP_NAME and m["synthetic"] is True
    assert m["replay"] == {"first": "2024-10-27", "last": C.DATA_END}
    assert m["demo_mondays"] == C.DEMO_MONDAYS
    assert {w["code"] for w in m["wards"]} == set(C.WARD_LABELS) and m["narrator"] == "template"
    assert m["tour_start_as_of"] == C.TOUR_START_AS_OF and [i["key"] for i in m["indications"]] == list(C.INDICATIONS)
    assert m["cds_hooks"]["discovery"] == "/cds-services" and "no EHR is connected" in m["cds_hooks"]["note"]


def test_health_never_contains_a_key(client, monkeypatch):
    secret = "sk-ant-test-not-a-real-key-0123456789"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    r = client.get("/api/health")
    assert r.json() | {"spend_today_usd": 0} == {
        "ok": True,
        "app_name": C.APP_NAME,
        "data_loaded": True,
        "narrator": "template",
        "key_set": True,
        "spend_today_usd": 0,
        "cap_usd": C.DAILY_SPEND_USD,
    }
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
    assert '<meta name="robots" content="noindex' in client.get("/").text  # the UI shell adds nofollow
    assert client.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"


def test_no_cors(client):
    r = client.get("/api/meta", headers={"Origin": "https://elsewhere.example"})
    assert "access-control-allow-origin" not in r.headers


def test_rate_limit_per_forwarded_ip(client, monkeypatch):
    monkeypatch.setattr(C, "RATE_LIMIT_PER_MIN", 2)
    viewer = {"X-Forwarded-For": "198.51.100.7, 203.0.113.9"}  # the proxy appended the last entry
    assert [client.get("/api/meta", headers=viewer).status_code for _ in range(2)] == [200, 200]
    r = client.get("/api/meta", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited" and r.headers["x-robots-tag"]
    assert client.get("/api/meta", headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200
    assert client.get("/").status_code == 200  # the static UI is not counted


def test_an_unexpected_error_is_a_plain_json_500(client, monkeypatch):
    def broken(*_):
        raise RuntimeError("internal detail: /srv/aei/views.py")

    monkeypatch.setattr(views, "filters_catalog", broken)
    r = client.get("/api/filters")
    assert r.status_code == 500 and r.json()["error"] == "server_error" and "internal detail" not in r.text
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get("/api/meta").status_code == 200


def test_request_bodies_are_capped(client):
    json_type = {"Content-Type": "application/json"}
    big = client.post(
        "/api/order-feedback", content=b'{"card_key": "' + b"x" * api.MAX_BODY_BYTES + b'"}', headers=json_type
    )
    assert big.status_code == 413 and big.json()["error"] == "too_large" and big.headers["x-robots-tag"]
    chunked = client.post("/api/order-feedback", content=iter([b'{"card_key": "x"}']), headers=json_type)
    assert chunked.status_code == 413  # no declared length
    small = {"as_of": "2026-03-15", "card_key": "card-1", "state": "info", "outcome": "shown"}
    assert client.post("/api/order-feedback", json=small).status_code == 200


def test_bad_session_header(client):
    r = client.get("/api/alerts", headers={C.SESSION_HEADER: "x"})
    assert r.status_code == 400 and "X-Demo-Session" in r.json()["message"]


def test_writes_need_a_session_and_a_reader_without_one_sees_the_seeds_only(client):
    anon = TestClient(api.app)  # no X-Demo-Session, like curl or an EHR
    revoke = anon.post("/api/alerts/seed-uro-esbl-2025/revoke", json={"as_of": "2025-06-08"})
    assert revoke.status_code == 400 and C.SESSION_HEADER in revoke.json()["message"]
    assert approve(anon).status_code == 400
    assert anon.post("/api/heads-up", json={"signal_id": ICU_CLUSTER, "as_of": "2026-03-29"}).status_code == 400
    shown = {
        "as_of": "2026-03-15",
        "card_key": "card-1",
        "source_id": "own_history",
        "state": "warning",
        "outcome": "shown",
    }
    assert anon.post("/api/order-feedback", json=shown).status_code == 400

    mine = approve(client, as_of="2026-03-15").json()["id"]
    assert [a["id"] for a in anon.get("/api/alerts?as_of=2026-03-15").json()] == ["seed-icu-mrsa-2026"]
    assert mine in [a["id"] for a in client.get("/api/alerts?as_of=2026-03-15").json()]
    got = {s["key"]: s["state"] for s in anon.get("/api/demo/scenarios").json()}
    assert got == {k: s["expect"] for k, s in SCENARIOS.items()}  # the refused revoke changed nothing


@pytest.mark.parametrize(
    "query, message",
    [
        ("as_of=2026-03-25", "must be a Sunday"),
        ("as_of=yesterday", "must be a date"),
        ("monday=2026-03-08", "must be a Monday"),
        ("as_of=2024-10-20", "replay range"),
        ("as_of=2026-10-04", "replay range"),
        ("as_of=2026-03-29&monday=2026-03-30", "not both"),
    ],
)
def test_bad_as_of_is_a_clear_400(client, query, message):
    r = client.get(f"/api/brief?{query}")
    assert r.status_code == 400 and message in r.json()["message"]


# --------------------------------------------------------------------------- brief, replay, case file
def test_brief_has_the_icu_mrsa_p1(client):
    b = client.get("/api/brief?as_of=2026-03-29").json()
    assert b["as_of"] == "2026-03-29" and b["monday"] == "2026-03-30" and b["counts"]["P1"] == 1
    p1 = items(b)[ICU_CLUSTER]
    assert (p1["priority"], p1["ward"], p1["kind"]) == ("P1", "ICU", "phenotype_cluster")
    assert all("alert" in i and "heads_up" in i for i in items(b).values())
    assert client.get("/api/brief?monday=2026-03-30").json()["counts"] == b["counts"]
    [line] = b["policy_states"]  # the policy section has its line even in a week it is not crossed
    assert (line["id"], line["active"], line["as_of"]) == ("tmp_uti_women_20", False, "2026-03-29")


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


def test_my_ward_shows_the_trimethoprim_line_on_urine_views_only(client):
    def banners(specimen):
        view = client.get(f"/api/my-ward?as_of=2026-06-21&ward=ED&specimen={specimen}").json()
        return [b["id"] for b in view["banners"]]

    assert banners("urine") == ["tmp_uti_women_20"]
    assert banners("blood_wound") == banners("wound") == []  # the line is about urinary E. coli


def test_my_ward_never_names_another_drug(client):
    """The trimethoprim line flags trimethoprim and names no alternative."""
    for lang in ("en", "fi"):
        view = client.get(f"/api/my-ward?as_of=2026-06-21&ward=PHC-N&specimen=urine&lang={lang}").json()
        [line] = [s for s in view["signals"] if s["kind"] == "policy_line"]
        assert "alternative" not in line["slots"]
        for text in [line["text"], *(b["text"] for b in view["banners"])]:
            assert not {"pivmecillinam", "pivmesillinaami", "mecillinam", "alternative", "vaihtoehto"} & set(
                text.lower().replace(".", " ").replace(":", " ").split()
            ), text
    assert "local_guide_alternative" not in client.get("/api/brief?as_of=2026-06-21").json()["policy_states"][0]


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
    assert f["stepup"]["positive"] is True and f["heads_ups"] == []
    # the timeline keeps the seed approved 9 Mar after it lapsed on 23 Mar
    assert [(a["id"], a["approved_on"], a["expires_on"], a["expired"]) for a in f["alerts"]] == [
        ("seed-icu-mrsa-2026", "2026-03-09", "2026-03-23", True)
    ]


def test_case_file_is_strictly_as_of(client):
    assert client.get(f"/api/signals/{ICU_CLUSTER}?as_of=2026-03-01").status_code == 404  # first sample 3 Mar


# --------------------------------------------------------------------------- alerts and heads-ups per session
def test_approved_alert_reaches_brief_my_ward_and_orders_for_that_session_only(client):
    r = approve(client)
    assert r.status_code == 201
    alert = r.json()
    assert (alert["approved_on"], alert["organism"], alert["signal_id"]) == (
        "2026-03-30",
        "Staphylococcus aureus",
        ICU_CLUSTER,
    )
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
    timeline = client.get("/api/alerts?as_of=2026-03-29&include_expired=1").json()
    assert [(a["id"], a["expired"], a["revoked_on"]) for a in timeline] == [
        ("seed-uro-esbl-2025", True, None),
        ("seed-icu-mrsa-2026", True, None),
        (alert["id"], False, "2026-03-30"),
    ]


def test_an_alert_scoped_to_indications_is_a_notice_for_the_others(client):
    alert = approve(client, indications=["bloodstream"]).json()
    assert alert["indications"] == ["bloodstream"]
    assert order(client, indication="bloodstream").json()["state"] == "warning"
    wound = order(client).json()
    assert (wound["state"], wound["source"]["id"]) == ("notice", alert["id"])
    assert approve(client, indications=["pneumonia"]).status_code == 400


@pytest.mark.parametrize(
    "signal_id, as_of, seed_id",
    [(ICU_CLUSTER, "2026-03-08", "seed-icu-mrsa-2026"), (URO_CLUSTER, "2025-06-08", "seed-uro-esbl-2025")],
)
def test_an_approved_cluster_alert_keeps_its_antibiogram_like_the_seed(client, signal_id, as_of, seed_id):
    alert = approve(client, signal_id=signal_id, as_of=as_of, wards=[]).json()
    seed = next(a for a in client.get(f"/api/alerts?as_of={as_of}").json() if a["id"] == seed_id)
    for key in ("resistant_to", "wards", "profile", "marker"):
        assert alert[key] == seed[key], key


def test_alert_needs_a_signal_that_exists_then(client):
    assert approve(client, as_of="2026-03-01").status_code == 404
    assert approve(client, wards=["NOPE"]).status_code == 400
    assert client.post("/api/alerts/alr-unknown/revoke", json={"as_of": "2026-03-29"}).status_code == 404


def test_alert_input_is_checked(client):
    for change in (
        {"expires_on": "9999-12-31"},
        {"approved_by_role": "ward_doctor"},
        {"message": "MRSA\u202e"},
        {"message": "MRSA\x00"},
    ):
        r = approve(client, **change)
        assert r.status_code == 400 and r.json()["error"] == "bad_request", change
    assert approve(client, wards=["ICU", "ICU"]).json()["wards"] == ["ICU"]


def test_revoke_needs_an_active_alert_and_no_body(client):
    alert = approve(client).json()  # from the brief of 30 Mar 2026
    r = client.post(f"/api/alerts/{alert['id']}/revoke", json={"as_of": "2026-03-08"})
    assert r.status_code == 400 and "not active" in r.json()["message"]  # before the alert existed
    assert [a["id"] for a in client.get("/api/alerts?as_of=2026-03-29").json()] == [alert["id"]]
    latest = approve(client, signal_id=None, as_of=C.DATA_END).json()
    revoked = client.post(f"/api/alerts/{latest['id']}/revoke")  # no body: the last data week
    assert revoked.status_code == 200 and revoked.json()["revoked_on"] == "2026-09-28"


def test_heads_up_is_drafted_approved_and_never_sent(client):
    r = client.post("/api/heads-up", json={"signal_id": ICU_CLUSTER, "as_of": "2026-03-29"})
    assert r.status_code == 201
    draft = r.json()
    assert (draft["status"], draft["audience"], draft["delivery"]) == ("draft", "ed", store.NOT_SENT)
    assert draft["validated"] is True and draft["text"] == (
        "Heads-up from infection control: possible MRSA cluster on Intensive care unit (ICU). 13 patients since 3 Mar; "
        "12 of 13 share the same antibiogram: cefoxitin R, vancomycin S, clindamycin R. Under investigation; typing "
        "advised. Dates are sample dates."
    )  # drug names, never panel codes such as FOX:R
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


def test_order_drugs_per_indication(client):
    uti = {d["drug"] for d in client.get("/api/order-drugs?indication=uti").json()}
    wound = {d["drug"] for d in client.get("/api/order-drugs?indication=wound").json()}
    assert uti == {d for d, _, _ in C.ORDER_DRUGS}  # every order drug has reported urine results
    assert wound == uti - C.URINE_ONLY
    assert client.get("/api/order-drugs?indication=nope").status_code == 422


def test_bad_orders_and_unknown_patients(client):
    assert order(client, drug="XYZ").status_code == 422
    assert client.get("/api/patients/P999999/history?as_of=2026-03-15").status_code == 404
    h = client.get("/api/patients/P008135/history?as_of=2026-03-15").json()
    assert h["previous_results"][0]["date"] == "2026-01-16"
    assert all(r["date"] <= "2026-03-15" for r in h["previous_results"])


def test_a_keep_reason_shown_in_finnish_is_accepted(client):
    keep = {"as_of": "2026-03-15", "card_key": "card-fi", "state": "warning", "outcome": "keep"}
    reason = i18n.label(C.KEEP_REASONS[0], "fi")
    assert reason != C.KEEP_REASONS[0]
    assert client.post("/api/order-feedback", json={**keep, "reason": reason}).json()["logged"] is True


def test_order_feedback_summary(client):
    shown = {"as_of": "2026-03-15", "card_key": "card-1", "source_id": "own_history", "state": "warning"}
    assert client.post("/api/order-feedback", json={**shown, "outcome": "shown"}).json()["logged"] is True
    assert client.post("/api/order-feedback", json={**shown, "outcome": "shown"}).json()["logged"] is False
    client.post("/api/order-feedback", json={**shown, "outcome": "edit"})
    client.post("/api/order-feedback", json={**shown, "outcome": "change", "changed_to": "NIT"})
    summary = client.get("/api/order-feedback/summary?as_of=2026-03-15").json()
    assert summary[0]["text"] == "shown 1 time, changed 1" and summary[0]["edited"] == 1
    assert client.get("/api/order-feedback/summary?as_of=2026-03-15", headers=AS_B).json() == []


# --------------------------------------------------------------------------- CDS Hooks
def hook_request(hook, scenario="ed-own-history"):
    s = SCENARIOS[scenario]
    atc = next(a for d, _, a in C.ORDER_DRUGS if d == s["drug"])
    medication = {
        "resourceType": "MedicationRequest",
        "id": "mr-1",
        "status": "draft",
        "intent": "order",
        "medicationCodeableConcept": {"coding": [{"system": cds_hooks.ATC_SYSTEM, "code": atc}]},
    }
    return {
        "hookInstance": "d1577c69-dfbe-44ad-ba6d-3e05e953b2ea",
        "hook": hook,
        "context": {
            "userId": "Practitioner/1",
            "patientId": s["patient_id"],
            "encounterId": "Encounter/1",
            "selections": ["MedicationRequest/mr-1"],
            "draftOrders": {"resourceType": "Bundle", "entry": [{"resource": medication}]},
            "extension": {
                f"{cds.SLUG}.unit": s["unit"],
                f"{cds.SLUG}.indication": s["indication"],
                f"{cds.SLUG}.as_of": s["as_of"],
            },
        },
    }


def test_cds_discovery_and_an_order_sign_warning(client):
    services = {s["hook"]: s["id"] for s in client.get("/cds-services").json()["services"]}
    assert set(services) == {"order-select", "order-sign"}
    cards = client.post(f"/cds-services/{services['order-sign']}", json=hook_request("order-sign")).json()["cards"]
    assert [c["indicator"] for c in cards] == ["warning"]
    assert all(link["url"].startswith("http://testserver/") for link in cards[0]["links"])
    assert [link["label"] for link in cards[0]["links"]] == [cds.DETAILS_LABEL]  # no SMART launch
    assert "suggestions" not in cards[0]  # the card never names another drug
    select = client.post(f"/cds-services/{services['order-select']}", json=hook_request("order-select")).json()
    assert [c["indicator"] for c in select["cards"]] == ["info"]

    feedback = {
        "feedback": [
            {
                "card": cards[0]["uuid"],
                "outcome": "overridden",
                "overrideReason": {"reason": {"code": "keep"}, "userComment": "free text, dropped"},
                "outcomeTimestamp": "2026-03-15T10:00:00Z",
            }
        ]
    }
    assert client.post(f"/cds-services/{services['order-sign']}/feedback", json=feedback).json() == {"logged": 1}
    summary = client.get("/api/order-feedback/summary?as_of=2026-03-15").json()
    own = next(s for s in summary if s["source_id"] == "own_history")
    assert (own["shown"], own["kept"]) == (2, 1)  # the select (info) and sign (warning) cards, one kept


def test_cds_without_a_session_is_logged_but_changes_nothing(client):
    anon = TestClient(api.app)  # an EHR sends no X-Demo-Session
    sign = next(s["id"] for s in cds_hooks.SERVICES if s["hook"] == "order-sign")
    cards = anon.post(f"/cds-services/{sign}", json=hook_request("order-sign", "uro-esbl")).json()["cards"]
    assert [(c["indicator"], c["extension"][f"{cds.SLUG}.source"]["id"]) for c in cards] == [
        ("warning", "seed-uro-esbl-2025")
    ]
    feedback = {
        "feedback": [
            {"card": cards[0]["uuid"], "outcome": "overridden", "overrideReason": {"reason": {"code": "keep"}}}
        ]
    }
    assert anon.post(f"/cds-services/{sign}/feedback", json=feedback).json() == {"logged": 1}
    [logged] = store.feedback_summary(store.ANONYMOUS, "2025-06-15")
    assert (logged["shown"], logged["kept"]) == (1, 1)
    summary = "/api/order-feedback/summary?as_of=2025-06-15"
    assert anon.get(summary).json() == client.get(summary).json() == []
    again = anon.post(f"/cds-services/{sign}", json=hook_request("order-sign", "uro-esbl")).json()["cards"]
    assert [c["indicator"] for c in again] == ["warning"]


def test_cds_errors(client):
    assert client.post("/cds-services/nope", json=hook_request("order-sign")).status_code == 404
    sign = next(s["id"] for s in cds_hooks.SERVICES if s["hook"] == "order-sign")
    assert client.post(f"/cds-services/{sign}", json=hook_request("order-select")).status_code == 422
    assert client.post(f"/cds-services/{sign}", json={"hook": "order-sign"}).status_code == 422
    listed = hook_request("order-sign")
    listed["context"]["patientId"] = ["P000001", "P000002"]
    r = client.post(f"/cds-services/{sign}", json=listed)
    assert r.status_code == 422 and "Lengths" not in r.text  # was pandas' message
    for reason in ("keep", ["keep"]):  # a reason must be a Coding object; both were a 500
        item = {"card": "abc", "outcome": "overridden", "overrideReason": {"reason": reason}}
        r = client.post(f"/cds-services/{sign}/feedback", json={"feedback": [item]})
        assert r.status_code == 422 and r.json()["error"] == "invalid_request" and r.headers["x-robots-tag"]


def test_brief_cache_is_used(client, cache_dir):
    client.get("/api/brief?as_of=2026-03-29")
    assert (cache_dir / "signals" / "2026-03-29.json").exists()
    brief.clear_memory_cache()
    assert client.get("/api/brief?as_of=2026-03-29").json()["counts"]["P1"] == 1
