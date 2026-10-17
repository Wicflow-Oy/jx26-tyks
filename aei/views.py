"""My ward, antibiogram, filter catalogue and trend views (CONTRACTS.md section 4.2). JSON-ready plain types only.

All views are strictly as-of: windows end on `as_of` inclusive, the prior 52 weeks are the 364 days before the window, and
the hospital reference for the stabilised estimate is the same specimen group (and organism, when filtered) on all units
up to `as_of`. Counting rules are applied to the rows inside each window (see aei.aggregates).
"""
import pandas as pd

from . import aggregates as ag
from . import config as C
from . import coverage as cv
from . import stats

FOOTER = "In-vitro coverage on this unit. Not a prescription; local guide first."
ANTIBIOGRAM_FOOTER = "Lab-reported S/R results per organism on this unit, first isolates only. Not a prescription."
SETTINGS = {"inpatient": "Inpatient wards", "outpatient": "Outpatient (emergency department and health centres)"}
SEXES = {"F": "Women", "M": "Men"}
_SEX_ALIASES = {"f": "F", "female": "F", "women": "F", "m": "M", "male": "M", "men": "M"}
SPECIMEN_LABELS = {"urine": "Urine", "blood_wound": "Blood and wound", "blood": "Blood", "wound": "Wound"}
RULE_LABELS = {"readme_period": "First isolate per patient, organism and specimen in the period (dataset README)",
               "30d": "First isolate per patient, organism and specimen in 30 days"}
WINDOW_LABELS = {"4w": "Last 4 weeks", "4m": "Last 4 months", "12m": "Last 12 months"}
PRIOR_DAYS = 364
_DAY = pd.Timedelta(days=1)


# ---------------------------------------------------------------- helpers
def _date(d) -> pd.Timestamp:
    return pd.Timestamp(d).normalize()


def _s(d: pd.Timestamp) -> str:
    return d.strftime("%Y-%m-%d")


def _filters(ds, ward, specimen_group, organism, sex, age_band, setting, rule, home_area=None) -> dict:
    """Validate and normalise filters; raises ValueError on unknown values."""
    if isinstance(ward, str) and "," in ward:
        ward = [w.strip() for w in ward.split(",") if w.strip()]
    if ward is None or ward == "" or len(ward) == 0:
        wards = None
    else:
        wards = (ward,) if isinstance(ward, str) else tuple(ward)
        bad = [w for w in wards if w not in C.WARD_LABELS]
        if bad:
            raise ValueError(f"unknown ward {bad}")
        wards = tuple(dict.fromkeys(wards))
    if specimen_group not in C.SPECIMEN_GROUPS:
        raise ValueError(f"unknown specimen group {specimen_group}")
    if organism is not None and organism not in ag.base(ds).orgs:
        raise ValueError(f"unknown organism {organism}")
    if sex is not None:
        sex = _SEX_ALIASES.get(str(sex).strip().lower())
        if sex is None:
            raise ValueError("sex must be F or M")
    if age_band is not None and age_band not in [b[2] for b in C.AGE_BANDS]:
        raise ValueError(f"unknown age band {age_band}")
    if setting is not None and setting not in SETTINGS:
        raise ValueError(f"setting must be one of {list(SETTINGS)}")
    if rule not in ag.RULES:
        raise ValueError(f"unknown counting rule {rule}")
    if home_area == "":
        home_area = None
    if home_area is not None and home_area not in _home_areas(ds):
        raise ValueError(f"unknown home area {home_area}")
    return {"wards": wards, "specimen_group": specimen_group, "organism": organism, "sex": sex, "age_band": age_band,
            "setting": setting, "home_area": home_area, "rule": rule}


def _home_areas(ds) -> list[str]:
    return sorted(str(a) for a in ds.isolates["home_area"].dropna().unique())


def _echo(f: dict, ward) -> dict:
    single = isinstance(ward, str) and "," not in ward
    return {"ward": None if f["wards"] is None else (f["wards"][0] if single else list(f["wards"])),
            "ward_label": None if f["wards"] is None else ", ".join(C.WARD_LABELS[w] for w in f["wards"]),
            "specimen_group": f["specimen_group"], "organism": f["organism"], "sex": f["sex"], "age_band": f["age_band"],
            "setting": f["setting"], "home_area": f["home_area"], "rule": f["rule"]}


