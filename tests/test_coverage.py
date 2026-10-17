"""Coverage cell tests: effective-result rules, small-n states, and goldens under both counting rules."""
import json

import numpy as np
import pandas as pd
import pytest

from aei import aggregates as ag
from aei import config as C
from aei import coverage as cv
from aei import data

ECOLI, SA, EF, PA = "Escherichia coli", "Staphylococcus aureus", "Enterococcus faecalis", "Pseudomonas aeruginosa"


def _rows(specs):
    """Synthetic isolates: specs = [(organism, {drug: "S"/"R"}), ...]."""
    out = []
    for i, (org, res) in enumerate(specs):
        r = {d: np.nan for d in C.DRUGS}
        r.update(res)
        out.append({"isolate_id": f"I{i}", "patient_id": f"P{i}", "organism": org, "specimen": "blood",
                    "sample_date": pd.Timestamp("2026-03-01"), "esbl": 0, "mrsa": int(org == SA and res.get("FOX") == "R"),
                    "vre": 0, "cpe": 0, **r})
    return pd.DataFrame(out)


def _ind(df, key):
    return cv.indicator_matrix(df)[:, cv.KEY_INDEX[key]]


# ---------------------------------------------------------------- effective results (aei.phenotype_rules)
def test_intrinsic_and_no_breakpoint_count_as_tested_not_covered():
    df = _rows([(ECOLI, {"VAN": "S"}), (ECOLI, {}), (PA, {"AMP": "S"}), (EF, {"MEC": "S"})])
    assert list(_ind(df, "VAN")[:2]) == [0.0, 0.0]          # intrinsic, even if a result says S
    assert _ind(df, "AMP")[2] == 0.0                        # P. aeruginosa ampicillin: intrinsic
    assert _ind(df, "MEC")[3] == 0.0                        # E. faecalis mecillinam: no breakpoint


def test_untested_non_intrinsic_is_excluded():
    df = _rows([(ECOLI, {"CIP": "S"}), (ECOLI, {})])
    v = _ind(df, "CIP")
    assert v[0] == 1.0 and np.isnan(v[1])


def test_s_aureus_beta_lactams_follow_cefoxitin():
    df = _rows([(SA, {"FOX": "S"}), (SA, {"FOX": "R", "MEM": "S"}), (SA, {"FOX": "S", "AMP": "S"})])
    for k in ("CXM", "CRO", "TZP", "MEM"):
        assert list(_ind(df, k)) == [1.0, 0.0, 1.0]
    # re-pinned for the shared effective result: MRSA is R to every beta-lactam (EUCAST Staphylococcus rule 1), an
    # MSSA's ampicillin stays untested (penicillinase unknown), and a reported ampicillin result stands
    assert np.isnan(_ind(df, "AMP")[0]) and list(_ind(df, "AMP")[1:]) == [0.0, 1.0]
    assert _ind(df, "CAZ")[0] == 0.0                         # intrinsic for S. aureus


def test_e_faecalis_tzp_follows_ampicillin_and_meropenem_has_no_breakpoint():
    df = _rows([(EF, {"AMP": "S"}), (EF, {"AMP": "R"})])
    assert list(_ind(df, "TZP")) == [1.0, 0.0]
    assert list(_ind(df, "MEM")) == [0.0, 0.0]               # re-pinned: no enterococcal MEM breakpoint (EUCAST v16.1)
    assert list(_ind(df, "CRO")) == [0.0, 0.0]


def test_combo_covered_if_any_member_covered():
    df = _rows([(SA, {"FOX": "R", "VAN": "S"}), (ECOLI, {"MEM": "S"}), (ECOLI, {"MEM": "R"}), (ECOLI, {})])
    assert list(_ind(df, "MEM+VAN")) == [1.0, 1.0, 0.0, 0.0]  # E. coli VAN is intrinsic: tested, not covered
    df2 = _rows([(EF, {})])                                    # meropenem: no breakpoint, so R even untested
    assert _ind(df2, "MEM")[0] == 0.0 and np.isnan(_ind(df2, "VAN")[0]) and _ind(df2, "MEM+VAN")[0] == 0.0
    assert np.isnan(_ind(df2, "TZP")[0])                     # nothing to infer from without an ampicillin result
    df3 = _rows([(ECOLI, {}), (SA, {})])
    assert np.isnan(_ind(df3, "CIP")).all() and np.isnan(_ind(df3, "VAN")[1])


