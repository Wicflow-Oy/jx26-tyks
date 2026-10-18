"""The Finnish twin of every English template (aei/templates*.py): same ids, same slots, same formats, so a Finnish
text carries exactly the numbers of the English one (tests/test_i18n.py checks it). Rendered by aei.i18n.render_id.

Wording follows THL and Finnish clinical microbiology (see aei/i18n.py). A Finnish short date ends in its own period
("5.7."), which also ends a sentence: no second period after it.
"""

from . import config as C
from .templates_outbreak import N_STATES
from .templates_trends import MAX_OUTLIER_PAIRS

_RESOLVED = "Päättynyt. Viimeksi nostettu esiin viikolla, joka päättyi {last_flagged:date}"
_THL_CHECK = "THL:n ohje: epidemiaselvitys (useita löydöksiä samassa yksikössä tavanomaista enemmän)."
_EXPECTED = (
    "Odotettu määrä, jos tämän herkkyysprofiilin osuus olisi sama kuin koko sairaalassa: "
    "{expected_low:int}–{expected_high:int} potilasta vuodessa tässä yksikössä (havaittu edeltävänä vuonna: "
    "{observed_year_before:int}). "
)
_CLUSTER_TITLE = "{ward}: mahdollinen rypäs ({organism_label})"

FI = {
    # templates.py: the ED heads-up
    "ed_cluster": {
        "text": (
            "Tiedoksi infektioiden torjunnasta. {ward_label} ({ward}): mahdollinen rypäs ({organism_label}). "
            "{n_patients:int} potilasta {first_date:short_date} alkaen; {n_share:int}/{n_patients:int} potilaalla sama "
            "herkkyysprofiili: {pattern}. Selvitys käynnissä; tyypitystä suositellaan. Päivämäärät ovat "
            "näytteenottopäiviä."
        )
    },
    "ed_case": {
        "text": (
            "Tiedoksi infektioiden torjunnasta. {ward_label} ({ward}): {marker_label} ({organism_label}), näyte: "
            "{specimen}, näytteenottopäivä {sample_date:short_date} Moniresistentti mikrobi THL:n ohjeen mukaan."
        )
    },
    # templates_outbreak.py
    "ob_thl_single": {
        "text": (
            "{ward}: {marker_label} ({organism_label}, {specimen}), näytteenottopäivä {sample_date:short_date}, "
            "{onset_label}. Moniresistentti mikrobi (THL:n ohje): jokainen tapaus. {action} Väli edelliseen "
            "{marker_label}-löydökseen datassa: {days_since_prev:int} pv."
        ),
        "title": "{ward}: {marker_label}-tapaus ({organism_label})",
    },
    "ob_thl_single_first": {
        "text": (
            "{ward}: {marker_label} ({organism_label}, {specimen}), näytteenottopäivä {sample_date:short_date}, "
            "{onset_label}. Moniresistentti mikrobi (THL:n ohje): jokainen tapaus. {action} Ensimmäinen "
            "{marker_label}-löydös datassa."
        ),
        "title": "{ward}: {marker_label}-tapaus ({organism_label})",
    },
    "ob_thl_single_resolved": {
        "text": (
            "{ward}: {marker_label} ({organism_label}, {specimen}), näytteenottopäivä "
            "{sample_date:date}. " + _RESOLVED + "; tapauskortti pysyy katsauksessa "
            "{active_weeks:int} viikkoa näytteenotosta."
        ),
        "title": "{ward}: {marker_label}-tapaus ({organism_label}), päättynyt",
    },
    "ob_thl_cluster_same": {
        "text": (
            "{ward}, {organism_label}: {n_patients:int} potilasta {first_date:short_date} alkaen; "
            "tavallisesti {usual_low:int}–{usual_high:int} samassa ajassa. "
            "{n_share:int}/{n_patients:int} potilaalla sama herkkyysprofiili ({pattern}). "
            + _THL_CHECK
            + " Tyypitystä suositellaan."
        ),
        "title": _CLUSTER_TITLE,
    },
    "ob_thl_cluster_mixed": {
        "text": (
            "{ward}, {organism_label}: {n_patients:int} potilasta {first_date:short_date} "
            "alkaen; tavallisesti {usual_low:int}–{usual_high:int} samassa ajassa. Vaihteleva: "
            "{n_profiles:int} eri herkkyysprofiilia, sääntöjemme mukaan alempi prioriteetti "
            "(todellinen tilanne tuntematon). " + _THL_CHECK
        ),
        "title": "{ward}, {organism_label}: potilaita tavallista enemmän",
    },
    "ob_thl_cluster_resolved": {
        "text": (
            "{ward}, {organism_label}: {n_patients:int} potilasta {first_date:short_date} "
            "alkaen. " + _RESOLVED + "; viimeksi tavanomaista tasoa enemmän "
            "{last_alert:short_date}"
        ),
        "title": "{ward}, {organism_label}: potilaita tavanomaista enemmän, päättynyt",
    },
    "ob_stepup": {
        "text": (
            "{ward}: uudet {marker_label}-potilaat viimeisten {window_weeks:int} viikon aikana: {y4:int}; tavallisesti "
            "{usual_low:int}–{usual_high:int} (edeltävät {baseline_weeks:int} viikkoa). Tapausmäärän nousun testi "
            "positiivinen, yhteistä herkkyysprofiilia ei löytynyt. Vain tukeva näyttö; tarkista, onko kyseessä rypäs."
        ),
        "title": "{ward}: uusia {marker_label}-potilaita tavallista enemmän",
    },
    "ob_stepup_resolved": {
        "text": (
            "{ward}: {marker_label}-tapausmäärän nousun testi. " + _RESOLVED + "; nyt uudet "
            "{marker_label}-potilaat viimeisten {window_weeks:int} viikon aikana: {y4:int}, "
            "tavallisesti {usual_low:int}–{usual_high:int} (edeltävät {baseline_weeks:int} "
            "viikkoa)."
        ),
        "title": "{ward}: uusia {marker_label}-potilaita tavallista enemmän, päättynyt",
    },
    "ob_phenotype_marker_resolved": {
        "text": (
            "{ward}, {organism_label}: poikkeava löydöskuvio ({pattern}) "
            "{first_date:short_date} alkaen. " + _RESOLVED + "; viimeksi havaittu "
            "{last_alert:short_date} Tämä herkkyysprofiili on "
            "{n_share:int}/{n_patients:int} potilaalla, joilla on {organism_label}."
        ),
        "title": _CLUSTER_TITLE + ", päättynyt",
    },
    "ob_phenotype_plain_resolved": {
        "text": (
            "{ward}, {organism_label}: poikkeava löydöskuvio ({pattern}) "
            "{first_date:short_date} alkaen. " + _RESOLVED + "; viimeksi havaittu "
            "{last_alert:short_date} Juuri tämä herkkyysprofiili on "
            "{n_share:int}/{n_patients:int} potilaalla, joilla on lähes sama profiili."
        ),
        "title": _CLUSTER_TITLE + ", päättynyt",
    },
    "ob_seen_before_resolved": {
        "text": (
            "{ward}, {organism_label}, herkkyysprofiili ({pattern}). " + _RESOLVED + "; "
            "yksikön {ward} rypäs, joka alkoi {cluster_first_date:date}, havaittiin viimeksi "
            "{last_alert:short_date}"
        ),
        "title": "{ward}: herkkyysprofiili ({organism_label}) nähty aiemmin, päättynyt",
    },
    "ob_seen_before_return_resolved": {
        "text": (
            "{ward}, {organism_label}, herkkyysprofiili ({pattern}) palannut "
            "yksikköön {ward}. " + _RESOLVED + "; viimeisin näyte {return_date:date}, "
            "ei sen jälkeen uusia potilaita tällä herkkyysprofiililla yksikössä "
            "{ward}."
        ),
        "title": "{ward}: herkkyysprofiili ({organism_label}) palannut tähän yksikköön, päättynyt",
    },
    # templates_trends.py
    "trend_resistance_change_resolved": {
        "text": (
            "{ward_label} · {finding}. " + _RESOLVED + ": {counts_last:xofn} {organism_label} -isolaattia; nyt "
            "{counts:xofn} viimeisten {window_weeks:int} viikon aikana."
        ),
        "title": "{ward}: {subject} tavallista useammin, päättynyt",
    },
    "trend_policy_line": {
        "text": (
            "{drug_label}: {organism_label}, {population_label}: resistenttien osuus {rate:pct1} ({counts:xofn}, "
            "viimeiset {window_weeks:int} viikkoa). Paikallinen {threshold:pct0}:n raja {relation} {crossed_on:date} "
            "päättyneestä viikosta lähtien. Sama jakso vuotta aiemmin: {rate_prior:pct1} ({counts_prior:xofn})."
        ),
        "title": "{drug_label}: paikallinen {threshold:pct0}:n raja {relation}",
    },
    "trend_policy_line_resolved": {
        "text": (
            "{drug_label}: {organism_label}, {population_label}. " + _RESOLVED + ": resistenttien osuus "
            "{rate_last:pct1} ({counts_last:xofn}); nyt {rate:pct1} ({counts:xofn}, viimeiset {window_weeks:int} "
            "viikkoa), alle paikallisen {threshold:pct0}:n rajan."
        ),
        "title": "{drug_label}: taas alle paikallisen {threshold:pct0}:n rajan",
    },
    "trend_ward_outlier_resolved": {
        "text": (
            "{ward_label}: resistenssi tavanomaista vaihteluväliä korkeampi. " + _RESOLVED + ": mikrobi–lääke-"
            "yhdistelmiä tavanomaisen vaihteluvälin yläpuolella {n_high_last:int}; nyt {n_high:int} (viimeiset "
            "{window_weeks:int} viikkoa)."
        ),
        "title": "{ward}: useita resistenssituloksia tavanomaisen vaihteluvälin yläpuolella, päättynyt",
    },
    "trend_expert_rule": {
        "text": "{rule_text}: {n_results:int} {results_word} {period_label} ({units_text}). Laboratorion tarkistus.",
        "title": "Laboratorion tarkistus: {rule_text}",
    },
    "trend_completeness_gap": {
        "text": (
            "{ward_label}: ei viljelyjä tällä viikolla (yleensä {expected:int} viikossa). Aukko datassa, syy "
            "tuntematon."
        ),
        "title": "{ward}: ei viljelyjä tällä viikolla",
    },
    "trend_completeness_low": {
        "text": (
            "{ward_label}: viljelyjä tällä viikolla {n_cultures:int} (yleensä {expected:int} viikossa). Aukko datassa, "
            "syy tuntematon."
        ),
        "title": "{ward}: tavallista vähemmän viljelyjä tällä viikolla",
    },
    "trend_completeness_resolved": {
        "text": (
            "{ward_label}: aukko datassa. " + _RESOLVED + ": viljelyjä {n_last:int} (yleensä {expected_last:int} "
            "viikossa), syy tuntematon; nyt viljelyjä {n_cultures:int} tällä viikolla."
        ),
        "title": "{ward}: aukko datassa, päättynyt",
    },
    "trend_completeness_ok": {
        "text": "Tällä viikolla dataa tuli kaikilta {n_units:int} yksiköltä.",
        "title": "Dataa tuli kaikilta yksiköiltä",
    },
    "trend_quiet": {
        "text": "Ei signaaleja {quiet:xofn} yksikössä ({units_text}).",
        "title": "Yksiköt ilman signaaleja",
    },
    "trend_quiet_none": {
        "text": "Kaikissa yksiköissä on tällä viikolla kohteita ({n_units:int} yksikköä).",
        "title": "Ei yksiköitä ilman signaaleja",
    },
    # templates_ui.py: the order layer and its CDS cards
    "cds_not_offered_urine": {"text": "testattu tässä paneelissa vain virtsanäytteiden isolaateista"},
    "cds_species__intrinsic": {"text": "EUCAST:n mukaan {organism} on luontaisesti resistentti"},
    "cds_species__no_breakpoint": {"text": "EUCAST ei anna raja-arvoa lajille {organism}"},
    "cds_untested": {"text": "ei testattu tässä paneelissa: {names}"},
    "cds_untested_share": {
        "text": "ei testattu tässä paneelissa: {names}; ilman tulosta {share:pct0} tämän potilasjoukon isolaateista"
    },
    "cds_species_note": {"text": "{drug_name}: {species} (potilaan isolaatti {date:date}, näyte: {specimen})."},
    "cds_reported_overruled": {"text": "{reason}; laboratorion vastaus {result}"},
    "cds_alert_title_cluster": {"text": "Mahdollinen rypäs ({what})"},
    "cds_alert_title_marker": {"text": "Hälytys: {what}"},
    "cds_alert_title_plain": {"text": "Infektioiden torjunnan hälytys"},
    "cds_alert_headline_r": {"text": "{title}, {ward_label}. Hälytyksen herkkyysprofiili: {drug} R."},
    "cds_alert_headline_r_how": {"text": "{title}, {ward_label}. Hälytyksen herkkyysprofiili: {drug} R ({how})."},
    "cds_alert_headline_applies": {"text": "{title}, {ward_label}. Hälytys koskee tätä lääkettä ({drug})."},
    "cds_alert_summary_r": {"text": "{title}, {unit}: hälytyksen herkkyysprofiilissa {drug} R"},
    "cds_alert_summary_applies": {"text": "{title}, {unit}: hälytys koskee tätä lääkettä ({drug})"},
    "cds_alert_text": {
        "text": "{message} Nostanut esiin: {role}, {approved_on:date}; voimassa {expires_on:short_date} asti."
    },
    "cds_notice_drug": {"text": "{title}, {unit}. Hälytys ei koske tätä lääkettä ({drug})."},
    "cds_notice_indications": {"text": "{title}, {unit}. Hälytys koskee vain indikaatioita: {indications}."},
    "cds_own_headline": {"text": "Potilaan {organism} -löydös {date:date}: {drug} R."},
    "cds_own_headline_how": {"text": "Potilaan {organism} -löydös {date:date}: {drug} R ({how})."},
    "cds_own_summary": {"text": "{drug_name}: potilaan {organism} -löydös {date:date} R ({how})"},
    "cds_own_text": {"text": "Potilaan {organism} -löydös ({specimen}, {unit}) {date:date}: {drug} R ({how})."},
    "cds_policy_summary__above": {
        "text": (
            "{drug_label}: resistenttien osuus {rate:pct1} ({counts:xofn}, viimeiset {weeks:int} viikkoa), yli "
            "paikallisen {threshold:pct0}:n rajan"
        )
    },
    "cds_policy_summary__at": {
        "text": (
            "{drug_label}: resistenttien osuus {rate:pct1} ({counts:xofn}, viimeiset {weeks:int} viikkoa), paikallisen "
            "{threshold:pct0}:n rajan tasolla"
        )
    },
    "cds_policy_population": {"text": "{organism} ({specimen}), {who}, {where}, {rule}"},
    "cds_policy_population_all": {"text": "{organism} ({specimen}), {where}, {rule}"},
    "cds_where_health_centres": {"text": "terveysasemat {units}"},
    "cds_where_units": {"text": "yksiköt {units}"},
    "cds_policy_text": {
        "text": (
            "Potilasjoukko: {population}. Infektioiden torjunnan asettama paikallinen raja; raja saavutettiin "
            "{crossed_on:date} päättyneellä viikolla."
        )
    },
    "cds_policy_text_prior": {
        "text": (
            "Potilasjoukko: {population}. Sama jakso vuotta aiemmin: {rate_prior:pct1} ({counts_prior:xofn}). "
            "Infektioiden torjunnan asettama paikallinen raja; raja saavutettiin {crossed_on:date} päättyneellä "
            "viikolla."
        )
    },
    "cds_line_summary__above": {
        "text": "{drug_name}: {counts:xofn} {word} ({rate:pct1}, {window}), {unit}; yli paikallisen {line:pct0}:n rajan"
    },
    "cds_line_summary__at": {
        "text": (
            "{drug_name}: {counts:xofn} {word} ({rate:pct1}, {window}), {unit}; paikallisen {line:pct0}:n rajan tasolla"
        )
    },
    "cds_line_summary__close": {
        "text": (
            "{drug_name}: {counts:xofn} {word} ({rate:pct1}, {window}), {unit}; lähellä paikallista {line:pct0}:n rajaa"
        )
    },
    "cds_line_text": {
        "text": "Infektioiden torjunnan asettama paikallinen raja ({drug}, {indication}): {line:pct0} resistenttejä."
    },
    "cds_population_unit": {"text": "{unit} ({details})"},
    "cds_population_community": {"text": "päivystys ja terveysasemat, potilaat alueelta {home_area} ({details})"},
    "cds_counts_none": {"text": "{window}: liian vähän dataa (n = {n:int})"},
    "cds_counts__low_n": {
        "text": "{window}: {counts:xofn} {word} ({rate:pct0}, {level:pct0}:n luottamusväli {ci:ci0}; pieni n)"
    },
    "cds_counts__ok": {"text": "{window}: {counts:xofn} {word} ({rate:pct0}, {level:pct0}:n luottamusväli {ci:ci0})"},
    "cds_your_drug": {"text": "{drug_name}, {population}: {recent}; {year}."},
    "cds_your_drug_not_shown": {"text": "{drug_name}, {population}: ei näytetä ({reason})."},
    "cds_chip_not_shown": {"text": "{drug_name}: {reason}"},
    "cds_chip_not_enough": {"text": "Liian vähän dataa: {unit}, {drug} (n = {n:int}, {window})"},
    "cds_chip_quiet": {"text": "Ei voimassa olevia hälytyksiä · {unit} · data {as_of:short_date} asti"},
    "cds_rule_own_history": {
        "text": (
            "potilaan omassa isolaatissa viimeisten {weeks:int} viikon ajalta on hankinnainen resistenssi tälle "
            "lääkkeelle"
        )
    },
    "cds_rule_not_enough": {
        "text": (
            "Ei dataa: alle {min_n:int} isolaattia, joilla on tulos, viimeisten {weeks:int} viikon aikana tässä "
            "potilasjoukossa tälle lääkkeelle."
        )
    },
    "cds_results_label": {"text": "Potilaan tulokset, viimeiset {weeks:int} viikkoa:"},
    "cds_rule_select": {"text": "Tiedoksi valintavaiheessa: {rule}. Kysymys toistetaan, kun määräys allekirjoitetaan."},
    "cds_rule__warning": {"text": "Varoitus: {rule}."},
    "cds_rule__info": {"text": "Tiedoksi: {rule}."},
    "cds_rule__notice": {"text": "Huomautus: {rule}."},
    "cds_keep": {"text": "Pidä {drug}"},
    "cds_banner_policy": {"text": "{summary}. Potilasjoukko: {population}. {message}."},
    # templates_ui.py: My ward
    "ward_footer": {"text": "In vitro -kattavuus: {where}. Ei lääkemääräys; paikallinen hoito-ohje ensin."},
    "ward_not_shown__urine_only": {"text": "{drug}: ei näytetä; vain virtsanäytteille"},
    "ward_not_shown__not_for_urine": {
        "text": "{drug}: ei näytetä virtsanäytteille; ei virtsatieinfektion empiirinen hoito"
    },
    "ward_not_shown__screening_only": {"text": "{drug}: ei näytetä; MRSA-seulontatesti, ei hoitovaihtoehto"},
    "ward_not_shown__species": {"text": "{drug}: ei näytetä; {clauses}"},
    "ward_species__intrinsic_one": {"text": "{names}: luontainen resistenssi (EUCAST)"},
    "ward_species__intrinsic_many": {"text": "{names}: luontainen resistenssi (EUCAST)"},
    "ward_species__no_breakpoint": {"text": "{names}: ei EUCAST-raja-arvoa"},
    "ward_not_shown__untested_all": {"text": "{drug}: ei näytetä; testaamatta: {names} (kaikki {scope} isolaatit)"},
    "ward_not_shown__untested_most": {
        "text": "{drug}: ei näytetä; testaamatta: {names} (valtaosa {scope} isolaateista)"
    },
    "ward_not_shown__untested_share": {
        "text": "{drug}: ei näytetä; testaamatta: {names} ({share:pct0} {scope} isolaateista)"
    },
}