def _unit(ds, f: dict) -> ag.Subset:
    return ag.subset(ds, specimen_group=f["specimen_group"], wards=f["wards"], organism=f["organism"], sex=f["sex"],
                     age_band=f["age_band"], setting=f["setting"], home_area=f["home_area"])


def _hospital(ds, f: dict) -> ag.Subset:
    return ag.subset(ds, specimen_group=f["specimen_group"], organism=f["organism"])


def _is_urine(specimen_group: str) -> bool:
    return C.SPECIMEN_GROUPS[specimen_group] == ["urine"]


def _window_counts(unit: ag.Subset, hosp: ag.Subset, as_of: pd.Timestamp, days: int, rule: str):
    lo = as_of - pd.Timedelta(days=days)
    plo = lo - pd.Timedelta(days=PRIOR_DAYS)
    return (unit.counts(lo, as_of, rule), unit.counts(plo, lo, rule), hosp.counts(plo, lo, rule),
            {"from": _s(lo + _DAY), "to": _s(as_of)})


def _organisms(c: cv.Counts) -> list[dict]:
    out = []
    for i in sorted(range(len(c.orgs)), key=lambda i: (-c.n[i], c.orgs[i])):
        if c.n[i] <= 0:
            continue
        flags = {f: int(c.flags[i, k]) for k, f in enumerate(cv.FLAGS) if c.flags[i, k] > 0}
        out.append({"organism": c.orgs[i], "label": cv.short_organism(c.orgs[i]), "n": int(c.n[i]), "flags": flags})
    return out


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _not_eligible_reason(key: str, c: cv.Counts, cell: dict, scope: str) -> str:
    gaps = cv.untested(c, key)
    names = [cv.short_organism(o) for o, _ in gaps[:3]] + (["other organisms"] if len(gaps) > 3 else [])
    share = 1 - (cell["tested_share"] or 0.0)
    amount = "most" if share > 0.5 else f"{round(100 * share):.0f}%"
    return f"{cv.label(key)} not shown: untested on {_join(names)} ({amount} of {scope} isolates)"


def _check_drug(key: str, specimen_group: str) -> None:
    ps = cv.parts(key)
    if any(p in C.HIDDEN_AS_OPTION for p in ps):
        raise ValueError(f"{cv.label(key)} is a screening test, not a therapy option")
    if any(p in C.URINE_ONLY for p in ps) and not _is_urine(specimen_group):
        raise ValueError(f"{cv.label(key)} is shown for urine only")


