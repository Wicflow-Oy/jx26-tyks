"""Templates for the trend detectors and the brief (workstream B2). Merged into `aei.templates.TEMPLATES`.

New ids only (prefix `trend_`); the base ids in templates.py are never redefined. These templates carry no literal
digits: window lengths and every count come through slots, so a test can check that each digit run in a rendered
text is a rendered slot value. Each template has a `title`: a short row title rendered from the same slots.
Wording: S/R results, no prediction language, "data gap, cause unknown".
A `_resolved` template is the item in the week after it stops: "Resolved. Last flagged week ending ..." with what was
last flagged and the value now.
"""

TEMPLATES = {
    "trend_resistance_change_resolved": {
        "text": (
            "{ward_label} · {finding}. Resolved. Last flagged week ending {last_flagged:date}: {counts_last:xofn} "
            "{organism_label}; now {counts:xofn} in the last {window_weeks:int} weeks."
        ),
        "title": "{ward}: more {subject} than usual, resolved",
    },
    "trend_policy_line": {
        "text": (
            "{drug_label}: {organism_label} in {population_label} is {rate:pct1} resistant ({counts:xofn}, last "
            "{window_weeks:int} weeks), {relation} the local {threshold:pct0} line since the week ending "
            "{crossed_on:date}. Same window a year earlier: {rate_prior:pct1} ({counts_prior:xofn})."
        ),
        "title": "{drug_label} {relation} the local {threshold:pct0} line",
    },
    "trend_policy_line_resolved": {
        "text": (
            "{drug_label}: {organism_label} in {population_label}. Resolved. Last flagged week ending "
            "{last_flagged:date}: {rate_last:pct1} resistant ({counts_last:xofn}); now {rate:pct1} ({counts:xofn}, "
            "last {window_weeks:int} weeks), below the local {threshold:pct0} line."
        ),
        "title": "{drug_label} back below the local {threshold:pct0} line",
    },
    "trend_ward_outlier_resolved": {
        "text": (
            "{ward_label}: resistance above the usual range. Resolved. Last flagged week ending {last_flagged:date}: "
            "{n_high_last:int} organism–drug pairs above their usual range; now {n_high:int} (last {window_weeks:int} "
            "weeks)."
        ),
        "title": "{ward}: several resistance results above the usual range, resolved",
    },
    "trend_expert_rule": {
        "text": "{rule_text}: {n_results:int} {results_word} {period_label} ({units_text}). Lab check.",
        "title": "Lab check: {rule_text}",
    },
    "trend_completeness_gap": {
        "text": "{ward_label}: no cultures this week (usually {expected:int} a week). Data gap, cause unknown.",
        "title": "{ward}: no cultures this week",
    },
    "trend_completeness_low": {
        "text": (
            "{ward_label}: {n_cultures:int} cultures this week (usually {expected:int} a week). Data gap, cause "
            "unknown."
        ),
        "title": "{ward}: fewer cultures than usual this week",
    },
    "trend_completeness_resolved": {
        "text": (
            "{ward_label}: data gap. Resolved. Last flagged week ending {last_flagged:date}: {n_last:int} cultures "
            "(usually {expected_last:int} a week), cause unknown; now {n_cultures:int} cultures this week."
        ),
        "title": "{ward}: data gap, resolved",
    },
    "trend_completeness_ok": {"text": "All {n_units:int} units sent data this week.", "title": "All units sent data"},
    "trend_quiet": {"text": "No signals on {quiet:xofn} units ({units_text}).", "title": "Quiet units"},
    "trend_quiet_none": {
        "text": "Every unit has at least one item this week ({n_units:int} units).",
        "title": "No quiet units",
    },
}

# Resistance change, one template per size of the two counts (stats.n_state): no percentage below 10 isolates, a
# "small n" tag below 30, as on My ward. `finding` is "Clindamycin resistant" or, for the cefoxitin screen,
# "MRSA (cefoxitin screen positive)"; `subject` is "S. aureus resistant to clindamycin" or "MRSA among S. aureus".
_NOW = {
    "not_enough_data": "{counts:xofn} {organism_label}",
    "low_n": "{counts:xofn} {organism_label} ({rate:pct0}, small n)",
    "ok": "{counts:xofn} {organism_label} ({rate:pct0})",
}
_BEFORE = {
    "not_enough_data": "{counts_prior:xofn}",
    "low_n": "{counts_prior:xofn} ({rate_prior:pct0}, small n)",
    "ok": "{counts_prior:xofn} ({rate_prior:pct0})",
}
for _w, _now in _NOW.items():
    for _p, _before in _BEFORE.items():
        TEMPLATES[f"trend_resistance_change__{_w}__{_p}"] = {
            "text": (
                "{ward_label} · {finding}: "
                + _now
                + " in the last {window_weeks:int} weeks vs "
                + _before
                + " in the {prior_weeks:int} weeks before. Changed; watch next week."
            ),
            "title": "{ward}: more {subject} than usual",
        }

# Ward outlier, one template per number of named pairs (at most the 20 pairs of resistance_change.PAIRS; a test
# checks the bound). Each pair is named with its count: "S. aureus clindamycin 13 of 20".
MAX_OUTLIER_PAIRS = 20
for _k in range(1, MAX_OUTLIER_PAIRS + 1):
    _pairs = "; ".join(f"{{pair{i}}} {{counts{i}:xofn}}" for i in range(1, _k + 1))
    TEMPLATES[f"trend_ward_outlier__{_k}"] = {
        "text": (
            "{ward_label}: resistance above the usual range in {high:xofn} organism–drug pairs in the last "
            "{window_weeks:int} weeks. Resistant of tested: " + _pairs + ". Other units: {other_high:xofn} pairs. "
            "Unusual pattern across several results."
        ),
        "title": "{ward}: several resistance results above the usual range",
    }
