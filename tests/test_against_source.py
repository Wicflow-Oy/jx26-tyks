"""Headline numbers checked against the raw CSVs: each test derives a demo number with plain pandas straight from the
dataset files (no aei code in the derivation) and requires the product's output to equal it and the pinned value."""
from functools import lru_cache

import pandas as pd
import pytest

from aei import cds, views
from aei import config as C
from aei.detectors import (
    completeness,
    expert_rules,
    phenotype,
    policy,
    resistance_change,
    thl,
)

RAW = C.DATA_DIR  # the same place aei/data.py reads from (AEI_DATA_DIR or the context repo)
if not (RAW / "isolates.csv").is_file():
    pytest.skip(f"synthetic dataset not found in {RAW}", allow_module_level=True)

README_DRUG_ORDER = ["AMP", "MEC", "TZP", "FOX", "CXM", "CRO", "CAZ", "MEM", "CIP", "TMP", "NIT", "VAN", "CLI"]
SA, ECOLI = "Staphylococcus aureus", "Escherichia coli"


# --------------------------------------------------------------------------- the source, read independently
@lru_cache(maxsize=1)
def source() -> pd.DataFrame:
    """One row per isolate: isolates + cultures + patients, susceptibility pivoted to one S/R column per drug."""
    cul = pd.read_csv(RAW / "cultures.csv", parse_dates=["sample_date", "admission_date"])
    iso = pd.read_csv(RAW / "isolates.csv")
    pat = pd.read_csv(RAW / "patients.csv")
    sus = pd.read_csv(RAW / "susceptibility.csv").pivot(index="isolate_id", columns="antibiotic_code", values="result")
    x = iso.merge(cul, on="culture_id").merge(pat, on="patient_id", how="left")
    x = x.merge(sus, left_on="isolate_id", right_index=True, how="left")
    x["care_day"] = (x.sample_date - x.admission_date).dt.days + 1  # admission day = day 1
    return x.sort_values(["sample_date", "isolate_id"]).reset_index(drop=True)


@lru_cache(maxsize=1)
def cultures() -> pd.DataFrame:
    return pd.read_csv(RAW / "cultures.csv", parse_dates=["sample_date"])


def window(df: pd.DataFrame, as_of: str, days: int) -> pd.DataFrame:
    """Rows with as_of - days < sample_date <= as_of."""
    end = pd.Timestamp(as_of)
    return df[(df.sample_date > end - pd.Timedelta(days=days)) & (df.sample_date <= end)]


def first_per_patient(df: pd.DataFrame) -> pd.DataFrame:
    """Dataset README rule: first isolate per patient x organism x specimen in the rows given."""
    return df.sort_values(["sample_date", "isolate_id"]).drop_duplicates(["patient_id", "organism", "specimen"])


def first_in_30_days(df: pd.DataFrame) -> pd.Series:
    """30-day rule on the full history: no same patient x organism x specimen isolate in the previous 30 days."""
    gap = df.groupby(["patient_id", "organism", "specimen"]).sample_date.diff().dt.days
    return gap.isna() | (gap > 30)


def resistant_of_tested(df: pd.DataFrame, drug: str) -> tuple[int, int]:
    tested = df[drug].dropna()
    return int((tested == "R").sum()), len(tested)


def profile(row) -> str:
    """The antibiogram as the brief prints it: tested drugs in README order, e.g. 'FOX:R VAN:S CLI:R'."""
    return " ".join(f"{d}:{row[d]}" for d in README_DRUG_ORDER if isinstance(row.get(d), str))


def icu_mrsa(as_of: str) -> pd.DataFrame:
    x = source()
    keep = (x.mrsa == 1) & (x.organism == SA) & (x.ward_code == "ICU")
    return x[keep & (x.sample_date >= "2026-03-03") & (x.sample_date <= as_of)]


# --------------------------------------------------------------------------- Monday brief
@pytest.mark.parametrize(("as_of", "patients"), [("2026-03-08", 3), ("2026-03-15", 6), ("2026-03-22", 9),
                                                 ("2026-03-29", 13)])
def test_icu_mrsa_cluster_patients_per_week(ds, as_of, patients):
    card = next(s for s in phenotype.detect(ds, as_of) if s["slots"]["ward"] == "ICU")
    assert icu_mrsa(as_of).patient_id.nunique() == card["slots"]["n_patients"] == patients


