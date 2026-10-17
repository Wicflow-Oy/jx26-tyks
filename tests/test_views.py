"""My ward, antibiogram, filter catalogue and trend views: contract shape, display rules, strict as-of, speed, wording."""
import json
import math
import re
import time

import pandas as pd
import pytest

from aei import aggregates as ag
from aei import config as C
from aei import data, views

BANNED = re.compile(r"predict|forecast|\bodds\b|probability that|best choice|recommended drug|s/i/r|decoy|outbreak confirmed|"
                    r"zero resistance", re.IGNORECASE)
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
    assert icu["windows"][0] == {"key": "4w", "label": "Last 4 weeks", "days": 28, "from": "2026-03-02", "to": "2026-03-29",
                                 "n_isolates": 24}
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
    assert hidden["CIP"]["reason"] == "Ciprofloxacin not shown: untested on S. aureus and E. faecalis (most of this unit's isolates)"
    assert hidden["AMP"]["code"] == "not_tested_enough" and "S. aureus" in hidden["AMP"]["reason"]


def test_icu_march_numbers(icu):
    # README rule (product default). The 4-week MRSA influx: 13 of 20 S. aureus are MRSA.
    mem, tzp, van = _cell(icu, "MEM"), _cell(icu, "TZP"), _cell(icu, "VAN")
    assert (mem["observed"]["covered"], mem["observed"]["tested"]) == (11, 24) and mem["state"] == "low_n"
    assert round(100 * mem["estimate"]["pct"]) == 74 and [round(100 * v) for v in mem["estimate"]["ci"]] == [61, 85]
    assert (tzp["observed"]["covered"], van["observed"]["covered"]) == (11, 20)
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
    assert [r["drug"] for r in out["rows"]][:3] == ["NIT", "MEC", "TMP"]           # urine-only drugs shown for urine
    assert {n["drug"] for n in out["not_shown"]} == {"CIP", "CAZ", "FOX"}         # CIP untested on 16% (E. faecalis, staphylococci)


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
        return views.my_ward(ds, "2026-09-27", specimen_group="urine", setting=setting, rule=rule)["windows"][1]["n_isolates"]

    # the 30-day flag partitions exactly; the README rule counts a patient seen in both settings once in "all"
    assert n12("30d") == n12("30d", "inpatient") + n12("30d", "outpatient")
    assert 0 < n12("readme_period") < n12("readme_period", "inpatient") + n12("readme_period", "outpatient")
    f = views.my_ward(ds, "2026-09-27", specimen_group="urine", sex="female", age_band="80+")
    assert f["filters"]["sex"] == "F" and f["filters"]["age_band"] == "80+"
    link = views.my_ward(ds, "2026-06-21", ward="ED,PHC-N,PHC-S", home_area="South", specimen_group="urine",
                         organism="Escherichia coli", sex="F")
    assert link["filters"]["ward"] == ["ED", "PHC-N", "PHC-S"] and link["filters"]["home_area"] == "South"
    nolink = views.my_ward(ds, "2026-06-21", ward="ED,PHC-N,PHC-S", specimen_group="urine", organism="Escherichia coli", sex="F")
    assert 0 < link["windows"][1]["n_isolates"] < nolink["windows"][1]["n_isolates"]
    north_only = views.my_ward(ds, "2026-06-21", ward="PHC-N", home_area="South", specimen_group="urine")
    assert north_only["windows"][1]["n_isolates"] == 0                          # PHC-N serves the North area only
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
    cut = data.Dataset(isolates=x[x.sample_date <= pd.Timestamp(as_of)].reset_index(drop=True),
                       cultures=ds.cultures, patients=ds.patients)
    for kw in ({"ward": "ICU", "specimen_group": "blood_wound"}, {"ward": PHC, "specimen_group": "urine", "sex": "F"}):
        assert views.my_ward(cut, as_of, **kw) == views.my_ward(ds, as_of, **kw)
    assert views.antibiogram(cut, as_of, "ICU", "blood_wound", "4w") == views.antibiogram(ds, as_of, "ICU", "blood_wound", "4w")
    assert (views.trend(cut, "ICU", "blood_wound", "MEM", as_of, weeks=8)
            == views.trend(ds, "ICU", "blood_wound", "MEM", as_of, weeks=8))


def test_rule_switch(ds):
    a = views.my_ward(ds, "2025-06-29", ward="URO", specimen_group="urine", rule="30d")
    assert a["filters"]["rule"] == "30d" and a["windows"][0]["n_isolates"] == 67       # the 36b window
    assert (_cell(a, "CRO")["observed"]["covered"], _cell(a, "CRO")["observed"]["tested"]) == (40, 65)


def test_antibiogram(ds):
    ab = views.antibiogram(ds, "2026-03-29", "ICU", "blood_wound", "4w")
    _plain(ab)
    assert ab["window"]["n_isolates"] == 24 and ab["window"]["from"] == "2026-03-02"
    sa = next(o for o in ab["organisms"] if o["organism"] == "Staphylococcus aureus")
    fox = next(d for d in sa["drugs"] if d["drug"] == "FOX")
    assert (fox["r"], fox["n"], fox["state"], fox["screening_only"]) == (13, 20, "low_n", True)
    assert fox["pct_s"] == pytest.approx(7 / 20)
    caz = next(d for d in sa["drugs"] if d["drug"] == "CAZ")
    assert caz["expected_resistant"] is True and caz["pct_s"] is None
    ec = next(o for o in ab["organisms"] if o["organism"] == "Escherichia coli")
    assert all(d["pct_s"] is None for d in ec["drugs"])                            # 2 isolates: not enough data


def test_filters_catalog(ds):
    fc = views.filters_catalog(ds)
    _plain(fc)
    assert [w["code"] for w in fc["wards"]] == list(C.WARD_LABELS)
    setting = {w["code"]: w["setting"] for w in fc["wards"]}
    assert setting["ED"] == "outpatient" and setting["PHC-N"] == "outpatient" and setting["ICU"] == "inpatient"
    assert [s["key"] for s in fc["specimen_groups"]] == list(C.SPECIMEN_GROUPS)
    assert len(fc["organisms"]) == 9 and fc["organisms"][0]["organism"] == "Escherichia coli"
    assert [s["code"] for s in fc["sexes"]] == ["F", "M"] and [a["key"] for a in fc["age_bands"]] == ["0-17", "18-64", "65-79", "80+"]
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
    assert last == _cell(icu, "MEM")                                              # sparkline end = the table cell
    assert tr["filters"]["home_area"] is None
    with pytest.raises(ValueError):
        views.trend(ds, "ICU", "blood_wound", "FOX", "2026-03-29")                 # never a therapy option
    with pytest.raises(ValueError):
        views.trend(ds, "ICU", "blood_wound", "NIT", "2026-03-29")                 # urine only


def test_wording(ds, icu):
    texts = [json.dumps(icu), json.dumps(views.filters_catalog(ds)),
             json.dumps(views.antibiogram(ds, "2026-03-29", "ICU", "blood_wound", "4w")),
             json.dumps(views.my_ward(ds, "2026-06-21", ward=PHC, specimen_group="urine", sex="F"))]
    for t in texts:
        assert not BANNED.search(t), BANNED.search(t)


def test_speed_cold(ds):
    ag.clear()
    t = time.perf_counter()
    views.my_ward(ds, "2026-03-29", ward="ICU", specimen_group="blood_wound")
    assert time.perf_counter() - t <= 1.5
    ag.clear()
    t = time.perf_counter()
    views.trend(ds, None, "urine", "NIT", "2026-09-27")
    assert time.perf_counter() - t <= 1.0
