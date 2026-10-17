"""'Seen before': antibiogram fingerprint matching (port of analysis 52_seen_before_expert_rules). Profile match, not typing.

Cluster mode, for each phenotype cluster shown at as_of: earlier patients with the same organism and exact antibiogram,
before the cluster's first sample, on the same unit vs elsewhere (by unit), and the antibiogram's background share
among the population to date (the marker population, e.g. all MRSA patients, or the organism with the same test panel).
Return mode, for each past marker phenotype cluster (MRSA, ESBL, VRE, CPE) that has stopped: a new patient with the
same organism and exact antibiogram on the same unit. Shown for 28 days after the latest such sample.
A share of 2% or more is labelled weak evidence (the ICU MRSA antibiogram is about a fifth of all MRSA patients).
Section seen_before, priority info. Strictly as-of: only isolates sampled on or before as_of are used.
"""
from __future__ import annotations

import pandas as pd

from .. import signal as S
from . import phenotype as ph

KIND = "seen_before"
RETURN_ACTIVE_DAYS = 28
RETURN_RUN_GAP_DAYS = 28
WEAK_SHARE = 0.02
LABEL = "Profile match, not typing: an identical antibiogram is a cheap day-0 proxy; typing confirms or rules out a link."


def _patients_with(ds, as_of, organism, pattern) -> pd.DataFrame:
    x = ph.upto(ds.isolates, as_of)
    same = x[(x.organism == organism) & (x.profile == pattern)]
    return same.sort_values(["sample_date", "isolate_id"]).drop_duplicates("patient_id")


def background(ds, as_of, organism, pattern, marker) -> dict:
    """Share of patients to date whose first isolate in the population has this antibiogram (analysis 52)."""
    x = ph.upto(ds.isolates, as_of)
    x = x[x.organism == organism]
    if marker:
        pop = x[x[marker] == 1]
        label = ph.organism_label(organism, marker)
    else:
        pop = x[x.profile.map(ph.panel_of) == ph.panel_of(pattern)]
        label = ph.short_org(organism)
    pop = pop.sort_values(["sample_date", "isolate_id"]).drop_duplicates("patient_id")
    n = len(pop)
    k = int((pop.profile == pattern).sum())
    return {"bg_n": n, "bg_k": k, "bg_share": k / n if n else 0.0, "bg_label": label,
            "strength": "weak" if (n == 0 or k / n >= WEAK_SHARE) else "rare"}


def cluster_matches(ds, as_of, ward, organism, pattern, first_sample) -> dict:
    same = _patients_with(ds, as_of, organism, pattern)
    before = same[same.sample_date < ph.ts(first_sample)]
    here = before[before.ward_code == ward]
    other = before[before.ward_code != ward]
    by_ward = other.groupby("ward_code").size().reset_index(name="n").sort_values(["n", "ward_code"], ascending=[False, True])
    return {"n_same_ward_before": len(here), "same_ward_dates": [ph.iso(d) for d in here.sample_date],
            "n_elsewhere_before": len(other), "elsewhere_by_ward": {r.ward_code: int(r.n) for r in by_ward.itertuples()},
            "n_patients_with_pattern_to_date": len(same), "isolate_ids": before.isolate_id.tolist(),
            "last_same_ward_date": ph.iso(here.sample_date.max()) if len(here) else None}