FI.update(
    {  # competing explanations (detectors/explanations.py)
        "ob_ach_h1": {
            "text": (
                "potilaita: havaittu {n:int}, odotettu {expected:dec2} ({p_count:p}); yleisin herkkyysprofiili "
                "{identical:xofn} potilaalla, taustalla {background:xofn} isolaatilla edeltävän vuoden aikana "
                "({p_identity:p}); sairaalasyntyisiä {hosp_onset:xofn}"
            ),
            "title": "Leviäminen yksikössä",
        },
        "ob_ach_h2": {"text": "eri herkkyysprofiileja potilailla: {n_antibiograms:int}", "title": "Sattuma"},
        "ob_ach_h3": {
            "text": (
                "{early:xofn} näytteistä otettu viimeistään hoitopäivänä {early_day:int}; ensimmäisen potilaan näyte "
                "hoitopäivänä {index_day:int}"
            ),
            "title": "Todettu jo tullessa",
        },
        "ob_ach_h3_outpatient": {
            "text": (
                "{early:xofn} näytteistä otettu viimeistään hoitopäivänä {early_day:int}; ensimmäinen potilas "
                "avohoidosta"
            ),
            "title": "Todettu jo tullessa",
        },
        "ob_ach_h4": {
            "text": (
                "yksikön viljelyt tällä jaksolla: {cultures:int}; edeltävän vuoden samanpituisilla jaksoilla "
                "keskimäärin {usual:dec1}"
            ),
            "title": "Näytteenoton muutos",
        },
        "ob_ach_h4_none": {
            "text": "yksikön viljelyt tällä jaksolla: {cultures:int}; ei aiempaa vertailujaksoa",
            "title": "Näytteenoton muutos",
        },
        "ob_ach_h5__0": {"text": "aineistossa ei ole näitä päivämääriä aiemmilta vuosilta", "title": "Kausivaihtelu"},
        "ob_ach_h6_agree": {
            "text": "jokaisen potilaan {marker}-merkitty isolaatti on {drug} R",
            "title": "Laboratorio- tai datavirhe",
        },
        "ob_ach_h6_disagree": {
            "text": "kaikki {marker}-merkityt isolaatit eivät ole {drug} R: tarkista laboratoriotiedot",
            "title": "Laboratorio- tai datavirhe",
        },
        "ob_ach_h6_none": {
            "text": "ei resistenssimerkkiä, jota verrata herkkyysprofiiliin",
            "title": "Laboratorio- tai datavirhe",
        },
    }
)
for _k in (1, 2):
    FI[f"ob_ach_h5__{_k}"] = {
        "text": (
            "potilaita yksikössä samoina päivinä "
            + "; ".join(f"vuonna {{y{i}}}: {{n{i}:int}}" for i in range(1, _k + 1))
        ),
        "title": "Kausivaihtelu",
    }

