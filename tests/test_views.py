"""My ward, filter catalogue and trend views: contract shape, display rules, strict as-of, speed, wording."""

import json
import math
import re
import time

import pandas as pd
import pytest

from aei import aggregates as ag
from aei import config as C
from aei import data, render, views

BANNED = re.compile(
    r"predict|forecast|\bodds\b|probability that|best choice|recommended drug|s/i/r|decoy|outbreak confirmed|"
    r"zero resistance",
    re.IGNORECASE,
)
PHC = ["PHC-N", "PHC-S"]


def _plain(obj):
    """Recursively assert only JSON-native types (no numpy scalars, no NaN)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, str)
            _plain(v)
    elif isinstance(obj, list):
        for v in obj:
            _plain(v)
    else:
        assert obj is None or type(obj) in (str, int, float, bool), (type(obj), obj)
        if type(obj) is float:
            assert math.isfinite(obj)


@pytest.fixture(scope="module")
def icu(ds):
    return views.my_ward(ds, "2026-03-29", ward="ICU", specimen_group="blood_wound")


def _cell(out, drug, window="4w"):
    return next(r for r in out["rows"] if r["drug"] == drug)["cells"][window]


def test_my_ward_shape_and_json(icu):
    assert icu["as_of"] == "2026-03-29" and icu["monday"] == "2026-03-30"
    assert icu["filters"]["ward"] == "ICU" and icu["filters"]["specimen_group"] == "blood_wound"
    assert icu["filters"]["rule"] == "readme_period" and icu["filters"]["windows"] == ["4w", "12m"]
    assert [w["key"] for w in icu["windows"]] == ["4w", "12m"]
    assert icu["windows"][0] == {
        "key": "4w",
        "label": "Last 4 weeks",
        "days": 28,
        "from": "2026-03-02",
        "to": "2026-03-29",
        "n_isolates": 24,
    }
    assert icu["local_setting"] == {"value": 0.80, "label": "local setting, set by stewardship"}
    assert icu["footer"] == "In-vitro coverage on this unit. Not a prescription; local guide first."
    _plain(icu)
    json.dumps(icu, allow_nan=False)


def test_rows_follow_display_order_and_hidden_drugs(icu):
    drugs = [r["drug"] for r in icu["rows"]]
    assert drugs == [d for d in C.DISPLAY_ORDER if d in drugs]
    assert drugs == ["CLI", "CXM", "CRO", "VAN", "TZP", "MEM", "CRO+VAN", "TZP+VAN", "MEM+VAN"]
    hidden = {n["drug"]: n for n in icu["not_shown"]}
    assert {"NIT", "MEC", "TMP"} <= set(hidden) and hidden["NIT"]["code"] == "urine_only"
    assert hidden["FOX"]["code"] == "screening_only" and "FOX" not in drugs
    assert (
        hidden["CIP"]["reason"]
        == "Ciprofloxacin not shown: untested on S. aureus and E. faecalis (most of this unit's isolates)"
    )
    assert hidden["AMP"]["code"] == "not_tested_enough" and "S. aureus" in hidden["AMP"]["reason"]


def _shown(cell) -> str:
    """The estimate as the screen prints it, e.g. "72% [58–83]"."""
    return f"{render.fmt(cell['estimate']['pct'], 'pct0')} [{render.fmt(cell['estimate']['ci'], 'ci0')}]"


def test_icu_march_numbers(icu):
    # README rule (product default). The 4-week MRSA influx: 13 of 20 S. aureus are MRSA. Re-pinned from MEM 74 [61-85]
    # and TZP 73 [60-84]: E. faecalis meropenem has no EUCAST breakpoint, and the Jeffreys floor.
    for drug, (shown, covered) in {
        "MEM": ("72% [58–83]", 11),
        "TZP": ("72% [59–83]", 11),
        "VAN": ("78% [61–90]", 20),
    }.items():
        c = _cell(icu, drug)
        assert (c["observed"]["covered"], c["observed"]["tested"]) == (covered, 24), drug
        assert c["state"] == "low_n" and c["estimate"]["method"] == "stabilised", drug
        assert _shown(c) == shown, drug
    mem, van = _cell(icu, "MEM"), _cell(icu, "VAN")
    assert mem["changed"]["changed"] and mem["changed"]["direction"] == "down"
    assert van["changed"]["changed"] and van["changed"]["direction"] == "up"
    assert _cell(icu, "MEM", "12m")["state"] == "ok" and _cell(icu, "MEM", "12m")["estimate"]["method"] == "observed"
    sa = icu["organisms"]["4w"][0]
    assert sa == {"organism": "Staphylococcus aureus", "label": "S. aureus", "n": 20, "flags": {"mrsa": 13}}
    assert icu["small_n_examples"] and icu["small_n_examples"][0]["window"] == "4w"


def test_small_n_rule_in_view(ds):
    out = views.my_ward(ds, "2026-03-29", ward="ICU", specimen_group="blood")
    for r in out["rows"]:
        for c in r["cells"].values():
            assert "covered" in c["observed"] and "tested" in c["observed"]
            if c["state"] == "not_enough_data":
                assert c["observed"]["pct"] is None and c["estimate"]["pct"] is None
            elif c["state"] == "low_n":
                assert c["estimate"]["method"] == "stabilised"
            else:
                assert c["estimate"]["method"] == "observed"
    assert any(c["state"] == "not_enough_data" for r in out["rows"] for c in r["cells"].values())


def test_uro_june_2025(ds):
    out = views.my_ward(ds, "2025-06-29", ward="URO", specimen_group="urine")
    assert out["windows"][0]["n_isolates"] == 69
    cro, nit = _cell(out, "CRO"), _cell(out, "NIT")
    assert (cro["observed"]["covered"], cro["observed"]["tested"]) == (42, 67) and cro["state"] == "ok"
    assert (nit["observed"]["covered"], nit["observed"]["tested"]) == (63, 69)
    assert cro["changed"]["changed"] and cro["changed"]["direction"] == "down"
    assert [r["drug"] for r in out["rows"]][:3] == ["NIT", "MEC", "TMP"]  # urine-only drugs shown for urine
    hidden = {n["drug"]: n["code"] for n in out["not_shown"]}  # CIP untested on 16% (E. faecalis, staphylococci)
    assert hidden == {
        "CIP": "not_tested_enough",
        "CAZ": "not_tested_enough",
        "FOX": "screening_only",
        "CLI": "not_for_urine",
        "VAN": "not_for_urine",
        **{
            combo: "not_for_urine" for combo in ("CRO+VAN", "TZP+VAN", "MEM+VAN")
        },  # with vancomycin: not for urine either
    }
    # the prior 52 weeks of the 12-month window would start in Jul 2023, before the data does
    assert all(r["cells"]["12m"]["changed"] is None for r in out["rows"])


def test_primary_care_women_trimethoprim(ds):
    allorg = views.my_ward(ds, "2026-06-21", ward=PHC, specimen_group="urine", sex="F")
    tmp = next(n for n in allorg["not_shown"] if n["drug"] == "TMP")
    assert tmp["reason"] == "Trimethoprim not shown: untested on E. faecalis (11% of the selected isolates)"
    assert allorg["filters"]["ward"] == PHC and allorg["filters"]["sex"] == "F"
    ec = views.my_ward(ds, "2026-06-21", ward=PHC, specimen_group="urine", sex="F", organism="Escherichia coli")
    c12 = _cell(ec, "TMP", "12m")
    # same 786 isolates as the policy line golden (160 of 786 resistant = 20.4% at the week ending 2026-06-21)
    assert (c12["observed"]["covered"], c12["observed"]["tested"]) == (626, 786)
    assert c12["below_local_setting"] is True


def test_filters_setting_sex_age_and_home_area(ds):
    def n12(rule, setting=None):
        return views.my_ward(ds, "2026-09-27", specimen_group="urine", setting=setting, rule=rule)["windows"][1][
            "n_isolates"
        ]

    # the 30-day flag partitions exactly; the README rule counts a patient seen in both settings once in "all"
    assert n12("30d") == n12("30d", "inpatient") + n12("30d", "outpatient")
    assert 0 < n12("readme_period") < n12("readme_period", "inpatient") + n12("readme_period", "outpatient")
    f = views.my_ward(ds, "2026-09-27", specimen_group="urine", sex="female", age_band="80+")
    assert f["filters"]["sex"] == "F" and f["filters"]["age_band"] == "80+"
    link = views.my_ward(
        ds,
        "2026-06-21",
        ward="ED,PHC-N,PHC-S",
        home_area="South",
        specimen_group="urine",
        organism="Escherichia coli",
        sex="F",
    )
    assert link["filters"]["ward"] == ["ED", "PHC-N", "PHC-S"] and link["filters"]["home_area"] == "South"
    nolink = views.my_ward(
        ds, "2026-06-21", ward="ED,PHC-N,PHC-S", specimen_group="urine", organism="Escherichia coli", sex="F"
    )
    assert 0 < link["windows"][1]["n_isolates"] < nolink["windows"][1]["n_isolates"]
    north_only = views.my_ward(ds, "2026-06-21", ward="PHC-N", home_area="South", specimen_group="urine")
    assert north_only["windows"][1]["n_isolates"] == 0  # PHC-N serves the North area only
    with pytest.raises(ValueError):
        views.my_ward(ds, "2026-06-21", ward="XYZ")
    with pytest.raises(ValueError):
        views.my_ward(ds, "2026-06-21", home_area="Atlantis")
    with pytest.raises(ValueError):
        views.my_ward(ds, "2026-06-21", setting="day-case")


def test_strictly_as_of(ds):
    """Removing every isolate sampled after as_of must not change any number in the views."""
    as_of = "2026-03-29"
    x = ds.isolates
    cut = data.Dataset(
        isolates=x[x.sample_date <= pd.Timestamp(as_of)].reset_index(drop=True),
        cultures=ds.cultures,
        patients=ds.patients,
    )
    for kw in ({"ward": "ICU", "specimen_group": "blood_wound"}, {"ward": PHC, "specimen_group": "urine", "sex": "F"}):
        assert views.my_ward(cut, as_of, **kw) == views.my_ward(ds, as_of, **kw)
    assert views.trend(cut, "ICU", "blood_wound", "MEM", as_of, weeks=8) == views.trend(
        ds, "ICU", "blood_wound", "MEM", as_of, weeks=8
    )


def test_rule_switch_reproduces_the_30d_counts(ds):
    """CONTRACTS 4.1 goldens through the view under the 30-day counting rule ("30d")."""
    icu = views.my_ward(ds, "2026-03-29", ward="ICU", specimen_group="blood_wound", rule="30d")
    assert icu["filters"]["rule"] == "30d" and icu["windows"][0]["n_isolates"] == 24
    # re-pinned from the original analysis's printed MEM 74 [61-85], TZP 73 [60-84], VAN 78 [62-91]; see test_coverage.GOLDEN for why
    for drug, (shown, covered) in {
        "MEM": ("72% [58–83]", 11),
        "TZP": ("72% [59–83]", 11),
        "VAN": ("78% [61–90]", 20),
    }.items():
        c = _cell(icu, drug)
        assert (c["observed"]["covered"], c["observed"]["tested"]) == (covered, 24), drug
        assert _shown(c) == shown, drug
    uro = views.my_ward(ds, "2025-06-29", ward="URO", specimen_group="urine", rule="30d")
    assert uro["windows"][0]["n_isolates"] == 67
    for drug, (covered, tested) in {"CRO": (40, 65), "NIT": (61, 67)}.items():
        c = _cell(uro, drug)
        assert (c["observed"]["covered"], c["observed"]["tested"]) == (covered, tested) and c["state"] == "ok", drug
    cip = next(n for n in uro["not_shown"] if n["drug"] == "CIP")  # 60 of 67 in 4 weeks, 84% in 12 months
    assert (
        cip["code"] == "not_tested_enough"
        and cip["window"] == "12m"
        and cip["tested_share"] < C.ELIGIBLE_MIN_TESTED_SHARE
    )


def test_rows_with_only_species_rules_are_not_shown(ds):
    """A row whose every result is EUCAST's species-level R ("0 of 957 covered") is hidden with the reason."""
    sa = views.my_ward(ds, "2026-03-29", ward="ICU", specimen_group="blood_wound", organism="Staphylococcus aureus")
    caz = next(n for n in sa["not_shown"] if n["drug"] == "CAZ")
    assert caz["code"] == "expected_resistant"
    assert caz["reason"] == "Ceftazidime not shown: S. aureus is intrinsically resistant (EUCAST)"
    ef = views.my_ward(ds, "2026-09-27", specimen_group="blood_wound", organism="Enterococcus faecalis")
    reasons = {n["drug"]: n["reason"] for n in ef["not_shown"] if n["code"] == "expected_resistant"}
    assert reasons["MEM"] == "Meropenem not shown: EUCAST has no breakpoint for E. faecalis"
    assert set(reasons) == {"CLI", "CXM", "CRO", "CAZ", "MEM"}
    assert {"VAN", "MEM+VAN"} <= {r["drug"] for r in ef["rows"]}  # vancomycin is a lab result here
    pa = views.my_ward(ds, "2026-09-27", specimen_group="wound", organism="Pseudomonas aeruginosa")
    assert "CRO+VAN" in {n["drug"] for n in pa["not_shown"]} and "TZP+VAN" in {r["drug"] for r in pa["rows"]}
    men = views.my_ward(ds, "2026-09-27", ward="URO", specimen_group="urine", organism="Escherichia coli", sex="M")
    assert not {"CLI", "VAN"} & {r["drug"] for r in men["rows"]}
    caz = next(n for n in men["not_shown"] if n["drug"] == "CAZ")  # untested: not a species rule
    assert caz["code"] == "not_tested_enough"
    assert caz["reason"] == "Ceftazidime not shown: untested on E. coli (all of this unit's isolates)"


