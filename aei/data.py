"""Load the synthetic dataset and derive the isolate table every other module uses. Read-only on the CSVs.

Isolate table columns (one row per isolate; see CONTRACTS.md section 1):
  isolate_id, culture_id, patient_id, organism, quantity, esbl, mrsa, vre, cpe,
  sample_date, admission_date, ward_code, ward_type, institution, specimen, age_years, age_band, sex, home_area,
  care_day_no (admission day = 1; NaN for outpatients), hosp_onset (care_day_no >= 3),
  week (0 = week of Mon 2 Oct 2023), week_start (Monday), year, profile ("AMP:R MEC:S ..."), n_R,
  AMP..CLI ("S"/"R"/NaN), first_year (first per patient x organism x specimen x calendar year),
  first_30d (no same patient x organism x specimen isolate in the previous 30 days)
"""
from functools import lru_cache
from dataclasses import dataclass
import pandas as pd
from . import config as C


@dataclass(frozen=True)
class Dataset:
    isolates: pd.DataFrame
    cultures: pd.DataFrame
    patients: pd.DataFrame


def _age_band(a):
    for lo, hi, lab in C.AGE_BANDS:
        if lo <= a <= hi:
            return lab
    return "unknown"


@lru_cache(maxsize=2)
def load(data_dir: str | None = None) -> Dataset:
    d = C.DATA_DIR if data_dir is None else data_dir
    pat = pd.read_csv(f"{d}/patients.csv")
    cul = pd.read_csv(f"{d}/cultures.csv", parse_dates=["sample_date", "admission_date"])
    iso = pd.read_csv(f"{d}/isolates.csv")
    sus = pd.read_csv(f"{d}/susceptibility.csv")
    cul = cul.merge(pat, on="patient_id", how="left")
    start = pd.Timestamp(C.DATA_START)
    cul["week"] = ((cul.sample_date - start).dt.days // 7).astype(int)
    cul["week_start"] = start + pd.to_timedelta(cul.week * 7, unit="D")
    cul["care_day_no"] = (cul.sample_date - cul.admission_date).dt.days + 1
    cul["hosp_onset"] = (cul.care_day_no >= C.HOSPITAL_ONSET_MIN_CARE_DAY).fillna(False)
    cul["age_band"] = cul.age_years.map(_age_band)
    wide = sus.pivot_table(index="isolate_id", columns="antibiotic_code", values="result", aggfunc="first").reindex(columns=C.DRUGS)
    prof = wide.apply(lambda r: " ".join(f"{k}:{r[k]}" for k in C.DRUGS if isinstance(r[k], str)), axis=1).rename("profile")
    nr = (wide == "R").sum(axis=1).rename("n_R")
    x = iso.merge(cul, on="culture_id").set_index("isolate_id").join(wide).join(prof).join(nr).reset_index()
    x = x.sort_values(["sample_date", "isolate_id"]).reset_index(drop=True)
    x["year"] = x.sample_date.dt.year
    x["first_year"] = ~x.duplicated(["patient_id", "organism", "specimen", "year"])
    prev = x.groupby(["patient_id", "organism", "specimen"]).sample_date.shift()
    x["first_30d"] = prev.isna() | ((x.sample_date - prev).dt.days > 30)
    for f in ["esbl", "mrsa", "vre", "cpe"]:
        x[f] = x[f].fillna(0).astype(int)
    return Dataset(isolates=x, cultures=cul, patients=pat)


def window(df: pd.DataFrame, as_of, days: int) -> pd.DataFrame:
    """Rows sampled in the `days`-day window ending on `as_of` (inclusive). Strictly as-of: nothing after `as_of`."""
    end = pd.Timestamp(as_of)
    return df[(df.sample_date > end - pd.Timedelta(days=days)) & (df.sample_date <= end)]


def first_isolates(df: pd.DataFrame, rule: str = "readme_period") -> pd.DataFrame:
    """Deduplicate within the rows given.
    readme_period: first isolate per patient x organism x specimen within the period passed in (dataset README rule).
    30d: keep rows flagged first_30d (no same isolate in the previous 30 days; computed on the full history)."""
    if rule == "readme_period":
        return df.sort_values(["sample_date", "isolate_id"]).drop_duplicates(["patient_id", "organism", "specimen"])
    if rule == "30d":
        return df[df.first_30d]
    raise ValueError(f"unknown counting rule {rule}")


def week_end(week: int) -> pd.Timestamp:
    """Sunday that ends data week `week` (week 0 = 2-8 Oct 2023)."""
    return pd.Timestamp(C.DATA_START) + pd.Timedelta(days=7 * week + 6)


def week_of(date) -> int:
    return int((pd.Timestamp(date) - pd.Timestamp(C.DATA_START)).days // 7)
