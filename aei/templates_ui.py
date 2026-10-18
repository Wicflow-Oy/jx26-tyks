"""Templates for the doctor's order layer and its CDS cards (aei/cds.py) and for My ward's reasons and footers
(aei/views.py). Merged into aei.templates.TEMPLATES; every id starts with "cds_" or "ward_".

Numbers only through slots: no digit appears in any text below, so the Finnish templates in aei/i18n.py carry
exactly the same numbers. Slots in these texts hold labels (drug, unit, organism) or a phrase rendered by another
template in the same language (`title`, `rule`, `how`, `recent`).
"""

TEMPLATES = {
    # why the order layer shows no number for a drug
    "cds_not_offered_urine": {"text": "tested on urine isolates only in this panel"},
    "cds_species__intrinsic": {"text": "EUCAST lists {organism} as intrinsically resistant"},
    "cds_species__no_breakpoint": {"text": "EUCAST has no breakpoint for {organism}"},
    "cds_untested": {"text": "not tested on {names} in this panel"},
    "cds_untested_share": {
        "text": "not tested on {names} in this panel; no result for {share:pct0} of this population's isolates"
    },
    "cds_species_note": {"text": "{drug_name}: {species} (this patient's {specimen} isolate of {date:date})."},
    "cds_reported_overruled": {"text": "{reason}; the laboratory reported {result}"},
    # approved infection-control alerts
    "cds_alert_title_cluster": {"text": "Possible {what} cluster"},
    "cds_alert_title_marker": {"text": "{what} alert"},
    "cds_alert_title_plain": {"text": "Infection-control alert"},
    "cds_alert_headline_r": {"text": "{title}, {ward_label}. The flagged antibiogram is R to {drug}."},
    "cds_alert_headline_r_how": {"text": "{title}, {ward_label}. The flagged antibiogram is R to {drug} ({how})."},
    "cds_alert_headline_applies": {"text": "{title}, {ward_label}. The alert applies to {drug}."},
    "cds_alert_summary_r": {"text": "{title} on {unit}: the flagged antibiogram is R to {drug}"},
    "cds_alert_summary_applies": {"text": "{title} on {unit}: the alert applies to {drug}"},
    "cds_alert_text": {
        "text": "As flagged by {role} on {approved_on:date}: {message} Expires {expires_on:short_date}."
    },
    "cds_notice_drug": {"text": "{title} on {unit}. The alert does not apply to {drug}."},
    "cds_notice_indications": {"text": "{title} on {unit}. The alert applies to {indications} only."},
    # this patient's own previous isolate
    "cds_own_headline": {"text": "This patient's {organism} of {date:date} was R to {drug}."},
    "cds_own_headline_how": {"text": "This patient's {organism} of {date:date} was R to {drug} ({how})."},
    "cds_own_summary": {"text": "{drug_name}: this patient's {organism} of {date:date} was R ({how})"},
    "cds_own_text": {"text": "This patient's {organism} ({specimen}, {unit}) of {date:date} was {drug} R ({how})."},
    # policy lines and local lines set by infection control
    "cds_policy_summary__above": {
        "text": (
            "{drug_label}: {rate:pct1} resistant ({counts:xofn}, last {weeks:int} weeks), above local {threshold:pct0} "
            "line"
        )
    },
    "cds_policy_summary__at": {
        "text": (
            "{drug_label}: {rate:pct1} resistant ({counts:xofn}, last {weeks:int} weeks), at local {threshold:pct0} "
            "line"
        )
    },
    "cds_policy_population": {"text": "{specimen} {organism}, {who}, {where}, {rule}"},
    "cds_policy_population_all": {"text": "{specimen} {organism}, {where}, {rule}"},
    "cds_where_health_centres": {"text": "health centres {units}"},
    "cds_where_units": {"text": "units {units}"},
    "cds_policy_text": {
        "text": (
            "Population: {population}. Local policy line set by infection control; crossed week ending "
            "{crossed_on:date}."
        )
    },
    "cds_policy_text_prior": {
        "text": (
            "Population: {population}. Same window a year earlier: {rate_prior:pct1} ({counts_prior:xofn}). Local "
            "policy line set by infection control; crossed week ending {crossed_on:date}."
        )
    },
    "cds_line_summary__above": {
        "text": "{drug_name}: {counts:xofn} {word} ({rate:pct1}, {window}) on {unit}, above the local {line:pct0} line"
    },
    "cds_line_summary__at": {
        "text": "{drug_name}: {counts:xofn} {word} ({rate:pct1}, {window}) on {unit}, at the local {line:pct0} line"
    },
    "cds_line_summary__close": {
        "text": (
            "{drug_name}: {counts:xofn} {word} ({rate:pct1}, {window}) on {unit}, close to the local {line:pct0} line"
        )
    },
    "cds_line_text": {
        "text": "Local line for {drug} in {indication}, set by infection control: {line:pct0} resistant."
    },
    # the order context
    "cds_population_unit": {"text": "{unit} ({details})"},
    "cds_population_community": {"text": "ED and health centres, patients from {home_area} ({details})"},
    "cds_counts_none": {"text": "{window}: not enough data (n = {n:int})"},
    "cds_counts__low_n": {
        "text": "{window}: {counts:xofn} {word} ({rate:pct0}, {level:pct0} interval {ci:ci0}; small n)"
    },
    "cds_counts__ok": {"text": "{window}: {counts:xofn} {word} ({rate:pct0}, {level:pct0} interval {ci:ci0})"},
    "cds_your_drug": {"text": "{drug_name} on {population}: {recent}; {year}."},
    "cds_your_drug_not_shown": {"text": "{drug_name} on {population}: not shown ({reason})."},
    "cds_chip_not_shown": {"text": "{drug_name}: {reason}"},
    "cds_chip_not_enough": {"text": "Not enough data on {unit} for {drug} (n = {n:int}, {window})"},
    "cds_chip_quiet": {"text": "No active alerts · {unit} · data to {as_of:short_date}"},
    "cds_rule_own_history": {
        "text": "this patient's own isolate in the last {weeks:int} weeks had acquired resistance to this drug"
    },
    "cds_rule_not_enough": {
        "text": (
            "No data: fewer than {min_n:int} isolates with a result in the last {weeks:int} weeks for this population "
            "and drug."
        )
    },
    "cds_results_label": {"text": "This patient's results, last {weeks:int} weeks:"},
    "cds_rule_select": {"text": "Info at selection: {rule}. It will ask again when the order is signed."},
    "cds_rule__warning": {"text": "Warning: {rule}."},
    "cds_rule__info": {"text": "Info: {rule}."},
    "cds_rule__notice": {"text": "Notice: {rule}."},
    "cds_keep": {"text": "Keep {drug}"},
    "cds_banner_policy": {"text": "{summary}. Population: {population}. {message}."},
    # My ward: footers and why a drug row is not shown
    "ward_footer": {"text": "In-vitro coverage on {where}. Not a prescription; local guide first."},
    "ward_not_shown__urine_only": {"text": "{drug} not shown: used for urine only"},
    "ward_not_shown__not_for_urine": {
        "text": "{drug} not shown for urine: not an empirical treatment for urinary tract infection"
    },
    "ward_not_shown__screening_only": {"text": "{drug} not shown: a screening test for MRSA, not a therapy option"},
    "ward_not_shown__species": {"text": "{drug} not shown: {clauses}"},
    "ward_species__intrinsic_one": {"text": "{names} is intrinsically resistant (EUCAST)"},
    "ward_species__intrinsic_many": {"text": "{names} are intrinsically resistant (EUCAST)"},
    "ward_species__no_breakpoint": {"text": "EUCAST has no breakpoint for {names}"},
    "ward_not_shown__untested_all": {"text": "{drug} not shown: untested on {names} (all of {scope} isolates)"},
    "ward_not_shown__untested_most": {"text": "{drug} not shown: untested on {names} (most of {scope} isolates)"},
    "ward_not_shown__untested_share": {
        "text": "{drug} not shown: untested on {names} ({share:pct0} of {scope} isolates)"
    },
}
