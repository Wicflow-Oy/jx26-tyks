"""Data completeness: units that sent no (or impossibly few) cultures this week.

For each unit, the week is the 7 days ending `as_of`; "usual" is the mean weekly culture count over the 56 days before
the week (8 weeks; at least 28 days of history). A unit is flagged when it sent no cultures while usually >= 5 a week,
or when the Poisson lower tail of this week's count is < 1e-6 (35's threshold). On this dataset that finds only the
PHC-S gap of 8-14 Dec 2025 (0 cultures, usually about 51). A gap is "data gap, cause unknown", never a statement about
resistance. In the week after a gap the unit is listed as resolved with that week's culture count.
"""

import pandas as pd
from scipy import stats as st

from .. import config as C
from .. import signal as sig
from ..data import to_json
from . import iso, ts, ward_label

HISTORY_DAYS = 56
MIN_HISTORY_DAYS = 28
SILENT_MIN_EXPECTED = 5.0
LOW_P = 1e-6
GAP_STATES = ("silent", "low")
METHOD = "culture volume this week vs the unit's previous 8 weeks (Poisson lower tail)"


def unit_volumes(ds, as_of) -> pd.DataFrame:
    """One row per unit in config.WARD_LABELS: n_week, expected (per week), p_low and state (ok|silent|low|no_history)."""
    end = ts(as_of)
    c = ds.cultures
    start = pd.Timestamp(C.DATA_START)
    wk_from = end - pd.Timedelta(days=6)
    hist_to = wk_from - pd.Timedelta(days=1)
    hist_from = max(hist_to - pd.Timedelta(days=HISTORY_DAYS - 1), start)
    hist_days = (hist_to - hist_from).days + 1
    week = c[(c.sample_date >= wk_from) & (c.sample_date <= end)].ward_code.value_counts()
    hist = c[(c.sample_date >= hist_from) & (c.sample_date <= hist_to)].ward_code.value_counts()
    rows = []
    for w in C.WARD_LABELS:
        n = int(week.get(w, 0))
        if hist_days < MIN_HISTORY_DAYS:
            rows.append({"ward": w, "n_week": n, "expected": None, "p_low": None, "state": "no_history"})
            continue
        exp = float(hist.get(w, 0)) * 7 / hist_days
        p = float(st.poisson.cdf(n, exp)) if exp > 0 else 1.0
        if n == 0 and exp >= SILENT_MIN_EXPECTED:
            state = "silent"
        elif p < LOW_P:
            state = "low"
        else:
            state = "ok"
        rows.append({"ward": w, "n_week": n, "expected": exp, "p_low": p, "state": state})
    out = pd.DataFrame(rows)
    out.attrs.update(week_from=iso(wk_from), week_to=iso(end), history_from=iso(hist_from), history_to=iso(hist_to))
    return out


def _evidence(v: pd.DataFrame, r, counts: dict) -> dict:
    return to_json(
        {
            "filter": {
                "ward": r.ward,
                "specimen": None,
                "organism": None,
                "drug": None,
                "date_from": v.attrs["week_from"],
                "date_to": v.attrs["week_to"],
                "rule": "all_cultures",
            },
            "counts": counts,
            "method": METHOD,
            "params": {
                "history_from": v.attrs["history_from"],
                "history_to": v.attrs["history_to"],
                "silent_min_expected": SILENT_MIN_EXPECTED,
                "low_p": LOW_P,
            },
        }
    )


def _signal(v: pd.DataFrame, r) -> dict:
    expected = round(r.expected)
    slots = {"ward": r.ward, "ward_label": ward_label(r.ward), "n_cultures": r.n_week, "expected": expected}
    tid = "trend_completeness_gap" if r.state == "silent" else "trend_completeness_low"
    counts = {"cultures_this_week": r.n_week, "expected_per_week": round(r.expected, 1), "p_low": r.p_low}
    return sig.make_signal(
        "completeness",
        {"ward": r.ward},
        priority="P2",
        as_of=v.attrs["week_to"],
        template_id=tid,
        slots=to_json(slots),
        evidence=_evidence(v, r, counts),
        ward=r.ward,
        first_sample_date=v.attrs["week_from"],
        section="data_quality",
        advice="Lab check",
    )


def _resolved_signal(v: pd.DataFrame, r, last: pd.DataFrame) -> dict:
    """`r`: the unit this week; `last`: last week's unit_volumes, when the unit was flagged."""
    was = last.set_index("ward").loc[r.ward]
    slots = {
        "ward": r.ward,
        "ward_label": ward_label(r.ward),
        "n_cultures": r.n_week,
        "last_flagged": last.attrs["week_to"],
        "n_last": was.n_week,
        "expected_last": round(was.expected),
    }
    counts = {
        "cultures_this_week": r.n_week,
        "last_flagged_cultures": was.n_week,
        "last_flagged_expected_per_week": round(was.expected, 1),
    }
    return sig.make_signal(
        "completeness",
        {"ward": r.ward},
        priority="P2",
        as_of=v.attrs["week_to"],
        template_id="trend_completeness_resolved",
        slots=to_json(slots),
        evidence=_evidence(v, r, counts),
        ward=r.ward,
        first_sample_date=v.attrs["week_from"],
        status="resolved",
        section="data_quality",
    )


def detect(ds, as_of, rule: str = "readme_period") -> list[dict]:
    end = ts(as_of)
    v = unit_volumes(ds, end)
    last = unit_volumes(ds, end - pd.Timedelta(days=7))
    gap_last_week = set(last.ward[last.state.isin(GAP_STATES)])
    out = []
    for r in v.itertuples(index=False):
        if r.state in GAP_STATES:
            out.append(_signal(v, r))
        elif r.ward in gap_last_week:
            out.append(_resolved_signal(v, r, last))
    return out


def status_line(ds, as_of) -> dict:
    """The data-quality line shown when every unit sent data: 'All 9 units sent data this week.' (info)."""
    end = ts(as_of)
    v = unit_volumes(ds, end)
    n_units = len(v)
    evidence = to_json(
        {
            "filter": {
                "ward": list(v.ward),
                "specimen": None,
                "organism": None,
                "drug": None,
                "date_from": v.attrs["week_from"],
                "date_to": v.attrs["week_to"],
                "rule": "all_cultures",
            },
            "counts": {"units": n_units, "cultures_this_week": dict(zip(v.ward, v.n_week.astype(int)))},
            "method": METHOD,
            "params": {"history_from": v.attrs["history_from"], "history_to": v.attrs["history_to"]},
        }
    )
    return sig.make_signal(
        "completeness",
        {"status": "all_units"},
        priority="info",
        as_of=iso(end),
        template_id="trend_completeness_ok",
        slots={"n_units": n_units},
        evidence=evidence,
        section="data_quality",
    )
