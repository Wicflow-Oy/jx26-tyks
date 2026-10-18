"""The doctor's order layer (CONTRACTS.md section 7b); aei/cds_hooks.py turns it into CDS Hooks 2.0 cards.

It flags the drug the doctor entered and never names another one: what is going on, this drug's numbers in this
population and one neutral sentence. The doctor keeps the order, edits it, or opens My ward to look at every drug.

Pure and deterministic. Something is said about an order only because of:
  (a) an approved infection-control alert active at `as_of + 1` on the ordering unit;
  (b) this patient's own isolate in the 52 weeks to `as_of` with an acquired R to the ordered drug. An intrinsic or
      no-breakpoint R is a property of the species: a passive note, never a warning;
  (c) a line infection control set: a policy line at or above its threshold, or this population's observed
      resistance at or near a line in `config.EMPIRICAL_LINES` (urinary trimethoprim, 20%).
Only (a) applying to this drug and indication, and (b), interrupt, and only when the order is signed; at selection
they show as info. An alert on the unit that does not apply to the order is a one-line notice without numbers.
Results come from the shared `phenotype_rules.effective`, so the numbers equal My ward's for the same population, and
My ward's rules decide whether a number is shown at all (CONTRACTS 4.1): never for a urine-only drug outside urine,
for a drug the indication's reference organism is intrinsically resistant to, or for a drug with a result on fewer
than 90% of the population's isolates. Never a block and never a patient-level estimate. This module imports neither
the narrator nor the second-opinion adapter (a test enforces it).

Every text is rendered from a template (aei/templates_ui.py) or a glossary phrase in the language `lang` (aei/i18n.py):
English by default, Finnish with lang="fi". Codes, ids and numbers do not change with the language.
"""

import re
import uuid
from urllib.parse import quote, urlencode

import pandas as pd

from . import config as C
from . import data, stats
from .data import FLAGS
from .i18n import join, label, render_id, short_organism
from .phenotype_rules import REASON_TEXT, SPECIES_LEVEL, effective
from .store import is_active

SLUG = re.sub(r"[^a-z0-9]+", "-", C.APP_NAME.lower()).strip("-")
SMALL_PRINT = "Observed unit-level information, not a prediction for this patient. The doctor decides."
LAG_NOTE = f"Dates are sample dates; results usually arrive about {C.RESULT_LAG_DAYS} days later."
ASK = "Consider whether this drug still fits. The decision is yours."
SIGN_NOTE = "It will ask again when the order is signed."
DETAILS_LABEL = "All drugs on My ward"
EDIT_LABEL = "Edit the order"
METHOD = (
    "first isolate per patient x organism x specimen; effective S/R from the shared phenotype rules (EUCAST "
    "breakpoints, expected resistant phenotypes and expert rules, and this laboratory's ESBL reporting rule); no "
    "number for a drug with a result on fewer than 90% of the population's isolates; Jeffreys 95% interval"
)
STAGES = ("select", "sign")
LEVELS = ("warning", "info", "notice")  # what fires speaks in this order
ORDER_NAMES = {code: name for code, name, _ in C.ORDER_DRUGS}
INDICATION_ALIASES = {"urinary": "uti"}  # policy lines and CDS requests may name the indication by organ
WINDOW_TEXT = {w: C.WINDOW_LABELS[w].lower() for w in ("4w", "12m")}  # 364 days is "last 52 weeks", not 12 months
HISTORY_WEEKS = C.WINDOWS["12m"] // 7  # a patient's own results and the year's numbers: the last 52 weeks
SPECIMEN_WORDS = {"urine": "urinary", "blood": "blood", "wound": "wound"}
COUNTING_RULES = {
    "readme_period": "first isolate per patient in the window",
    "30d": "first isolate per patient in 30 days",
}
_NS = uuid.UUID("6f2b6c1e-8d1a-5c3e-9a57-5a1d3c0e7b21")


class OrderError(ValueError):
    """An order this service cannot read: unknown unit, indication, drug, patient or hook (the API answers 422)."""


