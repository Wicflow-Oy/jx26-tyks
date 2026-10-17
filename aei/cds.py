"""Doctor's order context and CDS Hooks 2.0 cards (order-select / order-sign). CONTRACTS.md sections 7 and 7b.

`order_context` is pure and deterministic. Its sources are deterministic only:
  - approved, unexpired alerts at as_of + 1 covering the ordering unit (store rows, passed in);
  - this patient's own isolates in the 12 months to as_of (effective S/R via `phenotype_rules`);
  - local policy lines (`policy_states` rows) and the example empirical lines in `config.EMPIRICAL_LINES`;
  - observed counts for the unit's population (R of n, Jeffreys interval, `stats.n_state`).
Warning (interruptive) only at stage "sign", and only for (a) an alert covering this unit AND this drug or (b) the
patient's own isolate effectively R to this drug. Everything else is a passive info, no_data or quiet state.
It never blocks, never estimates anything for a patient, and never imports the narrator or the second-opinion adapter
(a test enforces it).
"""
from __future__ import annotations

import copy
import re
import uuid
from urllib.parse import quote, urlencode

import pandas as pd

from . import config as C
from . import data, stats
from .phenotype_rules import effective_column, effective_result
from .render import fmt

SLUG = re.sub(r"[^a-z0-9]+", "-", C.APP_NAME.lower()).strip("-")
EXT_UNIT, EXT_INDICATION, EXT_AS_OF = f"{SLUG}.unit", f"{SLUG}.indication", f"{SLUG}.as_of"
EXT_RULE, EXT_WHY, EXT_SOURCE, EXT_EVIDENCE = f"{SLUG}.rule", f"{SLUG}.why", f"{SLUG}.source", f"{SLUG}.evidence"
EXT_CARD_KEY, EXT_STATE = f"{SLUG}.card_key", f"{SLUG}.state"
ATC_SYSTEM = "http://www.whocc.no/atc"
OVERRIDE_SYSTEM = f"urn:{SLUG}:keep-reason"

SOURCE_LABEL = f"{C.APP_NAME} · infection control"
SMALL_PRINT = "Observed unit-level information, not a prediction for this patient. The doctor decides."
LOGGED_NOTE = "Your choice is logged anonymously for infection control."
SIGN_NOTE = "It will ask again when the order is signed."
INTERRUPT_RULE = ("Interrupts only at signing, and only when an approved alert covers this unit and this drug, or this "
                  "patient's own isolate in the last 12 months was resistant to it.")
LAG_NOTE = f"Dates are sample dates; results usually arrive about {C.RESULT_LAG_DAYS} days later."
ALTERNATIVES_LABEL = "Alternatives from the local guide (example, to be set by Tyks)"
SUMMARY_MAX = 140
STAGES = ("select", "sign")
STATES = ("quiet", "no_data", "info", "warning")
WINDOW_DAYS = {"4w": C.WINDOWS["4w"], "12m": C.WINDOWS["12m"]}
SMART_URL = "/smart/launch"

ORDER_NAMES = {code: name for code, name, _ in C.ORDER_DRUGS}
ORDER_ATC = {code: atc for code, _, atc in C.ORDER_DRUGS}
# ATC codes accepted from an order. Cefoxitin (J01DC01) is a lab screen, not an order option, so it is not mapped.
ATC_TO_ORDER = {atc: code for atc, code in C.ATC.items() if code in ORDER_NAMES and not (code == "FOX" and atc != ORDER_ATC["FOX"])}
LEGACY_INDICATIONS = {"urinary": "uti", "urine": "uti", "blood": "bloodstream", "sepsis": "bloodstream"}
KEEP_CODES = {re.sub(r"[^a-z0-9]+", "_", r.lower()).strip("_"): r for r in C.KEEP_REASONS}

SERVICES = [
    {"hook": "order-select", "id": f"{SLUG}-order-select", "title": f"{C.APP_NAME} unit resistance context",
     "description": "When an antibiotic is selected, shows passive information from approved infection-control alerts, "
                    "local lines and the unit's observed counts. Never interrupts at selection.", "prefetch": {}},
    {"hook": "order-sign", "id": f"{SLUG}-order-sign", "title": f"{C.APP_NAME} unit resistance check",
     "description": "Before an antibiotic order is signed, asks once when an approved alert covers this unit and drug, or "
                    "the patient's own recent isolate was resistant to it. Observed information only; the doctor decides.",
     "prefetch": {}},
]
SERVICE_HOOKS = {s["id"]: s["hook"] for s in SERVICES}
SERVICE_STAGE = {"order-select": "select", "order-sign": "sign"}

_SPECIMEN_ADJ = {"urine": "urinary", "blood": "blood", "wound": "wound"}
_NS = uuid.UUID("6f2b6c1e-8d1a-5c3e-9a57-5a1d3c0e7b21")
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~])")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class CdsRequestError(ValueError):
    """A malformed order-context or CDS Hooks request (the API answers 422)."""


