"""Coverage cell tests: EUCAST rules, small-n states, the 36b goldens and the product-default (README rule) values."""
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


# ---------------------------------------------------------------- EUCAST rules (11_fixes / 26_trace s_col)
def test_intrinsic_and_no_breakpoint_count_as_tested_not_covered():
    df = _rows([(ECOLI, {"VAN": "S"}), (ECOLI, {}), (PA, {"AMP": "S"}), (EF, {"MEC": "S"})])
    assert list(_ind(df, "VAN")[:2]) == [0.0, 0.0]          # intrinsic, even if a result says S
    assert _ind(df, "AMP")[2] == 0.0                        # P. aeruginosa ampicillin: intrinsic
    assert _ind(df, "MEC")[3] == 0.0                        # E. faecalis mecillinam: no breakpoint


def test_untested_non_intrinsic_is_excluded():
    df = _rows([(ECOLI, {"CIP": "S"}), (ECOLI, {})])
    v = _ind(df, "CIP")
    assert v[0] == 1.0 and np.isnan(v[1])


def test_s_aureus_beta_lactams_follow_cefoxitin_and_ampicillin_unreported():
    df = _rows([(SA, {"FOX": "S"}), (SA, {"FOX": "R", "MEM": "S"}), (SA, {"FOX": "S", "AMP": "S"})])
    for k in ("CXM", "CRO", "TZP", "MEM"):
        assert list(_ind(df, k)) == [1.0, 0.0, 1.0]
    assert np.isnan(_ind(df, "AMP")).all()
    assert _ind(df, "CAZ")[0] == 0.0                         # intrinsic for S. aureus


def test_e_faecalis_tzp_mem_follow_ampicillin():
    df = _rows([(EF, {"AMP": "S"}), (EF, {"AMP": "R"})])
    assert list(_ind(df, "TZP")) == [1.0, 0.0] and list(_ind(df, "MEM")) == [1.0, 0.0]
    assert list(_ind(df, "CRO")) == [0.0, 0.0]


def test_combo_covered_if_any_member_covered():
    df = _rows([(SA, {"FOX": "R", "VAN": "S"}), (ECOLI, {"MEM": "S"}), (ECOLI, {"MEM": "R"}), (ECOLI, {})])
    assert list(_ind(df, "MEM+VAN")) == [1.0, 1.0, 0.0, 0.0]  # E. coli VAN is intrinsic: tested, not covered
    # 26_trace rule kept exactly: E. faecalis MEM follows (AMP == "S"), so a missing AMP is tested and not covered
    df2 = _rows([(EF, {})])
    assert _ind(df2, "MEM")[0] == 0.0 and np.isnan(_ind(df2, "VAN")[0]) and _ind(df2, "MEM+VAN")[0] == 0.0
    df3 = _rows([(ECOLI, {}), (SA, {})])
    assert np.isnan(_ind(df3, "CIP")).all() and np.isnan(_ind(df3, "VAN")[1])


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


# ---------------------------------------------------------------- 36b goldens on the real (synthetic) dataset
def _frames(ds, ward, sg, as_of, rule, days=28):
    """The 36b frames: unit window, unit prior 52 weeks, hospital (same specimen group) up to as-of, hospital prior."""
    x = ds.isolates
    a = pd.Timestamp(as_of)
    lo = a - pd.Timedelta(days=days)
    spec = x.specimen.isin(C.SPECIMEN_GROUPS[sg])
    unit = x[spec & (x.ward_code == ward)]
    return (data.first_isolates(data.window(unit, a, days), rule), data.first_isolates(data.window(unit, lo, 364), rule),
            data.first_isolates(x[spec & (x.sample_date <= a)], rule), data.first_isolates(data.window(x[spec], lo, 364), rule))


# 36b_coverage_asof.txt, produced with 36b's own counting rule ("30d": x[x.first_30d], computed on the full history).
# Stabilised values are Monte Carlo medians/percentiles (36b used rng(7); we use stats.rng()), so they agree to within
# one percentage point of the printed integers; the observed counts are exact.
GOLDEN_36B = {
    ("ICU", "blood_wound", "2026-03-29"): {"n": 24, "MEM": (74, 61, 85, 11, 24), "TZP": (73, 60, 84, 11, 24),
                                           "VAN": (78, 62, 91, 20, 24)},
    ("URO", "urine", "2025-06-29"): {"n": 67, "CRO": (70, 60, 78, 40, 65), "CIP": (70, 60, 78, 35, 60),
                                     "NIT": (90, 83, 95, 61, 67)},
}


