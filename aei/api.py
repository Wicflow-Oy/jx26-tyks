"""The HTTP API (CONTRACTS.md sections 7, 7b and 10). Run: uvicorn aei.api:app --host 127.0.0.1 --port 8765

- The dataset loads once at startup. Without it the server still starts: /api/health says data_loaded=false and the
  data endpoints answer 503.
- Every view takes one as-of Sunday inside the replay range (or the brief's `monday`), so all screens agree.
- Writes need the browser's random X-Demo-Session id; a read without it sees the demo seeds only (see store.py).
- Public-demo hygiene: per-IP rate limit, request bodies up to 64 KB, X-Robots-Tag on every response (errors included),
  robots.txt disallows all, no CORS, and no request logging (uvicorn runs with --no-access-log; this module logs
  startup problems and unexpected errors, by path only).
- The static UI in web/ is mounted at / after every API route.
- Every endpoint that returns text takes `?lang=en|fi` (default en) and renders it in that language (aei/i18n.py);
  ids, codes and numbers are the same in both.
"""

import datetime as dt
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (
    brief,
    cds,
    cds_hooks,
    data,
    i18n,
    jev,
    narrator,
    phenotype_rules,
    precompute,
    store,
    templates,
    views,
)
from . import config as C
from .data import FLAGS
from .detectors.policy import policy_states
from .i18n import label
from .narrator.base import AUDIENCES, LANGUAGES
from .validator import validate_rendered, validate_skeleton

log = logging.getLogger(__name__)

REPLAY_FIRST = data.week_end(C.REPLAY_FIRST_WEEK).date()
REPLAY_LAST = dt.date.fromisoformat(C.DATA_END)
RATE_LIMITED_PATHS = ("/api/", "/cds-services")
LINE_LIST_MAX = 200  # newest rows shown; the epi curve and `n` always count every row
CLUSTER_KINDS = {"phenotype_cluster", "thl_rule"}
ROBOTS_TXT = "User-agent: *\nDisallow: /\n"
MAX_BODY_BYTES = 64 * 1024  # the largest real request, a CDS Hooks call, is a few KB
# What a cluster's marker implies beyond its reported R, as the shared phenotype rules apply it: MRSA, every other
# beta-lactam on the panel (EUCAST Staphylococcus expert rule 1); ESBL, cefuroxime and ceftriaxone (local rule).
MARKER_R = {"mrsa": phenotype_rules.MRSA_R, "esbl": C.LOCAL_ESBL_R}
CDS_HOOKS_NOTE = (
    "Standards-based route for an EHR that supports HL7 CDS Hooks 2.0 (order-select, order-sign). Simulated in this "
    "prototype: no EHR is connected."
)
SYNTHETIC_NOTE = "Synthetic isolate ids; no patient names or ids."


# --------------------------------------------------------------------------- app, startup, guards
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.narrator = narrator.get_narrator()  # a bad AEI_NARRATOR or AEI_LLM_BACKEND stops the start here
    store.seed_demo()  # the state DB may be ephemeral (/tmp in the container), so seed on every start
    try:
        app.state.ds = data.load()
    except OSError as e:
        log.error("dataset not loaded (%s); data endpoints answer 503, see DEPLOY.md step 2", type(e).__name__)
        app.state.ds = None
    yield


app = FastAPI(title=C.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None)


class RateLimiter:
    """At most RATE_LIMIT_PER_MIN requests per client IP in any 60 seconds. In memory only: no IP is written anywhere."""

    max_tracked = 10_000  # forget idle addresses beyond this many, so memory stays bounded

    def __init__(self):
        self.hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        recent = self.hits[ip]
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= C.RATE_LIMIT_PER_MIN:
            return False
        recent.append(now)
        if len(self.hits) > self.max_tracked:
            for idle in [k for k, q in self.hits.items() if q[-1] <= now - 60]:
                del self.hits[idle]
        return True


LIMITER = RateLimiter()


