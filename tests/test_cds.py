"""The order context and CDS Hooks cards (CONTRACTS.md 7 and 7b): demo scenarios, select vs sign, card shape."""
import subprocess
import sys
from pathlib import Path

import pytest

from aei import cds, store
from aei import config as C
from aei.detectors.policy import policy_states

SCENARIOS = {s["key"]: s for s in C.DEMO_SCENARIOS}
TMP_SUMMARY = "Trimethoprim: 20.4% resistant (160 of 786, last 52 weeks), above local 20% line"


@pytest.fixture(autouse=True)
def seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE_DB", tmp_path / "state.sqlite")
    store.reset()
    store.seed_demo()
    return store.alerts("judge-cccc-0003")


def _context(ds, seeds, key, stage="sign", **change):
    s = {**SCENARIOS[key], **change}
    return cds.order_context(ds, s["as_of"], s["patient_id"], s["unit"], s["indication"], s["drug"], stage, seeds,
                             policy_states(ds, s["as_of"]))


@pytest.mark.parametrize("key", SCENARIOS)
def test_demo_scenarios_reach_their_expected_state(ds, seeds, key):
    expect = SCENARIOS[key]["expect"]
    signed = _context(ds, seeds, key, "sign")
    assert (signed["state"], signed["interruptive"]) == (expect, expect == "warning")
    selected = _context(ds, seeds, key, "select")
    assert selected["state"] == ("info" if expect == "warning" else expect)
    assert not selected["interruptive"]
    if expect == "warning":
        assert cds.SIGN_NOTE in selected["rule"]
    assert len(signed["lines"]) <= 3


def test_previous_results_come_first_and_own_resistance_warns(ds, seeds):
    ctx = _context(ds, seeds, "ed-own-history")
    assert list(ctx).index("previous_results") < list(ctx).index("lines")
    first = ctx["previous_results"][0]
    assert (first["date"], first["organism"], first["drug_result"], first["reason"]) == (
        "2026-01-16", "Escherichia coli", "R", "reported")
    assert ctx["source"]["kind"] == "own_history"
    assert "TMP" not in ctx["actions"]["change_to"]  # never offered back as an alternative


def test_no_data_looks_different_from_quiet(ds, seeds):
    no_data = cds.order_context(ds, "2026-03-15", None, "URO", "bloodstream", "MEM", "sign", seeds, [])
    assert no_data["state"] == "no_data"
    assert no_data["chip"] == "Not enough data on URO for meropenem (n = 9, 12 months)"
    quiet = _context(ds, seeds, "medb-quiet")
    assert quiet["chip"] == "No active alerts · MED-B · data to 15 Mar"
    assert cds.card(quiet) is None and cds.card(no_data) is None


def test_nothing_after_as_of_speaks(ds, seeds):
    early = _context(ds, seeds, "uro-esbl", as_of="2025-06-01")  # the URO alert is approved on 9 Jun
    assert early["state"] != "warning"
    assert "seed-uro-esbl-2025" not in {r["id"] for r in early["evidence"]["reasons"]}
    s = SCENARIOS["phc-tmp"]
    later_policy = policy_states(ds, "2026-06-21")
    ctx = cds.order_context(ds, "2026-06-14", s["patient_id"], s["unit"], "uti", "TMP", "sign", seeds, later_policy)
    assert "tmp_uti_women_20" not in {r["id"] for r in ctx["evidence"]["reasons"]}


def test_alert_on_the_unit_for_another_drug_is_info_only(ds, seeds):
    ctx = _context(ds, seeds, "icu-mrsa", drug="VAN")
    assert ctx["state"] == "info" and ctx["source"]["id"] == "seed-icu-mrsa-2026"
    assert "not this drug" in ctx["rule"]


def test_alternatives_skip_drugs_an_active_alert_covers(ds, seeds):
    ctx = _context(ds, seeds, "icu-mrsa")
    assert "FOX" not in ctx["actions"]["change_to"]  # flucloxacillin is a beta-lactam: covered by the MRSA alert


