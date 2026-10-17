"""Data completeness: units that sent no (or impossibly few) cultures this week (ported from 35_data_gaps).

For each unit, the week is the 7 days ending `as_of`; "usual" is the mean weekly culture count over the 56 days before
the week (8 weeks; at least 28 days of history). A unit is flagged when it sent no cultures while usually >= 5 a week,
or when the Poisson lower tail of this week's count is < 1e-6 (35's threshold). On this dataset that finds only the
PHC-S gap of 8-14 Dec 2025 (0 cultures, usually about 51). A gap is "data gap, cause unknown; not zero resistance".
"""
import pandas as pd
from scipy import stats as st

from .. import config as C
from .. import signal as sig
from . import day, plain, ts, ward_label

HISTORY_DAYS = 56
MIN_HISTORY_DAYS = 28
SILENT_MIN_EXPECTED = 5.0
LOW_P = 1e-6
METHOD = "culture volume this week vs the unit's previous 8 weeks (Poisson lower tail; 35_data_gaps)"


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
    out.attrs.update(week_from=day(wk_from), week_to=day(end), history_from=day(hist_from), history_to=day(hist_to))
    return out


def detect(ds, as_of, rule: str = "readme_period") -> list[dict]:
    end = ts(as_of)
    v = unit_volumes(ds, end)
    out = []
    for r in v[v.state.isin(["silent", "low"])].itertuples(index=False):
        expected = round(r.expected)
        if r.state == "silent":
            tid, slots = "completeness_gap", {"ward_label": ward_label(r.ward), "expected": expected}
        else:
            tid, slots = "trend_completeness_low", {"ward_label": ward_label(r.ward), "n_cultures": r.n_week,
                                                    "expected": expected}
        evidence = plain({
            "filter": {"ward": r.ward, "specimen": None, "organism": None, "drug": None,
                       "date_from": v.attrs["week_from"], "date_to": v.attrs["week_to"], "rule": "all_cultures"},
            "counts": {"cultures_this_week": r.n_week, "expected_per_week": round(r.expected, 1), "p_low": r.p_low},
            "method": METHOD,
            "params": {"history_from": v.attrs["history_from"], "history_to": v.attrs["history_to"],
                       "silent_min_expected": SILENT_MIN_EXPECTED, "low_p": LOW_P},
        })
        out.append(sig.make_signal(
            "completeness", {"ward": r.ward}, priority="P2", as_of=day(end), template_id=tid, slots=plain(slots),
            evidence=evidence, ward=r.ward, first_sample_date=v.attrs["week_from"], section="data_quality",
            advice="Lab check"))
    return out


def status_line(ds, as_of) -> dict:
    """The data-quality line shown when every unit sent data: 'All 9 units sent data this week.' (info)."""
    end = ts(as_of)
    v = unit_volumes(ds, end)
    n_units = len(v)
    evidence = plain({
        "filter": {"ward": list(v.ward), "specimen": None, "organism": None, "drug": None,
                   "date_from": v.attrs["week_from"], "date_to": v.attrs["week_to"], "rule": "all_cultures"},
        "counts": {"units": n_units, "cultures_this_week": dict(zip(v.ward, v.n_week.astype(int)))},
        "method": METHOD, "params": {"history_from": v.attrs["history_from"], "history_to": v.attrs["history_to"]},
    })
    return sig.make_signal("completeness", {"status": "all_units"}, priority="info", as_of=day(end),
                           template_id="completeness_ok", slots={"n_units": n_units}, evidence=evidence,
                           section="data_quality")