def test_species_reason_and_has_result():
    assert cv.species_reason(ECOLI, "VAN") == "intrinsic" and cv.species_reason(EF, "MEM") == "no_breakpoint"
    assert cv.species_reason(SA, "MEM") is None and cv.species_reason(ECOLI, "CIP") is None
    e_coli = cv.counts_of(_rows([(ECOLI, {"MEM": "S"}), (ECOLI, {})]))
    assert not cv.has_result(e_coli, "VAN")                  # 2 tested, both only because the species is intrinsic R
    assert cv.has_result(e_coli, "MEM") and cv.has_result(e_coli, "MEM+VAN")
    assert not cv.has_result(e_coli, "CIP")                  # untested


def test_labels_and_aware():
    assert cv.label("MEM") == "Meropenem" and cv.label("MEM+VAN") == "Meropenem + vancomycin"
    assert cv.aware("MEM") == "Watch" and cv.aware("NIT") == "Access" and cv.aware("CRO+VAN") == "Watch"
    assert cv.short_organism(SA) == "S. aureus"
    with pytest.raises(ValueError):
        cv.parts("XYZ")


# ---------------------------------------------------------------- small-n states
@pytest.mark.parametrize("n,state", [(9, "not_enough_data"), (15, "low_n"), (40, "ok")])
def test_states_and_estimate_rule(n, state):
    win = _rows([(ECOLI, {"MEM": "S" if i % 3 else "R"}) for i in range(n)])
    ref = _rows([(ECOLI, {"MEM": "S"}) for _ in range(200)])
    c = cv.cell(win, "MEM", hosp_rows=pd.concat([ref, win]))
    covered = sum(1 for i in range(n) if i % 3)
    assert c["state"] == state
    assert c["observed"]["covered"] == covered and c["observed"]["tested"] == n   # x of n always present
    if state == "not_enough_data":
        assert c["observed"]["pct"] is None and c["estimate"]["pct"] is None and c["below_local_setting"] is None
        assert c["changed"] is None                                               # never next to "not enough data"
    elif state == "low_n":
        assert c["estimate"]["method"] == "stabilised"
        assert c["estimate"]["pct"] > c["observed"]["pct"]                        # pulled toward the 100% reference
        assert c["estimate"]["ci"][0] < c["estimate"]["pct"] < c["estimate"]["ci"][1]
    else:
        assert c["estimate"]["method"] == "observed" and c["estimate"]["pct"] == pytest.approx(covered / n)
    json.dumps(c, allow_nan=False)


def test_eligibility_tested_share():
    win = _rows([(ECOLI, {"CIP": "S"})] * 18 + [(SA, {"FOX": "S"})] * 2)
    c = cv.cell(win, "CIP")
    assert c["tested_share"] == pytest.approx(0.9) and c["eligible"] is True
    c = cv.cell(_rows([(ECOLI, {"CIP": "S"})] * 17 + [(SA, {"FOX": "S"})] * 3), "CIP")
    assert c["eligible"] is False
    assert cv.untested(cv.counts_of(win), "CIP") == [(SA, 2)]


def test_changed_flag_on_not_covered_counts():
    prior = _rows([(ECOLI, {"MEM": "S"})] * 200)
    win = _rows([(ECOLI, {"MEM": "R" if i < 8 else "S"}) for i in range(20)])
    c = cv.cell(win, "MEM", prior_rows=prior, hosp_rows=pd.concat([prior, win]))
    assert c["changed"]["changed"] is True and c["changed"]["direction"] == "down" and c["changed"]["p"] < 1e-3
    assert c["changed"]["prior"] == {"covered": 200, "tested": 200}
    quiet = cv.cell(_rows([(ECOLI, {"MEM": "S"})] * 20), "MEM", prior_rows=prior)
    assert quiet["changed"]["changed"] is False and quiet["changed"]["direction"] is None
    assert cv.cell(win, "MEM")["changed"] is None                                  # no prior baseline
    tiny = _rows([(ECOLI, {"MEM": "R" if i < 4 else "S"}) for i in range(9)])
    assert cv.cell(tiny, "MEM", prior_rows=prior)["changed"] is None               # 4 of 9: not enough data (my-ward #4)


