"""Workstream B1: outbreak detectors (phenotype, thl, stepup, seen_before). Offline and deterministic.
Goldens from CONTRACTS.md section 5.2 and analysis 09_leadtime, 08_hidden, 47_outbreak_prob, 52_seen_before_expert_rules."""

import json
import re

import pandas as pd
import pytest
from test_trend_detectors import check_title, check_title_template

from aei import brief, data, render, templates
from aei import config as C
from aei import detectors as registry
from aei import signal as sig
from aei.detectors import phenotype, seen_before, stepup, thl
from aei.templates_outbreak import TEMPLATES as OUTBREAK_TEMPLATES

DETECTORS = [phenotype, thl, stepup, seen_before]
ICU_PATTERN = "FOX:R VAN:S CLI:R"
URO_PATTERN = "AMP:R MEC:S TZP:S CXM:R CRO:R MEM:S CIP:R TMP:R NIT:S"
DIGITS = re.compile(r"\d+")
BANNED = [
    "predict",
    "forecast",
    "odds",
    "probability",
    "best choice",
    "recommended drug",
    "likely to",
    "will rise",
    "s/i/r",
    "decoy",
    "outbreak confirmed",
    "zero resistance",
]
SECTION_PRIORITY = {
    "phenotype_cluster": ("unusual_patterns", {"P1", "P2"}),
    "thl_rule": ("unusual_patterns", {"P1", "P2"}),
    "count_stepup": ("unusual_patterns", {"P3"}),
    "seen_before": ("seen_before", {"info"}),
}


def check_signal(s: dict) -> None:
    """Contract section 3: evidence shape, status, section/priority per kind, numbers only via slots, wording rules."""
    assert s["status"] in ("new", "ongoing", "resolved")
    section, priorities = SECTION_PRIORITY[s["kind"]]
    assert s["section"] == section and s["priority"] in priorities, (s["kind"], s["priority"])
    assert s["id"] == sig.signal_id(s["kind"], s["key"])
    ev = s["evidence"]
    assert {"filter", "counts", "method", "params"} <= ev.keys()
    assert {"ward", "specimen", "organism", "drug", "date_from", "date_to", "rule"} <= ev["filter"].keys()
    assert render.render_id(s["template_id"], s["slots"]) == s["text"]
    t = templates.TEMPLATES[s["template_id"]]
    allowed = set()
    for name, kind in render.slots_in(t["text"]):
        allowed |= set(DIGITS.findall(render.fmt(s["slots"][name], kind or t.get("formats", {}).get(name, "text"))))
    assert set(DIGITS.findall(s["text"])) <= allowed, s["text"]
    shown = " ".join([s["text"], str(s["advice"] or ""), ev["method"], str(ev.get("label", ""))]).lower()
    for word in BANNED:
        assert word not in shown, (word, shown)
    check_title(registry.with_title(s))
    if s["status"] == "resolved":  # brief D5: what was last flagged, not last week's present tense
        assert s["template_id"].endswith("_resolved") and "Resolved. Last flagged week ending" in s["text"]
        assert s["advice"] is None


