"""The order context and CDS Hooks cards (CONTRACTS.md 7 and 7b): demo scenarios, select vs sign, which numbers may be
shown, own-history warnings, notices, how rarely it speaks, that it never names another drug, and card shape."""

import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from aei import cds, cds_hooks, store, views
from aei import config as C
from aei.detectors.policy import policy_states

SCENARIOS = {s["key"]: s for s in C.DEMO_SCENARIOS}
TMP_SUMMARY = "Trimethoprim: 20.4% resistant (160 of 786, last 52 weeks), above local 20% line"
TMP_POPULATION = (
    "Population: urinary E. coli, women, health centres PHC-N + PHC-S, first isolate per patient in the window."
)


@pytest.fixture(autouse=True)
def seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE_DB", tmp_path / "state.sqlite")
    store.reset()
    store.seed_demo()
    return store.alerts("visitor-cccc-0003")


def _context(ds, seeds, key, stage="sign", **change):
    s = {**SCENARIOS[key], **change}
    return cds.order_context(
        ds,
        s["as_of"],
        s["patient_id"],
        s["unit"],
        s["indication"],
        s["drug"],
        stage,
        seeds,
        policy_states(ds, s["as_of"]),
    )


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
        assert cds.SIGN_NOTE in selected["rule"] and selected["ask"] == f"{cds.ASK} {cds.SIGN_NOTE}"
    assert [ln["key"] for ln in signed["lines"]] == (["happening", "your_drug"] if expect != "quiet" else ["your_drug"])
    assert set(signed["actions"]) == {"keep", "edit", "details"}
    assert signed["actions"]["keep"]["reasons"] == C.KEEP_REASONS


@pytest.mark.parametrize(
    ("key", "headline"),
    [
        # the headline is read from the alert, the patient's isolate or the line, never written freehand
        ("uro-esbl", "Possible ESBL E. coli cluster, Urology. The flagged antibiogram is R to ceftriaxone."),
        (
            "icu-mrsa",
            (
                "Possible MRSA cluster, Intensive care unit. The flagged antibiogram is R to cefuroxime (inferred: "
                "MRSA, cefoxitin screen positive)."
            ),
        ),
        ("ed-own-history", "This patient's E. coli of 16 Jan 2026 was R to trimethoprim."),
        ("phc-tmp", "Trimethoprim: 20.4% resistant (160 of 786, last 52 weeks), above local 20% line."),
    ],
)
def test_headline_comes_from_the_data(ds, seeds, key, headline):
    ctx = _context(ds, seeds, key)
    assert ctx["headline"] == headline and ctx["ask"] == cds.ASK


def test_uro_esbl_woman_sees_the_clone_in_her_population(ds, seeds):
    # a woman on URO, like 10 of the 11 clone patients; the raw-CSV derivation gives these
    nums = _line(_context(ds, seeds, "uro-esbl"), "your_drug")["numbers"]
    assert (nums["r"], nums["n"], nums["r12"], nums["n12"]) == (10, 29, 16, 257)


def test_no_data_looks_different_from_quiet(ds, seeds):
    # URO bloodstream meropenem became info once MSSA counts; URO has no wound cultures at all
    no_data = cds.order_context(ds, "2026-03-15", None, "URO", "wound", "MEM", "sign", seeds, [])
    assert no_data["state"] == "no_data"
    assert no_data["chip"] == "Not enough data on URO for meropenem (n = 0, last 52 weeks)"
    quiet = _context(ds, seeds, "medb-quiet")
    assert quiet["chip"] == "No active alerts · MED-B · data to 15 Mar"
    assert cds_hooks.card(quiet) is None and cds_hooks.card(no_data) is None


def test_nothing_after_as_of_speaks(ds, seeds):
    early = _context(ds, seeds, "uro-esbl", as_of="2025-06-01")  # the URO alert is approved on 9 Jun
    assert early["state"] != "warning"
    assert "seed-uro-esbl-2025" not in {r["id"] for r in early["evidence"]["reasons"]}
    s = SCENARIOS["phc-tmp"]
    later_policy = policy_states(ds, "2026-06-21")
    ctx = cds.order_context(ds, "2026-06-14", s["patient_id"], s["unit"], "uti", "TMP", "sign", seeds, later_policy)
    assert "tmp_uti_women_20" not in {r["id"] for r in ctx["evidence"]["reasons"]}