# --------------------------------------------------------------------------- small helpers
def iso_day(value) -> str:
    """'2026-03-29' from a date or a date string; anything else is an OrderError."""
    try:
        return pd.Timestamp(str(value)[:10]).date().isoformat()
    except ValueError as e:
        raise OrderError(f"not a date: {value!r}") from e


def indication_key(value):
    """The indication key; policy lines and CDS requests may name it by organ ("urinary")."""
    return INDICATION_ALIASES.get(value, value) if isinstance(value, str) else value


def _known(value, allowed, what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise OrderError(f"unknown {what}: {value!r}")
    return value


def _uuid(*parts) -> str:
    return str(uuid.uuid5(_NS, "|".join(str(p) for p in parts)))


# --------------------------------------------------------------------------- effective results and counts
def _effective(isolates: pd.DataFrame, drug: str) -> tuple[pd.Series, pd.Series]:
    """`phenotype_rules.effective` for what is ordered. The picker orders flucloxacillin as FOX: it is read from the
    cefoxitin screen, and of the species in this dataset EUCAST (Breakpoint Tables v16.1) gives flucloxacillin
    breakpoints for staphylococci only, so every other species is a no-breakpoint R."""
    result, reason = effective(isolates, drug)
    if drug != "FOX":
        return result, reason
    other = ~isolates["organism"].str.startswith("Staphylococcus")
    return result.mask(other, "R"), reason.mask(other, "no_breakpoint")


def _reason_text(drug: str, reason: str) -> str | None:
    """The words for a result's reason; an ordered flucloxacillin is read from the reported cefoxitin screen."""
    return "read from the cefoxitin screen" if drug == "FOX" and reason == "reported" else REASON_TEXT.get(reason)


def _windows(rows: pd.DataFrame, as_of) -> dict[str, pd.DataFrame]:
    """First isolate per patient x organism x specimen in each window (`4w`, `12m`)."""
    return {w: data.first_isolates(data.window(rows, as_of, C.WINDOWS[w])) for w in WINDOW_TEXT}


def counts(first: pd.DataFrame, drug: str, window: str) -> dict:
    """R (resistant or not covered) of n with a result, among one window's first isolates. Below 10 there is no
    percentage and no interval, as on My ward. `isolates` and `untested` ([organism, n] without a result, largest
    first) decide whether the number is shown at all."""
    result = _effective(first, drug)[0]
    r, n = int((result == "R").sum()), int(result.notna().sum())
    state = stats.n_state(n)
    shown = state != "not_enough_data"
    gaps = first.organism[result.isna()].value_counts()
    return {
        "r": r,
        "n": n,
        "pct": r / n if shown else None,
        "ci": list(stats.jeffreys_interval(r, n)) if shown else None,
        "state": state,
        "window": window,
        "isolates": len(first),
        "untested": sorted(([o, int(k)] for o, k in gaps.items()), key=lambda g: (-g[1], g[0])),
    }


def _not_offered(drug: str, indication: str, lang: str) -> str | None:
    """Why the indication never gets a number for this drug, whatever the data; None when it can."""
    ind = C.INDICATIONS[indication]
    if drug in C.URINE_ONLY and ind["specimen"] != "urine":
        return render_id("cds_not_offered_urine", {}, lang)
    org = ind["reference_organism"]
    if org:  # the shared rules on one isolate of the reference organism with no result say what the species implies
        why = _effective(pd.DataFrame({"organism": [org]}), drug)[1].iloc[0]
        if why in SPECIES_LEVEL:
            return render_id(f"cds_species__{why}", {"organism": short_organism(org)}, lang)
    return None


def _untested(c: dict, lang: str) -> str | None:
    """My ward's eligibility rule (CONTRACTS 4.1): with 10 or more isolates in a window, a result on at least 90%."""
    if c["isolates"] < C.SMALL_N_NONE or c["n"] / c["isolates"] >= C.ELIGIBLE_MIN_TESTED_SHARE:
        return None
    names = [short_organism(o) for o, _ in c["untested"][:3]] + (["other organisms"] if len(c["untested"]) > 3 else [])
    slots = {"names": join([label(n, lang) for n in names], lang)}
    if c["n"]:  # the share from the integers: 1 - 54 / 80 is 0.32499..., which would print 32% instead of 33%
        return render_id("cds_untested_share", slots | {"share": (c["isolates"] - c["n"]) / c["isolates"]}, lang)
    return render_id("cds_untested", slots, lang)


def _numbers(wins: dict, drug: str, indication: str, lang: str) -> tuple[dict, dict, str | None]:
    """The 4-week and 52-week counts, and why no number may be shown (None when it may)."""
    recent, year = counts(wins["4w"], drug, "4w"), counts(wins["12m"], drug, "12m")
    return recent, year, _not_offered(drug, indication, lang) or _untested(year, lang) or _untested(recent, lang)


def order_drugs(ds, indication: str, lang: str = "en") -> list[dict]:
    """The drug picker for one indication: the order drugs with a reported result on its specimen in the data."""
    indication = _known(indication_key(indication), C.INDICATIONS, "indication")
    x = ds.isolates
    reported = x.loc[x.specimen == C.INDICATIONS[indication]["specimen"], C.DRUGS].notna().any()
    return [
        {"drug": d, "name": label(name, lang), "atc": atc, "aware": C.ORDER_AWARE[name]}
        for d, name, atc in C.ORDER_DRUGS
        if reported[d]
    ]


# --------------------------------------------------------------------------- patient and population
def patient_info(ds, patient_id: str, as_of) -> dict:
    if not isinstance(patient_id, str) or not (ds.patients.patient_id == patient_id).any():
        raise OrderError(f"unknown patient {patient_id!r}")
    r = ds.patients[ds.patients.patient_id == patient_id].iloc[0]
    return {
        "id": patient_id,
        "sex": r.sex,
        "age": pd.Timestamp(as_of).year - int(r.birth_year),
        "home_area": r.home_area,
    }


def population(ds, as_of, unit: str, indication: str, patient: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Isolates of the indication's specimen up to `as_of`: the unit's own or, for a community unit (ED and health
    centres), those units' isolates from patients living in the patient's home area. A uti also matches the patient's
    sex, and a reference organism (uti: E. coli) narrows the rows to that organism."""
    ind, community = C.INDICATIONS[indication], unit in C.COMMUNITY_UNITS
    f = {
        "units": sorted(C.COMMUNITY_UNITS) if community else [unit],
        "specimen": ind["specimen"],
        "organism": ind["reference_organism"],
        "home_area": patient["home_area"] if community and patient else None,
        "sex": patient["sex"] if ind["sex_matched"] and patient else None,
    }
    x = ds.isolates
    keep = x.ward_code.isin(f["units"]) & (x.specimen == f["specimen"]) & (x.sample_date <= pd.Timestamp(as_of))
    for col in ("organism", "home_area", "sex"):
        if f[col] is not None:
            keep &= x[col] == f[col]
    return x[keep], f


def _history(ds, as_of, patient_id: str) -> pd.DataFrame:
    """This patient's isolates in the 52 weeks to `as_of`, newest first."""
    x = ds.isolates
    rows = data.window(x[x.patient_id == patient_id], as_of, C.WINDOWS["12m"])
    return rows.sort_values("sample_date", ascending=False, kind="stable")


def _previous(history: pd.DataFrame, drug: str | None, lang: str = "en") -> list[dict]:
    """Each isolate with its effective result for `drug`. When a species rule counts a reported result differently
    (C. freundii cefuroxime S counts as R), `reported_result` keeps the laboratory's own result and the reason says so.
    An ordered flucloxacillin is read from the cefoxitin screen, so the screen's result is never shown as its own."""
    none = pd.Series(None, index=history.index, dtype=object)
    result, reason = _effective(history, drug) if drug else (none, none)
    lab = history[drug] if drug in C.DRUGS and drug != "FOX" else none
    rows = []
    for i, r in history.iterrows():
        overruled = lab[i] if isinstance(lab[i], str) and lab[i] != result[i] else None
        why = label(_reason_text(drug, reason[i]), lang)
        if overruled:
            why = render_id("cds_reported_overruled", {"reason": why, "result": overruled}, lang)
        rows.append(
            {
                "date": r.sample_date.date().isoformat(),
                "unit": r.ward_code,
                "specimen": r.specimen,
                "organism": r.organism,
                "flags": [f.upper() for f in FLAGS if r[f] == 1],
                "drug_result": result[i],
                "reason": reason[i],
                "reported_result": overruled,
                "reason_text": why,
            }
        )
    return rows


def previous_results(ds, as_of, patient_id: str, drug: str | None = None, lang: str = "en") -> list[dict]:
    """This patient's isolates in the 52 weeks to `as_of`, newest first, each with the effective result for `drug`,
    its `phenotype_rules.REASONS` code and the words for it."""
    return _previous(_history(ds, as_of, patient_id), drug, lang)


def _acquired(h: dict) -> bool:
    """An R the isolate acquired, not a property of its species: only this warns."""
    return h["drug_result"] == "R" and h["reason"] not in SPECIES_LEVEL


def _species_notes(previous: list[dict], name: str, lang: str) -> list[str]:
    """One passive note per organism whose R to this drug is a property of its species (clinical review D-M4)."""
    notes = {}
    for h in previous:
        if h["drug_result"] == "R" and h["reason"] in SPECIES_LEVEL and h["organism"] not in notes:
            species = render_id(f"cds_species__{h['reason']}", {"organism": short_organism(h["organism"])}, lang)
            notes[h["organism"]] = render_id(
                "cds_species_note",
                {"drug_name": name, "species": species, "specimen": h["specimen"], "date": h["date"]},
                lang,
            )
    return list(notes.values())


# --------------------------------------------------------------------------- reasons (what fires)
# Each reason: kind, level (LEVELS), id, signal_id, flagged_by, flagged_on, rule, headline (None for a notice),
# summary (the chip and the CDS card summary, under 140 characters) and text (what is happening; None for a notice).
def _alert_text(a: dict, lang: str) -> str:
    """The alert's own message, then who flagged it and until when."""
    return render_id(
        "cds_alert_text",
        {
            "message": a["message"],
            "role": a["approved_by_role"].lower(),
            "approved_on": a["approved_on"],
            "expires_on": a["expires_on"],
        },
        lang,
    )


def _alert_title(a: dict, lang: str) -> str:
    """What an alert flagged, read from its own fields: "Possible ESBL E. coli cluster" when it carries a shared
    antibiogram, "VRE E. faecalis alert" for a marker finding, else "Infection-control alert"."""
    marker = (a["marker"] or "").upper()
    what = (
        marker
        if marker == "MRSA"
        else " ".join(filter(None, [marker, a["organism"] and short_organism(a["organism"])]))
    )
    if not what:
        return render_id("cds_alert_title_plain", {}, lang)
    return render_id("cds_alert_title_cluster" if a["profile"] else "cds_alert_title_marker", {"what": what}, lang)


def _antibiogram_how(a: dict, drug: str) -> str | None:
    """How the alert's antibiogram is R to the drug: "reported", or how it was read when the laboratory did not
    report it (MRSA: every beta-lactam). None when the alert's antibiogram is not R to the drug."""
    if drug not in a["resistant_to"]:
        return None
    isolate = {
        "organism": a["organism"],
        "esbl": int(a["marker"] == "esbl"),
        "mrsa": int(a["marker"] == "mrsa"),
        **dict(token.split(":") for token in (a["profile"] or "").split()),
    }
    return _reason_text(drug, _effective(pd.DataFrame([isolate]), drug)[1].iloc[0])


def _alert_reason(a: dict, unit: str, drug: str, indication: str, name: str, lang: str) -> dict:
    """A warning when the alert applies to this drug and indication (`drugs`, `indications`; none = every
    indication), else a one-line notice."""
    slots = {"title": _alert_title(a, lang), "unit": unit, "ward_label": C.WARD_LABELS[unit], "drug": name.lower()}
    base = {
        "kind": "alert",
        "id": a["id"],
        "signal_id": a["signal_id"],
        "flagged_by": label(a["approved_by_role"], lang),
        "flagged_on": a["approved_on"],
    }
    in_scope = not a["indications"] or indication in a["indications"]
    if drug in a["drugs"] and in_scope:
        how = _antibiogram_how(a, drug)
        headline = (
            "cds_alert_headline_applies"
            if how is None
            else "cds_alert_headline_r"
            if how == "reported"
            else "cds_alert_headline_r_how"
        )
        return {
            **base,
            "level": "warning",
            "rule": label("an approved alert applies to this unit, drug and indication", lang),
            "headline": render_id(headline, slots | {"how": how}, lang),
            "summary": render_id("cds_alert_summary_applies" if how is None else "cds_alert_summary_r", slots, lang),
            "text": _alert_text(a, lang),
        }
    if drug not in a["drugs"]:
        summary = render_id("cds_notice_drug", slots, lang)
    else:
        indications = join([label(C.INDICATIONS[i]["label"].lower(), lang) for i in a["indications"]], lang)
        summary = render_id("cds_notice_indications", slots | {"indications": indications}, lang)
    return {
        **base,
        "level": "notice",
        "rule": label("an approved alert on this unit does not apply to this order", lang),
        "headline": None,
        "summary": summary,
        "text": None,
    }


def _own_history_reason(h: dict, name: str, lang: str) -> dict:
    """`h` is a previous result already in `lang` (its reason_text)."""
    slots = {
        "organism": short_organism(h["organism"]),
        "date": h["date"],
        "drug": name.lower(),
        "drug_name": name,
        "how": h["reason_text"],
        "specimen": h["specimen"],
        "unit": h["unit"],
    }
    reported = h["reason_text"] == label("reported", lang)  # an ordered flucloxacillin is read, not reported
    return {
        "kind": "own_history",
        "level": "warning",
        "id": "own_history",
        "signal_id": None,
        "flagged_by": label("Laboratory result", lang),
        "flagged_on": h["date"],
        "rule": render_id("cds_rule_own_history", {"weeks": HISTORY_WEEKS}, lang),
        "headline": render_id("cds_own_headline" if reported else "cds_own_headline_how", slots, lang),
        "summary": render_id("cds_own_summary", slots, lang),
        "text": render_id("cds_own_text", slots, lang),
    }


def _policy_live(ps: dict, as_of: str) -> bool:
    """Strict as-of: a policy state computed for a later date never speaks for this one."""
    return ps["active"] and ps["as_of"] <= as_of


def _policy_units(ps: dict) -> set[str]:
    return set(ps["order_units"]) | set(ps["population"].get("wards", []))


def policy_summary(ps: dict, lang: str = "en") -> str:
    """'Trimethoprim: 20.4% resistant (160 of 786, last 52 weeks), above local 20% line' (under 140 characters)."""
    where = "above" if ps["rate"] > ps["threshold"] else "at"
    return render_id(
        f"cds_policy_summary__{where}",
        {
            "drug_label": ps["drug_label"],
            "rate": ps["rate"],
            "counts": (ps["x"], ps["n"]),
            "weeks": ps["window_days"] // 7,
            "threshold": ps["threshold"],
        },
        lang,
    )


def policy_population(ps: dict, lang: str = "en") -> str:
    """'urinary E. coli, women, health centres PHC-N + PHC-S, first isolate per patient in the window'."""
    wards = ps["population"].get("wards") or []
    units = {"units": " + ".join(wards)}
    if not wards:
        where = label("all units", lang)
    elif set(wards) <= {"PHC-N", "PHC-S"}:
        where = render_id("cds_where_health_centres", units, lang)
    else:
        where = render_id("cds_where_units", units, lang)
    who = {"F": "women", "M": "men"}.get(ps["population"].get("sex"))
    slots = {
        "specimen": SPECIMEN_WORDS[ps["specimen"]],
        "organism": short_organism(ps["organism"]),
        "who": who,
        "where": where,
        "rule": COUNTING_RULES[ps["counting_rule"]],
    }
    return render_id("cds_policy_population" if who else "cds_policy_population_all", slots, lang)


def _policy_reason(ps: dict, lang: str) -> dict:
    slots = {
        "population": policy_population(ps, lang),
        "crossed_on": ps["crossed_on"],
        "rate_prior": ps["rate_prior"],
        "counts_prior": (ps["x_prior"], ps["n_prior"]),
    }
    summary = policy_summary(ps, lang)
    return {
        "kind": "policy",
        "level": "info",
        "id": ps["id"],
        "signal_id": ps["signal_id"],
        "flagged_by": label("Infection control", lang),
        "flagged_on": ps["crossed_on"],
        "rule": label("a local policy line for this drug is at or above its threshold", lang),
        "headline": f"{summary}.",
        "summary": summary,
        "text": render_id("cds_policy_text" if ps["rate_prior"] is None else "cds_policy_text_prior", slots, lang),
    }


def _line_reason(
    nums: dict | None, unit: str, indication: str, drug: str, name: str, word: str, lang: str
) -> dict | None:
    """Info when this population's 52-week resistance, on 30 or more isolates, is at or above a line infection control
    set for this indication and drug (`config.EMPIRICAL_LINES`), or within INFO_MARGIN below it."""
    line = C.EMPIRICAL_LINES.get(indication, {}).get(drug)
    if line is None or nums is None or nums["state12"] != "ok" or nums["pct12"] < line - C.INFO_MARGIN:
        return None
    p = nums["pct12"]
    where = "above" if p > line else "at" if p == line else "close"
    slots = {
        "drug_name": name,
        "drug": name.lower(),
        "counts": (nums["r12"], nums["n12"]),
        "word": word,
        "rate": p,
        "window": WINDOW_TEXT["12m"],
        "unit": unit,
        "line": line,
        "indication": C.INDICATIONS[indication]["label"].lower(),
    }
    summary = render_id(f"cds_line_summary__{where}", slots, lang)
    return {
        "kind": "local_line",
        "level": "info",
        "id": f"line:{indication}:{drug}",
        "signal_id": None,
        "flagged_by": label("Infection control", lang),
        "flagged_on": None,
        "rule": label(
            "this population's observed resistance is at, above or close to a local line for this drug", lang
        ),
        "headline": f"{summary}.",
        "summary": summary,
        "text": render_id("cds_line_text", slots, lang),
    }


# --------------------------------------------------------------------------- the order context
def _population_text(unit: str, f: dict, lang: str) -> str:
    who = {"F": "women", "M": "men"}.get(f["sex"])
    bits = [f["specimen"], short_organism(f["organism"]) if f["organism"] else "all organisms", *([who] if who else [])]
    slots = {"unit": unit, "home_area": f["home_area"], "details": ", ".join(label(b, lang) for b in bits)}
    return render_id("cds_population_community" if f["home_area"] else "cds_population_unit", slots, lang)


def _counts_text(c: dict, word: str, lang: str) -> str:
    slots = {
        "window": WINDOW_TEXT[c["window"]],
        "n": c["n"],
        "counts": (c["r"], c["n"]),
        "word": word,
        "rate": c["pct"],
        "level": 0.95,
        "ci": c["ci"],
    }  # stats.jeffreys_interval is a 95% interval
    if c["state"] == "not_enough_data":
        return render_id("cds_counts_none", slots, lang)
    return render_id(f"cds_counts__{c['state']}", slots, lang)


def _no_data(name: str, unit: str, not_shown: str | None, year: dict, lang: str) -> tuple[str, str] | None:
    """Chip and rule when this population has no number for the drug, else None."""
    if not_shown:
        return (
            render_id("cds_chip_not_shown", {"drug_name": name, "reason": not_shown}, lang),
            label("No data: no number is shown for this drug in this population.", lang),
        )
    if year["state"] == "not_enough_data":
        slots = {"unit": unit, "drug": name.lower(), "n": year["n"], "window": WINDOW_TEXT["12m"]}
        return (
            render_id("cds_chip_not_enough", slots, lang),
            render_id("cds_rule_not_enough", {"min_n": C.SMALL_N_NONE, "weeks": HISTORY_WEEKS}, lang),
        )
    return None


def _verdict(
    top: dict | None, stage: str, no_data: tuple[str, str] | None, unit: str, as_of: str, lang: str
) -> tuple[str, str, str]:
    """State, chip and the plain sentence of the rule that fired. A warning waits for signing."""
    if top is None:
        if no_data:
            return ("no_data", *no_data)
        return (
            "quiet",
            render_id("cds_chip_quiet", {"unit": unit, "as_of": as_of}, lang),
            label(
                "Quiet: no alert, no local line near, and no acquired resistance in this patient's previous isolates.",
                lang,
            ),
        )
    if top["level"] == "warning" and stage == "select":
        return "info", top["summary"], render_id("cds_rule_select", {"rule": top["rule"]}, lang)
    return top["level"], top["summary"], render_id(f"cds_rule__{top['level']}", {"rule": top["rule"]}, lang)


def order_context(
    ds,
    as_of,
    patient_id: str | None,
    unit: str,
    indication: str,
    drug: str,
    stage: str = "select",
    alerts=(),
    policy_states=(),
    lang: str = "en",
) -> dict:
    """What the order screen shows for one draft order (CONTRACTS.md 7b): state quiet | no_data | notice | info |
    warning, about the drug entered only.

    `alerts` are `store.alerts(session)` rows (inactive ones are ignored here); `policy_states` are
    `detectors.policy.policy_states(ds, as_of)` rows. `patient_id=None` gives unit-level numbers only. Texts are in
    `lang`; the card key, codes and numbers are the same in every language."""
    as_of = iso_day(as_of)
    unit, drug, stage = (
        _known(unit, C.WARD_LABELS, "unit"),
        _known(drug, ORDER_NAMES, "drug"),
        _known(stage, STAGES, "stage"),
    )
    indication = _known(indication_key(indication), C.INDICATIONS, "indication")
    patient = patient_info(ds, patient_id, as_of) if patient_id is not None else None
    name, ind = label(ORDER_NAMES[drug], lang), C.INDICATIONS[indication]
    word = "resistant" if ind["reference_organism"] else "not covered"
    rows, pop = population(ds, as_of, unit, indication, patient)
    recent, year, not_shown = _numbers(_windows(rows, as_of), drug, indication, lang)
    nums = (
        None
        if not_shown
        else {
            **{k: recent[k] for k in ("r", "n", "pct", "ci", "state", "window")},
            "r12": year["r"],
            "n12": year["n"],
            "pct12": year["pct"],
            "ci12": year["ci"],
            "state12": year["state"],
        }
    )
    previous = _previous(_history(ds, as_of, patient_id) if patient else ds.isolates.iloc[:0], drug, lang)

    own_r = next(filter(_acquired, previous), None)
    policy = [
        ps
        for ps in policy_states
        if _policy_live(ps, as_of)
        and ps["drug"] == drug
        and indication_key(ps["order_indication"]) == indication
        and unit in _policy_units(ps)
        and (patient is None or ps["population"].get("sex") in (None, patient["sex"]))
    ]
    unit_alerts = [a for a in alerts if is_active(a, as_of) and unit in a["wards"]]
    reasons = [_alert_reason(a, unit, drug, indication, name, lang) for a in unit_alerts]
    reasons += [_own_history_reason(own_r, name, lang)] if own_r else []
    reasons += [_policy_reason(ps, lang) for ps in policy]
    if not policy:  # the policy line already says it
        reasons += filter(None, [_line_reason(nums, unit, indication, drug, name, word, lang)])
    reasons.sort(key=lambda r: LEVELS.index(r["level"]))  # stable: alerts before own history, policy before the line
    top = reasons[0] if reasons else None
    state, chip, rule = _verdict(top, stage, _no_data(name, unit, not_shown, year, lang), unit, as_of, lang)
    flags = state in ("info", "warning")
    pending = flags and top["level"] == "warning" and stage == "select"

    lines = []
    if flags:
        lines.append(
            {
                "key": "happening",
                "text": top["text"],
                "source": {k: top[k] for k in ("kind", "id", "flagged_by", "flagged_on")},
            }
        )
    if state != "notice":  # a notice is one line about the unit, without numbers
        slots = {"drug_name": name, "population": _population_text(unit, pop, lang), "reason": not_shown}
        text = (
            render_id("cds_your_drug_not_shown", slots, lang)
            if not_shown
            else render_id(
                "cds_your_drug",
                slots | {"recent": _counts_text(recent, word, lang), "year": _counts_text(year, word, lang)},
                lang,
            )
        )
        lines.append({"key": "your_drug", "numbers": nums, "not_shown": not_shown, "text": text})

    link = {
        "ward": unit,
        "specimen": ind["specimen"],
        **({"organism": pop["organism"]} if pop["organism"] else {}),
        "as_of": as_of,
    }
    ask = label(ASK, lang) + (f" {label(SIGN_NOTE, lang)}" if pending else "")
    return {
        "state": state,
        "stage": stage,
        "interruptive": state == "warning",
        "chip": chip,
        "headline": top["headline"] if flags else None,
        "ask": ask if flags else None,
        "rule": rule,
        "as_of": as_of,
        "unit": unit,
        "indication": indication,
        "drug": drug,
        "drug_name": name,
        "patient": patient,
        "previous_results": previous,
        "notes": _species_notes(previous, name, lang),
        "lines": lines,
        "actions": {
            "keep": {
                "label": render_id("cds_keep", {"drug": name.lower()}, lang),
                "reasons": [label(r, lang) for r in C.KEEP_REASONS],
            },
            "edit": {"label": label(EDIT_LABEL, lang)},
            "details": {"label": label(DETAILS_LABEL, lang), "link": "/#/ward?" + urlencode(link, quote_via=quote)},
        },
        "source": {"kind": top["kind"], "id": top["id"], "signal_id": top["signal_id"]} if top else None,
        "card_key": _uuid(as_of, unit, indication, drug, state, top["id"] if top else None),
        "evidence": {
            "population": {**pop, "date_to": as_of},
            "counts": nums,
            "not_shown": not_shown,
            "reasons": [{k: r[k] for k in ("kind", "level", "id", "summary")} for r in reasons],
            "method": label(METHOD, lang),
        },
        "note": label(LAG_NOTE, lang),
        "small_print": label(SMALL_PRINT, lang),
    }


# --------------------------------------------------------------------------- My ward banners
def banners(as_of, unit: str, alerts, policy_states, *, specimen_group: str, lang: str = "en") -> list[dict]:
    """Passive banners for My ward: alerts active at `as_of + 1` on this unit, and policy lines at or above their
    threshold that name this unit and whose specimen is in the view's `specimen_group` (the trimethoprim line is
    about urine, so a blood or wound view never shows it). No banner names a drug to use instead."""
    as_of, specimens = iso_day(as_of), C.SPECIMEN_GROUPS[_known(specimen_group, C.SPECIMEN_GROUPS, "specimen group")]
    out = [
        {"kind": "alert", "id": a["id"], "signal_id": a["signal_id"], "drugs": a["drugs"], "text": _alert_text(a, lang)}
        for a in alerts
        if is_active(a, as_of) and unit in a["wards"]
    ]
    out += [
        {
            "kind": "policy",
            "id": ps["id"],
            "signal_id": ps["signal_id"],
            "drugs": [ps["drug"]],
            "text": render_id(
                "cds_banner_policy",
                {
                    "summary": policy_summary(ps, lang),
                    "message": ps["message"],
                    "population": policy_population(ps, lang),
                },
                lang,
            ),
        }
        for ps in policy_states
        if _policy_live(ps, as_of) and unit in _policy_units(ps) and ps["specimen"] in specimens
    ]
    return out