def test_an_untested_share_rounds_half_up_from_the_counts(ds):
    """Re-verification #4: 26 of 80 isolates untested is 32.5%, which prints 33%, not the float 1 - 54 / 80."""
    view = views.my_ward(ds, "2026-03-08", ward="MED-A", specimen_group="wound")
    caz = next(n for n in view["not_shown"] if n["drug"] == "CAZ")
    assert caz["reason"].endswith("(33% of this unit's isolates)") and caz["tested_share"] == 54 / 80


def test_stabilised_interval_in_view_does_not_collapse(ds):
    """URO men E. coli meropenem 11 of 11 printed "100 [100-100]"."""
    men = views.my_ward(ds, "2026-09-27", ward="URO", specimen_group="urine", organism="Escherichia coli", sex="M")
    mem = _cell(men, "MEM")
    assert (mem["observed"]["covered"], mem["observed"]["tested"], mem["state"]) == (11, 11, "low_n")
    assert _shown(mem) == "99% [92–100]"


def test_no_change_claimed_without_a_percentage(ds):
    """ICU blood, 4 weeks to 29 Mar 2026: MEM 4 of 9 used to say "changed down"."""
    out = views.my_ward(ds, "2026-03-29", ward="ICU", specimen_group="blood")
    small = [r["cells"]["4w"] for r in out["rows"] if r["cells"]["4w"]["state"] == "not_enough_data"]
    assert small and all(c["changed"] is None for c in small)


