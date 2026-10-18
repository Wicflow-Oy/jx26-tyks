"""HL7 CDS Hooks 2.0 for the order layer (CONTRACTS.md section 7): discovery, reading an order-select or order-sign
request, and an info or warning order context (aei/cds.py) as a card. Simulated in this prototype: no EHR is connected.

A card carries no suggestions and no selectionBehavior: it flags the ordered drug, and the doctor decides (keep with a
reason, or edit the order in the EHR). order-select returns at most info; order-sign may warn.
"""

import re

from . import config as C
from .cds import HISTORY_WEEKS, SLUG, OrderError, indication_key, iso_day, order_context
from .i18n import label, render_id, short_organism
from .render import fmt

ATC_SYSTEM = "http://www.whocc.no/atc"
OVERRIDE_SYSTEM = f"urn:{SLUG}:keep-reason"
SERVICES = [
    {
        "hook": "order-select",
        "id": f"{SLUG}-order-select",
        "title": f"{C.APP_NAME} unit resistance context",
        "description": (
            "When an antibiotic is selected, flags it with passive information from approved infection-control alerts, "
            "local lines and the unit's observed counts. Never interrupts at selection and never names another drug."
        ),
        "prefetch": {},
    },
    {
        "hook": "order-sign",
        "id": f"{SLUG}-order-sign",
        "title": f"{C.APP_NAME} unit resistance check",
        "description": (
            "Before an antibiotic order is signed, asks once when an approved alert applies to this unit and drug, or "
            "the patient's own recent isolate had acquired resistance to it. The doctor decides."
        ),
        "prefetch": {},
    },
]
ORDER_ATC = {code: atc for code, _, atc in C.ORDER_DRUGS}
# Orders are read through config.ATC, minus screening markers (an order coded as cefoxitin is not flucloxacillin),
# plus the order picker's own codes.
ATC_TO_DRUG = {atc: d for atc, d in C.ATC.items() if d not in C.HIDDEN_AS_OPTION} | {a: d for d, a in ORDER_ATC.items()}
_MARKDOWN = re.compile(r"([\\`*_\[\]<>#|])")


def _md(text: str) -> str:
    """Alert messages are typed by users; escape them so a card's markdown cannot carry links, HTML or emphasis."""
    return _MARKDOWN.sub(r"\\\1", text)


def _atc_codes(medication_request: dict | None) -> list:
    return [
        c.get("code") for c in ((medication_request or {}).get("medicationCodeableConcept") or {}).get("coding") or []
    ]


def card(ctx: dict, medication_request: dict | None = None, lang: str = "en") -> dict | None:
    """The CDS Hooks card for an info or warning order context rendered in `lang`; None otherwise. It carries no
    suggestions: the card flags the ordered drug and the doctor decides (keep with a reason, or edit the order in the
    EHR)."""
    if ctx["state"] not in ("info", "warning"):
        return None
    name, lines = ctx["drug_name"], {ln["key"]: ln for ln in ctx["lines"]}
    detail = []
    if ctx["previous_results"]:
        detail.append(
            f"**{render_id('cds_results_label', {'weeks': HISTORY_WEEKS}, lang)}** "
            + "; ".join(
                f"{fmt(h['date'], 'date', lang)}, {h['unit']}, {label(h['specimen'], lang)}, {short_organism(h['organism'])}"
                + "".join(f" {f}" for f in h["flags"])
                + (
                    f": {name.lower()} {h['drug_result']} ({h['reason_text']})"
                    if h["drug_result"]
                    else f": {name.lower()} {h['reason_text']}"
                )
                for h in ctx["previous_results"][:5]
            )
        )
    notes = ctx["notes"] + [label(C.ATC_NOTES[c], lang) for c in _atc_codes(medication_request) if c in C.ATC_NOTES]
    detail += [f"**{label('Note:', lang)}** {n}" for n in notes]
    detail.append(f"**{label('What is happening:', lang)}** {_md(ctx['headline'])} {_md(lines['happening']['text'])}")
    detail.append(f"**{label('This drug in this population:', lang)}** {lines['your_drug']['text']}")
    detail += [ctx["ask"], ctx["note"], f"_{ctx['small_print']}_"]
    return {
        "uuid": ctx["card_key"],
        "summary": ctx["chip"][:140],
        "detail": "\n\n".join(detail),
        "indicator": ctx["state"],
        "source": {"label": f"{C.APP_NAME} · {label('infection control', lang)}"},
        "overrideReasons": (
            [{"code": "keep", "system": OVERRIDE_SYSTEM, "display": ctx["actions"]["keep"]["label"]}]
            + [
                {
                    "code": re.sub(r"\W+", "_", r.lower()).strip("_"),
                    "system": OVERRIDE_SYSTEM,
                    "display": label(r, lang),
                }
                for r in C.KEEP_REASONS
            ]
        ),
        "links": [
            {"label": ctx["actions"]["details"]["label"], "url": ctx["actions"]["details"]["link"], "type": "absolute"}
        ],
        "extension": {
            f"{SLUG}.rule": ctx["rule"],
            f"{SLUG}.source": ctx["source"],
            f"{SLUG}.evidence": ctx["evidence"],
        },
    }


def order_check(
    ds,
    as_of,
    unit: str,
    drug: str,
    indication: str,
    alerts,
    policy_states,
    *,
    patient_id: str | None = None,
    stage: str = "sign",
    medication_request: dict | None = None,
    lang: str = "en",
) -> list[dict]:
    """Section 7: the cards for one ordered drug, [] when quiet, no data or a notice."""
    c = card(
        order_context(ds, as_of, patient_id, unit, indication, drug, stage, alerts, policy_states, lang),
        medication_request,
        lang,
    )
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
        fields = {
            "unit": ext.get(f"{SLUG}.unit"),
            "indication": ext.get(f"{SLUG}.indication"),
            "as_of": ext.get(f"{SLUG}.as_of"),
            "patientId": ctx.get("patientId"),
        }
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
    unit, indication = fields["unit"], indication_key(fields["indication"])
    if unit not in (None, *C.WARD_LABELS) or indication not in (None, *C.INDICATIONS):
        raise OrderError(f"unknown unit or indication: {unit}, {indication}")
    return {
        "stage": "select" if hook == "order-select" else "sign",
        "unit": unit,
        "indication": indication,
        "as_of": iso_day(fields["as_of"] or C.DATA_END),
        "patient_id": fields["patientId"],
        "orders": orders,
    }


def hook_cards(ds, parsed: dict, alerts, policy_states, lang: str = "en") -> list[dict]:
    """Cards for every ordered drug in a parsed request, warnings first; order-select never returns more than info.
    Without our unit and indication extension there is nothing to say."""
    if parsed["unit"] is None or parsed["indication"] is None:
        return []
    pid = parsed["patient_id"]
    pid = pid if (ds.patients.patient_id == pid).any() else None  # an id outside the dataset: unit-level only
    cards = {
        c["uuid"]: c
        for o in parsed["orders"]
        for c in order_check(
            ds,
            parsed["as_of"],
            parsed["unit"],
            o["drug"],
            parsed["indication"],
            alerts,
            policy_states,
            patient_id=pid,
            stage=parsed["stage"],
            medication_request=o["resource"],
            lang=lang,
        )
    }
    return sorted(cards.values(), key=lambda c: c["indicator"] != "warning")