def one(sigs: list, **match) -> dict:
    hits = [s for s in sigs if all(s.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, [s["text"] for s in sigs]
    return hits[0]


def icu_clusters(ds, as_of) -> list:
    return [s for s in phenotype.detect(ds, as_of) if s["ward"] == "ICU" and s["key"]["profile"] == ICU_PATTERN]


def truncated(ds, as_of) -> data.Dataset:
    end = pd.Timestamp(as_of)
    return data.Dataset(
        isolates=ds.isolates[ds.isolates.sample_date <= end].copy(),
        cultures=ds.cultures[ds.cultures.sample_date <= end].copy(),
        patients=ds.patients,
    )


# ---------------------------------------------------------------- phenotype clusters


@pytest.mark.parametrize(
    "as_of, n_patients, n_share",
    [("2026-03-07", 3, 3), ("2026-03-13", 5, 5), ("2026-03-20", 8, 8), ("2026-03-27", 13, 12)],
)
def test_icu_mrsa_cluster_counts_by_as_of(ds, as_of, n_patients, n_share):
    (s,) = icu_clusters(ds, as_of)
    assert (s["slots"]["n_patients"], s["slots"]["n_share"]) == (n_patients, n_share)
    assert s["first_sample_date"] == "2026-03-03" and s["organism"] == "Staphylococcus aureus"
    assert s["priority"] == "P1" and s["advice"] == "Typing advised"
    assert s["evidence"]["filter"]["marker"] == "mrsa"
    assert f"{n_share} of {n_patients} share one antibiogram ({ICU_PATTERN})" in s["text"]


def test_icu_mrsa_cluster_first_alert_is_7_march(ds):
    assert icu_clusters(ds, "2026-03-06") == []
    (s,) = icu_clusters(ds, "2026-03-07")
    assert s["evidence"]["counts"]["first_alert_date"] == "2026-03-07"


def test_icu_cluster_status_across_weeks(ds):
    """new, then ongoing while it fires, resolved for exactly one week, then gone; one stable id throughout."""
    weeks = [str(d.date()) for d in pd.date_range("2026-03-01", "2026-04-19", freq="7D")]
    seen = {w: icu_clusters(ds, w) for w in weeks}
    assert [s[0]["status"] if s else None for s in seen.values()] == [
        None,
        "new",
        "ongoing",
        "ongoing",
        "ongoing",
        "ongoing",
        "resolved",
        None,
    ]
    assert len({s[0]["id"] for s in seen.values() if s}) == 1
    linked = [[x["status"] for x in seen_before.detect(ds, w) if x["ward"] == "ICU"] for w in weeks]
    assert linked == [[], ["new"], ["ongoing"], ["ongoing"], ["ongoing"], ["ongoing"], ["resolved"], []]


def test_uro_esbl_cluster_fires_by_4_june_2025(ds):
    assert [s for s in phenotype.detect(ds, "2025-06-03") if s["ward"] == "URO"] == []
    s = one(phenotype.detect(ds, "2025-06-04"), ward="URO")
    assert (s["slots"]["n_patients"], s["slots"]["n_share"], s["slots"]["pattern"]) == (4, 4, URO_PATTERN)
    assert s["organism"] == "Escherichia coli" and s["evidence"]["filter"]["marker"] == "esbl"
    assert s["priority"] == "P1" and s["status"] == "new"


def unit_patients_with_pattern(ds, ward, organism, pattern, first) -> int:
    """Patients on the unit with this exact antibiogram in the 52 weeks before the cluster's first sample, by hand."""
    x = ds.isolates
    first = pd.Timestamp(first)
    year = x[(x.sample_date >= first - pd.Timedelta(days=364)) & (x.sample_date < first)]
    return year[(year.ward_code == ward) & (year.organism == organism) & (year.profile == pattern)].patient_id.nunique()


def test_phenotype_card_separates_the_model_range_from_the_observed_count(ds):
    """Brief D6 / clinical D-L5: the range is a model at the hospital-wide rate, and the observed count stands beside it."""
    icu = one(phenotype.detect(ds, "2026-03-08"), ward="ICU")
    assert unit_patients_with_pattern(ds, "ICU", "Staphylococcus aureus", ICU_PATTERN, "2026-03-03") == 0
    # Re-pinned: the background share now prints its x of n (3 of 34), as the seen-before card does
    assert (
        "Expected with this antibiogram at the hospital-wide rate: 0–2 patients a year on this unit (observed in the "
        "year before: 0). In the year before, 3 of 34 MRSA patients hospital-wide had this antibiogram (9%)."
    ) in icu["text"]
    assert (
        icu["template_id"] == "ob_phenotype_marker__ok"
        and registry.with_title(icu)["title"] == "ICU: possible cluster of MRSA"
    )
    uro = one(phenotype.detect(ds, "2025-06-08"), ward="URO")
    assert unit_patients_with_pattern(ds, "URO", "Escherichia coli", URO_PATTERN, "2025-05-30") == 3
    assert "0–6 patients a year on this unit (observed in the year before: 3)" in uro["text"]
    assert " it " not in icu["text"] + uro["text"]


def test_medb_esbl_lookalike_is_heterogeneous_and_ranked_lower(ds):
    assert [s for s in phenotype.detect(ds, "2024-09-22") if s["ward"] == "MED-B"] == []
    s = one(thl.detect(ds, "2024-09-22"), ward="MED-B")
    assert s["template_id"] == "ob_thl_cluster_mixed" and s["priority"] == "P2" and s["advice"] is None
    assert (s["slots"]["n_patients"], s["slots"]["n_profiles"]) == (4, 3)
    assert "ranked lower by our rules (truth unknown)" in s["text"]
    uro = one(phenotype.detect(ds, "2025-06-08"), ward="URO")
    assert s["evidence"]["rank"]["score"] < uro["evidence"]["rank"]["score"]
    assert "decoy" not in json.dumps(s).lower()


def test_rule_is_validated_and_echoed(ds):
    a, b = icu_clusters(ds, "2026-03-15")[0], phenotype.detect(ds, "2026-03-15", rule="30d")[0]
    assert a["id"] == b["id"] and b["evidence"]["filter"]["rule"] == "30d"
    with pytest.raises(ValueError):
        phenotype.detect(ds, "2026-03-15", rule="weekly")


def test_case_file_rows(ds):
    """The case file lists the cluster's isolates and, for its seen-before match, the earlier patients (brief.py)."""
    (s,) = icu_clusters(ds, "2026-03-27")
    rows = brief.evidence_rows(ds, s, "2026-03-27")
    assert rows.patient_id.nunique() == 13 and "patient_id" not in brief.line_list(rows)[0]
    assert sum(d["n"] for d in brief.epi_curve(rows, s["evidence"]["filter"], "2026-03-27")) == len(rows)
    linked = one(seen_before.detect(ds, "2026-03-27"), ward="ICU")
    assert brief.evidence_rows(ds, linked, "2026-03-27").patient_id.nunique() == 11


def test_competing_explanations_are_counts_in_words(ds):
    """Each hypothesis keeps its rating code and states its counts as x of n (no percentage beside a small count, no
    Python list or boolean), with p-values as "p < 0.001"."""
    (s,) = icu_clusters(ds, "2026-03-29")
    hyp = {h["id"]: h for h in s["evidence"]["competing_explanations"]["hypotheses"]}
    assert (hyp["H1"]["label"], hyp["H1"]["rating"]) == ("Transmission on the unit", "strong")
    assert hyp["H1"]["evidence"] == (
        "patients: 13 observed vs 0.07 expected (p < 0.001); with the most common antibiogram: 12 of 13, vs 3 of 34 "
        "isolates in the year before (p < 0.001); hospital-onset: 10 of 13"
    )
    assert hyp["H6"]["evidence"] == "every patient's isolate flagged MRSA is cefoxitin R"
    for h in hyp.values():
        assert not any(t in h["evidence"] for t in ("%", "[", "True", "False")), h["evidence"]
        assert render.render_id(h["template_id"], h["slots"]) == h["evidence"]


# ---------------------------------------------------------------- THL rule cards


def test_vre_card_on_ger_by_14_sep_2026_brief(ds):
    assert [s for s in thl.detect(ds, "2026-09-06") if s["ward"] == "GER"] == []
    s = one(thl.detect(ds, "2026-09-13"), ward="GER")
    assert s["evidence"]["filter"]["marker"] == "vre" and s["template_id"] == "ob_thl_single"
    assert s["priority"] == "P1" and s["status"] == "new" and s["first_sample_date"] == "2026-09-11"


def test_thl_actions_follow_thl_2_2020(ds):
    """Clinical D-H3, D-M5, D-L1, D-L2, D-L3 (THL Ohjaus 2/2020 sections 5.2, 8.1.1, 8.1.3, 8.2.3, appendix 1)."""
    ger_kp = one(thl.detect(ds, "2026-06-21"), ward="GER")  # ESBL K. pneumoniae: contact precautions and screening
    assert ger_kp["organism"] == "Klebsiella pneumoniae"
    assert ger_kp["evidence"]["action"].startswith("Contact precautions; screen exposed patients")
    uro = one(phenotype.detect(ds, "2025-06-08"), ward="URO")  # ESBL E. coli: contact precautions by risk assessment
    assert uro["evidence"]["thl_rule"]["action"].startswith(
        "Standard precautions; contact precautions by risk assessment"
    )
    (icu,) = icu_clusters(ds, "2026-03-15")
    assert "new MRSA strains go to the THL reference lab" in icu["evidence"]["thl_rule"]["action"]
    ed = one(thl.detect(ds, "2026-02-01"), ward="ED")  # K. oxytoca CPE, outpatient: carrier flag, strain by agreement
    assert "Flag as carrier" in ed["text"] and "screen exposed" not in ed["text"]
    assert "strain to the THL reference lab (agree in advance for this species)" in ed["text"]
    meda = one(thl.detect(ds, "2026-09-27"), ward="MED-A")  # K. pneumoniae CPE, inpatient: routine strain submission
    assert "screen exposed patients" in meda["text"] and "agree in advance" not in meda["text"]
    cards = [s for s in thl.detect(ds, "2026-02-15") if s["template_id"].startswith("ob_thl_single")] + [ed, meda]
    for s in cards:  # the card text and the case file's action are one sentence
        assert s["evidence"]["action"] in s["text"] and "one week" not in s["evidence"]["action"]


def test_marker_cluster_check_folds_into_phenotype_cluster(ds):
    """The ICU MRSA same-unit THL check is evidence on the phenotype card, not a second card."""
    assert [s for s in thl.detect(ds, "2026-03-15") if s["ward"] == "ICU"] == []
    (s,) = icu_clusters(ds, "2026-03-15")
    assert s["evidence"]["thl_rule"]["rule"] == "mrsa_same_unit"


# ---------------------------------------------------------------- count step-up


def test_stepup_is_attached_as_evidence(ds):
    (icu,) = icu_clusters(ds, "2026-03-15")
    assert icu["evidence"]["stepup"]["positive"] and icu["evidence"]["stepup"]["y4"] == 6
    medb = one(thl.detect(ds, "2024-09-22"), ward="MED-B")
    assert medb["evidence"]["stepup"]["positive"]
    assert stepup.detect(ds, "2026-03-15") == [] and stepup.detect(ds, "2024-09-22") == []


def test_stepup_is_never_p1_on_its_own(ds, monkeypatch):
    monkeypatch.setattr(stepup, "_covered", lambda *args: False)
    sigs = stepup.detect(ds, "2026-03-15")
    one(sigs, ward="ICU")
    for s in sigs:
        assert s["kind"] == "count_stepup" and s["priority"] == "P3"
        check_signal(s)
    ended = one(stepup.detect(ds, "2026-04-19"), ward="ICU")  # a resolved item never says "test positive"
    assert ended["status"] == "resolved" and "positive" not in ended["text"]
    assert ended["text"].startswith("ICU: MRSA count step-up test. Resolved. Last flagged week ending 12 Apr 2026")


# ---------------------------------------------------------------- seen before


def test_seen_before_icu_mrsa_before_the_cluster(ds):
    s = one(seen_before.detect(ds, "2026-03-29"), ward="ICU")
    c = s["evidence"]["counts"]
    assert c["n_same_ward_before"] == 0 and "not seen on ICU before" in s["text"]
    assert c["n_elsewhere_before"] == 11
    assert c["elsewhere_by_ward"] == {"ED": 4, "SURG": 4, "MED-A": 1, "PHC-N": 1, "PHC-S": 1}
    assert "earlier patients elsewhere: 11 (ED 4, SURG 4, MED-A 1, PHC-N 1, PHC-S 1)" in s["text"]  # not "other 3"
    # Re-pinned from 23 of 94 "to date": that counted the cluster's own 12 patients (my-ward cross-area note), so the
    # background is now the MRSA patients sampled before the cluster's first sample on 3 Mar
    assert (c["bg_k"], c["bg_n"]) == (11, 80)
    assert "Before this cluster, 11 of 80 MRSA patients had this antibiogram (13.8%), so a match is weak" in s["text"]
    assert registry.with_title(s)["title"] == "ICU: MRSA antibiogram seen before on other units"


def test_seen_before_icu_mrsa_back_on_icu(ds):
    """The 22.7% of 110 golden is analysis 52 over the whole dataset, so it is reached at DATA_END; earlier dates
    show the share among the MRSA patients sampled up to that date."""
    s = one(seen_before.detect(ds, "2026-09-13"), ward="ICU")
    assert s["slots"]["return_date"] == "2026-09-12" and s["status"] == "new"
    end = one(seen_before.detect(ds, C.DATA_END), ward="ICU")
    assert end["slots"]["bg"] == [25, 110] and end["evidence"]["counts"]["bg_k"] == 25
    assert "To date, 25 of 110 MRSA patients had this antibiogram (22.7%)" in end["text"]
    assert registry.with_title(end)["title"] == "ICU: MRSA antibiogram back on this unit"


# ---------------------------------------------------------------- contract invariants


@pytest.mark.parametrize("as_of", ["2026-03-15", "2026-09-13"])
def test_strictly_as_of(ds, as_of):
    cut = truncated(ds, as_of)
    for mod in DETECTORS:
        full = json.dumps(mod.detect(ds, as_of), sort_keys=True, default=str)
        assert json.dumps(mod.detect(cut, as_of), sort_keys=True, default=str) == full, mod.__name__


def test_every_signal_meets_the_contract(ds):
    dates = [str((pd.Timestamp(m) - pd.Timedelta(days=1)).date()) for m in C.DEMO_MONDAYS]
    dates += ["2024-09-22", "2025-06-04", "2025-10-05", "2026-04-12", C.DATA_END]
    n = 0
    for as_of in dates:
        for mod in DETECTORS:
            for s in mod.detect(ds, as_of):
                check_signal(s)
                n += 1
    assert n > 20


def test_outbreak_templates_have_no_literal_numbers():
    for tid, t in OUTBREAK_TEMPLATES.items():
        assert tid.startswith("ob_") and templates.TEMPLATES[tid] is t
        assert not DIGITS.search(re.sub(r"\{[^}]*\}", "", t["text"])), tid
        check_title_template(tid)


def test_background_share_needs_ten_patients():
    """Brief D3 rule for every background share: x of n always, no percentage below 10, "small n" from 10 to 29."""
    slots = {
        "ward": "ICU",
        "organism_label": "VRE E. faecium",
        "pattern": "AMP:R VAN:R",
        "n_elsewhere": 0,
        "bg_label": "VRE E. faecium",
    }
    for n, key, pct in [(5, "few", None), (20, "weak_low_n", "10.0%, small n"), (40, "weak_ok", "5.0%")]:
        text = render.render_id(f"ob_seen_before__new__0__{key}", {**slots, "bg": [2, n], "bg_share": 2 / n})
        assert f"2 of {n} VRE E. faecium patients" in text and (pct in text if pct else "%" not in text), text
    for state in ("not_enough_data", "low_n", "ok"):
        assert (
            f"ob_phenotype_marker__{state}" in templates.TEMPLATES
            and f"ob_phenotype_plain__{state}" in templates.TEMPLATES
        )


def test_resolved_outbreak_items(ds):
    """Brief D5: the week after a cluster stops, its card and its seen-before match say so."""
    (s,) = icu_clusters(ds, "2026-04-12")
    assert s["status"] == "resolved" and s["advice"] is None
    assert s["text"] == (
        "ICU: unusual pattern of MRSA (FOX:R VAN:S CLI:R) since 3 Mar. Resolved. Last flagged week ending 5 Apr 2026; "
        "last detected 27 Mar. 12 of 13 MRSA patients share this antibiogram."
    )
    seen = one(seen_before.detect(ds, "2026-04-12"), ward="ICU")
    assert seen["status"] == "resolved" and seen["text"] == (
        "ICU MRSA pattern (FOX:R VAN:S CLI:R). Resolved. Last flagged week ending 5 Apr 2026; the ICU cluster that "
        "began 3 Mar 2026 was last detected 27 Mar."
    )


def test_outpatient_cluster_action(ds):
    """THL Ohjaus 2/2020 section 8.1.3: standard precautions at an outpatient unit, ward measures if admitted."""
    s = one(thl.detect(ds, "2024-08-25"), ward="PHC-S")
    assert s["template_id"] == "ob_thl_cluster_mixed"
    assert s["evidence"]["action"].startswith(
        "Standard precautions at the outpatient unit; contact precautions if admitted"
    )
    assert thl.action_text("mrsa", "Staphylococcus aureus", outpatient=True).startswith("Standard precautions")