# Generated families, mirroring templates_outbreak.py and templates_trends.py (same ids, same slots).
_SMALL = {"not_enough_data": "", "low_n": ", pieni n", "ok": ""}


def _pct(n_state: str, kind: str) -> str:
    """The share after a background x/n: none below 10, tagged "pieni n" below 30."""
    return "" if n_state == "not_enough_data" else f" ({{bg_share:{kind}}}{_SMALL[n_state]})"


for _n in N_STATES:
    FI[f"ob_phenotype_marker__{_n}"] = {
        "text": (
            "{ward}: poikkeava löydöskuvio. {organism_label}: {n_patients:int} potilasta {first_date:short_date} "
            "alkaen; {n_share:int}/{n_patients:int} potilaalla sama herkkyysprofiili ({pattern}). "
            + _EXPECTED
            + "Edeltävänä vuonna koko sairaalassa tämä herkkyysprofiili oli {bg:xofn} potilaalla, joilla on "
            "{bg_label}" + _pct(_n, "pct0") + ". Tyypitystä suositellaan."
        ),
        "title": _CLUSTER_TITLE,
    }
    FI[f"ob_phenotype_plain__{_n}"] = {
        "text": (
            "{ward}: poikkeava löydöskuvio. {organism_label}: {n_patients:int} potilasta {first_date:short_date} "
            "alkaen, herkkyysprofiilit lähes samat; {n_share:int}/{n_patients:int} potilaalla sama profiili "
            "({pattern}). " + _EXPECTED + "Edeltävänä vuonna koko sairaalassa tämä herkkyysprofiili oli {bg:xofn} "
            "{bg_label} -isolaatilla, joille on tehty samat herkkyysmääritykset"
            + _pct(_n, "pct1")
            + ". Tyypitystä suositellaan."
        ),
        "title": _CLUSTER_TITLE,
    }