def test_icu_mrsa_cluster_shares_one_antibiogram(ds):
    rows = icu_mrsa("2026-03-29")
    sharing = rows[rows.apply(profile, axis=1) == "FOX:R VAN:S CLI:R"].patient_id.nunique()
    card = next(s for s in phenotype.detect(ds, "2026-03-29") if s["slots"]["ward"] == "ICU")["slots"]
    assert (sharing, str(rows.sample_date.min().date())) == (card["n_share"], card["first_date"]) == (12, "2026-03-03")
    assert card["pattern"] == "FOX:R VAN:S CLI:R"


def _icu_staph_aureus(as_of: str, drug: str, days: int) -> tuple[int, int]:
    """S. aureus R of tested on ICU: first isolates taken hospital-wide in the period, then the ICU rows."""
    x = source()
    hospital = first_per_patient(window(x[(x.organism == SA) & x[drug].notna()], as_of, days))
    return resistant_of_tested(hospital[hospital.ward_code == "ICU"], drug)


@pytest.mark.parametrize(("drug", "now", "year_before"), [("FOX", (13, 20), (1, 71)), ("CLI", (13, 20), (4, 71))])
def test_icu_staph_aureus_resistance_change(ds, drug, now, year_before):
    item = next(s for s in resistance_change.detect(ds, "2026-03-29")
                if s["evidence"]["filter"]["ward"] == "ICU" and s["evidence"]["filter"]["drug"] == drug)
    source_now = _icu_staph_aureus("2026-03-29", drug, 28)
    source_before = _icu_staph_aureus("2026-03-01", drug, 364)  # the 52 weeks before the 4-week window
    assert (source_now, source_before) == (tuple(item["slots"]["counts"]), tuple(item["slots"]["counts_prior"]))
    assert (source_now, source_before) == (now, year_before)


@pytest.mark.xfail(strict=True, reason="D2: render.fmt pct0 uses Python round() (half to even), so 10 of 16 prints 62%")
def test_icu_cefoxitin_percentage_rounds_half_up(ds):
    r, n = _icu_staph_aureus("2026-04-05", "FOX", 28)
    assert (r, n) == (10, 16)
    item = next(s for s in resistance_change.detect(ds, "2026-04-05")
                if s["evidence"]["filter"]["ward"] == "ICU" and s["evidence"]["filter"]["drug"] == "FOX")
    assert f"{r} of {n} resistant ({int(100 * r / n + 0.5)}%" in item["text"]  # 62.5 -> 63


def _policy_population(as_of: str, days: int = 364) -> tuple[int, int]:
    """Trimethoprim R of tested, urinary E. coli, women, PHC-N + PHC-S, 52 weeks to as_of, README rule."""
    x = source()
    rows = x[(x.organism == ECOLI) & (x.specimen == "urine") & x.ward_code.isin(["PHC-N", "PHC-S"])
             & (x.sex == "F") & x.TMP.notna()]
    return resistant_of_tested(first_per_patient(window(rows, as_of, days)), "TMP")


def test_policy_line_trimethoprim_crossed_20_percent_on_21_jun_2026(ds):
    line = next(s for s in policy.detect(ds, "2026-06-21") if s["evidence"]["params"]["line_id"] == "tmp_uti_women_20")
    week_before = next(s for s in policy.policy_states(ds, "2026-06-14") if s["id"] == "tmp_uti_women_20")
    last_week = next(s for s in policy.policy_states(ds, "2026-09-27") if s["id"] == "tmp_uti_women_20")
    assert _policy_population("2026-06-21") == tuple(line["slots"]["counts"]) == (160, 786)  # 20.4%, at/above 20%
    assert _policy_population("2025-06-22") == tuple(line["slots"]["counts_prior"]) == (122, 769)  # a year earlier
    assert _policy_population("2026-06-14") == (week_before["x"], week_before["n"]) == (153, 787)  # 19.4%, below
    assert line["slots"]["crossed_on"] == "2026-06-21" and week_before["active"] is False
    assert _policy_population("2026-09-27") == (last_week["x"], last_week["n"]) == (144, 789)


