"""The order context and CDS Hooks cards (CONTRACTS.md 7 and 7b): demo scenarios, select vs sign, which numbers may be
shown, own-history warnings, alternatives and card shape."""
import subprocess
import sys
from pathlib import Path

import pytest

from aei import cds, store, views
from aei import config as C
from aei.detectors.policy import policy_states

SCENARIOS = {s["key"]: s for s in C.DEMO_SCENARIOS}
TMP_SUMMARY = "Trimethoprim: 20.4% resistant (160 of 786, last 52 weeks), above local 20% line"
TMP_POPULATION = "Population: urinary E. coli, women, health centres PHC-N + PHC-S, first isolate per patient in the window."


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


def _line(ctx, key):
    return next((ln for ln in ctx["lines"] if ln["key"] == key), None)


# --------------------------------------------------------------------------- demo scenarios and states
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


def test_uro_esbl_woman_sees_the_clone_in_her_population(ds, seeds):
    # order-view #7: a woman on URO, like 10 of the 11 clone patients; the verifier's raw-CSV derivation gives these
    nums = _line(_context(ds, seeds, "uro-esbl"), "your_drug")["numbers"]
    assert (nums["r"], nums["n"], nums["r12"], nums["n12"]) == (10, 29, 16, 257)


def test_no_data_looks_different_from_quiet(ds, seeds):
    # URO bloodstream meropenem became info once MSSA counts (clinical D-H2); URO has no wound cultures at all
    no_data = cds.order_context(ds, "2026-03-15", None, "URO", "wound", "MEM", "sign", seeds, [])
    assert no_data["state"] == "no_data"
    assert no_data["chip"] == "Not enough data on URO for meropenem (n = 0, last 52 weeks)"
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


# --------------------------------------------------------------------------- which numbers may be shown
def test_order_screen_equals_my_ward_for_the_same_population(ds, seeds):
    """One shared effective-result function (clinical D-H2): ICU wound cefuroxime is 41 of 132, not 41 of 74."""
    ward = views.my_ward(ds, "2026-03-15", "ICU", specimen_group="wound", windows="4w,12m")
    cells = {r["drug"]: r["cells"] for r in ward["rows"]}
    for drug in ("TZP", "CXM", "CRO", "MEM", "VAN", "CLI"):
        nums = cds.order_context(ds, "2026-03-15", None, "ICU", "wound", drug, "sign", seeds, [])["evidence"]["counts"]
        mine = {"4w": (nums["r"], nums["n"]), "12m": (nums["r12"], nums["n12"])}
        assert mine == {w: (c["observed"]["tested"] - c["observed"]["covered"], c["observed"]["tested"])
                        for w, c in cells[drug].items()}, drug
    assert mine["12m"] == (75, 132)  # clindamycin, the drug the old card offered under the MRSA alert
    hidden = {h["drug"] for h in ward["not_shown"]}
    for drug in ("AMP", "CIP", "CAZ", "NIT"):
        ctx = cds.order_context(ds, "2026-03-15", None, "ICU", "wound", drug, "sign", seeds, [])
        assert drug in hidden and ctx["evidence"]["counts"] is None, drug


@pytest.mark.parametrize(("as_of", "patient_id", "unit", "indication", "drug", "chip"), [
    # clinical D-H4 and order-view #3: pairs the laboratory never reports get a reason, never a number
    ("2026-09-27", "P001889", "PHC-S", "uti", "CAZ", "Ceftazidime: not tested on E. coli in this panel"),
    ("2026-06-21", "P001889", "PHC-N", "uti", "VAN", "Vancomycin: EUCAST lists E. coli as intrinsically resistant"),
    ("2026-03-15", "P008135", "ED", "uti", "FOX", "Flucloxacillin: EUCAST has no breakpoint for E. coli"),
    ("2026-07-05", None, "SURG", "wound", "MEC", "Pivmecillinam: tested on urine isolates only in this panel"),
    ("2026-03-15", None, "MED-A", "bloodstream", "CIP", ("Ciprofloxacin: not tested on S. aureus and E. faecalis in "
                                                          "this panel; no result for 38% of this population's isolates")),
])
def test_no_numbers_for_pairs_never_reported(ds, as_of, patient_id, unit, indication, drug, chip):
    ctx = cds.order_context(ds, as_of, patient_id, unit, indication, drug, "sign", [], [])
    assert (ctx["state"], ctx["chip"]) == ("no_data", chip)
    assert ctx["evidence"]["counts"] is None and _line(ctx, "your_drug")["numbers"] is None
    assert "%, 95% interval" not in _line(ctx, "your_drug")["text"]