@pytest.mark.parametrize(
    ("change", "chip"),
    [
        ({"drug": "VAN"}, "Possible MRSA cluster on ICU. The alert does not apply to vancomycin."),
        (
            {"indication": "uti"},
            ("Possible MRSA cluster on ICU. The alert applies to bloodstream infection and wound infection only."),
        ),
    ],
)
def test_an_alert_that_does_not_apply_is_a_one_line_notice(ds, seeds, change, chip):
    ctx = _context(ds, seeds, "icu-mrsa", **change)
    assert (ctx["state"], ctx["chip"], ctx["source"]["id"]) == ("notice", chip, "seed-icu-mrsa-2026")
    assert ctx["lines"] == [] and ctx["headline"] is None and not ctx["interruptive"]  # no numbers, no card
    assert cds_hooks.card(ctx) is None


def test_flucloxacillin_under_the_mrsa_alert_says_how_it_is_read(ds, seeds):
    ctx = _context(ds, seeds, "icu-mrsa", drug="FOX")
    assert ctx["state"] == "warning"
    assert ctx["headline"].endswith("R to flucloxacillin (read from the cefoxitin screen).")


# --------------------------------------------------------------------------- which numbers may be shown
def test_order_screen_equals_my_ward_for_the_same_population(ds, seeds):
    """One shared effective-result function: ICU wound cefuroxime is 41 of 132, not 41 of 74."""
    ward = views.my_ward(ds, "2026-03-15", "ICU", specimen_group="wound", windows="4w,12m")
    cells = {r["drug"]: r["cells"] for r in ward["rows"]}
    for drug in ("TZP", "CXM", "CRO", "MEM", "VAN", "CLI"):
        nums = cds.order_context(ds, "2026-03-15", None, "ICU", "wound", drug, "sign", seeds, [])["evidence"]["counts"]
        mine = {"4w": (nums["r"], nums["n"]), "12m": (nums["r12"], nums["n12"])}
        assert mine == {
            w: (c["observed"]["tested"] - c["observed"]["covered"], c["observed"]["tested"])
            for w, c in cells[drug].items()
        }, drug
    assert mine["12m"] == (75, 132)  # clindamycin, the drug the old card offered under the MRSA alert
    hidden = {h["drug"] for h in ward["not_shown"]}
    for drug in ("AMP", "CIP", "CAZ", "NIT"):
        ctx = cds.order_context(ds, "2026-03-15", None, "ICU", "wound", drug, "sign", seeds, [])
        assert drug in hidden and ctx["evidence"]["counts"] is None, drug


@pytest.mark.parametrize(
    ("as_of", "patient_id", "unit", "indication", "drug", "chip"),
    [
        # pairs the laboratory never reports get a reason, never a number
        ("2026-09-27", "P001889", "PHC-S", "uti", "CAZ", "Ceftazidime: not tested on E. coli in this panel"),
        ("2026-06-21", "P001889", "PHC-N", "uti", "VAN", "Vancomycin: EUCAST lists E. coli as intrinsically resistant"),
        ("2026-03-15", "P008135", "ED", "uti", "FOX", "Flucloxacillin: EUCAST has no breakpoint for E. coli"),
        ("2026-07-05", None, "SURG", "wound", "MEC", "Pivmecillinam: tested on urine isolates only in this panel"),
        (
            "2026-03-15",
            None,
            "MED-A",
            "bloodstream",
            "CIP",
            (
                "Ciprofloxacin: not tested on S. aureus and E. faecalis in this panel; no result for 38% of this "
                "population's isolates"
            ),
        ),
    ],
)
def test_no_numbers_for_pairs_never_reported(ds, as_of, patient_id, unit, indication, drug, chip):
    ctx = cds.order_context(ds, as_of, patient_id, unit, indication, drug, "sign", [], [])
    assert (ctx["state"], ctx["chip"]) == ("no_data", chip)
    assert ctx["evidence"]["counts"] is None and _line(ctx, "your_drug")["numbers"] is None
    assert "%, 95% interval" not in _line(ctx, "your_drug")["text"]


