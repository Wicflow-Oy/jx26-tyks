"""The doctor's order context and CDS Hooks 2.0 cards (order-select, order-sign). CONTRACTS.md sections 7 and 7b.

Pure and deterministic. Something is said about an order only because of:
  (a) an approved infection-control alert active at `as_of + 1` on the ordering unit;
  (b) this patient's own isolate in the 12 months to `as_of` with an effective R to the ordered drug;
  (c) a local policy line at or above its threshold, or the unit population's observed resistance near the example
      empirical line in `config.EMPIRICAL_LINES`.
Only (a) covering this drug and (b) interrupt, and only when the order is signed; at selection they show as info.
Never a block and never a patient-level estimate. This module imports neither the narrator nor the second-opinion
adapter (a test enforces it).
"""
import copy
import re
import uuid
from urllib.parse import quote, urlencode

import pandas as pd

from . import config as C
from . import data, stats
from .phenotype_rules import effective_column, effective_result
from .render import fmt
from .store import is_active

SLUG = re.sub(r"[^a-z0-9]+", "-", C.APP_NAME.lower()).strip("-")
SOURCE_LABEL = f"{C.APP_NAME} · infection control"
SMALL_PRINT = "Observed unit-level information, not a prediction for this patient. The doctor decides."
LAG_NOTE = f"Dates are sample dates; results usually arrive about {C.RESULT_LAG_DAYS} days later."
SIGN_NOTE = "It will ask again when the order is signed."
ALTERNATIVES_LABEL = "Alternatives from the local guide (example, to be set by Tyks)"
ATC_SYSTEM = "http://www.whocc.no/atc"
OVERRIDE_SYSTEM = f"urn:{SLUG}:keep-reason"
STAGES = ("select", "sign")
SERVICES = [
    {"hook": "order-select", "id": f"{SLUG}-order-select", "title": f"{C.APP_NAME} unit resistance context",
     "description": "When an antibiotic is selected, shows passive information from approved infection-control alerts, "
                    "local policy lines and the unit's observed counts. Never interrupts at selection.", "prefetch": {}},
    {"hook": "order-sign", "id": f"{SLUG}-order-sign", "title": f"{C.APP_NAME} unit resistance check",
     "description": "Before an antibiotic order is signed, asks once when an approved alert covers this unit and drug, or "
                    "the patient's own recent isolate was resistant to it. The doctor decides.", "prefetch": {}},
]
ORDER_NAMES = {code: name for code, name, _ in C.ORDER_DRUGS}
ORDER_ATC = {code: atc for code, _, atc in C.ORDER_DRUGS}
# Orders are read through config.ATC, minus screening markers (an order coded as cefoxitin is not flucloxacillin),
# plus the order picker's own codes.
ATC_TO_DRUG = {atc: d for atc, d in C.ATC.items() if d not in C.HIDDEN_AS_OPTION} | {a: d for d, a in ORDER_ATC.items()}
INDICATION_ALIASES = {"urinary": "uti"}  # policy lines and CDS requests may name the indication by organ
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


def _indication(value: str | None) -> str | None:
    return INDICATION_ALIASES.get(value, value)


def _uuid(*parts) -> str:
    return str(uuid.uuid5(_NS, "|".join(str(p) for p in parts)))


def _short(organism: str) -> str:
    genus, _, species = organism.partition(" ")
    return f"{genus[0]}. {species}" if species else organism


def _md(text: str) -> str:
    """Alert messages are typed by users; escape them so a card's markdown cannot carry links, HTML or emphasis."""
    return _MARKDOWN.sub(r"\\\1", text)


def _staph_only(drug: str, organism: str) -> bool:
    """Flucloxacillin (FOX in the picker) is read from the cefoxitin screen, which only means something for staphylococci."""
    return drug == "FOX" and not organism.startswith("Staphylococcus")


# --------------------------------------------------------------------------- patient, population, counts
def patient_info(ds, patient_id: str, as_of) -> dict:
    p = ds.patients[ds.patients.patient_id == patient_id]
    if p.empty:
        raise OrderError(f"unknown patient {patient_id}")
    r = p.iloc[0]
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


def _effective(rows: pd.DataFrame, drug: str) -> pd.Series:
    """Effective S/R for counting; pairs without a breakpoint count as not covered (section 4.1)."""
    e = effective_column(rows, drug)
    e[rows.organism.map(lambda o: drug in C.NO_BREAKPOINT.get(o, set()) or _staph_only(drug, o)).astype(bool)] = "R"
    return e


