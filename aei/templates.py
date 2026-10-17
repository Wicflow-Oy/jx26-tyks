"""Text templates for every brief item, card and banner. Owned by the detectors/brief workstream; extend, don't rename.

Each template: {"text": "... {slot:format} ...", "formats": {slot: format}}. Numbers ONLY through slots.
Wording rules: no prediction language ("predicts", "forecast", "odds", "best choice", "recommended drug"); results
are S/R; say "unusual pattern" and "typing advised"; never "decoy" or "outbreak confirmed".
"""
TEMPLATES = {
    "phenotype_cluster": {"text": "{ward_label}: {organism_label} in {n_patients:int} patients with one antibiogram ({pattern}). "
                                  "First sample {first_date:short_date}. {n_share:int} of {n_patients:int} share the pattern; "
                                  "usually {expected_low:int}–{expected_high:int} {ward_label} patients a year. Typing advised."},
    "resistance_change": {"text": "{ward_label} · {organism_label} · {drug_label}: {counts:xofn} resistant "
                                  "({rate:pct0}, last {window_label}) vs {rate_prior:pct0} in the 52 weeks before. Changed; watch next week."},
    "policy_line": {"text": "{drug_label}: {organism_label} in {population_label} is {rate:pct1} resistant "
                            "({counts:xofn}, last 52 weeks), above the local {threshold:pct0} line. 12 months ago: {rate_prior:pct1}."},
    "seen_before": {"text": "{ward_label} {organism_label} pattern: {same_ward_text}; {n_elsewhere:int} earlier patients elsewhere "
                            "({elsewhere_text}). Profile match, not typing."},
    "expert_rule": {"text": "{n_results:int} results to check: {rule_text}. Lab check."},
    "completeness_ok": {"text": "All {n_units:int} units sent data this week."},
    "completeness_gap": {"text": "{ward_label}: no results this week (usually {expected:int}). Data gap, cause unknown; not zero resistance."},
    "quiet": {"text": "No new signals on {n_quiet:int} other units."},
}

# Workstream modules add their own templates here (B1 outbreak detectors, B2 trends/brief). Existing ids above stay.
try:
    from .templates_outbreak import TEMPLATES as _OUTBREAK
    TEMPLATES.update(_OUTBREAK)
except ImportError:
    pass
try:
    from .templates_trends import TEMPLATES as _TRENDS
    TEMPLATES.update(_TRENDS)
except ImportError:
    pass