def test_drug_picker_offers_drugs_with_reported_results_on_the_specimen(ds):
    every = [d for d, _, _ in C.ORDER_DRUGS]
    assert [d["drug"] for d in cds.order_drugs(ds, "urinary")] == every  # urine panels include staphylococci
    for indication in ("wound", "bloodstream"):  # the urine-only drugs are never reported on blood or wound
        assert [d["drug"] for d in cds.order_drugs(ds, indication)] == [d for d in every if d not in C.URINE_ONLY]
    assert next(d for d in cds.order_drugs(ds, "wound") if d["drug"] == "FOX") == {
        "drug": "FOX",
        "name": "Flucloxacillin",
        "atc": "J01CF05",
        "aware": "Access",
    }
    with pytest.raises(cds.OrderError):
        cds.order_drugs(ds, "pneumonia")


# --------------------------------------------------------------------------- the patient's own results
def test_previous_results_come_first_and_own_resistance_warns(ds, seeds):
    ctx = _context(ds, seeds, "ed-own-history")
    assert list(ctx).index("previous_results") < list(ctx).index("lines")
    first = ctx["previous_results"][0]
    assert (first["date"], first["organism"], first["drug_result"], first["reason"], first["reason_text"]) == (
        "2026-01-16",
        "Escherichia coli",
        "R",
        "reported",
        "reported",
    )
    assert ctx["source"]["kind"] == "own_history"
    assert ctx["chip"] == "Trimethoprim: this patient's E. coli of 16 Jan 2026 was R (reported)"


@pytest.mark.parametrize(
    ("as_of", "patient_id", "unit", "drug", "note"),
    [
        # the laboratory reported this C. freundii cefuroxime S; no breakpoint, not "intrinsic"
        (
            "2026-03-08",
            "P006986",
            "PHC-S",
            "CXM",
            "Cefuroxime: EUCAST has no breakpoint for C. freundii (this patient's urine isolate of 16 Jun 2025).",
        ),
        # another species' intrinsic resistance is a note, not a warning
        (
            "2026-06-21",
            "P002543",
            "PHC-N",
            "TMP",
            "Trimethoprim: EUCAST lists P. aeruginosa as intrinsically resistant (this patient's wound isolate of 31 Dec 2025).",
        ),
    ],
)
def test_species_resistance_is_a_note_never_a_warning(ds, seeds, as_of, patient_id, unit, drug, note):
    ctx = cds.order_context(ds, as_of, patient_id, unit, "uti", drug, "sign", seeds, policy_states(ds, as_of))
    assert ctx["state"] != "warning" and "own_history" not in {r["kind"] for r in ctx["evidence"]["reasons"]}
    assert ctx["notes"] == [note]


def test_a_species_rule_keeps_the_laboratorys_own_result(ds, seeds):
    """C. freundii cefuroxime counts as R (no EUCAST breakpoint), and the reported S stays visible."""
    ctx = cds.order_context(ds, "2026-03-08", "P006986", "PHC-S", "uti", "CXM", "sign", seeds, [])
    row = next(r for r in ctx["previous_results"] if r["organism"] == "Citrobacter freundii")
    assert (row["date"], row["drug_result"], row["reason"], row["reported_result"]) == (
        "2025-06-16",
        "R",
        "no_breakpoint",
        "S",
    )
    assert row["reason_text"] == "no EUCAST breakpoint for this species; the laboratory reported S"
    assert all(r["reported_result"] is None for r in ctx["previous_results"] if r is not row)


def test_no_percentage_or_interval_below_ten_isolates(ds, seeds):
    """Re-verification #2: as on My ward, n = 2 gives counts and a state, never "100%" with an interval."""
    ctx = cds.order_context(ds, "2026-06-21", "P001889", "PHC-N", "bloodstream", "FOX", "sign", seeds, [])
    nums = _line(ctx, "your_drug")["numbers"]
    assert (nums["r"], nums["n"], nums["state"], nums["pct"], nums["ci"]) == (2, 2, "not_enough_data", None, None)
    assert nums["pct12"] is not None and ctx["evidence"]["counts"] == nums


def test_an_untested_share_rounds_half_up_from_the_counts():
    c = {"isolates": 80, "n": 54, "untested": [["Escherichia coli", 26]]}
    assert (
        cds._untested(c, "en") == "not tested on E. coli in this panel; no result for 33% of this population's isolates"
    )