class UnknownPatient(LookupError):
    """The patient id is not in the synthetic dataset (the API answers 404)."""


# --------------------------------------------------------------------------- small helpers
def _day(x) -> pd.Timestamp:
    return pd.Timestamp(str(x)[:10]).normalize()


def _iso(x) -> str:
    return _day(x).date().isoformat()


def _monday(as_of) -> str:
    return (_day(as_of) + pd.Timedelta(days=1)).date().isoformat()


def _uid(*parts) -> str:
    return str(uuid.uuid5(_NS, "|".join("" if p is None else str(p) for p in parts)))


def _fit(text: str, limit: int = SUMMARY_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _plain(text) -> str:
    return re.sub(r"\s+", " ", _CONTROL.sub(" ", str(text or ""))).strip()


def md_escape(text) -> str:
    """Untrusted text (an alert message) becomes inert markdown: no links, images, emphasis or HTML."""
    return _MD_SPECIAL.sub(r"\\\1", _plain(text))


def drug_name(code: str) -> str:
    """The orderable name (pivmecillinam for MEC, flucloxacillin for FOX in the order picker)."""
    return ORDER_NAMES.get(code) or C.ORDER_DRUG_NAMES.get(code) or C.DRUG_NAMES.get(code, code)


def short_organism(name: str) -> str:
    parts = str(name).split()
    return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else str(name)


def normalize_indication(indication: str | None) -> str | None:
    if indication is None:
        return None
    return indication if indication in C.INDICATIONS else LEGACY_INDICATIONS.get(indication, indication)


def _first(d: dict, *keys):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _pct(x, n):
    return None if not n else x / n


def _ci(x, n):
    return None if not n else list(stats.jeffreys_interval(int(x), int(n)))


# --------------------------------------------------------------------------- alerts and policy states
def alert_active(alert: dict, as_of) -> bool:
    """Approved, unexpired and not revoked at as_of + 1. Alerts approved after as_of + 1 are invisible."""
    d = _monday(as_of)
    approved, expires = alert.get("approved_on"), alert.get("expires_on")
    if alert.get("status", "approved") not in ("approved", "revoked") or not approved:
        return False
    if str(approved)[:10] > d or (expires and str(expires)[:10] < d):
        return False
    if alert.get("status") == "revoked":
        revoked = alert.get("revoked_on")
        if not revoked or str(revoked)[:10] <= d:
            return False
    return True


def policy_line(policy_id: str) -> dict | None:
    return next((p for p in C.POLICY_LINES if p["id"] == policy_id), None)


def normalize_policy_state(ps: dict) -> dict | None:
    """Map a `detectors.policy.policy_states` row onto the fields used here; None for an unknown policy line.
    `active` is recomputed from the counts against the threshold."""
    pid = _first(ps, "id", "policy_id", "line_id")
    line = policy_line(pid) if pid else None
    if line is None:
        return None
    x, n = _first(ps, "x", "n_resistant"), _first(ps, "n", "n_tested")
    rate = (x / n) if (x is not None and n) else _first(ps, "rate")
    threshold = float(_first(ps, "threshold") or line["threshold"])
    prior, x_prior, n_prior = _first(ps, "rate_prior", "prior_rate"), _first(ps, "x_prior"), _first(ps, "n_prior")
    if prior is None and x_prior is not None and n_prior:
        prior = x_prior / n_prior
    return {"id": pid, "line": line, "as_of": None if ps.get("as_of") is None else _iso(ps["as_of"]),
            "x": None if x is None else int(x), "n": None if n is None else int(n),
            "rate": None if rate is None else float(rate), "interval": _first(ps, "interval", "ci"),
            "rate_prior": None if prior is None else float(prior),
            "x_prior": None if x_prior is None else int(x_prior), "n_prior": None if n_prior is None else int(n_prior),
            "crossed_on": None if ps.get("crossed_on") is None else _iso(ps["crossed_on"]), "threshold": threshold,
            "alternative": ps.get("local_guide_alternative") or line.get("local_guide_alternative"),
            "signal_id": ps.get("signal_id"), "active": rate is not None and float(rate) >= threshold - 1e-12}


def _usable_state(st: dict | None, as_of: str) -> bool:
    """Strict as-of: a state computed for a later date, or crossed after as_of, never influences this date."""
    if st is None or not st["active"]:
        return False
    if st["as_of"] is not None and st["as_of"] > as_of:
        return False
    return not (st["crossed_on"] is not None and st["crossed_on"] > as_of)


def policy_matches(st: dict, unit: str, indication: str, drug: str, patient: dict | None) -> bool:
    """A policy line applies when it concerns this drug and the indication's specimen, lists the unit (as an ordering
    unit or in its population), and the patient's sex matches the line's population when the line names one."""
    line = st["line"]
    pop = line.get("population") or {}
    if drug != line["drug"] or C.INDICATIONS[indication]["specimen"] != line["specimen"]:
        return False
    if unit not in set(line.get("order_units") or []) | set(pop.get("wards") or []):
        return False
    return not (pop.get("sex") and patient is not None and patient["sex"] != pop["sex"])


def needs_policy_states(unit: str | None, indication: str | None, drug: str | None = None) -> bool:
    """True when some policy line could apply (the API skips the policy detector otherwise)."""
    indication = normalize_indication(indication)
    if unit is None or indication not in C.INDICATIONS:
        return False
    spec = C.INDICATIONS[indication]["specimen"]
    return any((drug is None or p["drug"] == drug) and p["specimen"] == spec
               and unit in set(p.get("order_units") or []) | set((p.get("population") or {}).get("wards") or [])
               for p in C.POLICY_LINES)


# --------------------------------------------------------------------------- patients, populations, counts
def patient_info(ds, patient_id: str, as_of) -> dict:
    p = ds.patients[ds.patients.patient_id == patient_id]
    if p.empty:
        raise UnknownPatient(patient_id)
    r = p.iloc[0]
    return {"id": patient_id, "sex": r.sex, "age": int(_day(as_of).year - int(r.birth_year)), "home_area": r.home_area}


def _is_staph(organism) -> bool:
    return str(organism).startswith("Staphylococcus")


def effective_for_population(rows: pd.DataFrame, drug: str) -> pd.Series:
    """Effective S/R per isolate for counting: `phenotype_rules.effective_column`, plus no-breakpoint pairs as not
    covered (coverage semantics, section 4.1). FOX in the order picker is flucloxacillin, read from the cefoxitin
    screen for staphylococci only; it has no activity against other organisms, so those count as not covered."""
    e = effective_column(rows, drug).copy()
    nb = rows.organism.map(lambda o: drug in C.NO_BREAKPOINT.get(o, set())).astype(bool)
    e[nb] = "R"
    if drug == "FOX":
        e[~rows.organism.map(_is_staph).astype(bool)] = "R"
    return e


def population(ds, as_of, unit: str, indication: str, patient: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """The unit's isolates (all dates up to as_of) for the indication's specimen. Community units (ED, PHC-N, PHC-S)
    use all community-unit isolates from patients living in the patient's home area; uti also matches the patient's
    sex; a reference organism (uti: E. coli) restricts to that organism."""
    ind = C.INDICATIONS[indication]
    x = ds.isolates
    rows = x[(x.specimen == ind["specimen"]) & (x.sample_date <= _day(as_of))]
    f = {"specimen": ind["specimen"], "organism": ind["reference_organism"], "home_area": None, "sex": None,
         "rule": "readme_period"}
    if unit in C.COMMUNITY_UNITS:
        f["units"] = sorted(C.COMMUNITY_UNITS)
        rows = rows[rows.ward_code.isin(f["units"])]
        if patient is not None:
            f["home_area"] = patient["home_area"]
            rows = rows[rows.home_area == patient["home_area"]]
    else:
        f["units"] = [unit]
        rows = rows[rows.ward_code == unit]
    if ind["sex_matched"] and patient is not None:
        f["sex"] = patient["sex"]
        rows = rows[rows.sex == patient["sex"]]
    if ind["reference_organism"]:
        rows = rows[rows.organism == ind["reference_organism"]]
    return rows, f


def counts(rows: pd.DataFrame, as_of, drug: str, window: str) -> dict:
    """R (or not covered) of n tested in one window, first isolates per patient x organism x specimen."""
    w = data.first_isolates(data.window(rows, as_of, WINDOW_DAYS[window]), "readme_period")
    e = effective_for_population(w, drug) if len(w) else pd.Series(dtype=object)
    tested = e.notna()
    r, n = int((e[tested] == "R").sum()), int(tested.sum())
    return {"r": r, "n": n, "pct": _pct(r, n), "ci": _ci(r, n), "state": stats.n_state(n), "window": window}


def drug_numbers(rows: pd.DataFrame, as_of, drug: str) -> dict:
    a, b = counts(rows, as_of, drug, "4w"), counts(rows, as_of, drug, "12m")
    return {"r": a["r"], "n": a["n"], "pct": a["pct"], "ci": a["ci"], "state": a["state"], "window": "4w",
            "r12": b["r"], "n12": b["n"], "pct12": b["pct"], "ci12": b["ci"], "state12": b["state"]}


def _own_effective(row, drug: str) -> tuple[str | None, str]:
    if drug == "FOX" and not _is_staph(row["organism"]):
        return None, "not applicable (flucloxacillin is read for staphylococci)"
    return effective_result(row, drug)


def previous_results(ds, as_of, patient_id: str, drug: str | None = None) -> list[dict]:
    """This patient's isolates in the 12 months to as_of (strictly as-of), newest first, with the effective result
    for `drug` and the reason ("reported", "inferred from MRSA", ...)."""
    x = ds.isolates
    h = data.window(x[x.patient_id == patient_id], as_of, WINDOW_DAYS["12m"])
    h = h.sort_values(["sample_date", "isolate_id"], ascending=[False, True])
    out = []
    for _, r in h.iterrows():
        res, reason = _own_effective(r, drug) if drug else (None, "no drug selected")
        out.append({"date": _iso(r.sample_date), "unit": r.ward_code, "specimen": r.specimen, "organism": r.organism,
                    "flags": [f.upper() for f in ("esbl", "mrsa", "vre", "cpe") if int(r[f]) == 1],
                    "drug": drug, "drug_result": res, "reason": reason, "profile": r.profile})
    return out


# --------------------------------------------------------------------------- texts
def _pop_text(unit: str, f: dict, reference: bool) -> str:
    who = {"F": "women", "M": "men"}.get(f.get("sex"))
    bits = []
    if unit in C.COMMUNITY_UNITS:
        bits.append("ED and health centres" + (f", patients from {f['home_area']}" if f.get("home_area") else ""))
    bits.append(f["specimen"])
    bits.append(short_organism(f["organism"]) if reference else "all organisms")
    if who:
        bits.append(who)
    return f"{unit} ({', '.join(bits)})"


def _numbers_text(nums: dict, reference: bool) -> str:
    word = "resistant" if reference else "not covered"
    if nums["state"] == "not_enough_data":
        recent = f"last 4 weeks: not enough data (n = {nums['n']})"
    else:
        recent = (f"{fmt((nums['r'], nums['n']), 'xofn')} {word} ({fmt(nums['pct'], 'pct0')}, 95% interval "
                  f"{fmt(tuple(nums['ci']), 'ci0')}), last 4 weeks" + (" (small n)" if nums["state"] == "low_n" else ""))
    if nums["state12"] == "not_enough_data":
        year = f"12 months: not enough data (n = {nums['n12']})"
    else:
        year = f"12 months: {fmt((nums['r12'], nums['n12']), 'xofn')} ({fmt(nums['pct12'], 'pct0')})"
    return f"{recent}; {year}"


def _alert_flag(a: dict) -> tuple[str, str]:
    who = C.ROLES.get(a.get("approved_by_role")) or a.get("approved_by") or a.get("approved_by_role") or "Infection control"
    return who, str(a.get("approved_on"))[:10]


# --------------------------------------------------------------------------- the order context
def order_context(ds, as_of, patient_id: str | None, unit: str, indication: str, drug: str, stage: str = "select",
                  alerts=(), policy_states=()) -> dict:
    """Doctor's order context for one draft order (CONTRACTS.md 7b). Pure and deterministic.

    `alerts` are store alert dicts (inactive ones are filtered here); `policy_states` are
    `detectors.policy.policy_states(ds, as_of)` rows. `patient_id=None` skips own history and the home-area/sex match."""
    as_of = _iso(as_of)
    indication = normalize_indication(indication)
    if unit not in C.WARD_LABELS:
        raise CdsRequestError(f"unknown unit {unit}")
    if indication not in C.INDICATIONS:
        raise CdsRequestError(f"unknown indication {indication}")
    if drug not in ORDER_NAMES:
        raise CdsRequestError(f"unknown drug {drug}")
    if stage not in STAGES:
        raise CdsRequestError(f"stage must be one of {STAGES}")
    patient = patient_info(ds, patient_id, as_of) if patient_id else None
    ind = C.INDICATIONS[indication]
    reference = bool(ind["reference_organism"])
    name, low = drug_name(drug), drug_name(drug).lower()
    rows, pop_filter = population(ds, as_of, unit, indication, patient)
    nums = drug_numbers(rows, as_of, drug)
    history = previous_results(ds, as_of, patient_id, drug) if patient else []

    reasons = []  # in display priority order; each {kind, level, id, text, summary, flagged_by, flagged_on}
    unit_alerts = [a for a in sorted(alerts or [], key=lambda a: (str(a.get("approved_on")), str(a.get("id"))))
                   if alert_active(a, as_of) and unit in (a.get("wards") or [])]
    for a in unit_alerts:
        if drug in (a.get("drugs") or []):
            who, on = _alert_flag(a)
            reasons.append({"kind": "alert", "level": "warning", "id": a["id"], "flagged_by": who, "flagged_on": on,
                            "text": f"{who}, {fmt(on, 'date')}: {_plain(a.get('message'))} This alert covers {low} on {unit}.",
                            "summary": f"Approved alert on {unit} covers {low}: {_plain(a.get('message'))}",
                            "chip": f"Infection control alert covers {low} · {unit}"})
    own_r = [h for h in history if h["drug_result"] == "R"]
    if own_r:
        h = own_r[0]
        reasons.append({"kind": "own_history", "level": "warning", "id": "own_history", "flagged_by": "Laboratory result",
                        "flagged_on": h["date"],
                        "text": f"This patient's {short_organism(h['organism'])} ({h['specimen']}) of {fmt(h['date'], 'date')} "
                                f"was {low} R ({h['reason']}).",
                        "summary": f"This patient's {short_organism(h['organism'])} of {fmt(h['date'], 'date')} was {low} R "
                                   f"({h['reason']})", "chip": f"This patient's previous isolate was {low} R"})
    for ps in policy_states or []:
        st = normalize_policy_state(ps)
        if _usable_state(st, as_of) and policy_matches(st, unit, indication, drug, patient):
            line = st["line"]
            counts_txt = f"{fmt((st['x'], st['n']), 'xofn')}, " if st["x"] is not None and st["n"] else ""
            body = (f"{_SPECIMEN_ADJ.get(line['specimen'], line['specimen'])} {short_organism(line['organism'])} in "
                    f"{_population_label(line)} is {fmt(st['rate'], 'pct1')} resistant ({counts_txt}last "
                    f"{line['window_days'] // 7} weeks), above the local {fmt(st['threshold'], 'pct0')} line")
            prior = f" 12 months earlier: {fmt(st['rate_prior'], 'pct1')}." if st["rate_prior"] is not None else ""
            crossed = f"; crossed week ending {fmt(st['crossed_on'], 'date')}" if st["crossed_on"] else ""
            reasons.append({"kind": "policy", "level": "info", "id": st["id"], "flagged_by": "Infection control",
                            "flagged_on": st["crossed_on"], "signal_id": st["signal_id"],
                            "text": f"{name}: {body}.{prior} Local policy line set by infection control{crossed}. "
                                    f"{line['message']}.",
                            "summary": f"{name}: {body}", "chip": f"Above the local line for {low}"})
    lines_cfg = C.EMPIRICAL_LINES.get(indication, {})
    empirical = lines_cfg.get(drug, lines_cfg.get("_default"))
    if (empirical is not None and nums["state12"] != "not_enough_data" and nums["pct12"] is not None
            and nums["pct12"] >= empirical - C.INFO_MARGIN - 1e-12
            and not any(r["kind"] == "policy" for r in reasons)):
        where = "at or above" if nums["pct12"] >= empirical - 1e-12 else "close to"
        word = "resistant" if reference else "not covered"
        reasons.append({"kind": "policy", "level": "info", "id": f"empirical:{indication}:{drug}",
                        "flagged_by": "Local guide (example, to be set by Tyks)", "flagged_on": None,
                        "text": f"{name} for {ind['label'].lower()}: {fmt((nums['r12'], nums['n12']), 'xofn')} {word} "
                                f"({fmt(nums['pct12'], 'pct0')}) in this unit's population over 12 months, {where} the "
                                f"local {fmt(empirical, 'pct0')} line (example, to be set by Tyks).",
                        "summary": f"{name}: {fmt((nums['r12'], nums['n12']), 'xofn')} {word} ({fmt(nums['pct12'], 'pct0')}, "
                                   f"12 months) on {unit}, {where} the local {fmt(empirical, 'pct0')} line",
                        "chip": f"{where.capitalize()} the local line for {low} · {unit}"})
    for a in unit_alerts:
        if drug not in (a.get("drugs") or []):
            who, on = _alert_flag(a)
            reasons.append({"kind": "alert", "level": "info", "id": a["id"], "flagged_by": who, "flagged_on": on,
                            "text": f"{who}, {fmt(on, 'date')}: {_plain(a.get('message'))} It does not cover {low}.",
                            "summary": f"Info: {_plain(a.get('message'))} (approved {fmt(on, 'short_date')})",
                            "chip": f"Infection control alert on {unit}"})

    has_warning = any(r["level"] == "warning" for r in reasons)
    if has_warning and stage == "sign":
        state = "warning"
    elif reasons:
        state = "info"
    elif nums["state12"] == "not_enough_data":
        state = "no_data"
    else:
        state = "quiet"
    top = next((r for r in reasons if r["level"] == "warning"), reasons[0] if reasons else None)
    if state == "warning":
        chip, rule = f"Check before signing · {top['chip']}", (
            "Warning at signing: " + ("an approved alert covers this unit and this drug." if top["kind"] == "alert"
                                      else "this patient's own isolate in the last 12 months was resistant to this drug."))
    elif state == "info":
        chip = top["chip"]
        rule = ("Info at selection; " + SIGN_NOTE[0].lower() + SIGN_NOTE[1:]) if has_warning else {
            "alert": "Info: an approved alert covers this unit but not this drug.",
            "policy": "Info: observed resistance is near or above a local line."}[top["kind"]]
    elif state == "no_data":
        chip = f"Not enough data on {unit} for {low} (n = {nums['n12']}, 12 months)"
        rule = "No data: fewer than 10 tested isolates in 12 months for this population and drug; nothing else applies."
    else:
        chip = f"No active alerts · {unit} · data to {fmt(as_of, 'short_date')}"
        rule = "Quiet: no alert, no local line near, and no resistant previous isolate for this patient."

    lines = []
    if top is not None:
        text = top["text"] + (f" {SIGN_NOTE}" if state == "info" and has_warning else "")
        lines.append({"key": "happening", "text": text,
                      "source": {"kind": top["kind"], "id": top["id"], "flagged_by": top["flagged_by"],
                                 "flagged_on": top["flagged_on"]}})
    lines.append({"key": "your_drug", "text": f"{name} on {_pop_text(unit, pop_filter, reference)}: "
                                              f"{_numbers_text(nums, reference)}.", "numbers": nums})
    guide = [d for d in C.LOCAL_GUIDE_EXAMPLE.get(indication, []) if d != drug]
    items = []
    for d in guide:
        c = counts(rows, as_of, d, "12m")
        items.append({"drug": d, "name": drug_name(d), "r": c["r"], "n": c["n"], "pct": c["pct"], "ci": c["ci"],
                      "state": c["state"], "window": "12m"})
    if items:
        lines.append({"key": "alternatives", "label": ALTERNATIVES_LABEL, "items": items})

    q = {"ward": unit, "specimen": ind["specimen"]}
    if ind["reference_organism"]:
        q["organism"] = ind["reference_organism"]
    q["as_of"] = as_of
    source_id = top["id"] if top else None
    return {
        "state": state, "stage": stage, "interruptive": state == "warning", "chip": chip, "rule": rule,
        "as_of": as_of, "monday": _monday(as_of), "unit": unit, "indication": indication, "drug": drug, "drug_name": name,
        "patient": patient, "previous_results": history, "lines": lines[:3],
        "actions": {"keep_reasons": list(C.KEEP_REASONS), "change_to": guide,
                    "details_link": "/#/ward?" + urlencode(q, quote_via=quote)},
        "card_key": _uid("order", as_of, unit, indication, drug, state, source_id),
        "source": None if top is None else {"kind": top["kind"], "id": top["id"]},
        "evidence": {"population": {**pop_filter, "date_to": as_of}, "counts": nums,
                     "reasons": [{k: r.get(k) for k in ("kind", "level", "id", "summary", "flagged_by", "flagged_on")}
                                 for r in reasons],
                     "alerts_considered": [a["id"] for a in unit_alerts], "empirical_line": empirical,
                     "info_margin": C.INFO_MARGIN, "method": "first isolates; effective S/R (MRSA and ESBL expert rules, "
                                                             "intrinsic resistance); Jeffreys 95% interval"},
        "note": LAG_NOTE, "small_print": SMALL_PRINT,
    }


def _population_label(line: dict) -> str:
    pop = line.get("population") or {}
    wards = pop.get("wards") or []
    place = "primary-care" if wards and all(w.startswith("PHC") for w in wards) else (
        ", ".join(C.WARD_LABELS.get(w, w) for w in wards) or "all-unit")
    return f"{place} {({'F': 'women', 'M': 'men'}).get(pop.get('sex'), 'patients')}"


# --------------------------------------------------------------------------- CDS Hooks cards
def swap_medication(mr: dict | None, atc: str, name: str) -> dict:
    """The draft MedicationRequest with its ATC coding swapped. Drug-specific dose and dispense fields are removed:
    the tool never proposes a dose."""
    res = copy.deepcopy(mr) if mr else {"resourceType": "MedicationRequest", "status": "draft", "intent": "order"}
    concept = {"coding": [{"system": ATC_SYSTEM, "code": atc, "display": name}], "text": name}
    if isinstance(res.get("medication"), dict) and "concept" in res["medication"]:  # FHIR R5 shape
        res["medication"] = {"concept": concept}
    else:  # FHIR R4 shape
        res["medicationCodeableConcept"] = concept
        res.pop("medicationReference", None)
    res.pop("dosageInstruction", None)
    res.pop("dispenseRequest", None)
    res["note"] = [*(res.get("note") or []), {"text": "Dose, route and duration to be set by the prescriber."}]
    return res


def _override_reasons(drug: str) -> list[dict]:
    return ([{"code": "keep", "system": OVERRIDE_SYSTEM, "display": f"Keep {drug_name(drug).lower()}"}]
            + [{"code": code, "system": OVERRIDE_SYSTEM, "display": text} for code, text in KEEP_CODES.items()])


def context_card(ctx: dict, *, medication_request: dict | None = None) -> dict | None:
    """One CDS Hooks card for an info or warning order context; None for quiet and no_data."""
    if ctx["state"] not in ("info", "warning"):
        return None
    happening = next((ln for ln in ctx["lines"] if ln["key"] == "happening"), None)
    top = ctx["evidence"]["reasons"][0] if ctx["evidence"]["reasons"] else {}
    if ctx["state"] == "warning":
        top = next(r for r in ctx["evidence"]["reasons"] if r["level"] == "warning")
    parts = []
    shown = [h for h in ctx["previous_results"] if h["drug_result"] is not None][:5]
    if shown:
        parts.append("**This patient's results (12 months):** " + "; ".join(
            f"{fmt(h['date'], 'date')} · {h['unit']} · {h['specimen']} · {short_organism(h['organism'])}"
            + (f" ({', '.join(h['flags'])})" if h["flags"] else "") + f" · {ctx['drug_name'].lower()} {h['drug_result']} "
            f"({h['reason']})" for h in shown))
    if happening:
        parts.append(f"**What is happening:** {md_escape(happening['text'])}")
    mine = next(ln for ln in ctx["lines"] if ln["key"] == "your_drug")
    parts.append(f"**Your drug on this unit:** {md_escape(mine['text'])}")
    alts = next((ln for ln in ctx["lines"] if ln["key"] == "alternatives"), None)
    if alts:
        parts.append(f"**{alts['label']}:** " + "; ".join(
            f"{i['name'].lower()} " + (f"{fmt((i['r'], i['n']), 'xofn')} ({fmt(i['pct'], 'pct0')}, 12 months)"
                                       if i["state"] != "not_enough_data" else f"not enough data (n = {i['n']})")
            for i in alts["items"]))
    parts += [LAG_NOTE, LOGGED_NOTE, f"_{SMALL_PRINT}_"]
    card_uuid = ctx["card_key"]
    suggestions = []
    for d in ctx["actions"]["change_to"]:
        atc = ORDER_ATC.get(d)
        suggestions.append({"label": f"Change to {drug_name(d).lower()}", "uuid": _uid(card_uuid, "suggestion", atc),
                            "actions": [{"type": "update",
                                         "description": f"Change the draft order from {ctx['drug_name'].lower()} to "
                                                        f"{drug_name(d).lower()} (ATC {atc}), from the local guide example. "
                                                        "Dose, route and duration stay with the prescriber.",
                                         "resource": swap_medication(medication_request, atc, drug_name(d))}]})
    card = {"uuid": card_uuid, "summary": _fit(top.get("summary") or ctx["chip"]), "detail": "\n\n".join(parts),
            "indicator": "warning" if ctx["state"] == "warning" else "info", "source": {"label": SOURCE_LABEL}}
    if suggestions:
        card["suggestions"] = suggestions
        card["selectionBehavior"] = "at-most-one"
    if ctx["state"] == "warning":
        card["overrideReasons"] = _override_reasons(ctx["drug"])
    card["links"] = [{"label": "Details", "url": ctx["actions"]["details_link"], "type": "absolute"},
                     {"label": f"Open in {C.APP_NAME} (SMART)", "url": SMART_URL, "type": "smart"}]
    card["extension"] = {EXT_RULE: INTERRUPT_RULE, EXT_WHY: ctx["rule"], EXT_STATE: ctx["state"],
                         EXT_CARD_KEY: card_uuid,
                         EXT_SOURCE: {"kind": top.get("kind"), "id": top.get("id"), "drug": ctx["drug"]},
                         EXT_EVIDENCE: ctx["evidence"]}
    return card


def order_check(ds, as_of, unit: str | None, drug: str | None, indication: str | None, alerts, policy_states, *,
                patient_id: str | None = None, stage: str = "sign", medication_request: dict | None = None) -> list[dict]:
    """Section 7 signature, section 7b rules: at most one card for one ordered drug ([] when quiet or no_data)."""
    indication = normalize_indication(indication)
    if unit is None or drug not in ORDER_NAMES or indication not in C.INDICATIONS:
        return []
    ctx = order_context(ds, as_of, patient_id, unit, indication, drug, stage, alerts, policy_states)
    card = context_card(ctx, medication_request=medication_request)
    return [card] if card else []


# --------------------------------------------------------------------------- CDS Hooks request handling
def _coding(res: dict) -> list[dict]:
    mcc = res.get("medicationCodeableConcept")
    if isinstance(mcc, dict):
        return mcc.get("coding") or []
    med = res.get("medication")
    if isinstance(med, dict) and isinstance(med.get("concept"), dict):
        return med["concept"].get("coding") or []
    return []


def medication_orders(context: dict) -> list[dict]:
    """MedicationRequests in `context.draftOrders` (only the `selections` for order-select), ATC -> order drug code."""
    bundle = context.get("draftOrders") or {}
    if not isinstance(bundle, dict):
        raise CdsRequestError("context.draftOrders must be a FHIR Bundle")
    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise CdsRequestError("draftOrders.entry must be a list")
    selections = context.get("selections")
    selected = set(selections) if isinstance(selections, list) and selections else None
    orders = []
    for e in entries[:50]:
        res = e.get("resource") if isinstance(e, dict) else None
        if not isinstance(res, dict) or res.get("resourceType") != "MedicationRequest":
            continue
        if selected is not None and f"MedicationRequest/{res.get('id')}" not in selected:
            continue
        atc = next((c.get("code") for c in _coding(res) if isinstance(c, dict) and c.get("code") in ATC_TO_ORDER
                    and c.get("system") in (None, ATC_SYSTEM)), None)
        orders.append({"atc": atc, "drug": ATC_TO_ORDER.get(atc), "resource": res})
    return orders


def parse_request(req: dict, service_id: str | None = None) -> dict:
    """Read hook, stage, patient, unit, indication, as_of and the ordered drugs from a CDS Hooks 2.0 request.
    The demo carries unit/indication/as_of in `context.extension` (a top-level `extension` is also read)."""
    hook = req.get("hook")
    if service_id is not None and SERVICE_HOOKS.get(service_id) != hook:
        raise CdsRequestError(f"service {service_id} handles hook {SERVICE_HOOKS.get(service_id)}, not {hook}")
    if hook not in SERVICE_STAGE:
        raise CdsRequestError(f"unsupported hook {hook}")
    ctx = req.get("context")
    if not isinstance(ctx, dict):
        raise CdsRequestError("context must be an object")
    ext = {**(req.get("extension") or {}), **(ctx.get("extension") or {})}
    out = {"hook": hook, "stage": SERVICE_STAGE[hook]}
    for key, name in ((EXT_UNIT, "unit"), (EXT_INDICATION, "indication"), (EXT_AS_OF, "as_of")):
        v = ext.get(key)
        if v is not None and (not isinstance(v, str) or len(v) > 32):
            raise CdsRequestError(f"extension {key} must be a short string")
        out[name] = v
    if out["unit"] is not None and out["unit"] not in C.WARD_LABELS:
        raise CdsRequestError(f"unknown unit {out['unit']}")
    out["indication"] = normalize_indication(out["indication"])
    if out["indication"] is not None and out["indication"] not in C.INDICATIONS:
        raise CdsRequestError(f"unknown indication {out['indication']}")
    pid = ctx.get("patientId")
    out["patient_id"] = pid if isinstance(pid, str) and re.fullmatch(r"P\d{6}", pid) else None
    out["orders"] = medication_orders(ctx)
    return out


def cards_for_request(ds, parsed: dict, as_of: str, alerts: list[dict], policy_states: list[dict]) -> list[dict]:
    """Every ordered drug through the order context; order-select never returns more than info cards."""
    cards, seen = [], set()
    if parsed["unit"] is None or parsed["indication"] is None:
        return []
    patient_id = parsed["patient_id"]
    if patient_id is not None and ds.patients[ds.patients.patient_id == patient_id].empty:
        patient_id = None  # not a synthetic patient from the dataset: unit-level numbers only
    for o in parsed["orders"]:
        if o["drug"] is None:
            continue
        for c in order_check(ds, as_of, parsed["unit"], o["drug"], parsed["indication"], alerts, policy_states,
                             patient_id=patient_id, stage=parsed["stage"], medication_request=o["resource"]):
            if c["uuid"] not in seen:
                seen.add(c["uuid"])
                cards.append(c)
    return sorted(cards, key=lambda c: 0 if c["indicator"] == "warning" else 1)


# --------------------------------------------------------------------------- banners (My ward)
def alert_banner(alert: dict) -> dict:
    return {"type": "alert", "indicator": "info", "alert_id": alert["id"], "signal_id": alert.get("signal_id"),
            "wards": alert.get("wards"), "drugs": alert.get("drugs"),
            "text": f"{_plain(alert.get('message'))} (approved {fmt(alert['approved_on'], 'short_date')}, "
                    f"expires {fmt(alert['expires_on'], 'short_date')})",
            "approved_on": alert.get("approved_on"), "expires_on": alert.get("expires_on")}


def policy_banner(ps: dict) -> dict | None:
    st = normalize_policy_state(ps)
    if st is None:
        return None
    line = st["line"]
    counts_txt = f"{fmt((st['x'], st['n']), 'xofn')}, " if st["x"] is not None and st["n"] else ""
    text = (f"{C.DRUG_NAMES[line['drug']]}: {_SPECIMEN_ADJ.get(line['specimen'], line['specimen'])} "
            f"{short_organism(line['organism'])} in {_population_label(line)} is {fmt(st['rate'], 'pct1')} resistant "
            f"({counts_txt}last {line['window_days'] // 7} weeks), {'above' if st['active'] else 'below'} the local "
            f"{fmt(st['threshold'], 'pct0')} line.")
    if st["active"]:
        text += f" {line['message']}."
    return {"type": "policy", "indicator": "info", "policy_id": st["id"], "signal_id": st["signal_id"],
            "active": st["active"], "drug": line["drug"], "text": text, "order_units": line.get("order_units"),
            "population_wards": (line.get("population") or {}).get("wards")}