def counts(rows: pd.DataFrame, as_of, drug: str, window: str) -> dict:
    """R (or not covered) of n tested in one window (`4w` or `12m`), first isolate per patient x organism x specimen."""
    w = data.first_isolates(data.window(rows, as_of, C.WINDOWS[window]))
    e = _effective(w, drug).dropna()
    r, n = int((e == "R").sum()), len(e)
    return {"r": r, "n": n, "pct": r / n if n else None, "ci": list(stats.jeffreys_interval(r, n)) if n else None,
            "state": stats.n_state(n), "window": window}


def _history(ds, as_of, patient_id: str) -> pd.DataFrame:
    """This patient's isolates in the 12 months to `as_of`, newest first."""
    x = ds.isolates
    rows = data.window(x[x.patient_id == patient_id], as_of, C.WINDOWS["12m"])
    return rows.sort_values("sample_date", ascending=False, kind="stable")


def _own_result(row, drug: str) -> tuple[str | None, str]:
    if _staph_only(drug, row.organism):
        return None, "not read for this organism"
    return effective_result(row, drug)


def _previous(history: pd.DataFrame, drug: str | None) -> list[dict]:
    out = []
    for _, r in history.iterrows():
        result, reason = _own_result(r, drug) if drug else (None, "no drug selected")
        out.append({"date": r.sample_date.date().isoformat(), "unit": r.ward_code, "specimen": r.specimen,
                    "organism": r.organism, "flags": [f.upper() for f in ("esbl", "mrsa", "vre", "cpe") if r[f] == 1],
                    "drug_result": result, "reason": reason})
    return out


def previous_results(ds, as_of, patient_id: str, drug: str | None = None) -> list[dict]:
    """This patient's isolates in the 12 months to `as_of`, newest first, each with the effective result for `drug`
    and its reason ("reported", "inferred from MRSA", ...)."""
    return _previous(_history(ds, as_of, patient_id), drug)


# --------------------------------------------------------------------------- reasons (what fires, in display order)
def _flagged(a: dict) -> str:
    return (f"Flagged by {a['approved_by_role'].lower()}, {fmt(a['approved_on'], 'date')}; "
            f"expires {fmt(a['expires_on'], 'short_date')}.")


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
            "rule": "this patient's own isolate in the last 12 months was resistant to this drug",
            "summary": f"{name}: this patient's {org} of {when} was R ({h['reason']})",
            "chip": f"This patient's previous isolate was {name.lower()} R",
            "text": f"This patient's {org} ({h['specimen']}, {h['unit']}) of {when} was {name.lower()} R ({h['reason']})."}


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


def _policy_reason(ps: dict) -> dict:
    earlier = (f" 12 months earlier: {fmt(ps['rate_prior'], 'pct1')} ({fmt((ps['x_prior'], ps['n_prior']), 'xofn')})."
               if ps["rate_prior"] is not None else "")
    return {"kind": "policy", "level": "info", "id": ps["id"], "signal_id": ps["signal_id"],
            "flagged_by": "Infection control", "flagged_on": ps["crossed_on"],
            "rule": "a local policy line for this drug is at or above its threshold", "summary": policy_summary(ps),
            "chip": f"Above the local line for {ps['drug_label'].lower()}",
            "text": f"{policy_summary(ps)} ({_short(ps['organism'])} in {ps['specimen']}, {ps['population_label']})."
                    f"{earlier} Local policy line set by infection control; crossed week ending "
                    f"{fmt(ps['crossed_on'], 'date')}. {ps['message']}: {ps['local_guide_alternative']['text']}.",
            "alternative": ps["local_guide_alternative"]["drug"]}