# --------------------------------------------------------------------------- it speaks rarely and never names a drug
def test_it_never_names_another_drug(ds, seeds):
    """The layer flags the drug entered and the doctor chooses: nothing it writes, the alert's own message included,
    names a drug other than the one ordered."""
    for key, s in SCENARIOS.items():
        for stage in cds.STAGES:
            ctx = _context(ds, seeds, key, stage)
            own = [
                ctx["chip"],
                ctx["headline"] or "",
                ctx["ask"] or "",
                _line(ctx, "your_drug")["text"],
                *(a["label"] for a in ctx["actions"].values()),
            ]
            others = [n for d, n, _ in C.ORDER_DRUGS if d != s["drug"]]
            assert not [n for n in others for text in own if n.lower() in text.lower()], (key, stage)
            card = cds_hooks.card(ctx)
            assert card is None or ("suggestions" not in card and "selectionBehavior" not in card)


def test_most_orders_are_quiet(ds, seeds):
    """Every scenario patient x indication x order drug at selection: never a warning there, and a minority of info
    even for these patients, picked because something is going on. The 45 info: the URO alert (5 drugs x 2
    indications), the ICU alert (9 x 2), two patients' own resistant E. coli (5 drugs x 3) and two trimethoprim lines."""
    states, sources = Counter(), Counter()
    for s in C.DEMO_SCENARIOS:
        states_now = policy_states(ds, s["as_of"])
        for indication in C.INDICATIONS:
            for d, _, _ in C.ORDER_DRUGS:
                ctx = cds.order_context(
                    ds, s["as_of"], s["patient_id"], s["unit"], indication, d, "select", seeds, states_now
                )
                states[ctx["state"]] += 1
                if ctx["state"] == "info":
                    sources[ctx["source"]["kind"]] += 1
    assert states == {"quiet": 51, "no_data": 49, "notice": 50, "info": 45}  # of 195; no warning before signing
    assert sources == {"alert": 28, "own_history": 15, "policy": 1, "local_line": 1}


# --------------------------------------------------------------------------- cards and CDS Hooks
def test_trimethoprim_policy_card(ds, seeds):
    s = SCENARIOS["phc-tmp"]
    [card] = cds_hooks.order_check(
        ds, s["as_of"], s["unit"], "TMP", "uti", seeds, policy_states(ds, s["as_of"]), patient_id=s["patient_id"]
    )
    assert card["summary"] == TMP_SUMMARY and len(card["summary"]) <= 140
    assert card["indicator"] == "info"
    assert card["source"] == {"label": f"{C.APP_NAME} · infection control"}
    detail = card["detail"]
    assert detail.startswith("**This patient's results")
    # "a year earlier" and "This drug in this population": the 364-day window
    for text in (
        TMP_POPULATION,
        "Same window a year earlier: 15.9%",
        "crossed week ending 21 Jun 2026",
        "**This drug in this population:**",
        cds.ASK,
        cds.SMALL_PRINT,
    ):
        assert text in detail
    assert "pivmecillinam" not in detail.lower() and "suggestions" not in card  # it names no other drug
    assert card["overrideReasons"][0]["code"] == "keep" and card["overrideReasons"][0]["display"] == "Keep trimethoprim"
    assert [link["type"] for link in card["links"]] == ["absolute"]  # no SMART launch in the demo
    assert card["links"][0] == {
        "label": cds.DETAILS_LABEL,
        "type": "absolute",
        "url": "/#/ward?ward=PHC-N&specimen=urine&organism=Escherichia%20coli&as_of=2026-06-21",
    }
    assert {f"{cds.SLUG}.rule", f"{cds.SLUG}.evidence"} <= set(card["extension"])


def _hook_request(hook, atc="J01DD04"):
    s = SCENARIOS["uro-esbl"]
    order = {
        "resourceType": "MedicationRequest",
        "id": "mr-1",
        "status": "draft",
        "intent": "order",
        "medicationCodeableConcept": {"coding": [{"system": cds_hooks.ATC_SYSTEM, "code": atc}]},
        "dosageInstruction": [{"text": "1 g once daily"}],
    }
    return {
        "hookInstance": "d1577c69-dfbe-44ad-ba6d-3e05e953b2ea",
        "hook": hook,
        "context": {
            "userId": "Practitioner/1",
            "patientId": s["patient_id"],
            "encounterId": "Encounter/1",
            "selections": ["MedicationRequest/mr-1"] if hook == "order-select" else None,
            "draftOrders": {"resourceType": "Bundle", "entry": [{"resource": order}]},
            "extension": {
                f"{cds.SLUG}.unit": "URO",
                f"{cds.SLUG}.indication": "urinary",
                f"{cds.SLUG}.as_of": s["as_of"],
            },
        },
    }