def test_expert_rule_counts_over_every_isolate(ds):
    x = source()
    esbl, mrsa = x[x.esbl == 1], x[(x.mrsa == 1) & (x.organism == SA)]
    cro_r_amp_s = (x.organism == ECOLI) & (x.CRO == "R") & (x.AMP == "S")
    cro_r_cxm_s = x.organism.isin([ECOLI, "Klebsiella pneumoniae"]) & (x.CRO == "R") & (x.CXM == "S")
    product = expert_rules.rule_counts(ds.isolates)
    assert (len(esbl), int(((esbl.CXM == "S") | (esbl.CRO == "S")).sum())) == tuple(product["esbl_ceph_s"].values()) \
        == (517, 0)
    assert (len(mrsa), int((mrsa.FOX == "S").sum())) == tuple(product["mrsa_fox_s"].values()) == (111, 0)
    assert int(cro_r_amp_s.sum()) == product["cro_r_amp_s"]["hits"] == 43
    assert int(cro_r_cxm_s.sum()) == product["cro_r_cxm_s"]["hits"] == 107
    product_union = expert_rules.masks(ds.isolates, "cro_r_amp_s")[1] | expert_rules.masks(ds.isolates, "cro_r_cxm_s")[1]
    assert int((cro_r_amp_s | cro_r_cxm_s).sum()) == int(product_union.sum()) == 109


def test_phc_s_data_gap_week_ending_14_dec_2025(ds):
    c = cultures()
    phc_s = c[c.ward_code == "PHC-S"]
    this_week = phc_s[phc_s.sample_date.between("2025-12-08", "2025-12-14")]
    eight_weeks = phc_s[phc_s.sample_date.between("2025-10-13", "2025-12-07")]
    item = next(s for s in completeness.detect(ds, "2025-12-14") if s["evidence"]["filter"]["ward"] == "PHC-S")
    assert (len(this_week), len(eight_weeks)) == (0, 411)
    assert item["evidence"]["counts"]["cultures_this_week"] == len(this_week)
    assert item["evidence"]["counts"]["expected_per_week"] == round(len(eight_weeks) / 8, 1) == 51.4
    assert "usually 51" in item["text"]


@pytest.mark.parametrize(("marker", "ward", "organism", "specimen", "sample_date", "care_day", "days_since_prev"), [
    ("cpe", "MED-A", "Klebsiella pneumoniae", "urine", "2026-09-21", 3, 142),
    ("vre", "GER", "Enterococcus faecalis", "wound", "2026-09-11", 2, 214),
])
def test_thl_alert_organism_cards_on_27_sep_2026(ds, marker, ward, organism, specimen, sample_date, care_day,
                                                 days_since_prev):
    x = source()
    cases = x[(x[marker] == 1) & (x.sample_date <= "2026-09-27")].drop_duplicates("patient_id")  # first case per patient
    case, previous = cases.iloc[-1], cases.iloc[-2]
    card = next(s for s in thl.detect(ds, "2026-09-27")
                if s["evidence"]["filter"].get("marker") == marker and s["evidence"]["filter"].get("isolate_ids_only"))
    assert card["evidence"]["isolate_ids"] == [case.isolate_id]
    assert (case.ward_code, case.organism, case.specimen, str(case.sample_date.date())) == \
        (card["slots"]["ward"], card["evidence"]["filter"]["organism"], card["slots"]["specimen"],
         card["slots"]["sample_date"]) == (ward, organism, specimen, sample_date)
    assert int(case.care_day) == card["evidence"]["counts"]["care_day"] == care_day
    assert (int(case.care_day) >= 3) == card["evidence"]["counts"]["hospital_onset"]
    assert (case.sample_date - previous.sample_date).days == card["slots"]["days_since_prev"] == days_since_prev


# --------------------------------------------------------------------------- My ward
GRAM_NEGATIVES = {ECOLI, "Proteus mirabilis", "Klebsiella pneumoniae", "Klebsiella oxytoca", "Citrobacter freundii",
                  "Pseudomonas aeruginosa"}


def covered_of_tested(rows: pd.DataFrame, drug: str) -> tuple[int, int]:
    """Coverage per README/EUCAST for this population: S covers; an S. aureus beta-lactam follows the cefoxitin screen;
    vancomycin never covers a Gram-negative (intrinsic, counted as tested); an untested isolate is left out."""
    def value(r):
        if r.organism == SA and drug in ("TZP", "MEM"):
            return r.FOX
        if r.organism in GRAM_NEGATIVES and drug == "VAN":
            return "R"
        return r[drug]
    v = rows.apply(value, axis=1).dropna()
    return int((v == "S").sum()), len(v)


