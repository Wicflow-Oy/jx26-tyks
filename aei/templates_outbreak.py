"""Templates for the outbreak detectors: phenotype clusters, THL rule cards, count step-up, seen before.

Merged into aei.templates.TEMPLATES. Base ids there are never redefined; every id here starts with "ob_".
Numbers only through slots: no digit appears in any literal text or title below (a test checks this). Text slots carry
labels (ward codes, organism names, antibiograms) or a fixed guidance sentence (`action`), never numbers.
Each template has a `title`: a short row title rendered from the same slots.
Wording rules: "unusual pattern", "typing advised", "profile match, not typing"; never "decoy" or
"outbreak confirmed"; no prediction language.
A `_resolved` template is the item in the week after it stops: "Resolved. Last flagged week ending ..." and what
the detector last saw, never last week's present tense.
"""

from . import config as C

N_STATES = ("not_enough_data", "low_n", "ok")  # stats.n_state


def _pct(n_state: str, kind: str) -> str:
    """The percentage after a background x of n: none below 10, tagged "small n" below 30, as for resistance changes."""
    return {"not_enough_data": "", "low_n": f" ({{bg_share:{kind}}}, small n)", "ok": f" ({{bg_share:{kind}}})"}[
        n_state
    ]


TEMPLATES = {
    # THL guidance rule cards: every CPE / VRE case; `action` is thl.action_text for the case
    "ob_thl_single": {
        "text": (
            "{ward}: {marker_label} ({organism_label}, {specimen}) sampled {sample_date:short_date}, {onset_label}. "
            "Alert organism (THL guidance): every case. {action} {days_since_prev:int} days since the previous "
            "{marker_label} in the data."
        ),
        "title": "{ward}: {marker_label} case ({organism_label})",
    },
    "ob_thl_single_first": {
        "text": (
            "{ward}: {marker_label} ({organism_label}, {specimen}) sampled {sample_date:short_date}, {onset_label}. "
            "Alert organism (THL guidance): every case. {action} First {marker_label} in the data."
        ),
        "title": "{ward}: {marker_label} case ({organism_label})",
    },
    "ob_thl_single_resolved": {
        "text": (
            "{ward}: {marker_label} ({organism_label}, {specimen}) sampled {sample_date:date}. Resolved. Last flagged "
            "week ending {last_flagged:date}; a case card stays on the brief for {active_weeks:int} weeks after the "
            "sample."
        ),
        "title": "{ward}: {marker_label} case ({organism_label}), resolved",
    },
    # THL guidance same-unit cluster check (MRSA, ESBL): several findings above the unit's usual level
    "ob_thl_cluster_same": {
        "text": (
            "{ward}: {n_patients:int} {organism_label} patients since {first_date:short_date}; usually "
            "{usual_low:int}–{usual_high:int} in that time. {n_share:int} of {n_patients:int} share the same antibiogram "
            "({pattern}). THL guidance: epidemic check (several findings above the usual level on one unit). Typing "
            "advised."
        ),
        "title": "{ward}: possible cluster of {organism_label}",
    },
    "ob_thl_cluster_mixed": {
        "text": (
            "{ward}: {n_patients:int} {organism_label} patients since {first_date:short_date}; usually "
            "{usual_low:int}–{usual_high:int} in that time. Heterogeneous: {n_profiles:int} antibiograms, ranked lower "
            "by our rules (truth unknown). THL guidance: epidemic check (several findings above the usual level on one "
            "unit)."
        ),
        "title": "{ward}: more {organism_label} patients than usual",
    },
    "ob_thl_cluster_resolved": {
        "text": (
            "{ward}: {n_patients:int} {organism_label} patients since {first_date:short_date}. Resolved. Last flagged "
            "week ending {last_flagged:date}; last above the usual level {last_alert:short_date}."
        ),
        "title": "{ward}: {organism_label} patients above the usual level, resolved",
    },
    # Count step-up test on its own (no cluster covers it): supporting evidence, P3, never P1
    "ob_stepup": {
        "text": (
            "{ward}: {y4:int} new {marker_label} patients in the last {window_weeks:int} weeks; usually "
            "{usual_low:int}–{usual_high:int} (prior {baseline_weeks:int} weeks). Count step-up test positive, no "
            "shared antibiogram found. Supporting evidence only; check for a cluster."
        ),
        "title": "{ward}: more new {marker_label} patients than usual",
    },
    "ob_stepup_resolved": {
        "text": (
            "{ward}: {marker_label} count step-up test. Resolved. Last flagged week ending {last_flagged:date}; now "
            "{y4:int} new {marker_label} patients in the last {window_weeks:int} weeks, usually "
            "{usual_low:int}–{usual_high:int} (prior {baseline_weeks:int} weeks)."
        ),
        "title": "{ward}: more new {marker_label} patients than usual, resolved",
    },
    # Phenotype clusters that have stopped (no detection for more than two weeks)
    "ob_phenotype_marker_resolved": {
        "text": (
            "{ward}: unusual pattern of {organism_label} ({pattern}) since {first_date:short_date}. Resolved. Last "
            "flagged week ending {last_flagged:date}; last detected {last_alert:short_date}. {n_share:int} of "
            "{n_patients:int} {organism_label} patients share this antibiogram."
        ),
        "title": "{ward}: possible cluster of {organism_label}, resolved",
    },
    "ob_phenotype_plain_resolved": {
        "text": (
            "{ward}: unusual pattern of {organism_label} ({pattern}) since {first_date:short_date}. Resolved. Last "
            "flagged week ending {last_flagged:date}; last detected {last_alert:short_date}. {n_share:int} of "
            "{n_patients:int} patients with near-identical antibiograms share this one."
        ),
        "title": "{ward}: possible cluster of {organism_label}, resolved",
    },
    "ob_seen_before_resolved": {
        "text": (
            "{ward} {organism_label} pattern ({pattern}). Resolved. Last flagged week ending {last_flagged:date}; the "
            "{ward} cluster that began {cluster_first_date:date} was last detected {last_alert:short_date}."
        ),
        "title": "{ward}: {organism_label} antibiogram seen before, resolved",
    },
    "ob_seen_before_return_resolved": {
        "text": (
            "{ward} {organism_label} pattern ({pattern}) back on {ward}. Resolved. Last flagged week ending "
            "{last_flagged:date}; latest sample {return_date:date}, no new patient with this antibiogram on {ward} "
            "since."
        ),
        "title": "{ward}: {organism_label} antibiogram back on this unit, resolved",
    },
}

