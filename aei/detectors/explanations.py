"""Competing explanations H1-H6 for a unit cluster, rated from counts only (port of analysis 19 and 41_replay_asof).

Cases: first isolate per patient of the marker (or, without a marker, a near-identical antibiogram of the organism) on
the unit from `start` to `as_of`. Backgrounds are the 365 days before `start`. As in 41, a marker's unit history and
hospital background pool every organism carrying that marker (e.g. ESBL E. coli and ESBL K. pneumoniae), which is
conservative; values.history_scope says so. Strictly as of `as_of`.

Each hypothesis keeps its rating as a code (`rating`: strong, moderate, weak, plausible, possible, unlikely, check,
"contributes (index imported?)") and its words as a template id and slots, like a brief item: `label` and `evidence`
are rendered in English here and re-rendered in Finnish by aei.i18n.localize_signal, together with `rating_label`.
"""

import numpy as np
import pandas as pd
from scipy import stats as st

from .. import config as C
from ..i18n import render_id
from . import iso, ts
from . import phenotype as ph

BACKGROUND_DAYS = 365
EARLY_CARE_DAY = 2  # a sample on care day 1 or 2 was most likely taken at admission
# The laboratory phenotype every isolate carrying a marker should show; a case without it points to a data problem
MARKER_CHECK = {"mrsa": "FOX", "esbl": "CRO", "cpe": "MEM", "vre": "VAN"}
NOTE = "Competing explanations rated from counts only (analysis 19/41). Phenotype is not genotype; typing advised."