def client_ip(request: Request) -> str:
    """The proxy appends the address it saw to X-Forwarded-For, so the last entry is the one a client cannot forge."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


def _body_too_large(request: Request) -> bool:
    """A chunked body has no declared length; it is refused rather than read to find out."""
    declared = int(request.headers.get("content-length") or 0)  # the HTTP server has already checked it is a number
    return declared > MAX_BODY_BYTES or "transfer-encoding" in request.headers


@app.middleware("http")
async def guard(request: Request, call_next):
    """Rate limit and body cap, then the route. An unexpected error becomes a plain JSON 500: the traceback goes to the
    log, never to the client. Every response carries X-Robots-Tag."""
    if request.url.path.startswith(RATE_LIMITED_PATHS) and not LIMITER.allow(client_ip(request)):
        response = _error(
            429, "rate_limited", "Too many requests from this address. Please wait a minute and try again."
        )
        response.headers["Retry-After"] = "60"
    elif _body_too_large(request):
        response = _error(
            413, "too_large", f"Request bodies are limited to {MAX_BODY_BYTES // 1024} KB, sent with a Content-Length."
        )
    else:
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unexpected error on %s", request.url.path)  # the path only: no query string or body
            response = _error(500, "server_error", "Something went wrong on the server. Please try again.")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _handler(status: int, code: str):
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return _error(status, code, str(exc))

    return handle


# Errors from the modules become plain JSON with the module's own message. OrderError is a ValueError; the most
# specific registered class wins.
app.add_exception_handler(store.NotFound, _handler(404, "not_found"))
app.add_exception_handler(store.WriteLimitReached, _handler(429, "write_limit"))
app.add_exception_handler(cds.OrderError, _handler(422, "bad_order"))
app.add_exception_handler(ValueError, _handler(400, "bad_request"))


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 503: "data_not_loaded"}
    return _error(exc.status_code, codes.get(exc.status_code, "error"), str(exc.detail))


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """The first problem in the same shape as every other error, e.g. "body.wards: Input should be a valid list"."""
    first = exc.errors()[0]
    return _error(422, "invalid_request", f"{'.'.join(map(str, first['loc']))}: {first['msg']}")


# --------------------------------------------------------------------------- request dependencies
def get_ds(request: Request) -> data.Dataset:
    ds = getattr(request.app.state, "ds", None)
    if ds is None:
        raise HTTPException(503, "The dataset is not loaded on this server; see /api/health.")
    return ds


def get_viewer(x_demo_session: Annotated[str | None, Header(alias=C.SESSION_HEADER)] = None) -> str | None:
    """Reads show this session's rows plus the seeds; without the header, the seeds only."""
    return store.session_id(x_demo_session)


Viewer = Annotated[str | None, Depends(get_viewer)]


def get_session(viewer: Viewer) -> str:
    """Writes need the header. Checked before any work, because drafting a heads-up may call the model."""
    return store.require_session(viewer)


