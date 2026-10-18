"""Phenotype-cluster detector: patients sharing one antibiogram on one unit (port of analysis 09_leadtime, the spec detector).

Daily, from day 182 (26-week learning period). On each day with a new isolate of a (unit, organism, antibiogram):
  npat  = distinct patients with that exact antibiogram on the unit in the last 28 days (>= 3 needed);
  f     = share of that antibiogram among all isolates of the organism with the same test panel, hospital-wide, in the
          364 days before the window (rarity gate: f < 15%; floored at 0.5 / n so a never-seen pattern is testable);
  n_org = distinct patients with the organism and panel on the unit in the window;
  alert when binom.sf(npat - 1, n_org, f) < 1e-4.
Alerts on the same unit x organism x antibiogram less than 15 days apart form one episode. An episode is active while
its last alert is at most 14 days old, and is listed as resolved for one more week.

Strictly as-of: an alert on day d uses only isolates sampled on or before d, so the alert table computed once over the
data is a prefix-stable list; at `as_of` only alerts with day <= as_of are used, and every count is cut at as_of.

This module also holds the helpers the other outbreak detectors (thl, stepup, seen_before) share.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st

from .. import config as C
from .. import signal as S
from .. import stats
from ..i18n import short_organism
from . import iso, ts, ward_label

KIND = "phenotype_cluster"
WINDOW_DAYS = 28
HISTORY_DAYS = 364
LEARN_DAYS = 182
MIN_PATIENTS = 3
RARITY_MAX_SHARE = 0.15
ALPHA = 1e-4
EPISODE_GAP_DAYS = 14
RESOLVED_LIST_DAYS = 7
MARKERS = ("cpe", "vre", "mrsa", "esbl")  # checked in this order when a cluster's isolates carry a flag
MARKER_LABELS = {"cpe": "CPE", "vre": "VRE", "mrsa": "MRSA", "esbl": "ESBL"}
CLASS_WEIGHT = {"cpe": 5, "vre": 5, "mrsa": 4, "esbl": 3, None: 1}  # ACH prioritiser (dossier 9.1)
SPECIMEN_WEIGHT = {"blood": 1.5, "wound": 1.2, "urine": 1.0}
H1_WEIGHT = {"strong": 3, "moderate": 2, "weak": 1}
DATE_BASIS = f"sample dates; results usually arrive about {C.RESULT_LAG_DAYS} days later (the data has no result time)"

_START = pd.Timestamp(C.DATA_START)
_CACHE: dict = {}


# ----------------------------------------------------------------------------------------------- shared helpers
RULES = ("readme_period", "30d")


def check_rule(rule: str) -> None:
    """B1 detectors count distinct patients (as the analysis does), so the isolate counting rule is not applied; it is
    validated and echoed in evidence.filter so the brief and the case file stay consistent."""
    if rule not in RULES:
        raise ValueError(f"unknown counting rule {rule}")


def day_no(date) -> int:
    return int((ts(date) - _START).days)


def day_date(day: int) -> pd.Timestamp:
    return _START + pd.Timedelta(days=int(day))


def organism_label(org: str, marker: str | None) -> str:
    if marker == "mrsa":
        return "MRSA"
    if marker == "vre":
        return "VRE " + short_organism(org)
    if marker in ("esbl", "cpe"):
        return f"{MARKER_LABELS[marker]} {short_organism(org)}"
    return short_organism(org)


def panel_of(profile: str) -> str:
    return " ".join(tok.split(":")[0] for tok in str(profile).split())


def parse_profile(profile: str) -> dict:
    return dict(tok.split(":") for tok in str(profile).split())


def near_mask(profiles: pd.Series, pattern: str) -> pd.Series:
    """Near-identical antibiograms: same test panel, at most one drug different, and at least one shared R."""
    p = parse_profile(pattern)
    r_set = {k for k, v in p.items() if v == "R"}
    cache: dict = {}

    def ok(q: str) -> bool:
        if q not in cache:
            d = parse_profile(q)
            cache[q] = d.keys() == p.keys() and sum(d[k] != p[k] for k in p) <= 1 and any(d[k] == "R" for k in r_set)
        return cache[q]

    return profiles.map(ok).astype(bool)


def marker_of(rows: pd.DataFrame) -> str | None:
    """Resistance marker carried by most of these isolates (cpe > vre > mrsa > esbl), else None."""
    for m in MARKERS:
        if len(rows) and rows[m].mean() >= 0.5:
            return m
    return None


def upto(df: pd.DataFrame, as_of) -> pd.DataFrame:
    return df[df.sample_date <= ts(as_of)]


def between(df: pd.DataFrame, lo, hi) -> pd.DataFrame:
    return df[(df.sample_date >= ts(lo)) & (df.sample_date <= ts(hi))]


def poisson_range(mu: float) -> tuple[int, int]:
    """Usual range of a count with mean mu: Poisson 2.5-97.5% quantiles; the upper end is at least 1."""
    mu = max(float(mu), 1e-9)
    return int(st.poisson.ppf(0.025, mu)), max(1, int(st.poisson.ppf(0.975, mu)))


def cached(ds, name: str, fn):
    """Per-dataset memo (in process). Keyed on the isolate table object plus its size and last row, so a truncated
    copy of the data (as the as-of tests use) is always computed fresh."""
    df = ds.isolates
    key = (
        name,
        id(df),
        len(df),
        str(df.sample_date.max()) if len(df) else "",
        df.isolate_id.iloc[-1] if len(df) else "",
    )
    hit = _CACHE.get(key)
    if hit is not None and hit[0] is df:
        return hit[1]
    val = fn(ds)
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[key] = (df, val)
    return val


def finish(now: list, prev_ids: set, resolved: list) -> list:
    """Status per CONTRACTS section 3: new / ongoing (active at as_of - 7) / resolved (listed one week after it stops)."""
    out = []
    for sig in now:
        sig["status"] = "ongoing" if sig["id"] in prev_ids else "new"
        out.append(sig)
    for sig in resolved:
        if sig["id"] in prev_ids:
            sig["status"] = "resolved"
            out.append(sig)
    return out


def rank(marker, specimens, h1_rating) -> dict:
    """ACH prioritiser score (dossier 9.1): class weight x H1 rating x specimen weight. Larger ranks higher."""
    sw = max([SPECIMEN_WEIGHT.get(s, 1.0) for s in specimens] or [1.0])
    cw, hw = CLASS_WEIGHT.get(marker, 1), H1_WEIGHT.get(h1_rating, 1)
    return {"class_weight": cw, "h1": h1_rating, "specimen_weight": sw, "score": round(cw * hw * sw, 2)}


# ----------------------------------------------------------------------------------------------- the daily core
def _daily_alerts(ds) -> pd.DataFrame:
    x = ds.isolates
    cols = ["day", "ward", "organism", "profile", "npat", "n_org", "f", "f_used", "p", "first_day", "n_hist_panel"]
    if x.empty:
        return pd.DataFrame(columns=cols)
    day = (x.sample_date - _START).dt.days.to_numpy()
    panel = x.profile.map(panel_of)
    op = pd.factorize(x.organism + "|" + panel)[0]
    opp = pd.factorize(x.organism + "|" + x.profile)[0]
    wop = pd.factorize(x.ward_code + "|" + x.organism + "|" + panel)[0]
    wopp = pd.factorize(x.ward_code + "|" + x.organism + "|" + x.profile)[0]
    pat = pd.factorize(x.patient_id)[0]
    nd = int(day.max()) + 1

    def cum(codes):
        m = np.zeros((codes.max() + 1, nd + 1), dtype=np.int32)
        np.add.at(m, (codes, day + 1), 1)
        return np.cumsum(m, axis=1)  # m[c, k + 1] = isolates of code c sampled on day <= k

    cop, copp = cum(op), cum(opp)

    def count(m, c, a, b):  # isolates with a < day <= b
        a, b = min(max(a, -1), nd - 1), min(max(b, -1), nd - 1)
        return int(m[c, b + 1] - m[c, a + 1])

    def slices(codes):
        o = np.lexsort((day, codes))
        sc = codes[o]
        rng = np.arange(codes.max() + 1)
        return o, np.searchsorted(sc, rng, "left"), np.searchsorted(sc, rng, "right"), day[o]

    o3, s3, e3, d3 = slices(wopp)
    o2, s2, e2, d2 = slices(wop)
    to_opp, to_op, to_wop = (np.zeros(wopp.max() + 1, int) for _ in range(3))
    to_opp[wopp], to_op[wopp], to_wop[wopp] = opp, op, wop
    order = np.argsort(day, kind="stable")
    days_sorted = day[order]
    ward, org, prof = x.ward_code.to_numpy(), x.organism.to_numpy(), x.profile.to_numpy()
    out = []
    for d in range(LEARN_DAYS, nd):
        lo_t, hi_t = np.searchsorted(days_sorted, d, "left"), np.searchsorted(days_sorted, d, "right")
        if lo_t == hi_t:
            continue
        for c in np.unique(wopp[order[lo_t:hi_t]]):
            a, b = s3[c], e3[c]
            lo = a + np.searchsorted(d3[a:b], d - WINDOW_DAYS, "right")
            hi = a + np.searchsorted(d3[a:b], d, "right")
            if hi - lo < MIN_PATIENTS:
                continue
            rows = o3[lo:hi]
            npat = len(np.unique(pat[rows]))
            if npat < MIN_PATIENTS:
                continue
            h_op = count(cop, to_op[c], d - WINDOW_DAYS - HISTORY_DAYS, d - WINDOW_DAYS)
            h_opp = count(copp, to_opp[c], d - WINDOW_DAYS - HISTORY_DAYS, d - WINDOW_DAYS)
            f = h_opp / h_op if h_op > 0 else 0.0
            if f >= RARITY_MAX_SHARE:
                continue
            w = to_wop[c]
            a2, b2 = s2[w], e2[w]
            lo2 = a2 + np.searchsorted(d2[a2:b2], d - WINDOW_DAYS, "right")
            hi2 = a2 + np.searchsorted(d2[a2:b2], d, "right")
            n_org = len(np.unique(pat[o2[lo2:hi2]]))
            fu = max(f, 0.5 / max(h_op, 1))
            p = float(st.binom.sf(npat - 1, n_org, fu))
            if p < ALPHA:
                r0 = rows[0]
                out.append((d, ward[r0], org[r0], prof[r0], npat, n_org, f, fu, p, int(day[rows].min()), h_op))
    return pd.DataFrame(out, columns=cols)


def _episodes_full(ds) -> list[dict]:
    """Episodes over the whole alert table; truncated per as_of in episodes() (prefix-stable)."""
    al = cached(ds, "phenotype_alerts", _daily_alerts)
    eps = []
    for (ward, org, prof), g in al.groupby(["ward", "organism", "profile"], sort=True):
        g = g.sort_values("day")
        brk = (g.day.diff().fillna(EPISODE_GAP_DAYS + 1) > EPISODE_GAP_DAYS).cumsum()
        for _, e in g.groupby(brk):
            eps.append({"ward": ward, "organism": org, "profile": prof, "alerts": e.reset_index(drop=True)})
    return eps


def episodes(ds, as_of) -> list[dict]:
    """Phenotype-cluster episodes known at `as_of` (alerts on or before as_of only)."""
    d = day_no(as_of)
    out = []
    for ep in cached(ds, "phenotype_episodes", _episodes_full):
        a = ep["alerts"][ep["alerts"].day <= d]
        if a.empty:
            continue
        first = a.iloc[0]
        out.append(
            {
                "ward": ep["ward"],
                "organism": ep["organism"],
                "profile": ep["profile"],
                "first_alert_day": int(first.day),
                "last_alert_day": int(a.day.max()),
                "first_sample_day": int(first.first_day),
                "n_alerts": len(a),
                "npat_first_alert": int(first.npat),
                "max_npat_28d": int(a.npat.max()),
                "min_p": float(a.p.min()),
                "first_alert": first.to_dict(),
                "last_alert": a.iloc[-1].to_dict(),
            }
        )
    return out


def _is_active(ep, as_of) -> bool:
    return day_no(as_of) - ep["last_alert_day"] <= EPISODE_GAP_DAYS


def episode_key(ep) -> dict:
    return {
        "ward": ep["ward"],
        "organism": ep["organism"],
        "profile": ep["profile"],
        "first_sample_date": iso(day_date(ep["first_sample_day"])),
    }


def active_clusters(ds, as_of, include_recent: bool = False) -> list[dict]:
    """Episodes active at as_of (last alert <= 14 days old); with include_recent also those that stopped within 7 days."""
    lim = EPISODE_GAP_DAYS + (RESOLVED_LIST_DAYS if include_recent else 0)
    out = []
    for ep in episodes(ds, as_of):
        if day_no(as_of) - ep["last_alert_day"] <= lim:
            ep = dict(ep)
            ep["active"] = _is_active(ep, as_of)
            ep["marker"] = cluster_marker(ds, ep, as_of)
            out.append(ep)
    return out


def cluster_marker(ds, ep, as_of) -> str | None:
    x = upto(ds.isolates, as_of)
    rows = x[
        (x.ward_code == ep["ward"])
        & (x.organism == ep["organism"])
        & (x.profile == ep["profile"])
        & (x.sample_date >= day_date(ep["first_sample_day"]))
    ]
    return marker_of(rows)


def population(ds, ward, organism, marker, pattern, date_from, date_to, with_lead_in_days: int = 0) -> pd.DataFrame:
    """Cluster population rows: the unit's isolates of the organism carrying the marker (or, without a marker, a
    near-identical antibiogram), sampled date_from..date_to inclusive. Never later than date_to."""
    x = ds.isolates
    x = x[x.ward_code == ward]
    if organism:
        x = x[x.organism == organism]
    x = between(x, ts(date_from) - pd.Timedelta(days=with_lead_in_days), date_to)
    if marker:
        return x[x[marker] == 1]
    return x[near_mask(x.profile, pattern)] if pattern else x


def _summary(ds, ep, as_of) -> dict:
    x = upto(ds.isolates, as_of)
    ward, org, prof = ep["ward"], ep["organism"], ep["profile"]
    first = day_date(ep["first_sample_day"])
    marker = ep["marker"]
    pop = population(ds, ward, org, marker, prof, first, as_of)
    pats = pop.sort_values(["sample_date", "isolate_id"]).drop_duplicates("patient_id")
    n_patients = len(pats)
    n_share = int(pop[pop.profile == prof].patient_id.nunique())
    # background: the 52 weeks before the first sample (excludes the cluster itself)
    h0, h1 = first - pd.Timedelta(days=HISTORY_DAYS), first - pd.Timedelta(days=1)
    hist = between(x, h0, h1)
    panel = panel_of(prof)
    org_panel = hist[(hist.organism == org) & (hist.profile.map(panel_of) == panel)]
    f_org = float((org_panel.profile == prof).mean()) if len(org_panel) else 0.0
    f_used = max(f_org, 0.5 / max(len(org_panel), 1))
    ward_year = org_panel[org_panel.ward_code == ward]
    n_ward_year = int(ward_year.patient_id.nunique())
    observed = int(ward_year[ward_year.profile == prof].patient_id.nunique())
    mu = f_used * n_ward_year
    lo, hi = poisson_range(mu)
    if marker:  # patients carrying the marker, and those of them with this antibiogram
        mk = hist[(hist[marker] == 1) & (hist.organism == org)]
        bg_k, bg_n = int(mk[mk.profile == prof].patient_id.nunique()), int(mk.patient_id.nunique())
        bg_label = organism_label(org, marker)
    else:  # isolates of the organism with the same tests (the detector's own background)
        bg_k, bg_n, bg_label = int((org_panel.profile == prof).sum()), len(org_panel), short_organism(org)
    return {
        "marker": marker,
        "first": first,
        "pop": pop,
        "n_patients": n_patients,
        "n_share": n_share,
        "f_org": f_org,
        "f_used": f_used,
        "n_ward_year": n_ward_year,
        "observed_year_before": observed,
        "expected_per_year": mu,
        "expected_low": lo,
        "expected_high": hi,
        "bg_k": bg_k,
        "bg_n": bg_n,
        "bg_share": bg_k / bg_n if bg_n else 0.0,
        "bg_label": bg_label,
        "specimens": sorted(pop.specimen.unique().tolist()),
    }


def last_flagged(as_of) -> str:
    """The week a resolved item was last shown as active: the brief one week before."""
    return iso(ts(as_of) - pd.Timedelta(days=RESOLVED_LIST_DAYS))


def build_signal(ds, ep, as_of, rule="readme_period") -> dict:
    """The cluster card; an episode that has stopped (`ep["active"]` False) gets the resolved text and no advice."""
    sm = _summary(ds, ep, as_of)
    ward, org, prof, marker = ep["ward"], ep["organism"], ep["profile"], sm["marker"]
    first = sm["first"]
    resolved = not ep["active"]
    slots = {
        "ward": ward,
        "ward_label": ward_label(ward),
        "organism_label": organism_label(org, marker),
        "n_patients": sm["n_patients"],
        "n_share": sm["n_share"],
        "pattern": prof,
        "first_date": iso(first),
        "expected_low": sm["expected_low"],
        "expected_high": sm["expected_high"],
        "observed_year_before": sm["observed_year_before"],
        "bg": [sm["bg_k"], sm["bg_n"]],
        "bg_share": sm["bg_share"],
        "bg_label": sm["bg_label"],
    }
    template_id = f"ob_phenotype_{'marker' if marker else 'plain'}"
    if resolved:
        slots.update(last_flagged=last_flagged(as_of), last_alert=iso(day_date(ep["last_alert_day"])))
        template_id += "_resolved"
    else:
        template_id += f"__{stats.n_state(sm['bg_n'])}"
    from . import explanations, stepup, thl  # late import: these modules import this one

    ach = explanations.competing_explanations(ds, ward, org, first, as_of, marker=marker, pattern=prof)
    h1 = next((h["rating"] for h in ach["hypotheses"] if h["id"] == "H1"), "weak")
    first_alert = day_date(ep["first_alert_day"])
    evidence = {
        "filter": {
            "ward": ward,
            "specimen": None,
            "organism": org,
            "drug": None,
            "date_from": iso(first),
            "date_to": iso(as_of),
            "rule": rule,
            "profile": prof,
            "marker": marker,
            "population": "marker" if marker else "near_identical",
        },
        "counts": {
            "n_patients": sm["n_patients"],
            "n_share": sm["n_share"],
            "n_isolates": len(sm["pop"]),
            "specimens": sm["specimens"],
            "patients_28d_at_first_alert": ep["npat_first_alert"],
            "max_patients_28d": ep["max_npat_28d"],
            "first_alert_date": iso(first_alert),
            "last_alert_date": iso(day_date(ep["last_alert_day"])),
            "n_alert_days": ep["n_alerts"],
            "lead_time_days_from_first_sample": int((first_alert - first).days),
            "min_p": ep["min_p"],
            "share_in_organism_panel_year_before": sm["f_org"],
            "share_used_in_test": sm["f_used"],
            "unit_patients_with_organism_panel_year_before": sm["n_ward_year"],
            "expected_per_year": round(sm["expected_per_year"], 3),
            "unit_patients_with_antibiogram_year_before": sm["observed_year_before"],
            "background_k": sm["bg_k"],
            "background_n": sm["bg_n"],
            "background_share": sm["bg_share"],
        },
        "method": (
            "phenotype cluster (spec detector, analysis 09_leadtime): daily, panel-aware, 26-week learning, rarity "
            "gate < 15% of the organism and panel in the prior 52 weeks, binomial p < 1e-4 on distinct patients in 28 "
            "days; episodes join alerts less than 15 days apart"
        ),
        "params": {
            "window_days": WINDOW_DAYS,
            "history_days": HISTORY_DAYS,
            "learning_days": LEARN_DAYS,
            "min_patients": MIN_PATIENTS,
            "rarity_max_share": RARITY_MAX_SHARE,
            "alpha": ALPHA,
            "episode_gap_days": EPISODE_GAP_DAYS,
            "share_floor": "0.5 / isolates of organism and panel",
            "expected_range": "Poisson 2.5-97.5% of share x unit patients a year (upper end at least 1)",
        },
        "isolate_ids": sm["pop"].isolate_id.tolist(),
        "competing_explanations": ach,
        "rank": rank(marker, sm["specimens"], h1),
        "date_basis": DATE_BASIS,
        "label": (
            "Phenotype cluster: the patients share an antibiogram; only typing shows whether they share a strain. "
            "Profile match, not typing."
        ),
    }
    if marker in ("mrsa", "esbl"):
        evidence["stepup"] = stepup.evidence_for(ds, as_of, ward, marker)
    thl_cover = thl.cover_for(ds, as_of, ward, org, marker, since=first)
    if thl_cover:
        evidence["thl_rule"] = thl_cover
    return S.make_signal(
        KIND,
        episode_key(ep),
        priority="P1" if marker else "P2",
        as_of=iso(as_of),
        template_id=template_id,
        slots=slots,
        evidence=evidence,
        ward=ward,
        organism=org,
        specimen=sm["specimens"][0] if len(sm["specimens"]) == 1 else None,
        first_sample_date=iso(first),
        section="unusual_patterns",
        advice=None if resolved else "Typing advised",
    )


def detect(ds, as_of, rule="readme_period") -> list[dict]:
    """Phenotype-cluster signals at `as_of`. Marker clusters (MRSA, ESBL, VRE, CPE) are P1; clusters without a
    resistance marker are P2 (the analysis ranked its two such episodes low; dossier 9.1 class weights)."""
    check_rule(rule)
    as_of = ts(as_of)
    prev_ids = {S.signal_id(KIND, episode_key(ep)) for ep in active_clusters(ds, as_of - pd.Timedelta(days=7))}
    now, resolved = [], []
    for ep in active_clusters(ds, as_of, include_recent=True):
        sig = build_signal(ds, ep, as_of, rule)
        (now if ep["active"] else resolved).append(sig)
    return finish(now, prev_ids, resolved)