def test_stabilised_interval_never_collapses_at_all_or_none_covered():
    """my-ward #1: 11 of 11 against a hospital rate of ~100% printed "100 [100-100]" before the Jeffreys floor."""
    ref = cv.counts_of(_rows([(ECOLI, {"MEM": "S", "VAN": "S"})] * 5000))
    win = cv.counts_of(_rows([(ECOLI, {"MEM": "S"})] * 11))
    mem, van = cv.stabilised(win, ref, "MEM"), cv.stabilised(win, ref, "VAN")    # E. coli VAN: intrinsic, 0 of 11
    assert mem["ci"][0] < 0.95 and mem["ci"][1] > mem["pct"]
    assert van["ci"][0] < van["pct"] and van["ci"][1] > 0.05


# ---------------------------------------------------------------- goldens on the real (synthetic) dataset
def _frames(ds, ward, sg, as_of, rule, days=28):
    """The 36b frames: unit window, unit prior 52 weeks, hospital (same specimen group) up to as-of, hospital prior."""
    x = ds.isolates
    a = pd.Timestamp(as_of)
    lo = a - pd.Timedelta(days=days)
    spec = x.specimen.isin(C.SPECIMEN_GROUPS[sg])
    unit = x[spec & (x.ward_code == ward)]
    return (data.first_isolates(data.window(unit, a, days), rule), data.first_isolates(data.window(unit, lo, 364), rule),
            data.first_isolates(x[spec & (x.sample_date <= a)], rule), data.first_isolates(data.window(x[spec], lo, 364), rule))


# Pinned from this implementation; every value equals a 400,000-draw run to the displayed integer. Tuple: (stabilised
# pct, ci lo, ci hi, covered, tested). "30d" is 36b's counting rule: its observed counts equal 36b_coverage_asof.txt.
# Re-pinned from 36b's printed estimates (ICU MEM 74 [61-85], TZP 73 [60-84], VAN 78 [62-91]; URO CRO 70 [60-78],
# CIP 70 [60-78], NIT 90 [83-95]): E. faecalis meropenem has no EUCAST breakpoint (v16.1), each organism's share has a
# Jeffreys floor (my-ward #1) and the draws went from 4,000 to 40,000 (my-ward #5).
GOLDEN = {
    ("30d", "ICU", "blood_wound", "2026-03-29"): {"n": 24, "MEM": (0.7155, 0.5798, 0.8275, 11, 24),
                                                  "TZP": (0.7235, 0.5925, 0.8309, 11, 24),
                                                  "VAN": (0.7790, 0.6118, 0.8995, 20, 24)},
    ("30d", "URO", "urine", "2025-06-29"): {"n": 67, "CRO": (0.6930, 0.5965, 0.7794, 40, 65),
                                           "CIP": (0.6909, 0.5928, 0.7770, 35, 60),
                                           "NIT": (0.8935, 0.8231, 0.9415, 61, 67)},
    ("readme_period", "ICU", "blood_wound", "2026-03-29"): {"n": 24, "MEM": (0.7156, 0.5814, 0.8280, 11, 24),
                                                            "TZP": (0.7248, 0.5928, 0.8318, 11, 24),
                                                            "VAN": (0.7760, 0.6069, 0.8970, 20, 24)},
    ("readme_period", "URO", "urine", "2025-06-29"): {"n": 69, "CRO": (0.6986, 0.6042, 0.7840, 42, 67),
                                                     "CIP": (0.6987, 0.6018, 0.7830, 37, 62),
                                                     "NIT": (0.8939, 0.8255, 0.9416, 63, 69)},
}