def test_icu_blood_and_wound_coverage_last_4_weeks(ds):
    x = source()
    rows = first_per_patient(window(x[(x.ward_code == "ICU") & x.specimen.isin(["blood", "wound"])], "2026-03-29", 28))
    view = views.my_ward(ds, "2026-03-29", ward="ICU", specimen_group="blood_wound")
    mix = {o: (len(g), int(g.mrsa.eq(1).sum())) for o, g in rows.groupby("organism")}
    assert mix == {SA: (20, 13), ECOLI: (2, 0), "Proteus mirabilis": (2, 0)}  # the coverage rules above cover all three
    assert len(rows) == view["windows"][0]["n_isolates"] == 24
    assert {o["organism"]: o["n"] for o in view["organisms"]["4w"]} == {o: n for o, (n, _) in mix.items()}
    cells = {r["drug"]: r["cells"]["4w"]["observed"] for r in view["rows"]}
    for drug, expected in {"MEM": (11, 24), "TZP": (11, 24), "VAN": (20, 24)}.items():
        assert covered_of_tested(rows, drug) == (cells[drug]["covered"], cells[drug]["tested"]) == expected, drug


@pytest.mark.parametrize(("sex", "expected"), [("M", (132, 957)), ("F", (89, 1587))])
def test_urinary_e_coli_ciprofloxacin_by_sex_last_12_months(ds, sex, expected):
    x = source()
    rows = first_per_patient(window(x[(x.organism == ECOLI) & (x.specimen == "urine") & (x.sex == sex)], "2026-09-27", 364))
    view = views.antibiogram(ds, "2026-09-27", specimen_group="urine", window="12m", organism=ECOLI, sex=sex)
    cip = next(d for o in view["organisms"] for d in o["drugs"] if d["drug"] == "CIP")
    assert resistant_of_tested(rows, "CIP") == (cip["r"], cip["n"]) == expected


@pytest.mark.parametrize(("as_of", "expected"), [("2025-07-06", (39, 375)), ("2026-09-27", (12, 328))])
def test_uro_e_coli_ceftriaxone_under_30_day_rule(ds, as_of, expected):
    x = source()
    x = x[first_in_30_days(x)]
    rows = window(x[(x.ward_code == "URO") & (x.organism == ECOLI) & (x.specimen == "urine")], as_of, 364)
    view = views.antibiogram(ds, as_of, ward="URO", specimen_group="urine", window="12m", rule="30d", organism=ECOLI)
    cro = next(d for o in view["organisms"] for d in o["drugs"] if d["drug"] == "CRO")
    assert resistant_of_tested(rows, "CRO") == (cro["r"], cro["n"]) == expected


# --------------------------------------------------------------------------- Doctor's order screen
COMMUNITY = ["ED", "PHC-N", "PHC-S"]  # an ED or health-centre order pools these units for the patient's home area


@pytest.mark.parametrize(("as_of", "patient_id", "unit", "drug", "last_4_weeks", "last_12_months"), [
    ("2026-06-21", "P001889", "PHC-N", "TMP", (14, 55), (85, 435)),  # phc-tmp
    ("2026-03-15", "P008135", "ED", "TMP", (5, 38), (69, 405)),  # ed-own-history
    ("2026-03-15", "P005490", "MED-B", "NIT", (0, 12), (0, 149)),  # medb-quiet
])
def test_order_screen_uti_numbers_for_demo_patients(ds, as_of, patient_id, unit, drug, last_4_weeks, last_12_months):
    x = source()
    patient = x[x.patient_id == patient_id].iloc[0]
    pop = x[(x.organism == ECOLI) & (x.specimen == "urine") & (x.sex == patient.sex)]
    pop = pop[pop.ward_code.isin(COMMUNITY) & (pop.home_area == patient.home_area)] if unit in COMMUNITY \
        else pop[pop.ward_code == unit]
    ctx = cds.order_context(ds, as_of, patient_id, unit, "uti", drug, "sign")
    nums = next(line for line in ctx["lines"] if line["key"] == "your_drug")["numbers"]
    assert resistant_of_tested(first_per_patient(window(pop, as_of, 28)), drug) == (nums["r"], nums["n"]) == last_4_weeks
    assert resistant_of_tested(first_per_patient(window(pop, as_of, 364)), drug) == (nums["r12"], nums["n12"]) \
        == last_12_months
