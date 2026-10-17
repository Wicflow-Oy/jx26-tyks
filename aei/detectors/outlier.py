"""Ward outlier count (ported from 44_team_ideas (A) and 48_outlier_vs_detectors).

For every ward x organism-drug cell (the 39 pairs) the last-4-week resistant count is compared with the unit's prior 52
weeks pooled toward the hospital (beta-binomial, the same prior as resistance_change). A cell is "above its usual range"
when the mid-p upper tail < 0.025. A ward fires when >= 3 of its cells are above range in the same week (48: about 2 chance
episodes a year on the unmodified data, vs about 15 at >= 2). Other units' share of high cells is shown for contrast.
"""
import pandas as pd
from scipy import stats as st

from .. import signal as sig
from . import day, drug_label, organism_label, plain, ts, ward_label, window_days
from .resistance_change import PRIOR_DAYS, cell_table

MIDP_ALPHA = 0.025
MIN_HIGH_CELLS = 3
METHOD = ("ward outlier count: organism-drug cells whose last-window resistance is above the unit's usual range "
          "(beta-binomial mid-p < 0.025), >= 3 cells on one ward (44_team_ideas, 48_outlier_vs_detectors)")


def _midp_up(x_w: int, n_w: int, prior: float, n_p: int) -> float:
    s = min(n_p + 10, 200)
    bb = st.betabinom(int(n_w), prior * s, (1 - prior) * s)
    return float(bb.sf(x_w) + 0.5 * bb.pmf(x_w))


def ward_cells(ds, as_of, rule: str = "readme_period", days: int = 28) -> pd.DataFrame:
    """cell_table plus `p_mid` and `high` (above usual range)."""
    t = cell_table(ds, as_of, rule, days).copy()
    t["p_mid"] = [_midp_up(r.x_w, r.n_w, r.prior, r.n_p) for r in t.itertuples(index=False)]
    t["high"] = t.p_mid < MIDP_ALPHA
    return t


def _cell_text(r) -> str:
    return f"{organism_label(r.organism)} {drug_label(r.drug).lower()}"


def detect(ds, as_of, rule: str = "readme_period", window: str = "4w") -> list[dict]:
    end = ts(as_of)
    days = window_days(window)
    t = ward_cells(ds, end, rule, days)
    if t.empty:
        return []
    per = t.groupby("ward").agg(cells=("high", "size"), high=("high", "sum"))
    out = []
    for ward, w in per[per.high >= MIN_HIGH_CELLS].iterrows():
        hc = t[(t.ward == ward) & t.high].sort_values(["p_mid", "organism", "drug"])
        others = per.drop(index=ward)
        slots = plain({"ward_label": ward_label(ward), "high": (int(w.high), int(w.cells)), "window_weeks": days // 7,
                       "cells_text": ", ".join(_cell_text(r) for r in hc.itertuples(index=False)),
                       "other_high": (int(others.high.sum()), int(others.cells.sum()))})
        evidence = plain({
            "filter": {"ward": ward, "specimen": None, "organism": None, "drug": None,
                       "date_from": day(end - pd.Timedelta(days=days - 1)), "date_to": day(end), "rule": rule},
            "counts": {"cells_high": int(w.high), "cells_evaluated": int(w.cells),
                       "other_units_cells_high": int(others.high.sum()), "other_units_cells": int(others.cells.sum()),
                       "cells": [{"organism": r.organism, "drug": r.drug, "resistant": r.x_w, "tested": r.n_w,
                                  "prior_resistant": r.x_p, "prior_tested": r.n_p, "p_mid": round(r.p_mid, 6)}
                                 for r in hc.itertuples(index=False)]},
            "method": METHOD,
            "params": {"midp_alpha": MIDP_ALPHA, "min_high_cells": MIN_HIGH_CELLS, "window_days": days,
                       "prior_days": PRIOR_DAYS},
        })
        first = hc.first_r.dropna().min() if hc.first_r.notna().any() else None
        out.append(sig.make_signal(
            "ward_outlier", {"ward": ward}, priority="P3", as_of=day(end), template_id="trend_ward_outlier",
            slots=slots, evidence=evidence, ward=ward, first_sample_date=first, section="changed"))
    return out
