"""Count step-up test per unit x marker (port of analysis 47_outbreak_prob, Model A). Supporting evidence only.

Series: weekly new-patient counts (30-day de-duplication per patient within the marker) per unit x marker (MRSA, ESBL).
At week t (the week holding as_of): y = the last 4 weeks; baseline = weeks t-55..t-4 (up to 52 weeks), with a Gamma
prior on the weekly rate pooled over the inpatient units (strength 13 weeks).
  H0: y ~ NegBin, the Poisson-Gamma marginal of a constant rate;  H1: y = x + E, E uniform on 3..8 extra cases.
  BF = p(y | H1) / p(y | H0); score = pi * BF / (pi * BF + 1 - pi) with pi = 1%; the test is positive at score >= 0.8.
It is a statistical test of a count step change, never a prediction, and never a P1. When a phenotype cluster or a
THL cluster check covers the same unit and marker, the test is attached to that signal (evidence.stepup) and no
separate item is shown. Otherwise it is a P3 item. The analysis found 0 positive quiet weeks in 18 series x 100 weeks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st

from .. import data as D
from .. import signal as S
from . import iso, ts, ward_label
from . import phenotype as ph

KIND = "count_stepup"
MARKERS = ("mrsa", "esbl")
PRIOR_PI = 0.01
PRIOR_WEEKS = 13
EXTRA_CASES = np.arange(3, 9)
POSITIVE_SCORE = 0.8
LEARN_WEEKS = 26
RECENT_WEEKS = 4  # y: new patients in the last 4 weeks, the week holding as_of included
BASELINE_WEEKS = 52  # the up to 52 weeks before them
DEDUP_DAYS = 30
LABEL = (
    "Count step-up test (Bayesian model comparison, analysis 47): a statistical test of a step change in new patients; "
    "supporting evidence only."
)


def _series(ds, as_of) -> dict:
    """{(ward, marker): weekly counts for weeks 0..t}, using only isolates sampled on or before as_of."""
    x = ph.upto(ds.isolates, as_of)
    t = D.week_of(as_of)
    out = {}
    wards = sorted(ds.isolates.ward_code.unique())
    for m in MARKERS:
        d = x[x[m] == 1].sort_values(["sample_date", "isolate_id"])
        prev = d.groupby("patient_id").sample_date.shift()
        d = d[prev.isna() | ((d.sample_date - prev).dt.days > DEDUP_DAYS)]
        for w in wards:
            wk = d.loc[d.ward_code == w, "week"].to_numpy()
            out[(w, m)] = np.bincount(wk, minlength=t + 1)[: t + 1].astype(float)
    return out


def _inpatient_wards(ds) -> list[str]:
    x = ds.isolates
    return sorted(x.loc[x.ward_type == "in", "ward_code"].unique())


def _score(ser, inp, w, m, t) -> dict | None:
    if t < LEARN_WEEKS:
        return None
    c = ser[(w, m)]
    hi = t - RECENT_WEEKS + 1  # the first week of y
    lo = max(0, hi - BASELINE_WEEKS)
    nb = hi - lo
    y = int(c[hi : t + 1].sum())
    base = float(c[lo:hi].sum())
    lam0 = max(sum(ser[(v, m)][lo:hi].sum() for v in inp) / (len(inp) * max(nb, 1)), 1 / 104)
    a, b = PRIOR_WEEKS * lam0 + base, PRIOR_WEEKS + nb
    r, p = a, b / (b + RECENT_WEEKS)
    lp0 = st.nbinom.logpmf(y, r, p)
    terms = [st.nbinom.logpmf(y - e, r, p) for e in EXTRA_CASES if y - e >= 0]
    if terms:
        log10bf = float((np.logaddexp.reduce(terms) - np.log(len(EXTRA_CASES)) - lp0) / np.log(10))
        logit = np.log(PRIOR_PI / (1 - PRIOR_PI)) + log10bf * np.log(10)  # prior logit + log BF
        score = float(1 / (1 + np.exp(-logit)))
    else:
        log10bf, score = float("-inf"), 0.0
    u_lo, u_hi = int(st.nbinom.ppf(0.025, r, p)), max(1, int(st.nbinom.ppf(0.975, r, p)))
    return {
        "week": t,
        "y4": y,
        "baseline_weeks": int(nb),
        "baseline_cases": int(base),
        "rate_prior_pooled": round(float(lam0), 4),
        "baseline_rate_per_week": round(float(a / b), 4),
        "usual_low": u_lo,
        "usual_high": u_hi,
        "log10_bf": None if np.isinf(log10bf) else round(log10bf, 4),  # None: fewer than 3 cases, H1 impossible
        "step_change_score": score,
        "positive": score >= POSITIVE_SCORE,
    }


def _ctx(ds, as_of):
    as_of = ts(as_of)
    return _series(ds, as_of), _inpatient_wards(ds), D.week_of(as_of)


def evidence_for(ds, as_of, ward, marker) -> dict | None:
    """Step-up block attached to a cluster signal on the same unit and marker."""
    if marker not in MARKERS:
        return None
    ser, inp, t = _ctx(ds, as_of)
    sc = _score(ser, inp, ward, marker, t)
    if sc is None:
        return None
    return {
        "ward": ward,
        "marker": marker,
        "week_start": iso(D.week_end(t) - pd.Timedelta(days=6)),
        **sc,
        "prior": PRIOR_PI,
        "label": LABEL,
    }


def _runs(ds, as_of) -> list[dict]:
    """Positive runs ending at the week of as_of (active) or the week before (just stopped)."""
    ser, inp, t = _ctx(ds, as_of)
    out = []
    for w in sorted({k[0] for k in ser}):
        for m in MARKERS:
            now = _score(ser, inp, w, m, t)
            if now is None:
                continue
            last = t if now["positive"] else t - 1
            sc_last = now if now["positive"] else _score(ser, inp, w, m, t - 1)
            if sc_last is None or not sc_last["positive"]:
                continue
            start = last
            while start - 1 >= LEARN_WEEKS and _score(ser, inp, w, m, start - 1)["positive"]:
                start -= 1
            out.append({"ward": w, "marker": m, "start_week": start, "active": now["positive"], "score": now})
    return out


def _key(run) -> dict:
    return {
        "ward": run["ward"],
        "marker": run["marker"],
        "first_week_start": iso(D.week_end(run["start_week"]) - pd.Timedelta(days=6)),
    }


def _covered(ds, as_of, ward, marker) -> bool:
    from . import thl

    for ep in ph.active_clusters(ds, as_of, include_recent=True):
        if ep["ward"] == ward and ep["marker"] == marker:
            return True
    for ep in thl.active_clusters(ds, as_of, include_recent=True):
        if ep["ward"] == ward and ep["marker"] == marker:
            return True
    return False


def _standalone(ds, as_of) -> list[dict]:
    return [r for r in _runs(ds, as_of) if not _covered(ds, as_of, r["ward"], r["marker"])]


def _signal(ds, run, as_of, rule) -> dict:
    sc = run["score"]
    w, m = run["ward"], run["marker"]
    first_week = D.week_end(run["start_week"]) - pd.Timedelta(days=6)
    date_from = ts(as_of) - pd.Timedelta(days=7 * RECENT_WEEKS - 1)
    rows = ph.population(ds, w, None, m, None, date_from, as_of)
    slots = {
        "ward": w,
        "ward_label": ward_label(w),
        "marker_label": ph.MARKER_LABELS[m],
        "y4": sc["y4"],
        "window_weeks": RECENT_WEEKS,
        "usual_low": sc["usual_low"],
        "usual_high": sc["usual_high"],
        "baseline_weeks": sc["baseline_weeks"],
    }
    if not run["active"]:
        slots["last_flagged"] = ph.last_flagged(as_of)
    evidence = {
        "filter": {
            "ward": w,
            "specimen": None,
            "organism": None,
            "drug": None,
            "date_from": iso(date_from),
            "date_to": iso(as_of),
            "rule": rule,
            "marker": m,
            "population": "marker",
        },
        "counts": {**sc, "first_positive_week_start": iso(first_week)},
        "method": LABEL,
        "params": {
            "prior": PRIOR_PI,
            "prior_weeks": PRIOR_WEEKS,
            "extra_cases": [int(EXTRA_CASES[0]), int(EXTRA_CASES[-1])],
            "positive_score": POSITIVE_SCORE,
            "baseline_weeks_max": BASELINE_WEEKS,
            "dedup_days": DEDUP_DAYS,
            "learning_weeks": LEARN_WEEKS,
        },
        "isolate_ids": rows.isolate_id.tolist(),
        "date_basis": ph.DATE_BASIS,
    }
    template_id = "ob_stepup" if run["active"] else "ob_stepup_resolved"
    return S.make_signal(
        KIND,
        _key(run),
        priority="P3",
        as_of=iso(as_of),
        template_id=template_id,
        slots=slots,
        evidence=evidence,
        ward=w,
        first_sample_date=iso(rows.sample_date.min()) if len(rows) else None,
        section="unusual_patterns",
        advice=None,
    )


def detect(ds, as_of, rule="readme_period") -> list[dict]:
    ph.check_rule(rule)
    as_of = ts(as_of)
    prev_ids = {S.signal_id(KIND, _key(r)) for r in _standalone(ds, as_of - pd.Timedelta(days=7)) if r["active"]}
    now, resolved = [], []
    for run in _standalone(ds, as_of):
        (now if run["active"] else resolved).append(_signal(ds, run, as_of, rule))
    return ph.finish(now, prev_ids, resolved)