@pytest.mark.parametrize("case", list(GOLDEN_36B))
def test_36b_goldens_with_36b_counting_rule(ds, case):
    ward, sg, as_of = case
    g = GOLDEN_36B[case]
    win, prior, hosp, hprior = _frames(ds, ward, sg, as_of, "30d")
    assert len(win) == g["n"]
    orgs = tuple(sorted(ds.isolates.organism.unique()))
    W, H = cv.counts_of(win, orgs), cv.counts_of(hosp, orgs)
    for drug, (m, lo, hi, x, n) in ((k, v) for k, v in g.items() if k != "n"):
        s = cv.stabilised(W, H, drug)
        assert abs(100 * s["pct"] - m) <= 1.0 and abs(100 * s["ci"][0] - lo) <= 1.0 and abs(100 * s["ci"][1] - hi) <= 1.0, (drug, s)
        c = cv.cell(win, drug, prior, hosp, hosp_prior_rows=hprior)
        assert (c["observed"]["covered"], c["observed"]["tested"]) == (x, n)
        if c["state"] == "low_n":                                     # ICU: n = 24, so the cell shows the stabilised value
            assert c["estimate"]["method"] == "stabilised" and c["estimate"]["pct"] == pytest.approx(s["pct"])
        else:                                                         # URO: n >= 30, so the cell shows the observed share
            assert c["state"] == "ok" and c["estimate"]["method"] == "observed"


# Product default (README rule: first isolate per patient x organism x specimen inside each window), pinned from this
# implementation with stats.rng(). Tuple: (estimate pct, ci lo, ci hi, covered, tested); est None = observed shown.
GOLDEN_README = {
    ("ICU", "blood_wound", "2026-03-29"): {"n": 24, "MEM": (0.7424, 0.6106, 0.8475, 11, 24), "TZP": (0.7327, 0.5998, 0.8415, 11, 24),
                                           "VAN": (0.7804, 0.6104, 0.9039, 20, 24)},
    ("URO", "urine", "2025-06-29"): {"n": 69, "CRO": (0.7032, 0.6074, 0.7888, 42, 67), "CIP": (0.7038, 0.6070, 0.7922, 37, 62),
                                     "NIT": (0.9021, 0.8366, 0.9479, 63, 69)},
}


@pytest.mark.parametrize("case", list(GOLDEN_README))
def test_product_default_readme_rule_values(ds, case):
    ward, sg, as_of = case
    g = GOLDEN_README[case]
    win, prior, hosp, hprior = _frames(ds, ward, sg, as_of, "readme_period")
    assert len(win) == g["n"]
    orgs = tuple(sorted(ds.isolates.organism.unique()))
    W, H = cv.counts_of(win, orgs), cv.counts_of(hosp, orgs)
    for drug, (m, lo, hi, x, n) in ((k, v) for k, v in g.items() if k != "n"):
        s = cv.stabilised(W, H, drug)                                 # the window WISCA value (36b method, README rule)
        assert s["pct"] == pytest.approx(m, abs=0.002) and s["ci"] == pytest.approx([lo, hi], abs=0.002)
        c = cv.cell(win, drug, prior, hosp, hosp_prior_rows=hprior)
        assert (c["observed"]["covered"], c["observed"]["tested"]) == (x, n)


def test_icu_march_cell_matches_contract_example(ds):
    win, prior, hosp, hprior = _frames(ds, "ICU", "blood_wound", "2026-03-29", "readme_period")
    c = cv.cell(win, "MEM", prior, hosp, hosp_prior_rows=hprior)
    assert c["drug"] == "MEM" and c["label"] == "Meropenem" and c["aware"] == "Watch" and c["state"] == "low_n"
    assert c["observed"]["covered"] == 11 and c["observed"]["tested"] == 24
    assert round(c["observed"]["pct"], 3) == 0.458 and [round(v, 2) for v in c["observed"]["ci"]] == [0.27, 0.65]
    assert round(c["estimate"]["pct"], 2) == 0.74 and [round(v, 2) for v in c["estimate"]["ci"]] == [0.61, 0.85]
    assert c["eligible"] is True and c["tested_share"] == 1.0 and c["below_local_setting"] is True
    assert c["changed"]["changed"] is True and c["changed"]["direction"] == "down" and c["changed"]["p"] < 1e-6


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
