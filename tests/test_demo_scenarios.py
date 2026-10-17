"""The demo seeds and scenarios quote real numbers from the synthetic data; keep them true."""
import pandas as pd
from aei import config as C, data
from aei.phenotype_rules import effective_column, effective_result


def test_uro_esbl_seed_numbers(ds):
    x = ds.isolates
    esbl = x[(x.ward_code == "URO") & (x.esbl == 1)]
    assert data.window(esbl, "2025-06-08", 14).patient_id.nunique() == 6
    prior = data.window(esbl, pd.Timestamp("2025-06-08") - pd.Timedelta(days=28), 364)
    assert 0.8 <= prior.patient_id.nunique() / 13 <= 1.6  # "usually about 1 a month"


def test_scenario_patients_seen_on_unit(ds):
    c = ds.cultures
    for s in C.DEMO_SCENARIOS:
        assert len(c[(c.patient_id == s["patient_id"]) & (c.ward_code == s["unit"])]), s["key"]


def test_ed_patient_has_own_trimethoprim_r(ds):
    h = data.window(ds.isolates[ds.isolates.patient_id == "P008135"], "2026-03-15", 364)
    assert any(effective_result(r, "TMP")[0] == "R" for _, r in h.iterrows())


def test_expert_rules():
    mrsa = {"organism": "Staphylococcus aureus", "mrsa": 1, "esbl": 0, "CXM": None, "FOX": "R"}
    assert effective_result(mrsa, "CXM") == ("R", "inferred from MRSA")
    assert effective_result(mrsa, "FOX") == ("R", "reported")
    assert effective_result({"organism": "Proteus mirabilis", "NIT": None}, "NIT") == ("R", "intrinsic")


def test_effective_column_matches_rowwise(ds):
    x = ds.isolates.sample(2000, random_state=1)
    for d in ["CXM", "FOX", "NIT"]:
        col = effective_column(x, d)
        row = [effective_result(r, d)[0] for _, r in x.iterrows()]
        assert list(col) == row