def competing_explanations(
    ds, ward: str, organism: str, start, as_of, marker: str | None = None, pattern: str | None = None
) -> dict:
    x = ph.upto(ds.isolates, as_of)
    s, e = ts(start), ts(as_of)
    pre0, pre1 = s - pd.Timedelta(days=BACKGROUND_DAYS), s - pd.Timedelta(days=1)
    if marker:
        pop = x[x[marker] == 1]
        cases = pop[(pop.ward_code == ward) & (pop.organism == organism)]
        ward_hist = pop[pop.ward_code == ward]
        bg_all = ph.between(pop, pre0, pre1)
    else:
        org = x[x.organism == organism]
        org = org[org.profile.map(ph.panel_of) == ph.panel_of(pattern)]
        cases = org[(org.ward_code == ward) & ph.near_mask(org.profile, pattern)]
        ward_hist = cases
        bg_all = ph.between(org, pre0, pre1)
    cases = ph.between(cases, s, e).sort_values(["sample_date", "isolate_id"]).drop_duplicates("patient_id")
    n = len(cases)
    if n == 0:
        return {"patients": 0, "identical": 0, "hypotheses": []}
    days = (e - s).days + 1
    hist = ph.between(ward_hist, pre0, pre1).drop_duplicates("patient_id")
    exp = len(hist) / BACKGROUND_DAYS * days
    p = float(st.poisson.sf(n - 1, max(exp, 0.05)))
    top = cases.profile.value_counts()
    n_top = int(top.iloc[0])
    ident = n_top / n
    bg_k = int((bg_all.profile == top.index[0]).sum())
    bgshare = bg_k / len(bg_all) if len(bg_all) else 0.0
    p_ident = float(st.binom.sf(n_top - 1, n, max(bgshare, 0.01)))
    n_hosp_onset = int(cases.hosp_onset.sum())
    n_early = int((cases.care_day_no <= EARLY_CARE_DAY).sum())
    cul = ds.cultures[(ds.cultures.ward_code == ward) & (ds.cultures.sample_date <= e)]
    vol = int(((cul.sample_date >= s) & (cul.sample_date <= e)).sum())
    prev = [
        int(((cul.sample_date >= s - pd.Timedelta(days=k)) & (cul.sample_date <= e - pd.Timedelta(days=k))).sum())
        for k in range(days, BACKGROUND_DAYS, days)
    ]
    vol_ratio = vol / np.mean(prev) if prev and np.mean(prev) > 0 else None
    years = list(range(pd.Timestamp(C.DATA_START).year + 1, s.year))  # earlier years only (the data starts in October)
    offsets = [pd.DateOffset(years=s.year - y) for y in years]
    other = [int(ph.between(ward_hist, s - off, e - off).patient_id.nunique()) for off in offsets]
    drug = MARKER_CHECK.get(marker)
    consistent = bool((cases[drug] == "R").all()) if drug else True
    idx_day = None if pd.isna(cases.iloc[0].care_day_no) else int(cases.iloc[0].care_day_no)

    ratings = {
        "H1": (
            "strong"
            if (ident >= 0.75 and p < 1e-4 and p_ident < 1e-3)
            else "moderate"
            if (p < 1e-3 and ident >= 0.5)
            else "weak"
        ),
        "H2": "unlikely" if p < 1e-4 and ident >= 0.75 else "plausible" if (p > 1e-3 or ident < 0.5) else "possible",
        "H3": "contributes (index imported?)" if n_early / n >= 0.2 else "unlikely",
        "H4": "unlikely" if (vol_ratio is not None and vol_ratio < 1.25) else "possible",
        "H5": "unlikely" if (not other or max(other) <= max(1, n // 4)) else "possible",
        "H6": "unlikely" if consistent else "check",
    }
    words = {  # hypothesis -> (template id, slots)
        "H1": (
            "ob_ach_h1",
            {
                "n": n,
                "expected": exp,
                "p_count": p,
                "identical": [n_top, n],
                "background": [bg_k, len(bg_all)],
                "p_identity": p_ident,
                "hosp_onset": [n_hosp_onset, n],
            },
        ),
        "H2": ("ob_ach_h2", {"n_antibiograms": len(top)}),
        "H3": (
            ("ob_ach_h3_outpatient", {"early": [n_early, n], "early_day": EARLY_CARE_DAY})
            if idx_day is None
            else ("ob_ach_h3", {"early": [n_early, n], "early_day": EARLY_CARE_DAY, "index_day": idx_day})
        ),
        "H4": (
            ("ob_ach_h4", {"cultures": vol, "usual": float(np.mean(prev))})
            if prev
            else ("ob_ach_h4_none", {"cultures": vol})
        ),
        "H5": (
            f"ob_ach_h5__{len(years)}",
            {**{f"y{i}": str(y) for i, y in enumerate(years, 1)}, **{f"n{i}": k for i, k in enumerate(other, 1)}},
        ),
        "H6": (
            ("ob_ach_h6_none", {})
            if drug is None
            else (
                f"ob_ach_h6_{'agree' if consistent else 'disagree'}",
                {"marker": ph.MARKER_LABELS[marker], "drug": C.DRUG_NAMES[drug].lower()},
            )
        ),
    }
    hypotheses = []
    for hid, (template_id, slots) in words.items():
        hypotheses.append(
            {
                "id": hid,
                "label": render_id(template_id, slots, field="title"),
                "rating": ratings[hid],
                "rating_label": ratings[hid],
                "evidence": render_id(template_id, slots),
                "template_id": template_id,
                "slots": slots,
            }
        )
    return {
        "patients": n,
        "identical": n_top,
        "n_antibiograms": len(top),
        "start": iso(s),
        "as_of": iso(e),
        "values": {
            "expected": round(exp, 3),
            "p_count": p,
            "identical_share": round(ident, 3),
            "background_share": round(bgshare, 4),
            "p_identity": p_ident,
            "hospital_onset_share": round(n_hosp_onset / n, 3),
            "care_day_1_2_share": round(n_early / n, 3),
            "index_care_day": idx_day,
            "culture_volume_ratio": None if vol_ratio is None else round(float(vol_ratio), 3),
            "same_window_earlier_years": other,
            "marker_consistent": consistent,
            "history_scope": (
                f"all organisms with {ph.MARKER_LABELS[marker]} on the unit (as analysis 41)"
                if marker
                else "the organism with a near-identical antibiogram on the unit"
            ),
        },
        "hypotheses": hypotheses,
        "note": NOTE,
    }