@pytest.mark.parametrize("case", list(GOLDEN))
def test_goldens_under_both_counting_rules(ds, case):
    rule, ward, sg, as_of = case
    g = GOLDEN[case]
    win, prior, hosp, hprior = _frames(ds, ward, sg, as_of, rule)
    assert len(win) == g["n"]
    orgs = tuple(sorted(ds.isolates.organism.unique()))
    W, H = cv.counts_of(win, orgs), cv.counts_of(hosp, orgs)
    for drug, (m, lo, hi, x, n) in ((k, v) for k, v in g.items() if k != "n"):
        s = cv.stabilised(W, H, drug)                                 # the window WISCA value (36b method)
        assert s["pct"] == pytest.approx(m, abs=0.002) and s["ci"] == pytest.approx([lo, hi], abs=0.002), drug
        c = cv.cell(win, drug, prior, hosp, hosp_prior_rows=hprior)
        assert (c["observed"]["covered"], c["observed"]["tested"]) == (x, n)
        if c["state"] == "low_n":                                     # ICU: n = 24, so the cell shows the stabilised value
            assert c["estimate"]["method"] == "stabilised" and c["estimate"]["pct"] == pytest.approx(s["pct"])
        else:                                                         # URO: n >= 30, so the cell shows the observed share
            assert c["state"] == "ok" and c["estimate"]["method"] == "observed"


def test_icu_march_cell_matches_contract_example(ds):
    win, prior, hosp, hprior = _frames(ds, "ICU", "blood_wound", "2026-03-29", "readme_period")
    c = cv.cell(win, "MEM", prior, hosp, hosp_prior_rows=hprior)
    assert c["drug"] == "MEM" and c["label"] == "Meropenem" and c["aware"] == "Watch" and c["state"] == "low_n"
    assert c["observed"]["covered"] == 11 and c["observed"]["tested"] == 24
    assert round(c["observed"]["pct"], 3) == 0.458 and [round(v, 2) for v in c["observed"]["ci"]] == [0.27, 0.65]
    # re-pinned from 0.74 [0.61, 0.85]: no E. faecalis meropenem breakpoint, and the Jeffreys floor (my-ward #1)
    assert round(c["estimate"]["pct"], 2) == 0.72 and [round(v, 2) for v in c["estimate"]["ci"]] == [0.58, 0.83]
    assert c["eligible"] is True and c["tested_share"] == 1.0 and c["below_local_setting"] is True
    # p re-pinned from < 1e-6: the prior year's 21 E. faecalis now count as meropenem R too (no breakpoint, EUCAST v16.1)
    assert c["changed"]["changed"] is True and c["changed"]["direction"] == "down" and c["changed"]["p"] < 1e-4
    assert c["changed"]["prior"] == {"covered": 153, "tested": 178}


def test_fast_path_equals_dataframe_path(ds):
    """views use aggregates.Subset slices; they must give the same cell as coverage.cell on DataFrames."""
    win, prior, hosp, hprior = _frames(ds, "ICU", "blood_wound", "2026-03-29", "readme_period")
    a = pd.Timestamp("2026-03-29")
    lo = a - pd.Timedelta(days=28)
    unit = ag.subset(ds, specimen_group="blood_wound", wards=("ICU",))
    h = ag.subset(ds, specimen_group="blood_wound")
    plo = lo - pd.Timedelta(days=364)
    for key in ("MEM", "VAN", "CIP", "MEM+VAN", "CLI"):
        fast = cv.to_json(cv.cell_from_counts(unit.counts(lo, a, "readme_period"), key, unit.counts(plo, lo, "readme_period"),
                                              h.counts(None, a, "readme_period"), h.counts(plo, lo, "readme_period")))
        slow = cv.cell(win, key, prior, hosp, hosp_prior_rows=hprior)
        assert fast == slow, key


def test_cell_is_deterministic_and_json_plain(ds):
    win, prior, hosp, hprior = _frames(ds, "ICU", "blood_wound", "2026-03-08", "readme_period")
    a = cv.cell(win, "TZP", prior, hosp, hosp_prior_rows=hprior)
    b = cv.cell(win, "TZP", prior, hosp, hosp_prior_rows=hprior)
    assert a == b
    s = json.dumps(a, allow_nan=False)
    assert "NaN" not in s


def test_to_json_cleans_numpy_and_nan():
    out = cv.to_json({"a": np.float64(np.nan), "b": np.int64(3), "c": (np.bool_(True), 1.5), "d": pd.Timestamp("2026-03-29")})
    assert out == {"a": None, "b": 3, "c": [True, 1.5], "d": "2026-03-29"}
    assert type(out["b"]) is int and type(out["c"][0]) is bool