def _cluster_signal(ds, ep, as_of, rule) -> dict:
    ward, org, prof, marker = ep["ward"], ep["organism"], ep["profile"], ep["marker"]
    first = ph.day_date(ep["first_sample_day"])
    mt = cluster_matches(ds, as_of, ward, org, prof, first)
    bg = background(ds, as_of, org, prof, marker)
    by = list(mt["elsewhere_by_ward"].items())
    k = min(len(by), 3)
    slots = {"ward": ward, "ward_label": ph.ward_label(ward), "organism_label": ph.organism_label(org, marker), "pattern": prof,
             "n_elsewhere": mt["n_elsewhere_before"], "bg_share": bg["bg_share"], "bg_n": bg["bg_n"], "bg_label": bg["bg_label"]}
    if mt["n_same_ward_before"]:
        slots.update({"n_same_before": mt["n_same_ward_before"], "last_same_date": mt["last_same_ward_date"]})
    for i, (w, n) in enumerate(by[:2], start=1):
        slots[f"w{i}"], slots[f"n{i}"] = w, n
    if k == 3:
        slots["n_other"] = sum(n for _, n in by[2:])
    tid = f"ob_seen_before__{'known' if mt['n_same_ward_before'] else 'new'}__{k}__{bg['strength']}"
    evidence = {
        "filter": {"ward": None, "specimen": None, "organism": org, "drug": None, "date_from": None,
                   "date_to": ph.iso(first - pd.Timedelta(days=1)), "rule": rule, "profile": prof, "isolate_ids_only": True},
        "counts": {**{k_: v for k_, v in mt.items() if k_ != "isolate_ids"}, **bg},
        "method": ("seen before (analysis 52): earlier patients (first isolate each) with the same organism and exact "
                   "antibiogram before the cluster's first sample, by unit; background share among the population to date"),
        "params": {"weak_share": WEAK_SHARE, "population": "marker" if marker else "organism with the same test panel"},
        "isolate_ids": mt["isolate_ids"],
        "cluster_id": S.signal_id(ph.KIND, ph.episode_key(ep)),
        "label": LABEL,
        "date_basis": ph.DATE_BASIS,
    }
    key = {"mode": "cluster", **ph.episode_key(ep)}
    return S.make_signal(KIND, key, priority="info", as_of=ph.iso(as_of), template_id=tid, slots=slots, evidence=evidence,
                         ward=ward, organism=org, first_sample_date=ph.iso(first), section="seen_before", advice=None)


def _returns(ds, as_of) -> list[dict]:
    """Return runs of past marker clusters' antibiograms on the same unit, known at as_of."""
    as_of = ph.ts(as_of)
    eps = ph.episodes(ds, as_of)
    out = []
    for ep in eps:
        if ph.day_no(as_of) - ep["last_alert_day"] <= ph.EPISODE_GAP_DAYS:
            continue  # still active: new cases belong to the cluster
        marker = ph.cluster_marker(ds, ep, as_of)
        if marker is None:
            continue
        end = ph.day_date(ep["last_alert_day"] + ph.EPISODE_GAP_DAYS)
        nxt = [e["first_sample_day"] for e in eps if (e["ward"], e["organism"], e["profile"]) == (ep["ward"], ep["organism"], ep["profile"])
               and e["first_sample_day"] > ep["last_alert_day"]]
        stop = ph.day_date(min(nxt)) - pd.Timedelta(days=1) if nxt else as_of
        x = ph.upto(ds.isolates, stop)
        r = x[(x.ward_code == ep["ward"]) & (x.organism == ep["organism"]) & (x.profile == ep["profile"]) & (x.sample_date > end)]
        r = r.sort_values(["sample_date", "isolate_id"]).drop_duplicates("patient_id")
        if r.empty:
            continue
        run_id = (r.sample_date.diff().dt.days.fillna(RETURN_RUN_GAP_DAYS + 1) > RETURN_RUN_GAP_DAYS).cumsum()
        last_run = r[run_id == run_id.max()]
        age = (as_of - last_run.sample_date.max()).days
        if age >= RETURN_ACTIVE_DAYS + ph.RESOLVED_LIST_DAYS:
            continue
        ep = dict(ep)
        ep["marker"] = marker
        out.append({"ep": ep, "rows": r, "run": last_run, "active": age < RETURN_ACTIVE_DAYS})
    return out


def _return_key(item) -> dict:
    return {"mode": "return", **ph.episode_key(item["ep"]), "first_return_date": ph.iso(item["run"].sample_date.min())}


