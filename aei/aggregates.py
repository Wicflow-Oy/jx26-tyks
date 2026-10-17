"""Precomputed row arrays so My ward and trend cells are array slices instead of repeated pandas filters.

The isolate table is sorted by (sample_date, isolate_id), so every filtered subset is too and a date window is one
contiguous slice. For the README rule ("first isolate per patient x organism x specimen inside the rows given") each
subset row stores the position of the previous same-key row in that subset; inside a slice starting at s, the first
isolates are exactly the rows whose previous position is < s. That equals `data.first_isolates(rows, "readme_period")`
on the same rows. The 30-day rule uses the `first_30d` flag. Kept in memory (no patient-level data is written to disk).
"""
import threading
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as C
from .coverage import FLAGS, Counts, counts_from_arrays, indicator_matrix, raw_matrix

RULES = ("readme_period", "30d")
_BASE: dict[int, tuple] = {}          # id(isolates) -> (isolates, Base); holding the frame pins its id
_SUBSETS: dict[tuple, "Subset"] = {}
_MAX_BASES, _MAX_SUBSETS = 2, 128
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Base:
    orgs: tuple
    org_code: np.ndarray
    dates: np.ndarray       # datetime64[ns], sorted
    key_code: np.ndarray    # patient x organism x specimen group id
    first30: np.ndarray
    ind: np.ndarray
    raw: np.ndarray
    flags: np.ndarray
    cols: dict              # filter columns as numpy arrays


def base(ds) -> Base:
    """Per-dataset arrays, built once per process (keyed on the isolate table's identity)."""
    x = ds.isolates
    hit = _BASE.get(id(x))
    if hit is not None and hit[0] is x:
        return hit[1]
    with _LOCK:
        hit = _BASE.get(id(x))
        if hit is not None and hit[0] is x:
            return hit[1]
        b = _build_base(x)
        while len(_BASE) >= _MAX_BASES:
            old = next(iter(_BASE))
            del _BASE[old]
            for k in [k for k in _SUBSETS if k[0] == old]:
                del _SUBSETS[k]
        _BASE[id(x)] = (x, b)
        return b


def _build_base(x: pd.DataFrame) -> Base:
    dates = x["sample_date"].to_numpy(dtype="datetime64[ns]")
    if len(dates) > 1 and (np.diff(dates) < np.timedelta64(0, "ns")).any():
        raise ValueError("isolate table must be sorted by sample_date")
    orgs = tuple(sorted(x["organism"].unique()))
    code = {o: i for i, o in enumerate(orgs)}
    return Base(orgs=orgs, org_code=x["organism"].map(code).to_numpy(dtype=int), dates=dates,
             key_code=x.groupby(["patient_id", "organism", "specimen"], sort=False).ngroup().to_numpy(),
             first30=x["first_30d"].to_numpy(dtype=bool), ind=indicator_matrix(x), raw=raw_matrix(x),
             flags=x[list(FLAGS)].to_numpy(dtype=float),
             cols={c: x[c].to_numpy() for c in ("ward_code", "ward_type", "specimen", "sex", "age_band", "organism", "home_area")})


class Subset:
    """Rows of the isolate table matching fixed (non-date) filters, with README-rule bookkeeping."""

    def __init__(self, b: Base, mask: np.ndarray):
        self.b = b
        self.idx = np.nonzero(mask)[0]
        self.dates = b.dates[self.idx]
        keys = b.key_code[self.idx]
        order = np.argsort(keys, kind="stable")
        ks = keys[order]
        prev_sorted = np.full(len(order), -1, dtype=int)
        if len(order) > 1:
            same = ks[1:] == ks[:-1]
            prev_sorted[1:] = np.where(same, order[:-1], -1)
        self.prev = np.empty(len(order), dtype=int)
        self.prev[order] = prev_sorted

    def __len__(self) -> int:
        return len(self.idx)

    def positions(self, lo, hi, rule: str = "readme_period") -> np.ndarray:
        """Subset positions of isolates with lo < sample_date <= hi (lo None = from the start), deduplicated by rule."""
        if rule not in RULES:
            raise ValueError(f"unknown counting rule {rule}")
        s = 0 if lo is None else int(np.searchsorted(self.dates, np.datetime64(pd.Timestamp(lo), "ns"), side="right"))
        e = int(np.searchsorted(self.dates, np.datetime64(pd.Timestamp(hi), "ns"), side="right"))
        if e <= s:
            return np.zeros(0, dtype=int)
        if rule == "readme_period":
            return s + np.nonzero(self.prev[s:e] < s)[0]
        return s + np.nonzero(self.b.first30[self.idx[s:e]])[0]

    def rows(self, lo, hi, rule: str = "readme_period") -> np.ndarray:
        """Row positions in ds.isolates (for line lists and tests)."""
        return self.idx[self.positions(lo, hi, rule)]

    def counts(self, lo, hi, rule: str = "readme_period") -> Counts:
        r = self.rows(lo, hi, rule)
        b = self.b
        return counts_from_arrays(b.orgs, b.org_code[r], b.ind[r], b.raw[r], b.flags[r])


def subset(ds, *, specimen_group: str, wards=None, organism=None, sex=None, age_band=None, setting=None,
           home_area=None) -> Subset:
    """Cached Subset for validated filters. wards: None or a tuple of ward codes; setting: inpatient|outpatient|None."""
    b = base(ds)
    key = (id(ds.isolates), specimen_group, tuple(wards) if wards else None, organism, sex, age_band, setting, home_area)
    hit = _SUBSETS.get(key)
    if hit is not None and hit.b is b:
        return hit
    c = b.cols
    mask = np.isin(c["specimen"], C.SPECIMEN_GROUPS[specimen_group])
    if wards:
        mask &= np.isin(c["ward_code"], list(wards))
    if organism is not None:
        mask &= c["organism"] == organism
    if sex is not None:
        mask &= c["sex"] == sex
    if age_band is not None:
        mask &= c["age_band"] == age_band
    if setting is not None:
        mask &= c["ward_type"] == {"inpatient": "in", "outpatient": "out"}[setting]
    if home_area is not None:
        mask &= c["home_area"] == home_area
    sub = Subset(b, mask)
    with _LOCK:
        if len(_SUBSETS) >= _MAX_SUBSETS:
            _SUBSETS.clear()
        _SUBSETS[key] = sub
    return sub


def clear() -> None:
    """Drop the in-memory caches (tests use this to time a cold view)."""
    with _LOCK:
        _BASE.clear()
        _SUBSETS.clear()