def _empirical_reason(nums: dict, unit: str, indication: str, drug: str, name: str, word: str) -> dict | None:
    """Info when the population's 12-month resistance is within INFO_MARGIN of the example empirical line, or above."""
    lines = C.EMPIRICAL_LINES[indication]
    line = lines.get(drug, lines["_default"])
    if nums["state12"] == "not_enough_data" or nums["pct12"] < line - C.INFO_MARGIN:
        return None
    where = "above" if nums["pct12"] >= line else "close to"
    observed = f"{fmt((nums['r12'], nums['n12']), 'xofn')} {word} ({fmt(nums['pct12'], 'pct0')}, 12 months)"
    return {"kind": "empirical", "level": "info", "id": f"empirical:{indication}:{drug}", "signal_id": None,
            "flagged_by": "Local guide (example, to be set by Tyks)", "flagged_on": None,
            "rule": "the unit's observed resistance is near or above the local line for this drug",
            "summary": f"{name}: {observed} on {unit}, {where} the local {fmt(line, 'pct0')} line",
            "chip": f"{where.capitalize()} the local line for {name.lower()} · {unit}",
            "text": f"{name} for {C.INDICATIONS[indication]['label'].lower()}: {observed} in this unit's population, "
                    f"{where} the local {fmt(line, 'pct0')} line (example, to be set by Tyks)."}


# --------------------------------------------------------------------------- the order context
def _population_text(unit: str, f: dict) -> str:
    where = f"ED and health centres, patients from {f['home_area']}" if f["home_area"] else unit
    who = {"F": "women", "M": "men"}.get(f["sex"])
    bits = [f["specimen"], _short(f["organism"]) if f["organism"] else "all organisms", *([who] if who else [])]
    return f"{where} ({', '.join(bits)})"


def _counts_text(c: dict, word: str, label: str) -> str:
    if c["state"] == "not_enough_data":
        return f"{label}: not enough data (n = {c['n']})"
    small = " (small n)" if c["state"] == "low_n" else ""
    return (f"{label}: {fmt((c['r'], c['n']), 'xofn')} {word} ({fmt(c['pct'], 'pct0')}, 95% interval "
            f"{fmt(c['ci'], 'ci0')}){small}")


def _verdict(reasons: list[dict], pending: bool, stage: str, year: dict, unit: str, name: str,
             as_of: str) -> tuple[str, str, str]:
    """State, chip and the plain sentence of the rule that fired. A warning waits for signing."""
    if pending and stage == "sign":
        return "warning", reasons[0]["chip"], f"Warning at signing: {reasons[0]['rule']}."
    if reasons:
        rule = f"Info at selection: {reasons[0]['rule']}. {SIGN_NOTE}" if pending else f"Info: {reasons[0]['rule']}."
        return "info", reasons[0]["chip"], rule
    if year["state"] == "not_enough_data":
        return ("no_data", f"Not enough data on {unit} for {name.lower()} (n = {year['n']}, 12 months)",
                "No data: fewer than 10 tested isolates in 12 months for this population and drug.")
    return ("quiet", f"No active alerts · {unit} · data to {fmt(as_of, 'short_date')}",
            "Quiet: no alert, no local line near, and no resistant previous isolate for this patient.")