def test_footer_names_the_scope(ds, icu):
    """The "on this unit" wording only when one unit is selected."""
    assert icu["footer"] == "In-vitro coverage on this unit. Not a prescription; local guide first."
    several = views.my_ward(ds, "2026-06-21", ward=PHC, specimen_group="urine")
    assert several["footer"] == "In-vitro coverage on the selected units. Not a prescription; local guide first."
    everyone = views.my_ward(ds, "2026-06-21", specimen_group="urine")
    assert everyone["footer"] == "In-vitro coverage on all units. Not a prescription; local guide first."


def test_filters_catalog(ds):
    fc = views.filters_catalog(ds)
    _plain(fc)
    assert [w["code"] for w in fc["wards"]] == list(C.WARD_LABELS)
    setting = {w["code"]: w["setting"] for w in fc["wards"]}
    assert setting["ED"] == "outpatient" and setting["PHC-N"] == "outpatient" and setting["ICU"] == "inpatient"
    assert [s["key"] for s in fc["specimen_groups"]] == list(C.SPECIMEN_GROUPS)
    # re-pinned: no counts and no order by count, which came from the whole dataset, after any replay date
    assert [o["organism"] for o in fc["organisms"]] == sorted(ds.isolates.organism.unique()) and len(
        fc["organisms"]
    ) == 9
    assert all(set(o) == {"organism", "label"} for o in fc["organisms"]) and all("n" not in h for h in fc["home_areas"])
    assert [w["label"] for w in fc["windows"]] == ["Last 4 weeks", "Last 16 weeks", "Last 52 weeks"]
    assert [s["code"] for s in fc["sexes"]] == ["F", "M"] and [a["key"] for a in fc["age_bands"]] == [
        "0-17",
        "18-64",
        "65-79",
        "80+",
    ]
    assert [s["key"] for s in fc["settings"]] == ["inpatient", "outpatient"]
    assert [h["key"] for h in fc["home_areas"]] == ["Centre", "East", "North", "South", "West"]
    assert [r["key"] for r in fc["rules"]] == ["readme_period", "30d"]


