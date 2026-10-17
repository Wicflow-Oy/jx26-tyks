"""THL guidance rule cards (analysis 08_hidden, 24_alert_burden, dossier rule table; THL OHJ 2/2020).

Single cards, P1, every case: the first CPE or VRE isolate of a patient. Shown for 28 days after the sample date
(the default 4-week window): "new" in its first week, "ongoing" after, listed as resolved for one more week.

Same-unit cluster checks ("several findings above the usual level on one unit", regardless of antibiogram identity;
identity is shown as a qualifier), MRSA and ESBL, per unit x organism, evaluated daily on days with a new marker isolate:
  n   = distinct marker patients on the unit in the last 28 days (MRSA >= 2, ESBL >= 3),
  exp = the unit's marker patients in the 364 days before the window, scaled to 28 days,
  fire when Poisson sf(n - 1, max(exp, 0.05)) < 1e-3; alerts less than 15 days apart form one episode.
A cluster card whose unit, organism and marker overlap a phenotype cluster is not shown separately: it is attached to
the phenotype signal as evidence (evidence.thl_rule). Same pattern (top antibiogram >= 75% of patients): MRSA P1,
ESBL P2. Heterogeneous: P2, "ranked lower by our rules (truth unknown)".
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st

from .. import signal as S
from . import phenotype as ph

KIND = "thl_rule"
SINGLE_MARKERS = ("cpe", "vre")
SINGLE_ACTIVE_DAYS = 28
CLUSTER_MIN_PATIENTS = {"mrsa": 2, "esbl": 3}
CLUSTER_ALPHA = 1e-3
WINDOW_DAYS = ph.WINDOW_DAYS
HISTORY_DAYS = ph.HISTORY_DAYS
SAME_PATTERN_SHARE = 0.75
ACTION_TEXT = {"cpe": "Single room with own WC, contact precautions, screen exposed patients (at least one week after "
                      "exposure ends), look-back over the past year, notify infection control; strain to the reference lab.",
               "vre": "Single room with own WC, contact precautions, screen exposed patients, look-back over the past "
                      "year, notify infection control; strain to the reference lab.",
               "mrsa": "Contact precautions; check ward overlap; typing if two or more are linked.",
               "esbl": "Standard precautions; epidemic check: same antibiogram? same room or ward days?"}


def _onset_label(r) -> str:
    if bool(r.hosp_onset):
        return "hospital-onset"
    if not pd.isna(r.care_day_no):
        return "early in the stay, not hospital-onset"
    return "outpatient sample"


# ----------------------------------------------------------------------------------------------- single cards
def _single_cases(ds, as_of, marker) -> pd.DataFrame:
    x = ph.upto(ds.isolates, as_of)
    return x[x[marker] == 1].sort_values(["sample_date", "isolate_id"]).drop_duplicates("patient_id")


def _single_key(r, marker) -> dict:
    return {"rule": marker, "ward": r.ward_code, "organism": r.organism, "first_sample_date": ph.iso(r.sample_date),
            "isolate_id": r.isolate_id}


def _single_items(ds, as_of, include_recent=False) -> list[tuple]:
    as_of = ph.ts(as_of)
    lim = SINGLE_ACTIVE_DAYS + (ph.RESOLVED_LIST_DAYS if include_recent else 0)
    out = []
    for m in SINGLE_MARKERS:
        cases = _single_cases(ds, as_of, m)
        for i, r in enumerate(cases.itertuples()):
            age = (as_of - r.sample_date).days
            if age < lim:
                prev = cases.iloc[i - 1].sample_date if i > 0 else None
                out.append((m, r, prev, age < SINGLE_ACTIVE_DAYS))
    return out


def _single_signal(m, r, prev, as_of, rule) -> dict:
    slots = {"ward": r.ward_code, "ward_label": ph.ward_label(r.ward_code), "marker_label": ph.MARKER_LABELS[m],
             "organism_label": ph.short_org(r.organism), "specimen": r.specimen, "sample_date": ph.iso(r.sample_date),
             "onset_label": _onset_label(r)}
    if prev is not None:
        slots["days_since_prev"] = int((r.sample_date - prev).days)
    care_day = None if pd.isna(r.care_day_no) else int(r.care_day_no)
    evidence = {
        "filter": {"ward": r.ward_code, "specimen": r.specimen, "organism": r.organism, "drug": None,
                   "date_from": ph.iso(r.sample_date), "date_to": ph.iso(as_of), "rule": rule, "marker": m,
                   "isolate_ids_only": True},
        "counts": {"n_patients": 1, "care_day": care_day, "hospital_onset": bool(r.hosp_onset),
                   "days_since_previous_case": slots.get("days_since_prev"),
                   "previous_case_date": None if prev is None else ph.iso(prev)},
        "method": f"THL guidance rule card: every {ph.MARKER_LABELS[m]} case (first {ph.MARKER_LABELS[m]} isolate of a patient)",
        "params": {"active_days": SINGLE_ACTIVE_DAYS, "hospital_onset_min_care_day": 3},
        "isolate_ids": [r.isolate_id],
        "action": ACTION_TEXT[m],
        "rank": ph.rank(m, [r.specimen], "strong"),
        "date_basis": ph.DATE_BASIS,
        "source": "THL OHJ 2/2020 (guidance, not legally binding); local infection-control rules apply",
    }
    return S.make_signal(KIND, _single_key(r, m), priority="P1", as_of=ph.iso(as_of),
                         template_id="ob_thl_single" if prev is not None else "ob_thl_single_first", slots=slots,
                         evidence=evidence, ward=r.ward_code, home_area=r.home_area, specimen=r.specimen, organism=r.organism,
                         first_sample_date=ph.iso(r.sample_date), section="unusual_patterns", advice=None)


# ----------------------------------------------------------------------------------------------- cluster checks
def _cluster_alerts(ds) -> pd.DataFrame:
    x = ds.isolates
    cols = ["day", "ward", "organism", "marker", "n", "expected", "p", "first_day"]
    out = []
    for m, min_n in CLUSTER_MIN_PATIENTS.items():
        mm = x[x[m] == 1]
        for (ward, org), g in mm.groupby(["ward_code", "organism"]):
            day = (g.sample_date - ph._START).dt.days.to_numpy()
            o = np.argsort(day, kind="stable")
            day, pat = day[o], g.patient_id.to_numpy()[o]
            for d in np.unique(day):
                if d < ph.LEARN_DAYS:
                    continue
                w = (day > d - WINDOW_DAYS) & (day <= d)
                n = len(np.unique(pat[w]))
                if n < min_n:
                    continue
                h = (day > d - WINDOW_DAYS - HISTORY_DAYS) & (day <= d - WINDOW_DAYS)
                exp = len(np.unique(pat[h])) / HISTORY_DAYS * WINDOW_DAYS
                p = float(st.poisson.sf(n - 1, max(exp, 0.05)))
                if p < CLUSTER_ALPHA:
                    out.append((int(d), ward, org, m, n, exp, p, int(day[w].min())))
    return pd.DataFrame(out, columns=cols)


def _cluster_episodes_full(ds) -> list[dict]:
    al = ph.cached(ds, "thl_cluster_alerts", _cluster_alerts)
    eps = []
    for (ward, org, m), g in al.groupby(["ward", "organism", "marker"], sort=True):
        g = g.sort_values("day")
        brk = (g.day.diff().fillna(ph.EPISODE_GAP_DAYS + 1) > ph.EPISODE_GAP_DAYS).cumsum()
        for _, e in g.groupby(brk):
            eps.append({"ward": ward, "organism": org, "marker": m, "alerts": e.reset_index(drop=True)})
    return eps


def cluster_episodes(ds, as_of) -> list[dict]:
    d = ph.day_no(as_of)
    out = []
    for ep in ph.cached(ds, "thl_cluster_episodes", _cluster_episodes_full):
        a = ep["alerts"][ep["alerts"].day <= d]
        if a.empty:
            continue
        out.append({"ward": ep["ward"], "organism": ep["organism"], "marker": ep["marker"],
                    "first_alert_day": int(a.day.iloc[0]), "last_alert_day": int(a.day.max()),
                    "first_sample_day": int(a.first_day.iloc[0]), "n_alerts": len(a),
                    "max_n_28d": int(a.n.max()), "min_p": float(a.p.min()), "last": a.iloc[-1].to_dict()})
    return out


def _cluster_key(ep) -> dict:
    return {"rule": f"{ep['marker']}_same_unit", "ward": ep["ward"], "organism": ep["organism"],
            "first_sample_date": ph.iso(ph.day_date(ep["first_sample_day"]))}


def _span(ep, as_of) -> tuple[int, int]:
    return ep["first_sample_day"], min(ep["last_alert_day"] + ph.EPISODE_GAP_DAYS, ph.day_no(as_of))


def _covered(ep, pheno_eps, as_of) -> bool:
    a0, a1 = _span(ep, as_of)
    for pe in pheno_eps:
        if pe["ward"] == ep["ward"] and pe["organism"] == ep["organism"] and pe["marker"] == ep["marker"]:
            b0, b1 = pe["first_sample_day"], min(pe["last_alert_day"] + ph.EPISODE_GAP_DAYS, ph.day_no(as_of))
            if a0 <= b1 and b0 <= a1:
                return True
    return False


def _pheno_with_markers(ds, as_of) -> list[dict]:
    out = []
    for pe in ph.episodes(ds, as_of):
        pe = dict(pe)
        pe["marker"] = ph.cluster_marker(ds, pe, as_of)
        out.append(pe)
    return out


def active_clusters(ds, as_of, include_recent=False, uncovered_only=True) -> list[dict]:
    """Same-unit cluster episodes active at as_of (last alert <= 14 days old), optionally the recently stopped ones."""
    lim = ph.EPISODE_GAP_DAYS + (ph.RESOLVED_LIST_DAYS if include_recent else 0)
    eps = [ep for ep in cluster_episodes(ds, as_of) if ph.day_no(as_of) - ep["last_alert_day"] <= lim]
    if not eps:
        return []
    pheno = _pheno_with_markers(ds, as_of) if uncovered_only else []
    out = []
    for ep in eps:
        if uncovered_only and _covered(ep, pheno, as_of):
            continue
        ep = dict(ep)
        ep["active"] = ph.day_no(as_of) - ep["last_alert_day"] <= ph.EPISODE_GAP_DAYS
        out.append(ep)
    return out


def _cluster_summary(ds, ep, as_of) -> dict:
    first = ph.day_date(ep["first_sample_day"])
    pop = ph.population(ds, ep["ward"], ep["organism"], ep["marker"], None, first, as_of)
    pats = pop.sort_values(["sample_date", "isolate_id"]).drop_duplicates("patient_id")
    top = pats.profile.value_counts()
    x = ph.upto(ds.isolates, as_of)
    hist = ph.between(x, first - pd.Timedelta(days=HISTORY_DAYS), first - pd.Timedelta(days=1))
    hist = hist[(hist.ward_code == ep["ward"]) & (hist.organism == ep["organism"]) & (hist[ep["marker"]] == 1)]
    days = (ph.ts(as_of) - first).days + 1
    mu = hist.patient_id.nunique() / HISTORY_DAYS * days
    lo, hi = ph.poisson_range(mu)
    return {"first": first, "pop": pop, "n_patients": len(pats), "top_pattern": top.index[0], "n_share": int(top.iloc[0]),
            "n_profiles": len(top), "profiles": {k: int(v) for k, v in top.items()}, "expected": mu, "usual_low": lo,
            "usual_high": hi, "days": days, "specimens": sorted(pop.specimen.unique().tolist()),
            "hosp_onset": int(pats.hosp_onset.sum())}


def _cluster_signal(ds, ep, as_of, rule) -> dict:
    sm = _cluster_summary(ds, ep, as_of)
    m = ep["marker"]
    same = sm["n_share"] / max(sm["n_patients"], 1) >= SAME_PATTERN_SHARE
    slots = {"ward": ep["ward"], "ward_label": ph.ward_label(ep["ward"]), "organism_label": ph.organism_label(ep["organism"], m),
             "n_patients": sm["n_patients"], "first_date": ph.iso(sm["first"]), "usual_low": sm["usual_low"],
             "usual_high": sm["usual_high"]}
    if same:
        slots.update({"n_share": sm["n_share"], "pattern": sm["top_pattern"]})
    else:
        slots["n_profiles"] = sm["n_profiles"]
    ach = ph.competing_explanations(ds, ep["ward"], ep["organism"], sm["first"], as_of, marker=m)
    h1 = next((h["rating"] for h in ach["hypotheses"] if h["id"] == "H1"), "weak")
    from . import stepup
    evidence = {
        "filter": {"ward": ep["ward"], "specimen": None, "organism": ep["organism"], "drug": None,
                   "date_from": ph.iso(sm["first"]), "date_to": ph.iso(as_of), "rule": rule, "marker": m,
                   "profile": sm["top_pattern"], "population": "marker"},
        "counts": {"n_patients": sm["n_patients"], "n_share_top_pattern": sm["n_share"], "n_antibiograms": sm["n_profiles"],
                   "patients_by_antibiogram": sm["profiles"], "hospital_onset_patients": sm["hosp_onset"],
                   "expected_in_period": round(sm["expected"], 3), "period_days": sm["days"],
                   "first_alert_date": ph.iso(ph.day_date(ep["first_alert_day"])),
                   "last_alert_date": ph.iso(ph.day_date(ep["last_alert_day"])), "max_patients_28d": ep["max_n_28d"],
                   "min_p": ep["min_p"], "specimens": sm["specimens"]},
        "method": (f"THL guidance same-unit cluster check ({ph.MARKER_LABELS[m]}): distinct patients in 28 days vs the "
                   "unit's prior 52 weeks, Poisson p < 1e-3, evaluated daily; identity shown as a qualifier"),
        "params": {"window_days": WINDOW_DAYS, "history_days": HISTORY_DAYS, "min_patients": CLUSTER_MIN_PATIENTS[m],
                   "alpha": CLUSTER_ALPHA, "same_pattern_share": SAME_PATTERN_SHARE, "episode_gap_days": ph.EPISODE_GAP_DAYS,
                   "learning_days": ph.LEARN_DAYS},
        "isolate_ids": sm["pop"].isolate_id.tolist(),
        "competing_explanations": ach,
        "stepup": stepup.evidence_for(ds, as_of, ep["ward"], m),
        "action": ACTION_TEXT[m],
        "rank": ph.rank(m, sm["specimens"], h1),
        "date_basis": ph.DATE_BASIS,
        "source": "THL OHJ 2/2020 (guidance, not legally binding); local infection-control rules apply",
    }
    if not same:
        evidence["label"] = (f"heterogeneous: {sm['n_profiles']} antibiograms, ranked lower by our rules (truth unknown)")
    return S.make_signal(KIND, _cluster_key(ep), priority="P1" if (same and m == "mrsa") else "P2", as_of=ph.iso(as_of),
                         template_id="ob_thl_cluster_same" if same else "ob_thl_cluster_mixed", slots=slots,
                         evidence=evidence, ward=ep["ward"], organism=ep["organism"],
                         specimen=sm["specimens"][0] if len(sm["specimens"]) == 1 else None,
                         first_sample_date=ph.iso(sm["first"]), section="unusual_patterns",
                         advice="Typing advised" if same else None)


def cover_for(ds, as_of, ward, organism, marker, since=None) -> dict | None:
    """The same-unit THL cluster check that a phenotype cluster absorbs (attached as evidence.thl_rule), if any."""
    if marker not in CLUSTER_MIN_PATIENTS:
        return None
    lo = ph.day_no(since) if since is not None else -10**9
    best = None
    for ep in cluster_episodes(ds, as_of):
        if (ep["ward"], ep["organism"], ep["marker"]) == (ward, organism, marker) and _span(ep, as_of)[1] >= lo:
            best = ep
    if best is None:
        return None
    return {"rule": f"{marker}_same_unit", "text": "THL guidance: epidemic check (several findings above the usual level on one unit)",
            "first_alert_date": ph.iso(ph.day_date(best["first_alert_day"])),
            "last_alert_date": ph.iso(ph.day_date(best["last_alert_day"])),
            "first_sample_date": ph.iso(ph.day_date(best["first_sample_day"])), "max_patients_28d": best["max_n_28d"],
            "min_p": best["min_p"], "action": ACTION_TEXT[marker],
            "note": "Shown with the phenotype cluster instead of as a separate card."}


# ----------------------------------------------------------------------------------------------- detect
def _active_ids(ds, as_of) -> set:
    ids = {S.signal_id(KIND, _single_key(r, m)) for m, r, _, active in _single_items(ds, as_of) if active}
    ids |= {S.signal_id(KIND, _cluster_key(ep)) for ep in active_clusters(ds, as_of)}
    return ids


def detect(ds, as_of, rule="readme_period") -> list[dict]:
    ph.check_rule(rule)
    as_of = ph.ts(as_of)
    prev_ids = _active_ids(ds, as_of - pd.Timedelta(days=7))
    now, resolved = [], []
    for m, r, prev, active in _single_items(ds, as_of, include_recent=True):
        (now if active else resolved).append(_single_signal(m, r, prev, as_of, rule))
    for ep in active_clusters(ds, as_of, include_recent=True):
        (now if ep["active"] else resolved).append(_cluster_signal(ds, ep, as_of, rule))
    return ph.finish(now, prev_ids, resolved)
