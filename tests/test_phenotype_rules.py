"""The shared effective-result rules (aei/phenotype_rules.py): one test per rule, on real isolates wherever the data
has one, plus two whole-dataset checks that no inference ever replaces a result the laboratory reported."""

import pandas as pd
import pytest

from aei import config as C
from aei.phenotype_rules import REASON_TEXT, REASONS, effective

SA, ECOLI = "Staphylococcus aureus", "Escherichia coli"
P008135_ECOLI, P008135_ESBL, P008135_EF = "C0035617-1", "C0034055-1", "C0035617-2"  # the ed-own-history patient
ICU_MRSA, MSSA = "C0037736-1", "C0000256-1"  # first isolate of the ICU cluster (3 Mar 2026); an ICU MSSA


@pytest.fixture(scope="module")
def iso(ds):
    return ds.isolates.set_index("isolate_id", drop=False)


def real(iso, isolate_id, drug):
    result, reason = effective(iso.loc[[isolate_id]], drug)
    return result.iloc[0], reason.iloc[0]


def made_up(drug, **row):
    """For combinations the data never has."""
    result, reason = effective(pd.DataFrame([row]), drug)
    return result.iloc[0], reason.iloc[0]


def test_reported_result_stands(iso):
    assert real(iso, P008135_ECOLI, "TMP") == ("R", "reported")
    assert real(iso, P008135_ECOLI, "CXM") == ("S", "reported")


def test_no_breakpoint_c_freundii_cefuroxime_is_r_over_a_reported_s(iso):
    # P006986's C. freundii of 16 Jun 2025, reported cefuroxime S: no EUCAST breakpoint, Expert Rules v3.3 rule 5
    assert iso.loc["C0026510-1", "CXM"] == "S"
    assert real(iso, "C0026510-1", "CXM") == ("R", "no_breakpoint")
    assert real(iso, "C0026510-1", "CRO") == ("S", "reported")


def test_no_breakpoint_e_faecalis_meropenem(iso):
    assert real(iso, P008135_EF, "MEM") == ("R", "no_breakpoint")  # EUCAST v16.1 Enterococcus: meropenem "-"


def test_intrinsic_pairs(iso):
    assert real(iso, "C0000109-1", "AMP") == ("R", "intrinsic")  # K. pneumoniae, reported R as well
    assert real(iso, "C0000333-1", "NIT") == ("R", "intrinsic")  # P. mirabilis, untested
    assert real(iso, P008135_ECOLI, "VAN") == ("R", "intrinsic")
    assert real(iso, MSSA, "CAZ") == ("R", "intrinsic")  # ERP v1.2 row 4.5


def test_mrsa_makes_every_beta_lactam_r(iso):
    for drug in ("AMP", "CXM", "CRO", "TZP", "MEM"):
        assert real(iso, ICU_MRSA, drug) == ("R", "inferred_mrsa"), drug
    assert [real(iso, ICU_MRSA, d) for d in ("FOX", "CLI", "VAN")] == [
        ("R", "reported"),
        ("R", "reported"),
        ("S", "reported"),
    ]


def test_mrsa_rule_comes_before_a_reported_s():
    # EUCAST Staphylococcus rule 1 says "report resistant to all beta-lactams"; no such report exists in the data
    assert made_up("MEM", organism=SA, FOX="R", MEM="S") == ("R", "inferred_mrsa")


def test_mssa_follows_the_cefoxitin_screen(iso):
    for drug in ("CXM", "CRO", "TZP", "MEM"):
        assert real(iso, MSSA, drug) == ("S", "inferred_mssa"), drug
    assert real(iso, MSSA, "AMP") == (None, "untested")  # penicillinase production is not in the data


def test_mssa_inference_never_replaces_a_reported_r():
    assert made_up("TZP", organism=SA, FOX="S", TZP="R") == ("R", "reported")


def test_e_faecalis_piperacillin_tazobactam_follows_ampicillin(iso):
    assert real(iso, P008135_EF, "TZP") == ("S", "inferred_ampicillin")  # ampicillin S
    assert real(iso, "C0003974-1", "TZP") == ("R", "inferred_ampicillin")  # ampicillin R


def test_local_esbl_rule_only_fills_an_untested_pair(iso):
    assert real(iso, P008135_ESBL, "CRO") == ("R", "reported")  # the laboratory reported it R itself
    assert made_up("CRO", organism=ECOLI, esbl=1) == ("R", "local_esbl_rule")
    # a local cephalosporin rule, not stretched to ceftazidime, which is never tested on Enterobacterales here
    assert real(iso, P008135_ESBL, "CAZ") == (None, "untested")


def test_untested_pair_is_left_out(iso):
    assert real(iso, P008135_ECOLI, "CIP") == ("S", "reported")
    assert made_up("CIP", organism=ECOLI) == (None, "untested")


def test_inferences_never_replace_a_reported_result(ds):
    x = ds.isolates
    for drug in C.DRUGS:
        result, reason = effective(x, drug)
        reported = x[drug].notna()
        assert set(reason[reported]) <= {"reported", "no_breakpoint", "intrinsic", "inferred_mrsa"}, drug
        assert (result[reason == "reported"] == x.loc[reason == "reported", drug]).all(), drug


def test_only_eucast_report_r_rules_overrule_a_report(ds):
    x = ds.isolates
    overruled = {}
    for drug in C.DRUGS:
        result, reason = effective(x, drug)
        changed = x[drug].notna() & (result != x[drug])
        for (organism, why), n in x[changed].groupby([x.organism[changed], reason[changed]]).size().items():
            overruled[(organism, drug, why)] = n
    assert overruled == {("Citrobacter freundii", "CXM", "no_breakpoint"): 517}


def test_every_reason_has_screen_text():
    assert set(REASON_TEXT) == set(REASONS)
