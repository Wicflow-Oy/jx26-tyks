"""Templates for the outbreak detectors (workstream B1): phenotype clusters, THL rule cards, count step-up, seen before.

Merged into aei.templates.TEMPLATES. Base ids there are never redefined; every id here starts with "ob_".
Numbers only through slots: no digit appears in any literal text below (a test checks this). Text slots carry
labels (ward codes, organism names, antibiograms) or a fixed guidance sentence (`action`), never numbers.
Wording rules: "unusual pattern", "typing advised", "profile match, not typing"; never "decoy" or
"outbreak confirmed"; no prediction language.
"""
from . import config as C

TEMPLATES = {
    # Phenotype cluster on a marker population (MRSA, ESBL, VRE, CPE): n_patients = marker patients on the unit since
    # the first sample; n_share = patients with the exact antibiogram. The expected range is a model (this
    # antibiogram's hospital-wide share x the unit's patients with the organism), so the observed count sits beside it.
    "ob_phenotype_marker": {"text": "{ward}: unusual pattern. {organism_label} in {n_patients:int} patients since "
                                    "{first_date:short_date}; {n_share:int} of {n_patients:int} share one antibiogram ({pattern}). "
                                    "Expected with this antibiogram at the hospital-wide rate: {expected_low:int}–{expected_high:int} "
                                    "patients a year on this unit (observed in the year before: {observed_year_before:int}). "
                                    "This antibiogram was {bg_share:pct0} of {bg_label} patients hospital-wide in the year "
                                    "before. Typing advised."},
    # Phenotype cluster without a resistance marker: n_patients = patients with a near-identical antibiogram (same
    # panel, at most one drug different, sharing a resistance). Background share is among all isolates of the organism.
    "ob_phenotype_plain": {"text": "{ward}: unusual pattern. {organism_label} in {n_patients:int} patients since "
                                   "{first_date:short_date} with near-identical antibiograms; {n_share:int} of {n_patients:int} "
                                   "share one ({pattern}). Expected with this antibiogram at the hospital-wide rate: "
                                   "{expected_low:int}–{expected_high:int} patients a year on this unit (observed in the year "
                                   "before: {observed_year_before:int}). This antibiogram was {bg_share:pct1} of {bg_label} "
                                   "isolates with the same tests hospital-wide in the year before. Typing advised."},
    # THL guidance rule cards: every CPE / VRE case; `action` is thl.action_text for the case
    "ob_thl_single": {"text": "{ward}: {marker_label} ({organism_label}, {specimen}) sampled {sample_date:short_date}, {onset_label}. "
                              "Alert organism (THL guidance): every case. {action} "
                              "{days_since_prev:int} days since the previous {marker_label} in the data."},
    "ob_thl_single_first": {"text": "{ward}: {marker_label} ({organism_label}, {specimen}) sampled {sample_date:short_date}, "
                                    "{onset_label}. Alert organism (THL guidance): every case. {action} "
                                    "First {marker_label} in the data."},
    # THL guidance same-unit cluster check (MRSA, ESBL): several findings above the unit's usual level
    "ob_thl_cluster_same": {"text": "{ward}: {n_patients:int} {organism_label} patients since {first_date:short_date}; usually "
                                    "{usual_low:int}–{usual_high:int} in that time. {n_share:int} of {n_patients:int} share one "
                                    "antibiogram ({pattern}). THL guidance: epidemic check (several findings above the usual level "
                                    "on one unit). Typing advised."},
    "ob_thl_cluster_mixed": {"text": "{ward}: {n_patients:int} {organism_label} patients since {first_date:short_date}; usually "
                                     "{usual_low:int}–{usual_high:int} in that time. Heterogeneous: {n_profiles:int} antibiograms, "
                                     "ranked lower by our rules (truth unknown). THL guidance: epidemic check (several findings "
                                     "above the usual level on one unit)."},
    # Count step-up test on its own (no cluster covers it): supporting evidence, P3, never P1
    "ob_stepup": {"text": "{ward}: {y4:int} new {marker_label} patients in the last {window_weeks:int} weeks; usually "
                          "{usual_low:int}–{usual_high:int} (prior {baseline_weeks:int} weeks). Count step-up test positive, "
                          "no shared antibiogram found. Supporting evidence only; check for a cluster."},
    "ob_stepup_resolved": {"text": "{ward}: count step-up test no longer positive. {y4:int} new {marker_label} patients in "
                                   "the last {window_weeks:int} weeks; usually {usual_low:int}–{usual_high:int} (prior "
                                   "{baseline_weeks:int} weeks)."},
}

# "Seen before", cluster mode: generated variants (same-unit history x number of other units x evidence strength).
# Every other unit is named with its count. The background is the population before the cluster, so the cluster's own
# patients never make its antibiogram look common.
_SAME = {"new": "not seen on {ward} before",
         "known": "earlier {ward} patients: {n_same_before:int}, last {last_same_date:date}"}


def _elsewhere(k: int) -> str:
    if k == 0:
        return "no earlier patients elsewhere"
    units = ", ".join(f"{{w{i}}} {{n{i}:int}}" for i in range(1, k + 1))
    return "earlier patients elsewhere: {n_elsewhere:int} (" + units + ")"


_SHARE_BEFORE = {"weak": "Before this cluster this antibiogram was {bg_share:pct1} of {bg_n:int} {bg_label} patients, "
                         "so a match is weak evidence.",
                 "rare": "Before this cluster this antibiogram was {bg_share:pct1} of {bg_n:int} {bg_label} patients "
                         "(uncommon)."}
for _s, _st in _SAME.items():
    for _k in range(len(C.WARD_LABELS)):
        for _w, _wt in _SHARE_BEFORE.items():
            TEMPLATES[f"ob_seen_before__{_s}__{_k}__{_w}"] = {
                "text": "{ward} {organism_label} pattern ({pattern}): " + _st + "; " + _elsewhere(_k) + ". " + _wt
                        + " Profile match, not typing."}

# "Seen before", return mode: a past cluster's antibiogram is back on the same unit
_SHARE_TO_DATE = {"weak": "This antibiogram is {bg_share:pct1} of {bg_n:int} {bg_label} patients to date, so a match is "
                          "weak evidence.",
                  "rare": "This antibiogram is {bg_share:pct1} of {bg_n:int} {bg_label} patients to date (uncommon)."}
for _w, _wt in _SHARE_TO_DATE.items():
    TEMPLATES[f"ob_seen_before_return__{_w}"] = {
        "text": "{ward} {organism_label} pattern ({pattern}) is back on {ward}: latest sample {return_date:short_date}; patients "
                "since the cluster that began {cluster_first_date:date}: {n_return:int}. " + _wt + " Profile match, not typing; "
                "typing advised."}