def order_context(ds, as_of, patient_id: str | None, unit: str, indication: str, drug: str, stage: str = "select",
                  alerts=(), policy_states=()) -> dict:
    """What the order screen shows for one draft order (CONTRACTS.md 7b): state quiet | no_data | info | warning.

    `alerts` are `store.alerts(session)` rows (inactive ones are ignored here); `policy_states` are
    `detectors.policy.policy_states(ds, as_of)` rows. `patient_id=None` gives unit-level numbers only."""
    as_of, indication = _iso(as_of), _indication(indication)
    if unit not in C.WARD_LABELS or indication not in C.INDICATIONS or drug not in ORDER_NAMES or stage not in STAGES:
        raise OrderError(f"unknown unit, indication, drug or stage: {unit}, {indication}, {drug}, {stage}")
    patient = patient_info(ds, patient_id, as_of) if patient_id else None
    name, ind = ORDER_NAMES[drug], C.INDICATIONS[indication]
    word = "resistant" if ind["reference_organism"] else "not covered"
    rows, pop = population(ds, as_of, unit, indication, patient)
    recent, year = counts(rows, as_of, drug, "4w"), counts(rows, as_of, drug, "12m")
    nums = {**{k: recent[k] for k in ("r", "n", "pct", "ci", "state", "window")},
            "r12": year["r"], "n12": year["n"], "pct12": year["pct"], "ci12": year["ci"], "state12": year["state"]}
    history = _history(ds, as_of, patient_id) if patient else ds.isolates.iloc[:0]
    previous = _previous(history, drug)

    # Reasons in display order: warnings, then infection-control sources before the example empirical line.
    unit_alerts = [a for a in alerts if is_active(a, as_of) and unit in a["wards"]]
    reasons = [_alert_reason(a, unit, name, True) for a in unit_alerts if drug in a["drugs"]]
    own_r = next((h for h in previous if h["drug_result"] == "R"), None)
    if own_r:
        reasons.append(_own_history_reason(own_r, name))
    reasons += [_policy_reason(ps) for ps in policy_states if _policy_live(ps, as_of) and ps["drug"] == drug
                and _indication(ps["order_indication"]) == indication and unit in _policy_units(ps)
                and (patient is None or ps["population"].get("sex") in (None, patient["sex"]))]
    reasons += [_alert_reason(a, unit, name, False) for a in unit_alerts if drug not in a["drugs"]]
    if not any(r["kind"] == "policy" for r in reasons):  # the policy line already says it; do not repeat it
        reasons += [r for r in [_empirical_reason(nums, unit, indication, drug, name, word)] if r]

    pending = any(r["level"] == "warning" for r in reasons)
    state, chip, rule = _verdict(reasons, pending, stage, year, unit, name, as_of)
    top = reasons[0] if reasons else None
    # Alternatives never include a drug that would itself warn: covered by an active alert here, or R in this patient.
    blocked = {drug} | {d for a in unit_alerts for d in a["drugs"]}
    blocked |= {d for d in ORDER_NAMES for _, r in history.iterrows() if _own_result(r, d)[0] == "R"}
    guide = [r["alternative"] for r in reasons if r.get("alternative")] + C.LOCAL_GUIDE_EXAMPLE[indication]
    change_to = [d for d in dict.fromkeys(guide) if d not in blocked]

    lines = []
    if top:
        lines.append({"key": "happening", "text": top["text"] + (f" {SIGN_NOTE}" if state == "info" and pending else ""),
                      "source": {k: top[k] for k in ("kind", "id", "flagged_by", "flagged_on")}})
    lines.append({"key": "your_drug", "numbers": nums,
                  "text": f"{name} on {_population_text(unit, pop)}: {_counts_text(recent, word, 'last 4 weeks')}; "
                          f"{_counts_text(year, word, '12 months')}."})
    if change_to:
        items = [{"drug": d, "name": ORDER_NAMES[d], **{k: c[k] for k in ("r", "n", "pct", "ci", "state")}}
                 for d in change_to for c in [counts(rows, as_of, d, "12m")]]
        lines.append({"key": "alternatives", "label": ALTERNATIVES_LABEL, "items": items, "text": "; ".join(
            f"{i['name']} " + (f"{fmt((i['r'], i['n']), 'xofn')} {word} (12 months)" if i["state"] != "not_enough_data"
                               else f"not enough data (n = {i['n']})") for i in items) + "."})

    link = {"ward": unit, "specimen": ind["specimen"], **({"organism": pop["organism"]} if pop["organism"] else {}),
            "as_of": as_of}
    source_id = top["id"] if top else None
    return {
        "state": state, "stage": stage, "interruptive": state == "warning", "chip": chip, "rule": rule,
        "summary": top["summary"] if top else chip, "as_of": as_of, "unit": unit, "indication": indication,
        "drug": drug, "drug_name": name, "patient": patient, "previous_results": previous, "lines": lines,
        "actions": {"keep_reasons": list(C.KEEP_REASONS), "change_to": change_to,
                    "details_link": "/#/ward?" + urlencode(link, quote_via=quote)},
        "source": {"kind": top["kind"], "id": top["id"], "signal_id": top["signal_id"]} if top else None,
        "card_key": _uuid(as_of, unit, indication, drug, state, source_id),
        "evidence": {"population": {**pop, "date_to": as_of}, "counts": nums,
                     "reasons": [{k: r[k] for k in ("kind", "level", "id", "summary")} for r in reasons],
                     "method": "first isolate per patient x organism x specimen; effective S/R (intrinsic resistance, "
                               "MRSA and ESBL expert rules); Jeffreys 95% interval"},
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


def card(ctx: dict, medication_request: dict | None = None) -> dict | None:
    """The CDS Hooks card for an info or warning order context; None when quiet or no data."""
    if ctx["state"] not in ("info", "warning"):
        return None
    name, lines = ctx["drug_name"], {ln["key"]: ln for ln in ctx["lines"]}
    detail = []
    if ctx["previous_results"]:
        detail.append("**This patient's results, last 12 months:** " + "; ".join(
            f"{fmt(h['date'], 'date')}, {h['unit']}, {h['specimen']}, {_short(h['organism'])}"
            + "".join(f" {f}" for f in h["flags"])
            + (f": {name.lower()} {h['drug_result']} ({h['reason']})" if h["drug_result"] else f": {h['reason']}")
            for h in ctx["previous_results"][:5]))
    detail.append(f"**What is happening:** {_md(lines['happening']['text'])}")
    detail.append(f"**Your drug on this unit:** {lines['your_drug']['text']}")
    if "alternatives" in lines:
        detail.append(f"**{ALTERNATIVES_LABEL}:** {lines['alternatives']['text']}")
    detail += [LAG_NOTE, f"_{SMALL_PRINT}_"]
    signal_id = ctx["source"]["signal_id"]
    details_url = f"/#/signal/{signal_id}?as_of={ctx['as_of']}" if signal_id else ctx["actions"]["details_link"]
    out = {
        "uuid": ctx["card_key"], "summary": ctx["summary"][:140], "detail": "\n\n".join(detail),
        "indicator": ctx["state"], "source": {"label": SOURCE_LABEL},
        "overrideReasons": [{"code": "keep", "system": OVERRIDE_SYSTEM, "display": f"Keep {name.lower()}"}] + [
            {"code": re.sub(r"\W+", "_", r.lower()).strip("_"), "system": OVERRIDE_SYSTEM, "display": r}
            for r in C.KEEP_REASONS],
        "links": [{"label": "Details", "url": details_url, "type": "absolute"},
                  {"label": f"Open in {C.APP_NAME} (SMART)", "url": "/smart/launch", "type": "smart"}],
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
    (for order-select, only the `selections`)."""
    hook = next((s["hook"] for s in SERVICES if s["id"] == service_id), None)
    if hook is None or request.get("hook") != hook:
        raise OrderError(f"service {service_id} does not handle hook {request.get('hook')}")
    try:
        ctx = request["context"]
        ext = ctx.get("extension") or {}
        unit, indication = ext.get(f"{SLUG}.unit"), _indication(ext.get(f"{SLUG}.indication"))
        as_of, patient_id = ext.get(f"{SLUG}.as_of") or C.DATA_END, ctx.get("patientId")
        selections = ctx.get("selections")
        orders = []
        for entry in (ctx.get("draftOrders") or {}).get("entry") or []:
            res = entry["resource"]
            if res.get("resourceType") != "MedicationRequest":
                continue
            if selections and f"MedicationRequest/{res.get('id')}" not in selections:
                continue
            codes = [c.get("code") for c in (res.get("medicationCodeableConcept") or {}).get("coding") or []]
            drug = next((ATC_TO_DRUG[c] for c in codes if c in ATC_TO_DRUG), None)
            if drug:
                orders.append({"drug": drug, "resource": res})
    except (KeyError, AttributeError, TypeError) as e:
        raise OrderError("context must hold an extension object and draftOrders as a FHIR Bundle") from e
    if unit not in (None, *C.WARD_LABELS) or indication not in (None, *C.INDICATIONS):
        raise OrderError(f"unknown unit or indication: {unit}, {indication}")
    return {"stage": "select" if hook == "order-select" else "sign", "unit": unit, "indication": indication,
            "as_of": _iso(as_of), "patient_id": patient_id, "orders": orders}


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
def banners(as_of, unit: str, alerts, policy_states) -> list[dict]:
    """Passive banners for My ward: alerts active at `as_of + 1` on this unit, and policy lines at or above their
    threshold that name this unit."""
    as_of = _iso(as_of)
    out = [{"kind": "alert", "id": a["id"], "signal_id": a["signal_id"], "drugs": a["drugs"],
            "text": f"{a['message']} {_flagged(a)}"} for a in alerts if is_active(a, as_of) and unit in a["wards"]]
    out += [{"kind": "policy", "id": ps["id"], "signal_id": ps["signal_id"], "drugs": [ps["drug"]],
             "text": f"{policy_summary(ps)}. {ps['message']}: {ps['local_guide_alternative']['text']}."}
            for ps in policy_states if _policy_live(ps, as_of) and unit in _policy_units(ps)]
    return out