def test_drug_picker_offers_what_the_indication_can_be_shown_for():
    uti = [d["drug"] for d in cds.order_drugs("urinary")]
    assert uti == ["MEC", "NIT", "TMP", "AMP", "CXM", "CIP", "CRO", "CAZ", "TZP", "MEM"]  # no FOX, CLI or VAN for E. coli
    wound = cds.order_drugs("wound")
    assert [d["drug"] for d in wound] == ["AMP", "FOX", "CLI", "CXM", "CIP", "CRO", "CAZ", "VAN", "TZP", "MEM"]
    assert next(d for d in wound if d["drug"] == "FOX") == {"drug": "FOX", "name": "Flucloxacillin", "atc": "J01CF05",
                                                            "aware": "Access"}
    with pytest.raises(cds.OrderError):
        cds.order_drugs("pneumonia")


# --------------------------------------------------------------------------- the patient's own results
def test_previous_results_come_first_and_own_resistance_warns(ds, seeds):
    ctx = _context(ds, seeds, "ed-own-history")
    assert list(ctx).index("previous_results") < list(ctx).index("lines")
    first = ctx["previous_results"][0]
    assert (first["date"], first["organism"], first["drug_result"], first["reason"], first["reason_text"]) == (
        "2026-01-16", "Escherichia coli", "R", "reported", "reported")
    assert ctx["source"]["kind"] == "own_history"
    assert ctx["chip"] == "This patient's E. coli of 16 Jan 2026 was trimethoprim R"
    assert ctx["actions"]["change_to"] == ["MEC", "NIT"]  # never TMP back; MEC returns once E. faecalis MEC no longer blocks


@pytest.mark.parametrize(("as_of", "patient_id", "unit", "drug", "note"), [
    # order-view #5 / clinical D-M6: the laboratory reported this C. freundii cefuroxime S; no breakpoint, not "intrinsic"
    ("2026-03-08", "P006986", "PHC-S", "CXM",
     "Cefuroxime: EUCAST has no breakpoint for C. freundii (this patient's urine isolate of 16 Jun 2025)."),
    # order-view #6 / clinical D-M4: another species' intrinsic resistance is a note, not a warning
    ("2026-06-21", "P002543", "PHC-N", "TMP",
     "Trimethoprim: EUCAST lists P. aeruginosa as intrinsically resistant (this patient's wound isolate of 31 Dec 2025)."),
])
def test_species_resistance_is_a_note_never_a_warning(ds, seeds, as_of, patient_id, unit, drug, note):
    ctx = cds.order_context(ds, as_of, patient_id, unit, "uti", drug, "sign", seeds, policy_states(ds, as_of))
    assert ctx["state"] != "warning" and "own_history" not in {r["kind"] for r in ctx["evidence"]["reasons"]}
    assert ctx["notes"] == [note]


# --------------------------------------------------------------------------- alternatives
def test_alternatives_never_repeat_the_alert_antibiogram(ds, seeds):
    # clinical D-H1 / order-view #1: the ICU clone is clindamycin R; no wound guide drug is left
    icu = _context(ds, seeds, "icu-mrsa")
    assert icu["actions"]["change_to"] == [] and _line(icu, "alternatives")["text"] == C.NO_GUIDE_ALTERNATIVE
    assert "suggestions" not in cds.card(icu)
    # order-view #2: the URO clone is trimethoprim R, so the women's cystitis list keeps pivmecillinam and nitrofurantoin
    uro = _context(ds, seeds, "uro-esbl")
    assert uro["actions"]["change_to"] == ["MEC", "NIT"]
    assert _line(uro, "alternatives")["source"] == "Käypä hoito 2024: uncomplicated cystitis in women"


def test_alternatives_at_or_above_their_line_are_dropped(ds, seeds):
    # clinical D-M1: MED-B trimethoprim is 32 of 149 (21%), above its own 20% line
    quiet = _context(ds, seeds, "medb-quiet")
    assert quiet["actions"]["change_to"] == ["MEC"]


def test_uti_alternatives_follow_the_patients_sex(ds, seeds):
    # clinical D-M2: a man gets the afebrile lower-UTI list (trimethoprim, nitrofurantoin), never pivmecillinam
    man = cds.order_context(ds, "2026-06-21", "P002543", "PHC-N", "uti", "CRO", "sign", seeds, [])
    assert man["patient"]["sex"] == "M" and man["actions"]["change_to"] == ["TMP", "NIT"]
    assert cds.order_context(ds, "2026-06-21", None, "PHC-N", "uti", "CRO", "sign", seeds, [])["actions"]["change_to"] == []