def _service(hook):
    return next(s["id"] for s in cds_hooks.SERVICES if s["hook"] == hook)


def test_cds_hooks_select_shows_info_and_sign_warns(ds, seeds):
    def cards(hook):
        parsed = cds_hooks.parse_hook_request(_service(hook), _hook_request(hook))
        assert parsed["orders"][0]["drug"] == "CRO" and parsed["indication"] == "uti"
        return cds_hooks.hook_cards(ds, parsed, seeds, policy_states(ds, parsed["as_of"]))

    [selected] = cards("order-select")
    assert selected["indicator"] == "info"
    [signed] = cards("order-sign")
    assert signed["indicator"] == "warning" and "suggestions" not in signed


def test_amoxicillin_orders_are_read_from_ampicillin(ds, seeds):
    sign = _service("order-sign")
    parsed = cds_hooks.parse_hook_request(sign, _hook_request("order-sign", atc="J01CA04"))
    assert [o["drug"] for o in parsed["orders"]] == ["AMP"]
    [card] = cds_hooks.hook_cards(ds, parsed, seeds, policy_states(ds, parsed["as_of"]))  # AMP is in the URO alert
    assert C.ATC_NOTES["J01CA04"] in card["detail"]


def test_cds_hooks_requests_that_say_nothing_or_are_malformed(ds, seeds):
    sign = _service("order-sign")
    with pytest.raises(cds.OrderError):
        cds_hooks.parse_hook_request(sign, _hook_request("order-select"))
    broken = _hook_request("order-sign")
    broken["context"]["draftOrders"] = {"entry": ["not a resource"]}
    with pytest.raises(cds.OrderError):
        cds_hooks.parse_hook_request(sign, broken)
    listed = _hook_request("order-sign")
    listed["context"]["patientId"] = ["P001948", "P001889"]  # once a pandas error text reached the client
    with pytest.raises(cds.OrderError, match="^patientId must be text$"):
        cds_hooks.parse_hook_request(sign, listed)
    unknown_drug = cds_hooks.parse_hook_request(sign, _hook_request("order-sign", atc="J01DC01"))  # cefoxitin: a screen
    assert unknown_drug["orders"] == []
    no_extension = _hook_request("order-sign")
    del no_extension["context"]["extension"]
    assert cds_hooks.hook_cards(ds, cds_hooks.parse_hook_request(sign, no_extension), seeds, []) == []


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "NOPE"},
        {"drug": "XYZ"},
        {"indication": ["uti"]},
        {"stage": "later"},
        {"patient_id": "P999999"},
        {"as_of": "not a date"},
    ],
)
def test_bad_order_input_is_an_order_error(ds, seeds, change):
    s = {**SCENARIOS["medb-quiet"], **change}
    with pytest.raises(cds.OrderError):
        cds.order_context(
            ds, s["as_of"], s["patient_id"], s["unit"], s["indication"], s["drug"], s.get("stage", "sign")
        )


# --------------------------------------------------------------------------- My ward banners
def test_banners_for_my_ward(ds, seeds):
    for specimen_group in ("blood_wound", "urine"):
        icu = cds.banners("2026-03-15", "ICU", seeds, policy_states(ds, "2026-03-15"), specimen_group=specimen_group)
        assert [b["id"] for b in icu] == ["seed-icu-mrsa-2026"]
    states = policy_states(ds, "2026-06-21")
    [phc] = cds.banners("2026-06-21", "PHC-N", seeds, states, specimen_group="urine")
    assert (
        phc["kind"] == "policy" and phc["text"] == f"{TMP_SUMMARY}. {TMP_POPULATION} Review the empirical UTI guidance."
    )
    # the trimethoprim line is about urine: a blood or wound view never shows it
    assert cds.banners("2026-06-21", "PHC-N", seeds, states, specimen_group="blood_wound") == []


def test_cds_never_imports_the_narrator():
    code = "import sys, aei.cds, aei.cds_hooks; print(sorted(m for m in sys.modules if m.startswith('aei.narrator')))"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "[]"