def _date(value: str, name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{name} must be a date like 2026-03-29.") from None


def parse_as_of(as_of: str | None = None, monday: str | None = None) -> str:
    """The as-of Sunday (CONTRACTS.md section 2) from `as_of`, or from `monday`, the brief's date. Default: the last
    data day."""
    if as_of and monday:
        raise HTTPException(400, "Pass as_of or monday, not both.")
    if not (as_of or monday):
        return C.DATA_END
    name, value = ("as_of", as_of) if as_of else ("monday", monday)
    given = _date(value, name)
    day = given if as_of else given - dt.timedelta(days=1)
    if day.weekday() != 6:
        expected = "a Sunday, the last data day of a week" if as_of else "a Monday, the date of a brief"
        raise HTTPException(400, f"{name} must be {expected}; {value} is a {given:%A}.")
    if not REPLAY_FIRST <= day <= REPLAY_LAST:
        raise HTTPException(400, f"as_of must be between {REPLAY_FIRST} and {REPLAY_LAST}, the replay range.")
    return day.isoformat()


Ds = Annotated[data.Dataset, Depends(get_ds)]
Session = Annotated[str, Depends(get_session)]
AsOf = Annotated[str, Depends(parse_as_of)]
Lang = Literal[i18n.LANGS]  # ?lang=en|fi


# --------------------------------------------------------------------------- request bodies
class Dated(BaseModel):
    """Writes carry the UI's global as_of (or the brief's monday), so stored state stays strictly as-of."""

    as_of: str | None = None
    monday: str | None = None

    def day(self) -> str:
        return parse_as_of(self.as_of, self.monday)


Code = Annotated[str, Field(min_length=1, max_length=64)]


class AlertIn(Dated):
    signal_id: Code | None = None
    wards: list[str] = Field(default_factory=list, max_length=len(C.WARD_LABELS))  # default: the signal's units
    drugs: list[str] = Field(default_factory=list, max_length=len(C.DRUGS))
    indications: list[str] = Field(default_factory=list, max_length=len(C.INDICATIONS))  # default: every indication
    message: str = Field(min_length=1, max_length=500)
    approved_by_role: str = "infection_control"
    expires_on: str | None = None


class HeadsUpIn(Dated):
    signal_id: Code
    language: Literal[LANGUAGES] = "en"


class NarrateIn(Dated):
    signal_id: Code
    audience: Literal[AUDIENCES] = "infection_control"
    language: Literal[LANGUAGES] = "en"


class RoleIn(BaseModel):
    approved_by_role: str = "infection_control"


class ValidateIn(BaseModel):
    text: str = Field(max_length=2000)
    slots: dict[str, str | int | float | list[int | float] | None] = Field(default_factory=dict, max_length=50)
    mode: Literal["skeleton", "rendered"] = "skeleton"


class OrderIn(Dated):
    patient_id: Code | None = None
    unit: Code
    indication: Code
    drug: Code
    stage: Literal[cds.STAGES] = "select"


class OrderFeedbackIn(Dated):
    card_key: Code
    source_id: Code | None = None
    state: Code
    outcome: Code
    reason: str | None = Field(None, max_length=100)
    changed_to: Code | None = None


class HookContext(BaseModel):
    model_config = ConfigDict(extra="allow")  # userId, draftOrders, extension...: read by cds_hooks.parse_hook_request
    patientId: Code | None = None


class HookIn(BaseModel):
    """A CDS Hooks 2.0 request. Other fields (fhirServer, prefetch...) are accepted and ignored."""

    model_config = ConfigDict(extra="allow")
    hook: str
    hookInstance: str
    context: HookContext


class Coding(BaseModel):
    model_config = ConfigDict(extra="allow")  # system and display are accepted and not stored
    code: Code


class OverrideReason(BaseModel):
    model_config = ConfigDict(extra="allow")  # the user's comment is accepted and never stored
    reason: Coding | None = None


class AcceptedSuggestion(BaseModel):
    id: Code


class HookFeedbackItem(BaseModel):
    model_config = ConfigDict(extra="allow")  # outcomeTimestamp is accepted; the store keeps its own time
    card: Code
    outcome: Code
    overrideReason: OverrideReason | None = None
    acceptedSuggestions: list[AcceptedSuggestion] = Field(default_factory=list, max_length=10)

    def reason_code(self) -> str | None:
        reason = self.overrideReason.reason if self.overrideReason else None
        return reason.code if reason else None


class HookFeedbackIn(BaseModel):
    feedback: list[HookFeedbackItem] = Field(max_length=20)


# --------------------------------------------------------------------------- helpers
def _monday(as_of: str) -> str:
    return (dt.date.fromisoformat(as_of) + dt.timedelta(days=1)).isoformat()


def _brief_items(ds, as_of: str, lang: str = "en") -> list[dict]:
    return [item for section in brief.build_brief(ds, as_of, lang=lang)["sections"] for item in section["items"]]


def _signal(ds, as_of: str, signal_id: str, lang: str = "en") -> dict:
    """A brief item at `as_of`, resolved ones included. Strict as-of: a signal that first fires later is not found."""
    found = next((s for s in _brief_items(ds, as_of, lang) if s["id"] == signal_id), None)
    if found is None:
        raise store.NotFound(f"signal {signal_id} is not in the brief for data to {as_of}")
    return found


def _alert_view(alert: dict | None, lang: str) -> dict | None:
    """An alert row as shown: its message and role in `lang` (a typed message stays as typed; the seeds have a
    Finnish version)."""
    if alert is None or lang == "en":
        return alert
    return {
        **alert,
        "message": label(alert["message"], lang),
        "approved_by_role": label(alert["approved_by_role"], lang),
    }


def _policy_view(ps: dict, lang: str) -> dict:
    """A policy line's state with its labels in `lang`."""
    return {**ps, **{k: label(ps[k], lang) for k in ("label", "drug_label", "population_label", "message")}}


def _narrate(request: Request, template_id: str, slots: dict, audience: str, language: str):
    """The narrator's text; the template narrator writes English only, so a Finnish request falling back to the
    template gets the reviewed Finnish template (same slots, same numbers)."""
    n = request.app.state.narrator.narrate(
        template_id, slots, audience=audience, language=language, client_ip=client_ip(request)
    )
    if n.provider == "template" and language in i18n.LANGS and language != "en":
        n.text, n.skeleton, n.language = (
            i18n.render_id(template_id, slots, language),
            i18n.FI[template_id]["text"],
            language,
        )
    return n


def _linked(alert: dict, item: dict) -> bool:
    """An alert approved from this item, or a demo seed (seeds have no signal id) on the cluster's unit and organism."""
    if alert["signal_id"] is not None:
        return alert["signal_id"] == item["id"]
    return item["kind"] in CLUSTER_KINDS and item["ward"] in alert["wards"] and item["organism"] == alert["organism"]


def _flagged_antibiogram(signal: dict | None) -> dict:
    """What an alert keeps of the signal it was approved from, as the demo seeds carry it (CONTRACTS.md section 7b):
    the shared antibiogram (`profile`), its marker, and `resistant_to`, the antibiogram's reported R plus what the
    marker implies. A signal without one shared antibiogram gives none; the alert's drugs still warn."""
    f = (signal or {}).get("evidence", {}).get("filter") or {}
    reported_r = {token.split(":")[0] for token in (f.get("profile") or "").split() if token.endswith(":R")}
    implied = MARKER_R.get(f.get("marker"), set()) if f.get("profile") else set()
    return {"profile": f.get("profile"), "marker": f.get("marker"), "resistant_to": sorted(reported_r | implied)}


def _wards(ward: str | None) -> list[str]:
    return [w.strip() for w in ward.split(",") if w.strip()] if ward else list(C.WARD_LABELS)


def _service(service_id: str) -> None:
    if service_id not in {s["id"] for s in cds_hooks.SERVICES}:
        raise store.NotFound(f"no CDS service {service_id}")


def _absolute_links(card: dict, request: Request) -> dict:
    """CDS Hooks links must be absolute; cds.py knows only paths, the public base URL is known here."""
    base = str(request.base_url).rstrip("/")
    for link in card.get("links", []):
        if link["url"].startswith("/"):
            link["url"] = base + link["url"]
    return card


# --------------------------------------------------------------------------- meta and health
@app.get("/api/health")
def health(request: Request) -> dict:
    """Names, booleans and the day's spend. Never a key."""
    loaded = getattr(request.app.state, "ds", None) is not None
    return {"ok": loaded, "app_name": C.APP_NAME, "data_loaded": loaded, **narrator.health()}


@app.get("/api/meta")
def meta(lang: Lang = "en") -> dict:
    return {
        "app_name": C.APP_NAME,
        "synthetic": True,
        "data_start": C.DATA_START,
        "data_end": C.DATA_END,
        "replay": {"first": REPLAY_FIRST.isoformat(), "last": C.DATA_END},
        "demo_mondays": C.DEMO_MONDAYS,
        "tour_start_as_of": C.TOUR_START_AS_OF,
        "result_lag_days": C.RESULT_LAG_DAYS,
        "wards": [{"code": w, "label": label(name, lang)} for w, name in C.WARD_LABELS.items()],
        "roles": [{"key": k, "label": label(name, lang)} for k, name in C.ROLES.items()],
        "indications": [
            {"key": k, "label": label(i["label"], lang), "specimen": i["specimen"]} for k, i in C.INDICATIONS.items()
        ],
        "cds_hooks": {"discovery": "/cds-services", "note": label(CDS_HOOKS_NOTE, lang)},
        "narrator": narrator.selected(),
        "second_opinion": jev.status(),
        "session_header": C.SESSION_HEADER,
    }


@app.get("/api/filters")
def filters(ds: Ds, lang: Lang = "en") -> dict:
    return views.filters_catalog(ds, lang)


# --------------------------------------------------------------------------- infection control: brief, replay, case file
@app.get("/api/brief")
def get_brief(
    ds: Ds, session: Viewer, as_of: AsOf, window: str = "4w", rule: str = "readme_period", lang: Lang = "en"
) -> dict:
    """The Monday brief, each item with this session's linked active alert and latest heads-up (or None), plus the
    state of every policy line, so the policy section always has its lines even when none is crossed."""
    out = brief.build_brief(ds, as_of, window=window, rule=rule, lang=lang) | {
        "policy_states": [_policy_view(ps, lang) for ps in policy_states(ds, as_of)]
    }
    alerts, heads_ups = store.alerts(session, as_of), store.heads_ups(session, as_of)
    for section in out["sections"]:
        for item in section["items"]:
            item["alert"] = _alert_view(next((a for a in reversed(alerts) if _linked(a, item)), None), lang)
            item["heads_up"] = next((h for h in heads_ups if h["signal_id"] == item["id"]), None)
    return out


@app.get("/api/replay/weeks")
def replay_weeks(ds: Ds) -> list[dict]:
    return precompute.replay_weeks(ds)


@app.get("/api/feed")
def feed(ds: Ds, as_of: AsOf, lang: Lang = "en") -> dict:
    """The "continuously updated" ticker: cultures and isolates sampled in the week ending as_of, by unit. Counts only."""
    end = pd.Timestamp(as_of)
    cultures = data.window(ds.cultures, end, 7).ward_code.value_counts()
    isolates = data.window(ds.isolates, end, 7)
    flagged = isolates.groupby("ward_code")[list(FLAGS)].sum()
    n_isolates = isolates.ward_code.value_counts()
    units = [
        {
            "ward": w,
            "label": label(name, lang),
            "cultures": int(cultures.get(w, 0)),
            "isolates": int(n_isolates.get(w, 0)),
            "flagged": {f.upper(): int(flagged.at[w, f]) for f in FLAGS if w in flagged.index and flagged.at[w, f]},
        }
        for w, name in C.WARD_LABELS.items()
    ]
    return {
        "as_of": as_of,
        "monday": _monday(as_of),
        "from": (end - pd.Timedelta(days=6)).date().isoformat(),
        "to": as_of,
        "refreshed": label("nightly", lang),
        "note": label(cds.LAG_NOTE, lang),
        "units": units,
        "totals": {"cultures": sum(u["cultures"] for u in units), "isolates": sum(u["isolates"] for u in units)},
    }


@app.get("/api/signals/{signal_id}")
def case_file(signal_id: str, ds: Ds, session: Viewer, as_of: AsOf, lang: Lang = "en") -> dict:
    """Everything behind one brief item: the signal, its line list and epi curve, seen-before matches, step-up
    evidence, and this session's linked alerts (expired and revoked ones too, for the timeline) and heads-ups."""
    signal = _signal(ds, as_of, signal_id, lang)
    rows = brief.evidence_rows(ds, signal, as_of)
    return {
        "as_of": as_of,
        "monday": _monday(as_of),
        "signal": signal,
        "line_list": {"n": len(rows), "rows": brief.line_list(rows.tail(LINE_LIST_MAX))},
        "epi_curve": brief.epi_curve(rows, signal["evidence"].get("filter") or {}, as_of),
        "seen_before": [
            s
            for s in _brief_items(ds, as_of, lang)
            if s["kind"] == "seen_before" and s["evidence"].get("cluster_id") == signal_id
        ],
        "stepup": signal["evidence"].get("stepup"),
        "alerts": [
            _alert_view(a, lang) for a in store.alerts(session, as_of, include_expired=True) if _linked(a, signal)
        ],
        "heads_ups": store.heads_ups(session, as_of, signal_id),
        "note": f"{label(cds.LAG_NOTE, lang)} {label(SYNTHETIC_NOTE, lang)}",
    }


@app.get("/api/second-opinion/{signal_id}")
def second_opinion(signal_id: str, ds: Ds, as_of: AsOf) -> dict:
    """Jev on an infection-control item, only when configured and calibrated. Never used in prescribing."""
    if jev.status() != "configured":
        return {"status": "not_configured"}
    return jev.JevAdapter().assess(_signal(ds, as_of, signal_id)) or {"status": "no_answer"}


# --------------------------------------------------------------------------- alerts and heads-ups (per session)
@app.post("/api/alerts", status_code=201)
def approve_alert(body: AlertIn, ds: Ds, session: Session) -> dict:
    as_of = body.day()
    signal = _signal(ds, as_of, body.signal_id) if body.signal_id else None
    expires_on = _date(body.expires_on, "expires_on") if body.expires_on else None
    return store.approve_alert(
        session,
        signal_id=body.signal_id,
        as_of=as_of,
        wards=body.wards or (brief.units_of(signal) if signal else []),
        drugs=body.drugs,
        indications=body.indications,
        message=body.message,
        approved_by_role=body.approved_by_role,
        expires_on=expires_on,
        organism=signal["organism"] if signal else None,
        specimen=signal["specimen"] if signal else None,
        **_flagged_antibiogram(signal),
    )


@app.get("/api/alerts")
def list_alerts(session: Viewer, as_of: AsOf, include_expired: bool = False, lang: Lang = "en") -> list[dict]:
    """Alerts active on the brief's Monday (as_of + 1). With include_expired=1, every alert approved by then, each
    with `expired` and `revoked_on` as known that Monday ("Approved 9 Mar · expired 23 Mar")."""
    return [_alert_view(a, lang) for a in store.alerts(session, as_of, include_expired=include_expired)]


@app.post("/api/alerts/{alert_id}/revoke")
def revoke_alert(alert_id: str, session: Session, body: Dated | None = None) -> dict:
    """Revoke from the brief of the given date on; without a body, from the last data week's brief."""
    return store.revoke_alert(session, alert_id, (body or Dated()).day())


@app.post("/api/heads-up", status_code=201)
def draft_heads_up(body: HeadsUpIn, request: Request, ds: Ds, session: Session, lang: Lang = "en") -> dict:
    """A heads-up for the ED, narrated from the signal's computed slots with drug names (templates.ed_heads_up).
    Written in the body's `language`, else in `?lang=`. Stored as a draft; never sent."""
    as_of = body.day()
    language = body.language if "language" in body.model_fields_set else lang
    signal = _signal(ds, as_of, body.signal_id)
    template_id, slots = templates.ed_heads_up(signal, language if language in i18n.LANGS else "en")
    n = _narrate(request, template_id, slots, "ed", language)
    draft = store.draft_heads_up(
        session, signal_id=signal["id"], as_of=as_of, text=n.text, audience="ed", provider=n.provider
    )
    return {**draft, "validated": n.validated, "fallback_reason": n.fallback_reason}


@app.post("/api/heads-up/{heads_up_id}/approve")
def approve_heads_up(heads_up_id: str, session: Session, body: RoleIn | None = None) -> dict:
    return store.approve_heads_up(session, heads_up_id, (body or RoleIn()).approved_by_role)


@app.get("/api/feedback")
@app.get("/api/order-feedback/summary")
def feedback_summary(session: Viewer, as_of: AsOf) -> list[dict]:
    """Infection control's view of order-card outcomes per source: counts only, no user or patient ids."""
    return store.feedback_summary(session, as_of)


@app.post("/api/narrate")
def narrate(body: NarrateIn, request: Request, ds: Ds, lang: Lang = "en") -> dict:
    signal = _signal(ds, body.day(), body.signal_id)
    language = body.language if "language" in body.model_fields_set else lang
    return _narrate(request, signal["template_id"], signal["slots"], body.audience, language).to_dict()


@app.post("/api/validate")
def validate(body: ValidateIn) -> dict:
    if body.mode == "skeleton":
        return validate_skeleton(body.text, list(body.slots)).to_dict()
    return validate_rendered(body.text, body.slots).to_dict()


# --------------------------------------------------------------------------- the ward doctor: My ward and orders
@app.get("/api/my-ward")
def my_ward(
    ds: Ds,
    session: Viewer,
    as_of: AsOf,
    ward: str | None = None,
    specimen: str = "blood_wound",
    organism: str | None = None,
    sex: str | None = None,
    age_band: str | None = None,
    setting: str | None = None,
    home_area: str | None = None,
    windows: str = "4w,12m",
    rule: str = "readme_period",
    lang: Lang = "en",
) -> dict:
    """Coverage on the unit(s), plus banners (active alerts and policy lines touching them) and the active signals."""
    view = views.my_ward(
        ds,
        as_of,
        ward,
        specimen_group=specimen,
        organism=organism,
        sex=sex,
        age_band=age_band,
        setting=setting,
        windows=windows,
        rule=rule,
        home_area=home_area,
        lang=lang,
    )
    alerts, states = store.alerts(session), policy_states(ds, as_of)
    banners = {
        b["id"]: b
        for w in _wards(ward)
        for b in cds.banners(as_of, w, alerts, states, specimen_group=specimen, lang=lang)
    }
    return {
        **view,
        "banners": list(banners.values()),
        "signals": brief.signals_for(ds, as_of, ward=_wards(ward) if ward else None, rule=rule, lang=lang),
    }


@app.get("/api/trend")
def trend(
    ds: Ds,
    as_of: AsOf,
    drug: str,
    ward: str | None = None,
    specimen: str = "blood_wound",
    weeks: int = 52,
    window: str = "4w",
    organism: str | None = None,
    rule: str = "readme_period",
    sex: str | None = None,
    age_band: str | None = None,
    setting: str | None = None,
    home_area: str | None = None,
    lang: Lang = "en",
) -> dict:
    return views.trend(
        ds,
        ward,
        specimen,
        drug,
        as_of,
        weeks,
        window,
        organism,
        rule,
        sex=sex,
        age_band=age_band,
        setting=setting,
        home_area=home_area,
        lang=lang,
    )


@app.post("/api/order-context")
def order_context(body: OrderIn, ds: Ds, session: Viewer, lang: Lang = "en") -> dict:
    as_of = body.day()
    return cds.order_context(
        ds,
        as_of,
        body.patient_id,
        body.unit,
        body.indication,
        body.drug,
        body.stage,
        store.alerts(session),
        policy_states(ds, as_of),
        lang,
    )


@app.get("/api/order-drugs")
def order_drugs(ds: Ds, indication: str, lang: Lang = "en") -> list[dict]:
    """The drug picker for one indication: the order drugs with a reported result on its specimen."""
    return cds.order_drugs(ds, indication, lang)


@app.get("/api/patients/{patient_id}/history")
def patient_history(patient_id: str, ds: Ds, as_of: AsOf, lang: Lang = "en") -> dict:
    """The patient's isolates in the 12 months to as_of, newest first."""
    if not (ds.patients.patient_id == patient_id).any():
        raise store.NotFound(f"patient {patient_id} not found")
    return {
        "as_of": as_of,
        "window": "12m",
        "patient": cds.patient_info(ds, patient_id, as_of),
        "previous_results": cds.previous_results(ds, as_of, patient_id, lang=lang),
    }


@app.get("/api/demo/scenarios")
def demo_scenarios(ds: Ds, session: Viewer, lang: Lang = "en") -> list[dict]:
    """The scenario picker: each scenario with the state it shows at signing for this session."""
    alerts, out = store.alerts(session), []
    for s in C.DEMO_SCENARIOS:
        ctx = cds.order_context(
            ds,
            s["as_of"],
            s["patient_id"],
            s["unit"],
            s["indication"],
            s["drug"],
            "sign",
            alerts,
            policy_states(ds, s["as_of"]),
            lang,
        )
        out.append(
            {**s, "why": label(s["why"], lang), "state": ctx["state"], "chip": ctx["chip"], "patient": ctx["patient"]}
        )
    return out


@app.post("/api/order-feedback")
def order_feedback(body: OrderFeedbackIn, session: Session) -> dict:
    return store.log_order_feedback(
        session,
        card_key=body.card_key,
        source_id=body.source_id,
        state=body.state,
        outcome=body.outcome,
        as_of=body.day(),
        reason=body.reason,
        changed_to=body.changed_to,
    )


# --------------------------------------------------------------------------- CDS Hooks 2.0 (simulated; no EHR connected)
@app.get("/cds-services")
def cds_discovery(lang: Lang = "en") -> dict:
    return {
        "services": [
            {**s, "title": label(s["title"], lang), "description": label(s["description"], lang)}
            for s in cds_hooks.SERVICES
        ]
    }


@app.post("/cds-services/{service_id}")
def cds_hook(service_id: str, body: HookIn, request: Request, ds: Ds, session: Viewer, lang: Lang = "en") -> dict:
    """order-select returns at most info cards; order-sign may return a warning. Every returned card is logged as
    shown, because a later feedback call names only the card's uuid. An EHR sends no session header: it sees the
    seeds only, and its cards are logged under store.ANONYMOUS."""
    _service(service_id)
    parsed = cds_hooks.parse_hook_request(service_id, body.model_dump())
    parsed["as_of"] = parse_as_of(parsed["as_of"])
    cards = cds_hooks.hook_cards(ds, parsed, store.alerts(session), policy_states(ds, parsed["as_of"]), lang)
    try:
        for c in cards:
            store.log_order_feedback(
                session or store.ANONYMOUS,
                card_key=c["uuid"],
                source_id=c["extension"][f"{cds.SLUG}.source"]["id"],
                state=c["indicator"],
                outcome="shown",
                as_of=parsed["as_of"],
            )
    except store.WriteLimitReached:
        log.warning("CDS cards returned without logging them as shown: the session's write limit is reached")
    return {"cards": [_absolute_links(c, request) for c in cards]}


@app.post("/cds-services/{service_id}/feedback")
def cds_feedback(service_id: str, body: HookFeedbackIn, session: Viewer) -> dict:
    """Appended to the session's feedback log (store.ANONYMOUS for an EHR, which sends no session header); feedback
    never changes an alert. Only the override reason code is kept, never the user's comment."""
    _service(service_id)
    for item in body.feedback:
        store.log_cds_feedback(
            session or store.ANONYMOUS,
            service_id=service_id,
            card_uuid=item.card,
            outcome=item.outcome,
            override_reason=item.reason_code(),
            accepted_suggestions=[s.id for s in item.acceptedSuggestions],
        )
    return {"logged": len(body.feedback)}


# --------------------------------------------------------------------------- robots and the static UI (last)
@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots() -> str:
    return ROBOTS_TXT


app.mount("/", StaticFiles(directory=C.ROOT / "web", html=True), name="web")