# ---------------------------------------------------------------- views
def my_ward(ds, as_of, ward=None, specimen_group="blood_wound", organism=None, sex=None, age_band=None, setting=None,
            windows=("4w", "12m"), rule="readme_period", home_area=None) -> dict:
    """Coverage table for one unit (or several, or all) as of a Sunday: rows in config.DISPLAY_ORDER, one cell per window.
    home_area keeps the unit's isolates from patients living in that area (the hospital reference is not narrowed)."""
    as_of = _date(as_of)
    f = _filters(ds, ward, specimen_group, organism, sex, age_band, setting, rule, home_area)
    windows = tuple(w.strip() for w in windows.split(",")) if isinstance(windows, str) else tuple(windows)
    for w in windows:
        if w not in C.WINDOWS:
            raise ValueError(f"unknown window {w}")
    unit, hosp = _unit(ds, f), _hospital(ds, f)
    hosp_asof = hosp.counts(None, as_of, rule)
    scope = "this unit's" if f["wards"] is not None and len(f["wards"]) == 1 else "the selected"
    urine = _is_urine(specimen_group)

    winfo, organisms, wcounts, cells = [], {}, {}, {}
    for w in windows:
        win, prior, hprior, span = _window_counts(unit, hosp, as_of, C.WINDOWS[w], rule)
        winfo.append({"key": w, "label": WINDOW_LABELS.get(w, w), "days": C.WINDOWS[w], **span, "n_isolates": win.total})
        organisms[w] = _organisms(win)
        wcounts[w] = win
        cells[w] = {k: cv.cell_from_counts(win, k, prior, hosp_asof, hprior) for k in C.DISPLAY_ORDER}

    rows, not_shown = [], []
    for k in C.DISPLAY_ORDER:
        ps = cv.parts(k)
        if any(p in C.HIDDEN_AS_OPTION for p in ps):
            continue
        if any(p in C.URINE_ONLY for p in ps) and not urine:
            not_shown.append({"drug": k, "label": cv.label(k), "reason": f"{cv.label(k)} not shown: used for urine only",
                              "code": "urine_only"})
            continue
        blocking = [w for w in windows if wcounts[w].total >= C.SMALL_N_NONE and cells[w][k]["eligible"] is False]
        if blocking:
            w = max(blocking, key=lambda w: C.WINDOWS[w])
            not_shown.append({"drug": k, "label": cv.label(k), "code": "not_tested_enough", "window": w,
                              "tested_share": cells[w][k]["tested_share"],
                              "untested": [{"organism": o, "n": n} for o, n in cv.untested(wcounts[w], k)],
                              "reason": _not_eligible_reason(k, wcounts[w], cells[w][k], scope)})
            continue
        rows.append({"drug": k, "label": cv.label(k), "aware": cv.aware(k), "cells": {w: cells[w][k] for w in windows}})
    for d in C.DRUGS:
        if d in C.HIDDEN_AS_OPTION:
            not_shown.append({"drug": d, "label": cv.label(d), "code": "screening_only",
                              "reason": f"{cv.label(d)} not shown: a screening test for MRSA, not a therapy option"})

    examples = [{"drug": r["drug"], "label": r["label"], "window": windows[0],
                 "covered": r["cells"][windows[0]]["observed"]["covered"], "tested": r["cells"][windows[0]]["observed"]["tested"],
                 "estimate_pct": r["cells"][windows[0]]["estimate"]["pct"], "estimate_ci": r["cells"][windows[0]]["estimate"]["ci"]}
                for r in rows if windows and r["cells"][windows[0]]["state"] == "low_n"][:3]
    return cv.to_json({
        "as_of": _s(as_of), "monday": _s(as_of + _DAY), "filters": {**_echo(f, ward), "windows": list(windows)},
        "windows": winfo, "rows": rows, "not_shown": not_shown, "organisms": organisms,
        "local_setting": {"value": cv.LOCAL_SETTING, "label": cv.LOCAL_SETTING_LABEL},
        "small_n": {"not_enough_data_below": C.SMALL_N_NONE, "low_n_below": C.SMALL_N_LOW, "pooling_k": C.POOLING_K},
        "small_n_examples": examples, "result_lag_days": C.RESULT_LAG_DAYS, "footer": FOOTER,
    })


def antibiogram(ds, as_of, ward=None, specimen_group="blood_wound", window="4w", rule="readme_period", *, organism=None,
                sex=None, age_band=None, setting=None, home_area=None) -> dict:
    """Per-organism lab results (R of n, % S with a Jeffreys interval, small-n state) for the "organism" tab."""
    as_of = _date(as_of)
    f = _filters(ds, ward, specimen_group, organism, sex, age_band, setting, rule, home_area)
    if window not in C.WINDOWS:
        raise ValueError(f"unknown window {window}")
    lo = as_of - pd.Timedelta(days=C.WINDOWS[window])
    c = _unit(ds, f).counts(lo, as_of, rule)
    shown = [d for d in C.DRUGS if d not in C.URINE_ONLY or _is_urine(specimen_group)]
    orgs = []
    for o in _organisms(c):
        i = c.orgs.index(o["organism"])
        drugs = []
        for d in shown:
            j = cv.RAW_INDEX[d]
            n, s = int(c.t_raw[i, j]), int(c.s_raw[i, j])
            er = cv.never_covered(o["organism"], d)
            if n == 0 and not er:
                continue
            state = stats.n_state(n) if n > 0 else None
            show = state is not None and state != "not_enough_data"
            drugs.append({"drug": d, "label": cv.label(d), "r": n - s, "s": s, "n": n, "state": state,
                          "pct_s": s / n if show else None, "ci": list(stats.jeffreys_interval(s, n)) if show else None,
                          "expected_resistant": er, "screening_only": d in C.HIDDEN_AS_OPTION})
        orgs.append({**o, "drugs": drugs})
    return cv.to_json({
        "as_of": _s(as_of), "monday": _s(as_of + _DAY), "filters": _echo(f, ward),
        "window": {"key": window, "label": WINDOW_LABELS.get(window, window), "days": C.WINDOWS[window],
                   "from": _s(lo + _DAY), "to": _s(as_of), "n_isolates": c.total},
        "drugs": [{"drug": d, "label": cv.label(d), "screening_only": d in C.HIDDEN_AS_OPTION} for d in shown],
        "organisms": orgs, "footer": ANTIBIOGRAM_FOOTER,
    })


