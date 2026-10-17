"""The doctor's order context and CDS Hooks 2.0 cards (order-select, order-sign). CONTRACTS.md sections 7 and 7b.

Pure and deterministic. Something is said about an order only because of:
  (a) an approved infection-control alert active at `as_of + 1` on the ordering unit;
  (b) this patient's own isolate in the 52 weeks to `as_of` with an acquired R to the ordered drug. An intrinsic or
      no-breakpoint R is a property of the species: a passive note, never a warning;
  (c) a local policy line at or above its threshold, or the population's observed resistance near the example
      empirical line in `config.EMPIRICAL_LINES`.
Only (a) covering this drug and (b) interrupt, and only when the order is signed; at selection they show as info.
Results come from the shared `phenotype_rules.effective`, so the numbers equal My ward's for the same population, and
My ward's rules decide whether a number is shown at all (CONTRACTS 4.1): never for a urine-only drug outside urine,
for a drug the indication's reference organism is intrinsically resistant to, or for a drug with a result on fewer
than 90% of the population's isolates. Never a block and never a patient-level estimate. This module imports neither
the narrator nor the second-opinion adapter (a test enforces it).
"""
import copy
import re
import uuid
from urllib.parse import quote, urlencode

import pandas as pd

from . import config as C
from . import data, stats
from .phenotype_rules import REASON_TEXT, effective
from .render import fmt
from .store import is_active

SLUG = re.sub(r"[^a-z0-9]+", "-", C.APP_NAME.lower()).strip("-")
SOURCE_LABEL = f"{C.APP_NAME} · infection control"
SMALL_PRINT = "Observed unit-level information, not a prediction for this patient. The doctor decides."
LAG_NOTE = f"Dates are sample dates; results usually arrive about {C.RESULT_LAG_DAYS} days later."
SIGN_NOTE = "It will ask again when the order is signed."
ALTERNATIVES_LABEL = "Alternatives from the local guide (example, to be set by Tyks)"
METHOD = ("first isolate per patient x organism x specimen; effective S/R from the shared phenotype rules (EUCAST "
          "breakpoints, expected resistant phenotypes and expert rules, and this laboratory's ESBL reporting rule); "
          "no number for a drug with a result on fewer than 90% of the population's isolates; Jeffreys 95% interval")
ATC_SYSTEM = "http://www.whocc.no/atc"
OVERRIDE_SYSTEM = f"urn:{SLUG}:keep-reason"
STAGES = ("select", "sign")
SERVICES = [
    {"hook": "order-select", "id": f"{SLUG}-order-select", "title": f"{C.APP_NAME} unit resistance context",
     "description": "When an antibiotic is selected, shows passive information from approved infection-control alerts, "
                    "local policy lines and the unit's observed counts. Never interrupts at selection.", "prefetch": {}},
    {"hook": "order-sign", "id": f"{SLUG}-order-sign", "title": f"{C.APP_NAME} unit resistance check",
     "description": "Before an antibiotic order is signed, asks once when an approved alert covers this unit and drug, or "
                    "the patient's own recent isolate had acquired resistance to it. The doctor decides.", "prefetch": {}},
]
ORDER_NAMES = {code: name for code, name, _ in C.ORDER_DRUGS}
ORDER_ATC = {code: atc for code, _, atc in C.ORDER_DRUGS}
# Orders are read through config.ATC, minus screening markers (an order coded as cefoxitin is not flucloxacillin),
# plus the order picker's own codes.
ATC_TO_DRUG = {atc: d for atc, d in C.ATC.items() if d not in C.HIDDEN_AS_OPTION} | {a: d for d, a in ORDER_ATC.items()}
INDICATION_ALIASES = {"urinary": "uti"}  # policy lines and CDS requests may name the indication by organ
WINDOW_TEXT = {w: C.WINDOW_LABELS[w].lower() for w in ("4w", "12m")}  # 364 days is "last 52 weeks", not 12 months
# EUCAST Expected Resistant Phenotypes v1.2 and breakpoint dashes describe the species, not a resistance the
# isolate acquired: they never make an own-history warning and never block an alternative.
SPECIES_LEVEL = {"intrinsic", "no_breakpoint"}
SPECIES_TEXT = {"intrinsic": "EUCAST lists {org} as intrinsically resistant", "no_breakpoint": "EUCAST has no breakpoint for {org}"}
SPECIMEN_WORDS = {"urine": "urinary", "blood": "blood", "wound": "wound"}
COUNTING_RULES = {"readme_period": "first isolate per patient in the window", "30d": "first isolate per patient in 30 days"}
_NS = uuid.UUID("6f2b6c1e-8d1a-5c3e-9a57-5a1d3c0e7b21")
_MARKDOWN = re.compile(r"([\\`*_\[\]<>#|])")


