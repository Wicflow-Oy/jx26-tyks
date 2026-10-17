"""The demo scenarios' stated reasons hold against the data. The seed messages and antibiograms are checked against the
raw CSVs in tests/test_against_source.py, and the shared result rules in tests/test_phenotype_rules.py."""
from aei import config as C
from aei import data
from aei.phenotype_rules import effective

SCENARIOS = {s["key"]: s for s in C.DEMO_SCENARIOS}


def history(ds, key: str):
    s = SCENARIOS[key]
    return data.window(ds.isolates[ds.isolates.patient_id == s["patient_id"]], s["as_of"], C.WINDOWS["12m"])


def test_seeds_are_approved_on_demo_mondays():
    assert {s["approved_on"] for s in C.DEMO_ALERT_SEEDS} <= set(C.DEMO_MONDAYS)


def test_scenario_patients_seen_on_unit(ds):
    c = ds.cultures
    for s in C.DEMO_SCENARIOS:
        assert len(c[(c.patient_id == s["patient_id"]) & (c.ward_code == s["unit"])]), s["key"]


def test_alert_scenarios_order_a_drug_their_seed_covers():
    seeds = {s["wards"][0]: s for s in C.DEMO_ALERT_SEEDS}
    for key in ("uro-esbl", "icu-mrsa"):
        s = SCENARIOS[key]
        assert s["drug"] in seeds[s["unit"]]["drugs"]
        assert seeds[s["unit"]]["approved_on"] <= s["as_of"] <= seeds[s["unit"]]["expires_on"]


def test_ed_patient_had_a_reported_trimethoprim_r_on_16_jan_2026(ds):
    h = history(ds, "ed-own-history")
    result, reason = effective(h, "TMP")
    own_r = h[(result == "R") & (reason == "reported")]
    assert [(str(d.date()), o) for d, o in zip(own_r.sample_date, own_r.organism)] == [("2026-01-16", "Escherichia coli")]


def test_quiet_patient_previous_isolate_is_nitrofurantoin_s(ds):
    result, reason = effective(history(ds, "medb-quiet"), "NIT")
    assert (list(result), list(reason)) == (["S"], ["reported"])