def _return_signal(ds, item, as_of, rule) -> dict:
    ep, rows, run = item["ep"], item["rows"], item["run"]
    ward, org, prof, marker = ep["ward"], ep["organism"], ep["profile"], ep["marker"]
    first = ph.day_date(ep["first_sample_day"])
    bg = background(ds, as_of, org, prof, marker)
    cluster_pop = ph.population(ds, ward, org, marker, prof, first, ph.day_date(ep["last_alert_day"]))
    in_cluster = set(cluster_pop.patient_id)
    latest = run.iloc[-1]
    slots = {"ward": ward, "ward_label": ph.ward_label(ward), "organism_label": ph.organism_label(org, marker), "pattern": prof,
             "return_date": ph.iso(latest.sample_date), "cluster_first_date": ph.iso(first), "n_return": len(rows),
             "bg_share": bg["bg_share"], "bg_n": bg["bg_n"], "bg_label": bg["bg_label"]}
    ach = ph.competing_explanations(ds, ward, org, run.sample_date.min(), as_of, marker=marker)
    evidence = {
        "filter": {"ward": ward, "specimen": None, "organism": org, "drug": None, "date_from": ph.iso(run.sample_date.min()),
                   "date_to": ph.iso(as_of), "rule": rule, "profile": prof, "marker": marker, "isolate_ids_only": True},
        "counts": {"n_return_patients_since_cluster": len(rows), "n_in_current_run": len(run),
                   "return_dates": [ph.iso(d) for d in rows.sample_date],
                   "latest_care_day": None if pd.isna(latest.care_day_no) else int(latest.care_day_no),
                   "latest_hospital_onset": bool(latest.hosp_onset),
                   "returning_patient_was_in_cluster": [bool(p in in_cluster) for p in rows.patient_id],
                   "cluster_first_sample": ph.iso(first), "cluster_last_alert": ph.iso(ph.day_date(ep["last_alert_day"])),
                   "cluster_patients": int(cluster_pop.patient_id.nunique()), **bg},
        "method": ("seen before, return mode (analysis 52): a new patient with the exact antibiogram of a stopped marker "
                   "cluster on the same unit; shown for 28 days after the latest such sample"),
        "params": {"active_days": RETURN_ACTIVE_DAYS, "run_gap_days": RETURN_RUN_GAP_DAYS, "weak_share": WEAK_SHARE},
        "isolate_ids": rows.isolate_id.tolist(),
        "cluster_id": S.signal_id(ph.KIND, ph.episode_key(ep)),
        "competing_explanations": ach,
        "label": LABEL,
        "date_basis": ph.DATE_BASIS,
    }
    return S.make_signal(KIND, _return_key(item), priority="info", as_of=ph.iso(as_of),
                         template_id=f"ob_seen_before_return__{bg['strength']}", slots=slots, evidence=evidence, ward=ward,
                         organism=org, specimen=latest.specimen, first_sample_date=ph.iso(run.sample_date.min()),
                         section="seen_before", advice="Typing advised")


def matches(ds, signal) -> dict | None:
    """Seen-before matches for a phenotype cluster signal (for the case file)."""
    k = signal.get("key", {})
    if signal.get("kind") != ph.KIND or "profile" not in k:
        return None
    m = signal["evidence"]["filter"].get("marker")
    return {**cluster_matches(ds, signal["as_of"], k["ward"], k["organism"], k["profile"], k["first_sample_date"]),
            **background(ds, signal["as_of"], k["organism"], k["profile"], m), "label": LABEL}


def _active_ids(ds, as_of) -> set:
    ids = {S.signal_id(KIND, {"mode": "cluster", **ph.episode_key(ep)}) for ep in ph.active_clusters(ds, as_of)}
    ids |= {S.signal_id(KIND, _return_key(it)) for it in _returns(ds, as_of) if it["active"]}
    return ids


def detect(ds, as_of, rule="readme_period") -> list[dict]:
    ph.check_rule(rule)
    as_of = ph.ts(as_of)
    prev_ids = _active_ids(ds, as_of - pd.Timedelta(days=7))
    now, resolved = [], []
    for ep in ph.active_clusters(ds, as_of, include_recent=True):
        (now if ep["active"] else resolved).append(_cluster_signal(ds, ep, as_of, rule))
    for it in _returns(ds, as_of):
        (now if it["active"] else resolved).append(_return_signal(ds, it, as_of, rule))
    return ph.finish(now, prev_ids, resolved)
