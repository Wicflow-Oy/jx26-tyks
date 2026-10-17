"""Policy lines (config.POLICY_LINES): rolling 52-week resistance under the line's own counting rule; fires while >= threshold.

Ported from 51_codex_fixes_check (README rule: first isolate per patient inside the rolling window, among tested isolates)
and 07/11 (the 30-day episode rule, `first_30d`). The line's `counting_rule` governs the policy item and the order card,
so the brief's rule toggle does not move the line; `policy_states(..., rule="30d")` shows the alternative count.

`policy_states(ds, as_of)` is read by the order-screen card (workstream D): exact counts, Jeffreys interval, the rate
one year earlier, the threshold, `crossed_on` (first week-end at or above the line in the current run) and the
local-guide alternative quoted from config (never chosen by a model).
"""
from collections import OrderedDict

import pandas as pd

from .. import config as C
from .. import data, stats
from .. import signal as sig
from . import day, drug_label, ds_key, organism_label, plain, ts, ward_label

METHOD = "rolling 52-week resistant share under the policy line's counting rule (51_codex_fixes_check)"
_POP: dict = {}
_RATES: "OrderedDict[tuple, tuple[int, int]]" = OrderedDict()
_RATES_MAX = 4096


def _population(ds, line: dict) -> pd.DataFrame:
    """Tested isolates in the line's population (organism, specimen, wards, sex); cached per dataset."""
    key = (ds_key(ds), line["id"])
    if key not in _POP:
        x = ds.isolates
        pop = line.get("population", {})
        m = (x.organism == line["organism"]) & (x.specimen == line["specimen"]) & x[line["drug"]].notna()
        if pop.get("wards"):
            m &= x.ward_code.isin(pop["wards"])
        if pop.get("sex"):
            m &= x.sex == pop["sex"]
        _POP[key] = x.loc[m, ["isolate_id", "patient_id", "organism", "specimen", "sample_date", "first_30d",
                              line["drug"]]].sort_values(["sample_date", "isolate_id"])
    return _POP[key]


def _counts(ds, line: dict, end: pd.Timestamp, rule: str) -> tuple[int, int]:
    key = (ds_key(ds), line["id"], str(end.date()), rule)
    if key in _RATES:
        return _RATES[key]
    w = data.first_isolates(data.window(_population(ds, line), end, int(line["window_days"])), rule)
    res = (int((w[line["drug"]] == "R").sum()), len(w))
    _RATES[key] = res
    while len(_RATES) > _RATES_MAX:
        _RATES.popitem(last=False)
    return res


def _at_or_above(x: int, n: int, threshold: float) -> bool:
    return n > 0 and x / n >= threshold


def population_label(line: dict) -> str:
    pop = line.get("population", {})
    who = {"F": "women", "M": "men"}.get(pop.get("sex"), "patients")
    wards = pop.get("wards") or []
    if wards and all(w.startswith("PHC") for w in wards):
        where = "primary care"
    elif wards:
        where = ", ".join(ward_label(w) for w in wards)
    else:
        where = "all units"
    return f"{who} in {where}"


def _organism_text(line: dict) -> str:
    spec = {"urine": "urinary ", "blood": "blood ", "wound": "wound "}.get(line.get("specimen"), "")
    return f"{spec}{organism_label(line['organism'])}"


def state(ds, line: dict, as_of, rule: str | None = None) -> dict:
    end = ts(as_of)
    rule = rule or line.get("counting_rule", "readme_period")
    thr = float(line["threshold"])
    x, n = _counts(ds, line, end, rule)
    active = _at_or_above(x, n, thr)
    crossed = None
    if active:
        crossed, t = end, end - pd.Timedelta(days=7)
        start = pd.Timestamp(C.DATA_START)
        while t >= start and _at_or_above(*_counts(ds, line, t, rule), thr):
            crossed, t = t, t - pd.Timedelta(days=7)
    prior_end = end - pd.Timedelta(days=int(line["window_days"]))
    xp, np_ = _counts(ds, line, prior_end, rule)
    lo, hi = stats.jeffreys_interval(x, n)
    days = int(line["window_days"])
    return plain({
        "id": line["id"], "signal_id": sig.signal_id("policy_line", {"line": line["id"]}), "label": line["label"],
        "as_of": day(end), "drug": line["drug"], "drug_label": drug_label(line["drug"]), "organism": line["organism"],
        "specimen": line["specimen"], "population": line.get("population", {}), "population_label": population_label(line),
        "rate": x / n if n else None, "x": x, "n": n, "interval": [lo, hi],
        "rate_prior": xp / np_ if np_ else None, "x_prior": xp, "n_prior": np_, "prior_as_of": day(prior_end),
        "threshold": thr, "crossed_on": None if crossed is None else day(crossed), "active": active,
        "local_guide_alternative": dict(line["local_guide_alternative"]), "message": line["message"],
        "order_units": list(line.get("order_units", [])), "order_indication": line.get("order_indication"),
        "counting_rule": rule, "window_days": days,
        "date_from": day(end - pd.Timedelta(days=days - 1)), "date_to": day(end),
    })


def policy_states(ds, as_of, rule: str | None = None) -> list[dict]:
    """State of every policy line at `as_of` (strictly as-of). `rule=None` uses each line's own counting rule."""
    return [state(ds, line, as_of, rule) for line in C.POLICY_LINES]


def detect(ds, as_of, rule: str = "readme_period") -> list[dict]:
    """Policy-line items for the brief. The line's own counting rule applies (see module docstring)."""
    out = []
    for line in C.POLICY_LINES:
        s = state(ds, line, as_of)
        if not s["active"]:
            continue
        slots = {"drug_label": s["drug_label"], "organism_label": _organism_text(line),
                 "population_label": s["population_label"], "rate": s["rate"], "counts": [s["x"], s["n"]],
                 "window_weeks": s["window_days"] // 7, "relation": "above" if s["rate"] > s["threshold"] else "at",
                 "threshold": s["threshold"], "crossed_on": s["crossed_on"], "rate_prior": s["rate_prior"],
                 "counts_prior": [s["x_prior"], s["n_prior"]], "interval": s["interval"],
                 "alternative": s["local_guide_alternative"]["text"]}
        pop = line.get("population", {})
        evidence = {
            "filter": {"ward": list(pop.get("wards") or []) or None, "specimen": line["specimen"],
                       "organism": line["organism"], "drug": line["drug"], "sex": pop.get("sex"),
                       "date_from": s["date_from"], "date_to": s["date_to"], "rule": s["counting_rule"]},
            "counts": {"resistant": s["x"], "tested": s["n"], "prior_resistant": s["x_prior"],
                       "prior_tested": s["n_prior"], "interval": s["interval"]},
            "method": METHOD,
            "params": {"threshold": s["threshold"], "window_days": s["window_days"], "line_id": line["id"],
                       "crossed_on": s["crossed_on"], "prior_as_of": s["prior_as_of"]},
        }
        out.append(sig.make_signal(
            "policy_line", {"line": line["id"]}, priority="P2", as_of=s["as_of"], template_id="trend_policy_line",
            slots=slots, evidence=evidence, ward=None, specimen=line["specimen"], organism=line["organism"],
            drug=line["drug"], section="policy", advice=line["message"]))
    return out
