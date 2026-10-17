"""Ward outlier count (ported from 44_team_ideas (A) and 48_outlier_vs_detectors).

For every ward x organism-drug cell (the 39 pairs) the last-4-week resistant count is compared with the unit's prior 52
weeks pooled toward the hospital (beta-binomial, the same prior as resistance_change). A cell is "above its usual range"
when the mid-p upper tail < 0.025 and it has enough isolates to speak of a rate: at least 10 tested or 3 resistant
(B2 addition, not in 44/48: "1 of 1" is not a rate). A ward fires when >= 3 of its cells are above range in the same
week (48: about 2 chance episodes a year on the unmodified data, vs about 15 at >= 2). Other units' high cells are shown
for contrast. The text names every high cell with its count, and the evidence lists the isolates those cells counted.
In the week after a ward stops firing it is listed as resolved.
"""
import pandas as pd
from scipy import stats as st

from .. import config as C
from .. import signal as sig
from . import day, drug_label, organism_label, plain, ts, ward_label, window_days
from . import resistance_change as rc

MIDP_ALPHA = 0.025
MIN_HIGH_CELLS = 3
MIN_TESTED = C.SMALL_N_NONE  # a cell needs this many tested isolates ...
MIN_RESISTANT = rc.MIN_RESISTANT  # ... or this many resistant ones to count as above its range
METHOD = ("ward outlier count: organism-drug cells whose last-window resistance is above the unit's usual range "
          "(beta-binomial mid-p < 0.025; at least 10 tested or 3 resistant), >= 3 cells on one ward "
          "(44_team_ideas, 48_outlier_vs_detectors)")


def _midp_up(x_w: int, n_w: int, prior: float, n_p: int) -> float:
    s = min(n_p + 10, 200)
    bb = st.betabinom(int(n_w), prior * s, (1 - prior) * s)
    return float(bb.sf(x_w) + 0.5 * bb.pmf(x_w))


def ward_cells(ds, as_of, rule: str = "readme_period", days: int = 28) -> pd.DataFrame:
    """cell_table plus `p_mid`, `assessed` (enough isolates) and `high` (assessed and above its usual range)."""
    t = rc.cell_table(ds, as_of, rule, days).copy()
    t["p_mid"] = [_midp_up(r.x_w, r.n_w, r.prior, r.n_p) for r in t.itertuples(index=False)]
    t["assessed"] = (t.n_w >= MIN_TESTED) | (t.x_w >= MIN_RESISTANT)
    t["high"] = t.assessed & (t.p_mid < MIDP_ALPHA)
    return t


def _per_ward(t: pd.DataFrame) -> pd.DataFrame:
    return t.groupby("ward").agg(cells=("assessed", "sum"), high=("high", "sum"))


def _pair(r) -> str:
    """'S. aureus clindamycin'; the cefoxitin screen reads as MRSA (see resistance_change.finding)."""
    if r.drug == "FOX":
        return f"{organism_label(r.organism)} cefoxitin screen (MRSA)"
    return f"{organism_label(r.organism)} {drug_label(r.drug).lower()}"


def _filter(ward, end, days, rule) -> dict:
    return {"ward": ward, "specimen": None, "organism": None, "drug": None,
            "date_from": day(end - pd.Timedelta(days=days - 1)), "date_to": day(end), "rule": rule}


def _params(days) -> dict:
    return {"midp_alpha": MIDP_ALPHA, "min_high_cells": MIN_HIGH_CELLS, "min_tested": MIN_TESTED,
            "min_resistant": MIN_RESISTANT, "window_days": days, "prior_days": rc.PRIOR_DAYS}


def _signal(t, per, ward, end, days, rule) -> dict:
    hc = t[(t.ward == ward) & t.high].sort_values(["p_mid", "organism", "drug"])
    others = per.drop(index=ward)
    slots = {"ward_label": ward_label(ward), "high": (per.at[ward, "high"], per.at[ward, "cells"]),
             "window_weeks": days // 7, "other_high": (others.high.sum(), others.cells.sum())}
    for i, r in enumerate(hc.itertuples(index=False), start=1):
        slots[f"pair{i}"], slots[f"counts{i}"] = _pair(r), (r.x_w, r.n_w)
    evidence = plain({
        "filter": _filter(ward, end, days, rule),
        "counts": {"cells_high": per.at[ward, "high"], "cells_assessed": per.at[ward, "cells"],
                   "other_units_cells_high": others.high.sum(), "other_units_cells_assessed": others.cells.sum(),
                   "cells": [{"organism": r.organism, "drug": r.drug, "resistant": r.x_w, "tested": r.n_w,
                              "prior_resistant": r.x_p, "prior_tested": r.n_p, "p_mid": round(r.p_mid, 6)}
                             for r in hc.itertuples(index=False)]},
        "method": METHOD, "params": _params(days),
        "isolate_ids": list(dict.fromkeys(i for ids in hc.isolate_ids for i in ids)),
    })
    first = hc.first_r.dropna().min() if hc.first_r.notna().any() else None
    return sig.make_signal(
        "ward_outlier", {"ward": ward}, priority="P3", as_of=day(end), template_id=f"trend_ward_outlier__{len(hc)}",
        slots=plain(slots), evidence=evidence, ward=ward, first_sample_date=first, section="changed")


def _resolved_signal(ward, per, last, end, days, rule) -> dict:
    n_high = per.at[ward, "high"] if ward in per.index else 0
    slots = {"ward_label": ward_label(ward), "window_weeks": days // 7, "n_high": n_high,
             "n_high_last": last.at[ward, "high"], "last_flagged": day(end - pd.Timedelta(days=7))}
    evidence = plain({
        "filter": _filter(ward, end, days, rule),
        "counts": {"cells_high": n_high, "last_flagged_cells_high": last.at[ward, "high"]},
        "method": METHOD, "params": _params(days),
    })
    return sig.make_signal(
        "ward_outlier", {"ward": ward}, priority="P3", as_of=day(end), template_id="trend_ward_outlier_resolved",
        slots=plain(slots), evidence=evidence, ward=ward, status="resolved", section="changed")


def detect(ds, as_of, rule: str = "readme_period", window: str = "4w") -> list[dict]:
    end = ts(as_of)
    days = window_days(window)
    t = ward_cells(ds, end, rule, days)
    per = _per_ward(t)
    firing = per.index[per.high >= MIN_HIGH_CELLS]
    out = [_signal(t, per, ward, end, days, rule) for ward in firing]
    last = _per_ward(ward_cells(ds, end - pd.Timedelta(days=7), rule, days))
    for ward in last.index[last.high >= MIN_HIGH_CELLS].difference(firing):
        out.append(_resolved_signal(ward, per, last, end, days, rule))
    return out