_SAME = {
    "new": "ei aiemmin yksikössä {ward}",
    "known": "aiemmat potilaat yksikössä {ward}: {n_same_before:int}, viimeisin {last_same_date:date}",
}


def _elsewhere(k: int) -> str:
    if k == 0:
        return "ei aiempia potilaita muualla"
    units = ", ".join(f"{{w{i}}} {{n{i}:int}}" for i in range(1, k + 1))
    return "aiemmat potilaat muualla: {n_elsewhere:int} (" + units + ")"


def _background(lead: str) -> dict:
    had = lead + " tämä herkkyysprofiili oli {bg:xofn} potilaalla, joilla on {bg_label}"
    out = {"few": had + ": liian vähän tapauksia yleisyyden arvioimiseen."}
    for n in ("low_n", "ok"):
        out[f"weak_{n}"] = had + _pct(n, "pct1") + ", joten vastaavuus on heikko näyttö."
        out[f"rare_{n}"] = had + _pct(n, "pct1") + ", joten profiili on harvinainen."
    return out


def _seen_title(same: str, k: int) -> str:
    if same == "known":
        return "{ward}: herkkyysprofiili ({organism_label}) nähty tässä yksikössä aiemmin"
    return (
        "{ward}: herkkyysprofiili ({organism_label}) nähty aiemmin muissa yksiköissä"
        if k
        else "{ward}: herkkyysprofiilia ({organism_label}) ei ole nähty aiemmin"
    )