# Phenotype clusters, one template per size of the background population (stats.n_state).
# Marker population (MRSA, ESBL, VRE, CPE): n_patients = marker patients on the unit since the first sample; n_share =
# patients with the exact antibiogram. The expected range is a model (this antibiogram's hospital-wide share x the
# unit's patients with the organism), so the observed count sits beside it.
# Without a marker: n_patients = patients with a near-identical antibiogram (same panel, at most one drug different,
# sharing a resistance); the background is all isolates of the organism with the same tests.
_EXPECTED = (
    "Expected with this antibiogram at the hospital-wide rate: {expected_low:int}–{expected_high:int} patients a year "
    "on this unit (observed in the year before: {observed_year_before:int}). "
)
for _n in N_STATES:
    TEMPLATES[f"ob_phenotype_marker__{_n}"] = {
        "text": (
            "{ward}: unusual pattern. {organism_label} in {n_patients:int} patients since {first_date:short_date}; "
            "{n_share:int} of {n_patients:int} share the same antibiogram ({pattern}). "
            + _EXPECTED
            + "In the year before, {bg:xofn} {bg_label} patients hospital-wide had this antibiogram"
            + _pct(_n, "pct0")
            + ". Typing advised."
        ),
        "title": "{ward}: possible cluster of {organism_label}",
    }
    TEMPLATES[f"ob_phenotype_plain__{_n}"] = {
        "text": (
            "{ward}: unusual pattern. {organism_label} in {n_patients:int} patients since {first_date:short_date} with "
            "near-identical antibiograms; {n_share:int} of {n_patients:int} share the same exact antibiogram ({pattern}). "
            + _EXPECTED
            + "In the year before, {bg:xofn} {bg_label} isolates with the same tests hospital-wide had this "
            "antibiogram" + _pct(_n, "pct1") + ". Typing advised."
        ),
        "title": "{ward}: possible cluster of {organism_label}",
    }

# "Seen before". Every other unit is named with its count. The background share is labelled weak or rare evidence
# from 10 patients up; below that it is too few to judge.
_SAME = {
    "new": "not seen on {ward} before",
    "known": "earlier {ward} patients: {n_same_before:int}, last {last_same_date:date}",
}


def _elsewhere(k: int) -> str:
    if k == 0:
        return "no earlier patients elsewhere"
    units = ", ".join(f"{{w{i}}} {{n{i}:int}}" for i in range(1, k + 1))
    return "earlier patients elsewhere: {n_elsewhere:int} (" + units + ")"