# --------------------------------------------------------------------------- cards and CDS Hooks
def test_trimethoprim_policy_card(ds, seeds):
    s = SCENARIOS["phc-tmp"]
    [card] = cds.order_check(ds, s["as_of"], s["unit"], "TMP", "uti", seeds, policy_states(ds, s["as_of"]),
                             patient_id=s["patient_id"])
    assert card["summary"] == TMP_SUMMARY and len(card["summary"]) <= 140
    assert card["indicator"] == "info"
    assert card["source"] == {"label": f"{C.APP_NAME} · infection control"}
    detail = card["detail"]
    assert detail.startswith("**This patient's results")
    # "a year earlier" and "Your drug in this population": order-view #10 and the 364-day window (my-ward D8)
    for text in (TMP_POPULATION, "Same window a year earlier: 15.9%", "crossed week ending 21 Jun 2026", "pivmecillinam",
                 "**Your drug in this population:**", cds.SMALL_PRINT):
        assert text in detail
    first = card["suggestions"][0]
    assert first["label"] == "Change to pivmecillinam"
    assert first["actions"][0]["type"] == "update"
    assert first["actions"][0]["resource"]["medicationCodeableConcept"]["coding"][0]["code"] == "J01CA08"
    assert card["selectionBehavior"] == "at-most-one"
    assert card["overrideReasons"][0]["code"] == "keep" and card["overrideReasons"][0]["display"] == "Keep trimethoprim"
    assert [link["type"] for link in card["links"]] == ["absolute"]  # no SMART launch in the demo (audit #11)
    assert card["links"][0]["url"].startswith("/#/signal/pol-")
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


def test_amoxicillin_orders_are_read_from_ampicillin(ds, seeds):
    sign = _service("order-sign")
    parsed = cds.parse_hook_request(sign, _hook_request("order-sign", atc="J01CA04"))
    assert [o["drug"] for o in parsed["orders"]] == ["AMP"]
    [card] = cds.hook_cards(ds, parsed, seeds, policy_states(ds, parsed["as_of"]))  # AMP is in the URO alert
    assert C.ATC_NOTES["J01CA04"] in card["detail"]


def test_cds_hooks_requests_that_say_nothing_or_are_malformed(ds, seeds):
    sign = _service("order-sign")
    with pytest.raises(cds.OrderError):
        cds.parse_hook_request(sign, _hook_request("order-select"))
    broken = _hook_request("order-sign")
    broken["context"]["draftOrders"] = {"entry": ["not a resource"]}
    with pytest.raises(cds.OrderError):
        cds.parse_hook_request(sign, broken)
    listed = _hook_request("order-sign")
    listed["context"]["patientId"] = ["P001948", "P001889"]  # audit #10: once a pandas error text reached the client
    with pytest.raises(cds.OrderError, match="^patientId must be text$"):
        cds.parse_hook_request(sign, listed)
    unknown_drug = cds.parse_hook_request(sign, _hook_request("order-sign", atc="J01DC01"))  # cefoxitin: a screen
    assert unknown_drug["orders"] == []
    no_extension = _hook_request("order-sign")
    del no_extension["context"]["extension"]
    assert cds.hook_cards(ds, cds.parse_hook_request(sign, no_extension), seeds, []) == []


@pytest.mark.parametrize("change", [{"unit": "NOPE"}, {"drug": "XYZ"}, {"indication": ["uti"]}, {"stage": "later"},
                                    {"patient_id": "P999999"}, {"as_of": "not a date"}])
def test_bad_order_input_is_an_order_error(ds, seeds, change):
    s = {**SCENARIOS["medb-quiet"], **change}
    with pytest.raises(cds.OrderError):
        cds.order_context(ds, s["as_of"], s["patient_id"], s["unit"], s["indication"], s["drug"], s.get("stage", "sign"))


# --------------------------------------------------------------------------- My ward banners
def test_banners_for_my_ward(ds, seeds):
    for specimen_group in ("blood_wound", "urine"):
        icu = cds.banners("2026-03-15", "ICU", seeds, policy_states(ds, "2026-03-15"), specimen_group=specimen_group)
        assert [b["id"] for b in icu] == ["seed-icu-mrsa-2026"]
    states = policy_states(ds, "2026-06-21")
    [phc] = cds.banners("2026-06-21", "PHC-N", seeds, states, specimen_group="urine")
    assert phc["kind"] == "policy" and phc["text"].startswith(f"{TMP_SUMMARY}. {TMP_POPULATION}")
    # the trimethoprim line is about urine: a blood or wound view never shows it
    assert cds.banners("2026-06-21", "PHC-N", seeds, states, specimen_group="blood_wound") == []


def test_cds_imports_neither_narrator_nor_jev():
    code = "import sys, aei.cds; print(sorted(m for m in sys.modules if m.startswith(('aei.narrator', 'aei.jev'))))"
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "[]"