for _s, _st in _SAME.items():
    for _k in range(len(C.WARD_LABELS)):
        for _e, _bt in _background("Ennen tätä rypästä").items():
            FI[f"ob_seen_before__{_s}__{_k}__{_e}"] = {
                "text": (
                    "{ward}, {organism_label}, herkkyysprofiili ({pattern}): "
                    + _st
                    + "; "
                    + _elsewhere(_k)
                    + ". "
                    + _bt
                    + " Profiilivastaavuus, ei tyypitys."
                ),
                "title": _seen_title(_s, _k),
            }
for _e, _bt in _background("Tähän mennessä").items():
    FI[f"ob_seen_before_return__{_e}"] = {
        "text": (
            "{ward}, {organism_label}, herkkyysprofiili ({pattern}) on palannut yksikköön {ward}: viimeisin näyte "
            "{return_date:short_date}; potilaat {cluster_first_date:date} alkaneen ryppään jälkeen: {n_return:int}. "
            + _bt
            + " Profiilivastaavuus, ei tyypitys; tyypitystä suositellaan."
        ),
        "title": "{ward}: herkkyysprofiili ({organism_label}) palannut tähän yksikköön",
    }

_NOW = {
    "not_enough_data": "{counts:xofn} {organism_label} -isolaattia",
    "low_n": "{counts:xofn} {organism_label} -isolaattia ({rate:pct0}, pieni n)",
    "ok": "{counts:xofn} {organism_label} -isolaattia ({rate:pct0})",
}
_BEFORE = {
    "not_enough_data": "{counts_prior:xofn}",
    "low_n": "{counts_prior:xofn} ({rate_prior:pct0}, pieni n)",
    "ok": "{counts_prior:xofn} ({rate_prior:pct0})",
}
for _w, _now in _NOW.items():
    for _p, _before in _BEFORE.items():
        FI[f"trend_resistance_change__{_w}__{_p}"] = {
            "text": (
                "{ward_label} · {finding}: "
                + _now
                + " viimeisten {window_weeks:int} viikon aikana; vrt. "
                + _before
                + " edeltävien {prior_weeks:int} viikon aikana. Muuttunut; seuraa tilannetta ensi viikolla."
            ),
            "title": "{ward}: {subject} tavallista useammin",
        }

for _k in range(1, MAX_OUTLIER_PAIRS + 1):
    _pairs = "; ".join(f"{{pair{i}}}: {{counts{i}:xofn}}" for i in range(1, _k + 1))
    FI[f"trend_ward_outlier__{_k}"] = {
        "text": (
            "{ward_label}: resistenssi tavanomaista vaihteluväliä korkeampi {high:xofn} mikrobi–lääke-yhdistelmässä "
            "viimeisten {window_weeks:int} viikon aikana. Resistenttejä testatuista: " + _pairs + ". Muut yksiköt: "
            "{other_high:xofn} yhdistelmää. Poikkeava löydöskuvio useissa tuloksissa."
        ),
        "title": "{ward}: useita resistenssituloksia tavanomaisen vaihteluvälin yläpuolella",
    }