def _background(lead: str) -> dict:
    """The background sentence by evidence key (seen_before.background): few, or weak/rare x low_n/ok."""
    had = lead + ", {bg:xofn} {bg_label} patients had this antibiogram"
    out = {"few": had + ": too few to say how common it is."}
    for n in ("low_n", "ok"):
        out[f"weak_{n}"] = had + _pct(n, "pct1") + ", so a match is weak evidence."
        out[f"rare_{n}"] = had + _pct(n, "pct1") + ", so it is uncommon."
    return out


def _seen_title(same: str, k: int) -> str:
    if same == "known":
        return "{ward}: {organism_label} antibiogram seen on this unit before"
    return (
        "{ward}: {organism_label} antibiogram seen before on other units"
        if k
        else "{ward}: {organism_label} antibiogram not seen before"
    )


# Cluster mode: same-unit history x number of other units x background. The background is the population before the
# cluster, so the cluster's own patients never make its antibiogram look common.
for _s, _st in _SAME.items():
    for _k in range(len(C.WARD_LABELS)):
        for _e, _bt in _background("Before this cluster").items():
            TEMPLATES[f"ob_seen_before__{_s}__{_k}__{_e}"] = {
                "text": (
                    "{ward} {organism_label} pattern ({pattern}): "
                    + _st
                    + "; "
                    + _elsewhere(_k)
                    + ". "
                    + _bt
                    + " Profile match, not typing."
                ),
                "title": _seen_title(_s, _k),
            }

# Return mode: a past cluster's antibiogram is back on the same unit
for _e, _bt in _background("To date").items():
    TEMPLATES[f"ob_seen_before_return__{_e}"] = {
        "text": (
            "{ward} {organism_label} pattern ({pattern}) is back on {ward}: latest sample {return_date:short_date}; patients "
            "since the cluster that began {cluster_first_date:date}: {n_return:int}. " + _bt + " Profile match, not "
            "typing; typing advised."
        ),
        "title": "{ward}: {organism_label} antibiogram back on this unit",
    }

# Competing explanations of a cluster (detectors/explanations.py): the title is the hypothesis, the text the counts
# behind its rating. Counts as x of n, no percentages; expected values and p-values in their own formats.
TEMPLATES.update(
    {
        "ob_ach_h1": {
            "text": (
                "patients: {n:int} observed vs {expected:dec2} expected ({p_count:p}); with the most common "
                "antibiogram: {identical:xofn}, vs {background:xofn} isolates in the year before ({p_identity:p}); "
                "hospital-onset: {hosp_onset:xofn}"
            ),
            "title": "Transmission on the unit",
        },
        "ob_ach_h2": {"text": "distinct antibiograms among the patients: {n_antibiograms:int}", "title": "Coincidence"},
        "ob_ach_h3": {
            "text": (
                "{early:xofn} sampled by care day {early_day:int}; the first patient sampled on care day "
                "{index_day:int}"
            ),
            "title": "Present on admission",
        },
        "ob_ach_h3_outpatient": {
            "text": "{early:xofn} sampled by care day {early_day:int}; the first patient an outpatient",
            "title": "Present on admission",
        },
        "ob_ach_h4": {
            "text": (
                "cultures on the unit in this period: {cultures:int}; on average {usual:dec1} in periods of the same "
                "length in the year before"
            ),
            "title": "Change in testing",
        },
        "ob_ach_h4_none": {
            "text": "cultures on the unit in this period: {cultures:int}; no earlier period to compare",
            "title": "Change in testing",
        },
        "ob_ach_h5__0": {"text": "no earlier year in the data covers these dates", "title": "Seasonal"},
        "ob_ach_h6_agree": {
            "text": "every patient's isolate flagged {marker} is {drug} R",
            "title": "Laboratory or data artefact",
        },
        "ob_ach_h6_disagree": {
            "text": "not every isolate flagged {marker} is {drug} R: check the laboratory data",
            "title": "Laboratory or data artefact",
        },
        "ob_ach_h6_none": {
            "text": "no resistance marker to compare with the antibiogram",
            "title": "Laboratory or data artefact",
        },
    }
)
# The same dates in each earlier year of the data (at most two: it starts in October 2023 and ends in 2026)
for _k in (1, 2):
    TEMPLATES[f"ob_ach_h5__{_k}"] = {
        "text": (
            "patients on the unit on the same dates "
            + "; ".join(f"in {{y{i}}}: {{n{i}:int}}" for i in range(1, _k + 1))
        ),
        "title": "Seasonal",
    }