class OrderError(ValueError):
    """An order this service cannot read: unknown unit, indication, drug, patient or hook (the API answers 422)."""


# --------------------------------------------------------------------------- small helpers
def _iso(value) -> str:
    try:
        return pd.Timestamp(str(value)[:10]).date().isoformat()
    except ValueError as e:
        raise OrderError(f"not a date: {value!r}") from e


def _indication(value):
    return INDICATION_ALIASES.get(value, value) if isinstance(value, str) else value


def _known(value, allowed, what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise OrderError(f"unknown {what}: {value!r}")
    return value


def _uuid(*parts) -> str:
    return str(uuid.uuid5(_NS, "|".join(str(p) for p in parts)))


def _short(organism: str) -> str:
    genus, _, species = organism.partition(" ")
    return f"{genus[0]}. {species}" if species else organism


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _md(text: str) -> str:
    """Alert messages are typed by users; escape them so a card's markdown cannot carry links, HTML or emphasis."""
    return _MARKDOWN.sub(r"\\\1", text)


def _line(indication: str, drug: str) -> float:
    lines = C.EMPIRICAL_LINES[indication]
    return lines.get(drug, lines["_default"])


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


def _windows(rows: pd.DataFrame, as_of) -> dict[str, pd.DataFrame]:
    """First isolate per patient x organism x specimen in each window (`4w`, `12m`)."""
    return {w: data.first_isolates(data.window(rows, as_of, C.WINDOWS[w])) for w in WINDOW_TEXT}


def counts(first: pd.DataFrame, drug: str, window: str) -> dict:
    """R (resistant or not covered) of n with a result, among one window's first isolates. `isolates` and `untested`
    ([organism, n] without a result, largest first) decide whether the number is shown at all."""
    result = _effective(first, drug)[0]
    r, n = int((result == "R").sum()), int(result.notna().sum())
    gaps = first.organism[result.isna()].value_counts()
    return {"r": r, "n": n, "pct": r / n if n else None, "ci": list(stats.jeffreys_interval(r, n)) if n else None,
            "state": stats.n_state(n), "window": window, "isolates": len(first),
            "untested": sorted(([o, int(k)] for o, k in gaps.items()), key=lambda g: (-g[1], g[0]))}


def _not_offered(drug: str, indication: str) -> str | None:
    """Why the indication never gets a number for this drug, whatever the data; None when it can."""
    ind = C.INDICATIONS[indication]
    if drug in C.URINE_ONLY and ind["specimen"] != "urine":
        return "tested on urine isolates only in this panel"
    org = ind["reference_organism"]
    if org:  # the shared rules on one isolate of the reference organism with no result say what the species implies
        why = _effective(pd.DataFrame({"organism": [org]}), drug)[1].iloc[0]
        if why in SPECIES_LEVEL:
            return SPECIES_TEXT[why].format(org=_short(org))
    return None


def _untested(c: dict) -> str | None:
    """My ward's eligibility rule (CONTRACTS 4.1): with 10 or more isolates in a window, a result on at least 90%."""
    if c["isolates"] < C.SMALL_N_NONE or c["n"] / c["isolates"] >= C.ELIGIBLE_MIN_TESTED_SHARE:
        return None
    names = [_short(o) for o, _ in c["untested"][:3]] + (["other organisms"] if len(c["untested"]) > 3 else [])
    reason = f"not tested on {_join(names)} in this panel"
    if c["n"]:
        reason += f"; no result for {fmt(1 - c['n'] / c['isolates'], 'pct0')} of this population's isolates"
    return reason


def _numbers(wins: dict, drug: str, indication: str) -> tuple[dict, dict, str | None]:
    """The 4-week and 52-week counts, and why no number may be shown (None when it may)."""
    recent, year = counts(wins["4w"], drug, "4w"), counts(wins["12m"], drug, "12m")
    return recent, year, _not_offered(drug, indication) or _untested(year) or _untested(recent)


def order_drugs(indication: str) -> list[dict]:
    """The drug picker for one indication: the order drugs this view can give numbers for (CONTRACTS 7b)."""
    indication = _known(_indication(indication), C.INDICATIONS, "indication")
    return [{"drug": d, "name": name, "atc": atc, "aware": C.ORDER_AWARE[name]}
            for d, name, atc in C.ORDER_DRUGS if _not_offered(d, indication) is None]


# --------------------------------------------------------------------------- patient and population
def patient_info(ds, patient_id: str, as_of) -> dict:
    if not isinstance(patient_id, str) or not (ds.patients.patient_id == patient_id).any():
        raise OrderError(f"unknown patient {patient_id!r}")
    r = ds.patients[ds.patients.patient_id == patient_id].iloc[0]
    return {"id": patient_id, "sex": r.sex, "age": pd.Timestamp(as_of).year - int(r.birth_year), "home_area": r.home_area}


def population(ds, as_of, unit: str, indication: str, patient: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Isolates of the indication's specimen up to `as_of`: the unit's own or, for a community unit (ED and health
    centres), those units' isolates from patients living in the patient's home area. A uti also matches the patient's
    sex, and a reference organism (uti: E. coli) narrows the rows to that organism."""
    ind, community = C.INDICATIONS[indication], unit in C.COMMUNITY_UNITS
    f = {"units": sorted(C.COMMUNITY_UNITS) if community else [unit], "specimen": ind["specimen"],
         "organism": ind["reference_organism"], "home_area": patient["home_area"] if community and patient else None,
         "sex": patient["sex"] if ind["sex_matched"] and patient else None}
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


def _previous(history: pd.DataFrame, drug: str | None) -> list[dict]:
    none = pd.Series(None, index=history.index, dtype=object)
    result, reason = _effective(history, drug) if drug else (none, none)
    return [{"date": r.sample_date.date().isoformat(), "unit": r.ward_code, "specimen": r.specimen,
             "organism": r.organism, "flags": [f.upper() for f in ("esbl", "mrsa", "vre", "cpe") if r[f] == 1],
             "drug_result": result[i], "reason": reason[i], "reason_text": REASON_TEXT.get(reason[i])}
            for i, r in history.iterrows()]


def previous_results(ds, as_of, patient_id: str, drug: str | None = None) -> list[dict]:
    """This patient's isolates in the 52 weeks to `as_of`, newest first, each with the effective result for `drug`,
    its `phenotype_rules.REASONS` code and the words for it."""
    return _previous(_history(ds, as_of, patient_id), drug)


def _acquired(h: dict) -> bool:
    """An R the isolate acquired, not a property of its species: only this warns, and blocks an alternative."""
    return h["drug_result"] == "R" and h["reason"] not in SPECIES_LEVEL


def _acquired_drugs(history: pd.DataFrame) -> set[str]:
    """Order drugs with an acquired R in this patient's history: offering them back would itself warn."""
    return {d for d in ORDER_NAMES if any(map(_acquired, _previous(history, d)))}


def _species_notes(previous: list[dict], name: str) -> list[str]:
    """One passive note per organism whose R to this drug is a property of its species (clinical review D-M4)."""
    notes = {}
    for h in previous:
        if h["drug_result"] == "R" and h["reason"] in SPECIES_LEVEL:
            notes.setdefault(h["organism"], f"{name}: {SPECIES_TEXT[h['reason']].format(org=_short(h['organism']))} "
                                            f"(this patient's {h['specimen']} isolate of {fmt(h['date'], 'date')}).")
    return list(notes.values())


# --------------------------------------------------------------------------- reasons (what fires, in display order)
def _flagged(a: dict) -> str:
    return (f"Flagged by {a['approved_by_role'].lower()}, {fmt(a['approved_on'], 'date')}; "
            f"expires {fmt(a['expires_on'], 'short_date')}.")


def _alert_resistant(a: dict) -> set[str]:
    """What an alert covers plus its antibiogram's R (`resistant_to`, when the alert carries it)."""
    return set(a["drugs"]) | set(a.get("resistant_to") or ())


def _alert_reason(a: dict, unit: str, name: str, covers: bool) -> dict:
    base = {"kind": "alert", "id": a["id"], "signal_id": a["signal_id"], "flagged_by": a["approved_by_role"],
            "flagged_on": a["approved_on"]}
    if covers:
        return {**base, "level": "warning", "rule": "an approved alert covers this unit and this drug",
                "summary": f"{name} on {unit}: an approved infection-control alert covers this drug",
                "chip": f"Infection-control alert covers {name.lower()} · {unit}", "text": f"{a['message']} {_flagged(a)}"}
    return {**base, "level": "info", "rule": "an approved alert covers this unit but not this drug",
            "summary": f"Approved infection-control alert on {unit}; it does not cover {name.lower()}",
            "chip": f"Infection-control alert on {unit}",
            "text": f"{a['message']} {_flagged(a)} It does not cover {name.lower()}."}


def _own_history_reason(h: dict, name: str) -> dict:
    when, org = fmt(h["date"], "date"), _short(h["organism"])
    return {"kind": "own_history", "level": "warning", "id": "own_history", "signal_id": None,
            "flagged_by": "Laboratory result", "flagged_on": h["date"],
            "rule": "this patient's own isolate in the last 52 weeks had acquired resistance to this drug",
            "summary": f"{name}: this patient's {org} of {when} was R ({h['reason_text']})",
            "chip": f"This patient's {org} of {when} was {name.lower()} R",
            "text": f"This patient's {org} ({h['specimen']}, {h['unit']}) of {when} was {name.lower()} R "
                    f"({h['reason_text']})."}


def _policy_live(ps: dict, as_of: str) -> bool:
    """Strict as-of: a policy state computed for a later date never speaks for this one."""
    return ps["active"] and ps["as_of"] <= as_of


def _policy_units(ps: dict) -> set[str]:
    return set(ps["order_units"]) | set(ps["population"].get("wards", []))


def policy_summary(ps: dict) -> str:
    """'Trimethoprim: 20.4% resistant (160 of 786, last 52 weeks), above local 20% line' (under 140 characters)."""
    where = "above" if ps["rate"] > ps["threshold"] else "at"
    return (f"{ps['drug_label']}: {fmt(ps['rate'], 'pct1')} resistant ({fmt((ps['x'], ps['n']), 'xofn')}, last "
            f"{ps['window_days'] // 7} weeks), {where} local {fmt(ps['threshold'], 'pct0')} line")


def policy_population(ps: dict) -> str:
    """'urinary E. coli, women, health centres PHC-N + PHC-S, first isolate per patient in the window'."""
    wards = ps["population"].get("wards") or []
    if not wards:
        where = "all units"
    elif set(wards) <= {"PHC-N", "PHC-S"}:
        where = "health centres " + " + ".join(wards)
    else:
        where = "units " + " + ".join(wards)
    who = {"F": "women", "M": "men"}.get(ps["population"].get("sex"))
    return ", ".join([f"{SPECIMEN_WORDS[ps['specimen']]} {_short(ps['organism'])}", *([who] if who else []), where,
                      COUNTING_RULES[ps["counting_rule"]]])


def _policy_reason(ps: dict) -> dict:
    earlier = (f" Same window a year earlier: {fmt(ps['rate_prior'], 'pct1')} "
               f"({fmt((ps['x_prior'], ps['n_prior']), 'xofn')})." if ps["rate_prior"] is not None else "")
    return {"kind": "policy", "level": "info", "id": ps["id"], "signal_id": ps["signal_id"],
            "flagged_by": "Infection control", "flagged_on": ps["crossed_on"],
            "rule": "a local policy line for this drug is at or above its threshold", "summary": policy_summary(ps),
            "chip": f"Above the local line for {ps['drug_label'].lower()}",
            "text": f"{policy_summary(ps)}. Population: {policy_population(ps)}.{earlier} Local policy line set by "
                    f"infection control; crossed week ending {fmt(ps['crossed_on'], 'date')}. {ps['message']}: "
                    f"{ps['local_guide_alternative']['text']}.",
            "alternative": ps["local_guide_alternative"]["drug"]}


def _empirical_reason(nums: dict, unit: str, indication: str, drug: str, name: str, word: str) -> dict | None:
    """Info when the population's 52-week resistance is within INFO_MARGIN of the example empirical line, or above."""
    line = _line(indication, drug)
    if nums["state12"] == "not_enough_data" or nums["pct12"] < line - C.INFO_MARGIN:
        return None
    where = "above" if nums["pct12"] >= line else "close to"
    observed = f"{fmt((nums['r12'], nums['n12']), 'xofn')} {word} ({fmt(nums['pct12'], 'pct0')}, {WINDOW_TEXT['12m']})"
    return {"kind": "empirical", "level": "info", "id": f"empirical:{indication}:{drug}", "signal_id": None,
            "flagged_by": "Local guide (example, to be set by Tyks)", "flagged_on": None,
            "rule": "the observed resistance in this population is near or above the local line for this drug",
            "summary": f"{name}: {observed} on {unit}, {where} the local {fmt(line, 'pct0')} line",
            "chip": f"{where.capitalize()} the local line for {name.lower()} · {unit}",
            "text": f"{name} for {C.INDICATIONS[indication]['label'].lower()}: {observed} in this population, "
                    f"{where} the local {fmt(line, 'pct0')} line (example, to be set by Tyks)."}


# --------------------------------------------------------------------------- the order context
def _population_text(unit: str, f: dict) -> str:
    where = f"ED and health centres, patients from {f['home_area']}" if f["home_area"] else unit
    who = {"F": "women", "M": "men"}.get(f["sex"])
    bits = [f["specimen"], _short(f["organism"]) if f["organism"] else "all organisms", *([who] if who else [])]
    return f"{where} ({', '.join(bits)})"


def _counts_text(c: dict, word: str) -> str:
    label = WINDOW_TEXT[c["window"]]
    if c["state"] == "not_enough_data":
        return f"{label}: not enough data (n = {c['n']})"
    small = "; small n" if c["state"] == "low_n" else ""
    return (f"{label}: {fmt((c['r'], c['n']), 'xofn')} {word} ({fmt(c['pct'], 'pct0')}, 95% interval "
            f"{fmt(c['ci'], 'ci0')}{small})")


def _alternatives(wins: dict, indication: str, guide: list[str], blocked: set[str]) -> list[dict]:
    """Guide drugs worth offering: none that would itself warn (`blocked`), none this population shows no number for,
    and none at or above its empirical line over the last 52 weeks (clinical review D-M1)."""
    out = []
    for d in dict.fromkeys(guide):
        _, year, not_shown = _numbers(wins, d, indication)
        above = year["state"] != "not_enough_data" and year["pct"] >= _line(indication, d)
        if d not in blocked and not not_shown and not above:
            out.append({"drug": d, "name": ORDER_NAMES[d], "aware": C.ORDER_AWARE[ORDER_NAMES[d]],
                        **{k: year[k] for k in ("r", "n", "pct", "ci", "state")}})
    return out


def _alternatives_text(items: list[dict], word: str) -> str:
    return "; ".join(f"{i['name']}: " + (f"{fmt((i['r'], i['n']), 'xofn')} {word} ({fmt(i['pct'], 'pct0')}, "
                                         if i["state"] != "not_enough_data" else f"not enough data (n = {i['n']}, ")
                     + f"{WINDOW_TEXT['12m']})" for i in items) + "."


def _no_data(name: str, unit: str, not_shown: str | None, year: dict) -> tuple[str, str] | None:
    """Chip and rule when this population has no number for the drug, else None."""
    if not_shown:
        return f"{name}: {not_shown}", "No data: no number is shown for this drug in this population."
    if year["state"] == "not_enough_data":
        return (f"Not enough data on {unit} for {name.lower()} (n = {year['n']}, {WINDOW_TEXT['12m']})",
                "No data: fewer than 10 isolates with a result in the last 52 weeks for this population and drug.")
    return None


def _verdict(reasons: list[dict], pending: bool, stage: str, no_data: tuple[str, str] | None, unit: str,
             as_of: str) -> tuple[str, str, str]:
    """State, chip and the plain sentence of the rule that fired. A warning waits for signing."""
    if pending and stage == "sign":
        return "warning", reasons[0]["chip"], f"Warning at signing: {reasons[0]['rule']}."
    if reasons:
        rule = f"Info at selection: {reasons[0]['rule']}. {SIGN_NOTE}" if pending else f"Info: {reasons[0]['rule']}."
        return "info", reasons[0]["chip"], rule
    if no_data:
        return ("no_data", *no_data)
    return ("quiet", f"No active alerts · {unit} · data to {fmt(as_of, 'short_date')}",
            "Quiet: no alert, no local line near, and no acquired resistance in this patient's previous isolates.")


def order_context(ds, as_of, patient_id: str | None, unit: str, indication: str, drug: str, stage: str = "select",
                  alerts=(), policy_states=()) -> dict:
    """What the order screen shows for one draft order (CONTRACTS.md 7b): state quiet | no_data | info | warning.

    `alerts` are `store.alerts(session)` rows (inactive ones are ignored here); `policy_states` are
    `detectors.policy.policy_states(ds, as_of)` rows. `patient_id=None` gives unit-level numbers only."""
    as_of = _iso(as_of)
    unit, drug, stage = _known(unit, C.WARD_LABELS, "unit"), _known(drug, ORDER_NAMES, "drug"), _known(stage, STAGES, "stage")
    indication = _known(_indication(indication), C.INDICATIONS, "indication")
    patient = patient_info(ds, patient_id, as_of) if patient_id is not None else None
    name, ind = ORDER_NAMES[drug], C.INDICATIONS[indication]
    word = "resistant" if ind["reference_organism"] else "not covered"
    rows, pop = population(ds, as_of, unit, indication, patient)
    wins = _windows(rows, as_of)
    recent, year, not_shown = _numbers(wins, drug, indication)
    nums = None if not_shown else {**{k: recent[k] for k in ("r", "n", "pct", "ci", "state", "window")},
                                   "r12": year["r"], "n12": year["n"], "pct12": year["pct"], "ci12": year["ci"],
                                   "state12": year["state"]}
    history = _history(ds, as_of, patient_id) if patient else ds.isolates.iloc[:0]
    previous = _previous(history, drug)

    # Reasons in display order: warnings, then infection-control sources before the example empirical line.
    unit_alerts = [a for a in alerts if is_active(a, as_of) and unit in a["wards"]]
    reasons = [_alert_reason(a, unit, name, True) for a in unit_alerts if drug in a["drugs"]]
    own_r = next(filter(_acquired, previous), None)
    if own_r:
        reasons.append(_own_history_reason(own_r, name))
    reasons += [_policy_reason(ps) for ps in policy_states if _policy_live(ps, as_of) and ps["drug"] == drug
                and _indication(ps["order_indication"]) == indication and unit in _policy_units(ps)
                and (patient is None or ps["population"].get("sex") in (None, patient["sex"]))]
    reasons += [_alert_reason(a, unit, name, False) for a in unit_alerts if drug not in a["drugs"]]
    if nums and not any(r["kind"] == "policy" for r in reasons):  # the policy line already says it
        reasons += [r for r in [_empirical_reason(nums, unit, indication, drug, name, word)] if r]

    pending = any(r["level"] == "warning" for r in reasons)
    state, chip, rule = _verdict(reasons, pending, stage, _no_data(name, unit, not_shown, year), unit, as_of)
    top = reasons[0] if reasons else None

    blocked = {drug} | {d for a in unit_alerts for d in _alert_resistant(a)} | _acquired_drugs(history)
    example = C.local_guide_example(indication, patient["sex"] if patient else None)
    guide = [r["alternative"] for r in reasons if r.get("alternative")] + (example["drugs"] if example else [])
    alternatives = _alternatives(wins, indication, guide, blocked)

    lines = []
    if top:
        lines.append({"key": "happening", "text": top["text"] + (f" {SIGN_NOTE}" if state == "info" and pending else ""),
                      "source": {k: top[k] for k in ("kind", "id", "flagged_by", "flagged_on")}})
    drug_text = (f"not shown ({not_shown})" if not_shown else
                 f"{_counts_text(recent, word)}; {_counts_text(year, word)}")
    lines.append({"key": "your_drug", "numbers": nums, "not_shown": not_shown,
                  "text": f"{name} on {_population_text(unit, pop)}: {drug_text}."})
    if alternatives or (reasons and guide):
        lines.append({"key": "alternatives", "label": ALTERNATIVES_LABEL, "items": alternatives,
                      "source": example["source"] if example else None,
                      "text": _alternatives_text(alternatives, word) if alternatives else C.NO_GUIDE_ALTERNATIVE})

    link = {"ward": unit, "specimen": ind["specimen"], **({"organism": pop["organism"]} if pop["organism"] else {}),
            "as_of": as_of}
    source_id = top["id"] if top else None
    return {
        "state": state, "stage": stage, "interruptive": state == "warning", "chip": chip, "rule": rule,
        "summary": top["summary"] if top else chip, "as_of": as_of, "unit": unit, "indication": indication,
        "drug": drug, "drug_name": name, "patient": patient, "previous_results": previous,
        "notes": _species_notes(previous, name), "lines": lines,
        "actions": {"keep_reasons": list(C.KEEP_REASONS), "change_to": [a["drug"] for a in alternatives],
                    "details_link": "/#/ward?" + urlencode(link, quote_via=quote)},
        "source": {"kind": top["kind"], "id": top["id"], "signal_id": top["signal_id"]} if top else None,
        "card_key": _uuid(as_of, unit, indication, drug, state, source_id),
        "evidence": {"population": {**pop, "date_to": as_of}, "counts": nums, "not_shown": not_shown,
                     "reasons": [{k: r[k] for k in ("kind", "level", "id", "summary")} for r in reasons],
                     "method": METHOD},
        "note": LAG_NOTE, "small_print": SMALL_PRINT,
    }


# --------------------------------------------------------------------------- CDS Hooks cards
def swap_medication(medication_request: dict | None, drug: str) -> dict:
    """The draft MedicationRequest with its ATC coding swapped. The dose is removed: this service never proposes one."""
    res = copy.deepcopy(medication_request) or {"resourceType": "MedicationRequest", "status": "draft", "intent": "order"}
    res["medicationCodeableConcept"] = {"coding": [{"system": ATC_SYSTEM, "code": ORDER_ATC[drug],
                                                    "display": ORDER_NAMES[drug]}], "text": ORDER_NAMES[drug]}
    res.pop("dosageInstruction", None)
    return res


def _atc_codes(medication_request: dict | None) -> list:
    return [c.get("code") for c in ((medication_request or {}).get("medicationCodeableConcept") or {}).get("coding") or []]


def card(ctx: dict, medication_request: dict | None = None) -> dict | None:
    """The CDS Hooks card for an info or warning order context; None when quiet or no data."""
    if ctx["state"] not in ("info", "warning"):
        return None
    name, lines = ctx["drug_name"], {ln["key"]: ln for ln in ctx["lines"]}
    detail = []
    if ctx["previous_results"]:
        detail.append("**This patient's results, last 52 weeks:** " + "; ".join(
            f"{fmt(h['date'], 'date')}, {h['unit']}, {h['specimen']}, {_short(h['organism'])}"
            + "".join(f" {f}" for f in h["flags"])
            + (f": {name.lower()} {h['drug_result']} ({h['reason_text']})" if h["drug_result"] else
               f": {name.lower()} {h['reason_text']}")
            for h in ctx["previous_results"][:5]))
    detail += [f"**Note:** {n}" for n in ctx["notes"] + [C.ATC_NOTES[c] for c in _atc_codes(medication_request)
                                                          if c in C.ATC_NOTES]]
    detail.append(f"**What is happening:** {_md(lines['happening']['text'])}")
    detail.append(f"**Your drug in this population:** {lines['your_drug']['text']}")
    if "alternatives" in lines:
        alt = lines["alternatives"]
        detail.append(f"**{ALTERNATIVES_LABEL}:** {alt['text']}" + (f" Source: {alt['source']}." if alt["source"] else ""))
    detail += [LAG_NOTE, f"_{SMALL_PRINT}_"]
    signal_id = ctx["source"]["signal_id"]
    details_url = f"/#/signal/{signal_id}?as_of={ctx['as_of']}" if signal_id else ctx["actions"]["details_link"]
    out = {
        "uuid": ctx["card_key"], "summary": ctx["summary"][:140], "detail": "\n\n".join(detail),
        "indicator": ctx["state"], "source": {"label": SOURCE_LABEL},
        "overrideReasons": [{"code": "keep", "system": OVERRIDE_SYSTEM, "display": f"Keep {name.lower()}"}] + [
            {"code": re.sub(r"\W+", "_", r.lower()).strip("_"), "system": OVERRIDE_SYSTEM, "display": r}
            for r in C.KEEP_REASONS],
        "links": [{"label": "Details", "url": details_url, "type": "absolute"}],
        "extension": {f"{SLUG}.rule": ctx["rule"], f"{SLUG}.source": ctx["source"], f"{SLUG}.evidence": ctx["evidence"]},
    }
    if ctx["actions"]["change_to"]:
        out["selectionBehavior"] = "at-most-one"
        out["suggestions"] = [
            {"label": f"Change to {ORDER_NAMES[d].lower()}", "uuid": _uuid(ctx["card_key"], d), "actions": [
                {"type": "update", "resource": swap_medication(medication_request, d),
                 "description": f"Change {name.lower()} to {ORDER_NAMES[d].lower()} (ATC {ORDER_ATC[d]}), from the "
                                "local guide example. Dose, route and duration stay with the prescriber."}]}
            for d in ctx["actions"]["change_to"]]
    return out


def order_check(ds, as_of, unit: str, drug: str, indication: str, alerts, policy_states, *,
                patient_id: str | None = None, stage: str = "sign", medication_request: dict | None = None) -> list[dict]:
    """Section 7: the cards for one ordered drug, [] when quiet or no data."""
    c = card(order_context(ds, as_of, patient_id, unit, indication, drug, stage, alerts, policy_states),
             medication_request)
    return [c] if c else []


def parse_hook_request(service_id: str, request: dict) -> dict:
    """Read a CDS Hooks 2.0 request: the stage from the hook; unit, indication and as_of from `context.extension`
    (as_of defaults to the last data day); the patient id; and each draft MedicationRequest's drug from its ATC code
    (for order-select, only the `selections`). Anything malformed is an OrderError with a plain message."""
    hook = next((s["hook"] for s in SERVICES if s["id"] == service_id), None)
    if hook is None or request.get("hook") != hook:
        raise OrderError(f"service {service_id} does not handle hook {request.get('hook')}")
    try:
        ctx = request["context"]
        ext = ctx.get("extension") or {}
        fields = {"unit": ext.get(f"{SLUG}.unit"), "indication": ext.get(f"{SLUG}.indication"),
                  "as_of": ext.get(f"{SLUG}.as_of"), "patientId": ctx.get("patientId")}
        selections = ctx.get("selections")
        orders = []
        for entry in (ctx.get("draftOrders") or {}).get("entry") or []:
            res = entry["resource"]
            if res.get("resourceType") != "MedicationRequest":
                continue
            if selections and f"MedicationRequest/{res.get('id')}" not in selections:
                continue
            drug = next((ATC_TO_DRUG[c] for c in _atc_codes(res) if c in ATC_TO_DRUG), None)
            if drug:
                orders.append({"drug": drug, "resource": res})
    except (KeyError, AttributeError, TypeError) as e:
        raise OrderError("context must hold an extension object and draftOrders as a FHIR Bundle") from e
    for k, v in fields.items():
        if v is not None and not isinstance(v, str):
            raise OrderError(f"{k} must be text")
    if selections is not None and not isinstance(selections, list):
        raise OrderError("selections must be a list")
    unit, indication = fields["unit"], _indication(fields["indication"])
    if unit not in (None, *C.WARD_LABELS) or indication not in (None, *C.INDICATIONS):
        raise OrderError(f"unknown unit or indication: {unit}, {indication}")
    return {"stage": "select" if hook == "order-select" else "sign", "unit": unit, "indication": indication,
            "as_of": _iso(fields["as_of"] or C.DATA_END), "patient_id": fields["patientId"], "orders": orders}


def hook_cards(ds, parsed: dict, alerts, policy_states) -> list[dict]:
    """Cards for every ordered drug in a parsed request, warnings first; order-select never returns more than info.
    Without our unit and indication extension there is nothing to say."""
    if parsed["unit"] is None or parsed["indication"] is None:
        return []
    pid = parsed["patient_id"]
    pid = pid if (ds.patients.patient_id == pid).any() else None  # an id outside the dataset: unit-level only
    cards = {c["uuid"]: c for o in parsed["orders"] for c in order_check(
        ds, parsed["as_of"], parsed["unit"], o["drug"], parsed["indication"], alerts, policy_states, patient_id=pid,
        stage=parsed["stage"], medication_request=o["resource"])}
    return sorted(cards.values(), key=lambda c: c["indicator"] != "warning")


# --------------------------------------------------------------------------- My ward banners
def banners(as_of, unit: str, alerts, policy_states, *, specimen_group: str) -> list[dict]:
    """Passive banners for My ward: alerts active at `as_of + 1` on this unit, and policy lines at or above their
    threshold that name this unit and whose specimen is in the view's `specimen_group` (the trimethoprim line is
    about urine, so a blood or wound view never shows it)."""
    as_of, specimens = _iso(as_of), C.SPECIMEN_GROUPS[_known(specimen_group, C.SPECIMEN_GROUPS, "specimen group")]
    out = [{"kind": "alert", "id": a["id"], "signal_id": a["signal_id"], "drugs": a["drugs"],
            "text": f"{a['message']} {_flagged(a)}"} for a in alerts if is_active(a, as_of) and unit in a["wards"]]
    out += [{"kind": "policy", "id": ps["id"], "signal_id": ps["signal_id"], "drugs": [ps["drug"]],
             "text": f"{policy_summary(ps)}. Population: {policy_population(ps)}. {ps['message']}: "
                     f"{ps['local_guide_alternative']['text']}."}
            for ps in policy_states if _policy_live(ps, as_of) and unit in _policy_units(ps)
            and ps["specimen"] in specimens]
    return out