def test_trend(ds, icu):
    tr = views.trend(ds, "ICU", "blood_wound", "MEM", "2026-03-29")
    _plain(tr)
    s = tr["series"]
    assert len(s) == 52 and s[-1]["as_of"] == "2026-03-29" and s[0]["as_of"] == "2025-04-06"
    assert all(pd.Timestamp(p["as_of"]).dayofweek == 6 for p in s)
    last = {k: v for k, v in s[-1].items() if k not in ("as_of", "from", "to")}
    assert last == _cell(icu, "MEM")  # sparkline end = the table cell
    assert tr["filters"]["home_area"] is None
    with pytest.raises(ValueError):
        views.trend(ds, "ICU", "blood_wound", "FOX", "2026-03-29")  # never a therapy option
    with pytest.raises(ValueError):
        views.trend(ds, "ICU", "blood_wound", "NIT", "2026-03-29")  # urine only
    with pytest.raises(ValueError):
        views.trend(ds, "URO", "urine", "VAN", "2026-03-29")  # not shown for urine


def test_wording(ds, icu):
    texts = [
        json.dumps(icu),
        json.dumps(views.filters_catalog(ds)),
        json.dumps(views.my_ward(ds, "2026-06-21", ward=PHC, specimen_group="urine", sex="F")),
    ]
    for t in texts:
        assert not BANNED.search(t), BANNED.search(t)


def test_speed_cold(ds):
    """CONTRACTS 4.2 budgets with the in-memory aggregates dropped first (the dataset itself loads once at startup)."""
    ag.clear()
    t = time.perf_counter()
    views.my_ward(ds, "2026-03-29", ward="ICU", specimen_group="blood_wound")
    assert time.perf_counter() - t <= 1.5
    ag.clear()
    t = time.perf_counter()
    views.my_ward(ds, "2026-09-27", specimen_group="urine", windows=("4w", "4m", "12m"))  # all units, every window
    assert time.perf_counter() - t <= 1.5
    for args in (
        (None, "urine", "NIT", "2026-09-27"),
        ("ICU", "blood_wound", "MEM+VAN", "2026-09-27"),
    ):  # 41 of 52 low_n
        ag.clear()
        t = time.perf_counter()
        views.trend(ds, *args)
        assert time.perf_counter() - t <= 1.0, args
