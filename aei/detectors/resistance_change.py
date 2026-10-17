"""Resistance change on a ward: organism x drug, last 4 weeks vs the unit's own prior 52 weeks (ported from 39_resistance_hybrid).

Cells are the 39/44/48 organism-drug pairs on each ward. Counts are resistant of tested, deduplicated with the counting
`rule` separately inside the window and inside the prior period (39 used first_30d over all rows). The prior rate is the
unit's prior 52 weeks pooled toward the hospital-wide rate over the same weeks (`stats.change_test`, m = 10, strength
capped at 200); "changed" when the beta-binomial predictive p < config.CHANGE_ALPHA. Strictly as-of.
Brief gate (B2 addition, not in 39): a brief item also needs >= MIN_RESISTANT resistant isolates in the window, so
"2 of 2" cells stay on the antibiogram chip and off the brief.
"""
from collections import OrderedDict

import pandas as pd

from .. import config as C
from .. import data, stats
from .. import signal as sig
from . import (
    day,
    drug_label,
    ds_key,
    organism_label,
    plain,
    ts,
    ward_label,
    window_days,
)

PAIRS = ([("Escherichia coli", d) for d in ["AMP", "CXM", "CRO", "CIP", "TMP", "MEC", "TZP"]]
         + [("Klebsiella pneumoniae", d) for d in ["CXM", "CRO", "CIP", "TZP"]]
         + [("Staphylococcus aureus", d) for d in ["FOX", "CLI"]]
         + [("Pseudomonas aeruginosa", d) for d in ["TZP", "CAZ", "CIP", "MEM"]]
         + [("Proteus mirabilis", d) for d in ["AMP", "CIP", "TMP"]])
PRIOR_DAYS = 364
MIN_RESISTANT = 3
METHOD = ("beta-binomial predictive test: last window vs the unit's prior 52 weeks pooled toward the hospital rate "
          "(39_resistance_hybrid)")

_COLS = ["isolate_id", "patient_id", "organism", "specimen", "sample_date", "ward_code", "first_30d"]
_CACHE: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
_CACHE_MAX = 64


def cell_table(ds, as_of, rule: str = "readme_period", days: int = 28) -> pd.DataFrame:
    """One row per ward x organism x drug with tested isolates in the window: x_w/n_w (window), x_p/n_p (unit prior 52
    weeks), x_h/n_h (hospital prior), prior (pooled rate), p (one-sided 'more resistant' p) and changed."""
    end = ts(as_of)
    key = (ds_key(ds), str(end.date()), rule, int(days))
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    x = ds.isolates
    orgs = sorted({o for o, _ in PAIRS})
    m = (x.sample_date > end - pd.Timedelta(days=days + PRIOR_DAYS)) & (x.sample_date <= end) & x.organism.isin(orgs)
    sub = x.loc[m, _COLS + sorted({d for _, d in PAIRS})]
    rows = []
    for org, d in PAIRS:
        g = sub.loc[(sub.organism == org) & sub[d].notna(), _COLS + [d]]
        win = data.first_isolates(data.window(g, end, days), rule)
        pri = data.first_isolates(data.window(g, end - pd.Timedelta(days=days), PRIOR_DAYS), rule)
        wr = (win[d] == "R").groupby(win.ward_code).agg(["sum", "size"])
        pr = (pri[d] == "R").groupby(pri.ward_code).agg(["sum", "size"])
        first_r = win[win[d] == "R"].groupby("ward_code").sample_date.min()
        x_h, n_h = int((pri[d] == "R").sum()), len(pri)
        for ward, r in wr.iterrows():
            x_w, n_w = int(r["sum"]), int(r["size"])
            x_p, n_p = (int(pr.at[ward, "sum"]), int(pr.at[ward, "size"])) if ward in pr.index else (0, 0)
            ct = stats.change_test(x_w, n_w, x_p, n_p, x_h, n_h)
            fr = first_r.get(ward)
            rows.append({"ward": ward, "organism": org, "drug": d, "x_w": x_w, "n_w": n_w, "x_p": x_p, "n_p": n_p, "x_h": x_h, "n_h": n_h,
                             "prior": float(ct["prior"]), "expected": float(ct["expected"]), "p": float(ct["p"]),
                             "changed": bool(ct["changed"]),
                             "first_r": None if fr is None or pd.isna(fr) else str(pd.Timestamp(fr).date())})
    out = pd.DataFrame(rows, columns=["ward", "organism", "drug", "x_w", "n_w", "x_p", "n_p", "x_h", "n_h", "prior",
                                      "expected", "p", "changed", "first_r"])
    _CACHE[key] = out
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return out


def detect(ds, as_of, rule: str = "readme_period", window: str = "4w") -> list[dict]:
    end = ts(as_of)
    days = window_days(window)
    t = cell_table(ds, end, rule, days)
    out = []
    hits = t[t.changed & (t.x_w >= MIN_RESISTANT)]
    for r in hits.sort_values(["p", "ward", "organism", "drug"]).itertuples(index=False):
        rate = r.x_w / r.n_w
        rate_prior = r.x_p / r.n_p if r.n_p else None
        slots = plain({"ward_label": ward_label(r.ward), "organism_label": organism_label(r.organism),
                       "drug_label": drug_label(r.drug), "counts": (r.x_w, r.n_w), "rate": rate,
                       "window_weeks": days // 7, "rate_prior": rate_prior, "counts_prior": (r.x_p, r.n_p),
                       "prior_weeks": PRIOR_DAYS // 7})
        evidence = plain({
            "filter": {"ward": r.ward, "specimen": None, "organism": r.organism, "drug": r.drug,
                       "date_from": day(end - pd.Timedelta(days=days - 1)), "date_to": day(end), "rule": rule},
            "counts": {"resistant": r.x_w, "tested": r.n_w, "prior_resistant": r.x_p, "prior_tested": r.n_p,
                       "hospital_prior_resistant": r.x_h, "hospital_prior_tested": r.n_h,
                       "expected_resistant": round(r.expected, 2), "prior_rate_pooled": round(r.prior, 4),
                       "p": r.p},
            "method": METHOD,
            "params": {"alpha": C.CHANGE_ALPHA, "min_resistant": MIN_RESISTANT, "window_days": days, "prior_days": PRIOR_DAYS, "pool_m": 10,
                       "prior_strength_cap": 200, "prior_from": day(end - pd.Timedelta(days=days + PRIOR_DAYS - 1)),
                       "prior_to": day(end - pd.Timedelta(days=days))},
        })
        out.append(sig.make_signal(
            "resistance_change", {"ward": r.ward, "organism": r.organism, "drug": r.drug},
            priority="P2", as_of=day(end), template_id="trend_resistance_change", slots=slots, evidence=evidence,
            ward=r.ward, organism=r.organism, drug=r.drug, first_sample_date=r.first_r, section="changed"))
    return out