def test_trimethoprim_policy_card(ds, seeds):
    s = SCENARIOS["phc-tmp"]
    [card] = cds.order_check(ds, s["as_of"], s["unit"], "TMP", "uti", seeds, policy_states(ds, s["as_of"]),
                             patient_id=s["patient_id"])
    assert card["summary"] == TMP_SUMMARY and len(card["summary"]) <= 140
    assert card["indicator"] == "info"
    assert card["source"] == {"label": f"{C.APP_NAME} · infection control"}
    detail = card["detail"]
    assert detail.startswith("**This patient's results")
    for text in ("12 months earlier: 15.9%", "crossed week ending 21 Jun 2026", "pivmecillinam", cds.SMALL_PRINT):
        assert text in detail
    first = card["suggestions"][0]
    assert first["label"] == "Change to pivmecillinam"
    assert first["actions"][0]["type"] == "update"
    assert first["actions"][0]["resource"]["medicationCodeableConcept"]["coding"][0]["code"] == "J01CA08"
    assert card["selectionBehavior"] == "at-most-one"
    assert card["overrideReasons"][0]["code"] == "keep" and card["overrideReasons"][0]["display"] == "Keep trimethoprim"
    assert card["links"][0]["url"].startswith("/#/signal/pol-") and card["links"][1]["type"] == "smart"
    assert {f"{cds.SLUG}.rule", f"{cds.SLUG}.evidence"} <= set(card["extension"])


def _hook_request(hook, atc="J01DD04"):
    s = SCENARIOS["uro-esbl"]
    order = {"resourceType": "MedicationRequest", "id": "mr-1", "status": "draft", "intent": "order",
             "medicationCodeableConcept": {"coding": [{"system": cds.ATC_SYSTEM, "code": atc}]},
             "dosageInstruction": [{"text": "1 g once daily"}]}
    return {"hookInstance": "d1577c69-dfbe-44ad-ba6d-3e05e953b2ea", "hook": hook,
            "context": {"userId": "Practitioner/1", "patientId": s["patient_id"], "encounterId": "Encounter/1",
                        "selections": ["MedicationRequest/mr-1"] if hook == "order-select" else None,
                        "draftOrders": {"resourceType": "Bundle", "entry": [{"resource": order}]},
                        "extension": {f"{cds.SLUG}.unit": "URO", f"{cds.SLUG}.indication": "urinary",
                                      f"{cds.SLUG}.as_of": s["as_of"]}}}


def _service(hook):
    return next(s["id"] for s in cds.SERVICES if s["hook"] == hook)


def test_cds_hooks_select_shows_info_and_sign_warns(ds, seeds):
    def cards(hook):
        parsed = cds.parse_hook_request(_service(hook), _hook_request(hook))
        assert parsed["orders"][0]["drug"] == "CRO" and parsed["indication"] == "uti"
        return cds.hook_cards(ds, parsed, seeds, policy_states(ds, parsed["as_of"]))

    [selected] = cards("order-select")
    assert selected["indicator"] == "info"
    [signed] = cards("order-sign")
    assert signed["indicator"] == "warning"
    swapped = signed["suggestions"][0]["actions"][0]["resource"]
    assert swapped["id"] == "mr-1" and "dosageInstruction" not in swapped


def test_cds_hooks_requests_that_say_nothing_or_are_malformed(ds, seeds):
    sign = _service("order-sign")
    with pytest.raises(cds.OrderError):
        cds.parse_hook_request(sign, _hook_request("order-select"))
    broken = _hook_request("order-sign")
    broken["context"]["draftOrders"] = {"entry": ["not a resource"]}
    with pytest.raises(cds.OrderError):
        cds.parse_hook_request(sign, broken)
    unknown_drug = cds.parse_hook_request(sign, _hook_request("order-sign", atc="J01DC01"))  # cefoxitin: a screen
    assert unknown_drug["orders"] == []
    no_extension = _hook_request("order-sign")
    del no_extension["context"]["extension"]
    assert cds.hook_cards(ds, cds.parse_hook_request(sign, no_extension), seeds, []) == []


def test_banners_for_my_ward(ds, seeds):
    icu = cds.banners("2026-03-15", "ICU", seeds, policy_states(ds, "2026-03-15"))
    assert [b["id"] for b in icu] == ["seed-icu-mrsa-2026"]
    phc = cds.banners("2026-06-21", "PHC-N", seeds, policy_states(ds, "2026-06-21"))
    assert [b["kind"] for b in phc] == ["policy"] and phc[0]["text"].startswith(TMP_SUMMARY)


def test_cds_imports_neither_narrator_nor_jev():
    code = "import sys, aei.cds; print(sorted(m for m in sys.modules if m.startswith(('aei.narrator', 'aei.jev'))))"
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "[]"