def filters_catalog(ds) -> dict:
    """Everything the filter bar can offer, from config and the data."""
    x = ds.isolates
    wt = x.groupby("ward_code")["ward_type"].first().to_dict()
    org_n = x["organism"].value_counts()
    return cv.to_json({
        "wards": [{"code": w, "label": lab, "setting": {"in": "inpatient", "out": "outpatient"}.get(wt.get(w))}
                  for w, lab in C.WARD_LABELS.items()],
        "specimen_groups": [{"key": k, "label": SPECIMEN_LABELS.get(k, k), "specimens": list(v)} for k, v in C.SPECIMEN_GROUPS.items()],
        "organisms": [{"organism": o, "label": cv.short_organism(o), "n": int(n)} for o, n in org_n.items()],
        "sexes": [{"code": k, "label": v} for k, v in SEXES.items()],
        "age_bands": [{"key": lab, "label": lab, "min": lo, "max": None if hi >= 200 else hi} for lo, hi, lab in C.AGE_BANDS],
        "settings": [{"key": k, "label": v} for k, v in SETTINGS.items()],
        "home_areas": [{"key": a, "label": a, "n": int((x["home_area"] == a).sum())} for a in _home_areas(ds)],
        "windows": [{"key": k, "label": WINDOW_LABELS.get(k, k), "days": d} for k, d in C.WINDOWS.items()],
        "rules": [{"key": k, "label": v, "default": k == "readme_period"} for k, v in RULE_LABELS.items()],
        "drugs": [{"drug": k, "label": cv.label(k), "aware": cv.aware(k), "urine_only": any(p in C.URINE_ONLY for p in cv.parts(k))}
                  for k in C.DISPLAY_ORDER],
    })


def trend(ds, ward, specimen_group, drug, as_of, weeks=52, window="4w", organism=None, rule="readme_period", *, sex=None,
          age_band=None, setting=None, home_area=None) -> dict:
    """Weekly series of the rolling-window cell (observed + estimate) for sparklines, oldest first, ending on as_of."""
    as_of = _date(as_of)
    f = _filters(ds, ward, specimen_group, organism, sex, age_band, setting, rule, home_area)
    if window not in C.WINDOWS:
        raise ValueError(f"unknown window {window}")
    _check_drug(drug, specimen_group)
    weeks = int(weeks)
    if not 1 <= weeks <= 260:
        raise ValueError("weeks must be 1..260")
    unit, hosp = _unit(ds, f), _hospital(ds, f)
    j = cv.KEY_INDEX[drug]
    series = []
    for i in range(weeks - 1, -1, -1):
        end = as_of - pd.Timedelta(days=7 * i)
        win, prior, hprior, span = _window_counts(unit, hosp, end, C.WINDOWS[window], rule)
        # the hospital as-of reference only feeds the stabilised (low_n) estimate, so count it only when needed
        ref = hosp.counts(None, end, rule) if stats.n_state(int(win.tst[:, j].sum())) == "low_n" else hprior
        c = cv.cell_from_counts(win, drug, prior, ref, hprior)
        series.append({"as_of": _s(end), **span, **c})
    return cv.to_json({
        "as_of": _s(as_of), "monday": _s(as_of + _DAY), "drug": drug, "label": cv.label(drug), "aware": cv.aware(drug),
        "window": window, "weeks": weeks, "filters": _echo(f, ward), "series": series,
        "local_setting": {"value": cv.LOCAL_SETTING, "label": cv.LOCAL_SETTING_LABEL},
    })
