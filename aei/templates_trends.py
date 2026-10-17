"""Templates for the trend detectors and the brief (workstream B2). Merged into `aei.templates.TEMPLATES`.

New ids only (prefix `trend_`); the base ids in templates.py are never redefined. These templates carry no literal
digits: window lengths and every count come through slots, so a test can check that each digit run in a rendered
text is a rendered slot value. Wording: S/R results, no prediction language, "data gap, cause unknown".
"""
TEMPLATES = {
    "trend_resistance_change": {
        "text": "{ward_label} · {organism_label} · {drug_label}: {counts:xofn} resistant ({rate:pct0}, last {window_weeks:int} "
                "weeks) vs {rate_prior:pct0} ({counts_prior:xofn}) in the {prior_weeks:int} weeks before. Changed; watch next week."},
    "trend_policy_line": {
        "text": "{drug_label}: {organism_label} in {population_label} is {rate:pct1} resistant ({counts:xofn}, last "
                "{window_weeks:int} weeks), {relation} the local {threshold:pct0} line since the week ending {crossed_on:date}. "
                "Same window a year earlier: {rate_prior:pct1} ({counts_prior:xofn}). Local guide alternative: {alternative}."},
    "trend_ward_outlier": {
        "text": "{ward_label}: {high:xofn} organism–drug resistance rates above their usual range in the last {window_weeks:int} "
                "weeks ({cells_text}); other units {other_high:xofn}. Unusual pattern across several results."},
    "trend_expert_rule": {
        "text": "{rule_text}: {n_results:int} {results_word} {period_label} ({units_text}). Lab check."},
    "trend_completeness_low": {
        "text": "{ward_label}: {n_cultures:int} cultures this week (usually {expected:int}). Data gap, cause unknown; "
                "not zero resistance."},
    "trend_quiet": {
        "text": "No signals on {quiet:xofn} units ({units_text})."},
    "trend_quiet_none": {
        "text": "Every unit has at least one item this week ({n_units:int} units)."},
}
