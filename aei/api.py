"""The HTTP API (CONTRACTS.md sections 7, 7b and 10). Run: uvicorn aei.api:app --host 127.0.0.1 --port 8765

- The dataset loads once at startup. Without it the server still starts: /api/health says data_loaded=false and the
  data endpoints answer 503.
- Every view takes one as-of Sunday inside the replay range (or the brief's `monday`), so all screens agree.
- Writes belong to the browser's random X-Demo-Session id (see store.py); the demo seeds are visible to every session.
- Public-demo hygiene: per-IP rate limit, X-Robots-Tag on every response, robots.txt disallows all, no CORS, and no
  request logging (uvicorn runs with --no-access-log; this module logs startup problems only).
- The static UI in web/ is mounted at / after every API route.
"""
import datetime as dt
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import brief, cds, data, jev, narrator, precompute, store, views
from . import config as C
from .detectors.policy import policy_states
from .narrator.base import AUDIENCES, LANGUAGES
from .validator import validate_rendered, validate_skeleton

log = logging.getLogger(__name__)

REPLAY_FIRST = data.week_end(C.REPLAY_FIRST_WEEK).date()
REPLAY_LAST = dt.date.fromisoformat(C.DATA_END)
RATE_LIMITED_PATHS = ("/api/", "/cds-services")
LINE_LIST_MAX = 200  # newest rows shown; the epi curve and `n` always count every row
CLUSTER_KINDS = {"phenotype_cluster", "thl_rule"}
FLAGS = ("esbl", "mrsa", "vre", "cpe")
ROBOTS_TXT = "User-agent: *\nDisallow: /\n"


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


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path.startswith(RATE_LIMITED_PATHS) and not LIMITER.allow(client_ip(request)):
        response = _error(429, "rate_limited", "Too many requests from this address. Please wait a minute and try again.")
        response.headers["Retry-After"] = "60"
    else:
        response = await call_next(request)
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


# --------------------------------------------------------------------------- request dependencies
def get_ds(request: Request) -> data.Dataset:
    ds = getattr(request.app.state, "ds", None)
    if ds is None:
        raise HTTPException(503, "The dataset is not loaded on this server; see /api/health.")
    return ds


def get_session(x_demo_session: Annotated[str | None, Header(alias=C.SESSION_HEADER)] = None) -> str:
    try:
        return store.session_id(x_demo_session)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


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


class HookIn(BaseModel):
    """A CDS Hooks 2.0 request. Other fields (fhirServer, prefetch...) are accepted and ignored."""
    model_config = ConfigDict(extra="allow")
    hook: str
    hookInstance: str
    context: dict


class HookFeedbackItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    card: str
    outcome: str
    overrideReason: dict | None = None
    acceptedSuggestions: list[dict] = Field(default_factory=list, max_length=10)


class HookFeedbackIn(BaseModel):
    feedback: list[HookFeedbackItem] = Field(max_length=20)


# --------------------------------------------------------------------------- helpers
def _monday(as_of: str) -> str:
    return (dt.date.fromisoformat(as_of) + dt.timedelta(days=1)).isoformat()


def _brief_items(ds, as_of: str) -> list[dict]:
    return [item for section in brief.build_brief(ds, as_of)["sections"] for item in section["items"]]


def _signal(ds, as_of: str, signal_id: str) -> dict:
    """A brief item at `as_of`, resolved ones included. Strict as-of: a signal that first fires later is not found."""
    found = next((s for s in _brief_items(ds, as_of) if s["id"] == signal_id), None)
    if found is None:
        raise store.NotFound(f"signal {signal_id} is not in the brief for data to {as_of}")
    return found


def _linked(alert: dict, item: dict) -> bool:
    """An alert approved from this item, or a demo seed (seeds have no signal id) on the cluster's unit and organism."""
    if alert["signal_id"] is not None:
        return alert["signal_id"] == item["id"]
    return item["kind"] in CLUSTER_KINDS and item["ward"] in alert["wards"] and item["organism"] == alert["organism"]


def _wards(ward: str | None) -> list[str]:
    return [w.strip() for w in ward.split(",") if w.strip()] if ward else list(C.WARD_LABELS)


def _filtered(x: pd.DataFrame, f: dict) -> pd.DataFrame:
    """Re-run a signal's evidence filter (CONTRACTS.md section 3) under its counting rule."""
    keep = pd.Series(True, index=x.index)
    for column, key in (("ward_code", "ward"), ("organism", "organism"), ("sex", "sex"), ("profile", "profile")):
        if f.get(key) is not None:
            keep &= x[column].isin([f[key]] if isinstance(f[key], str) else f[key])
    if f.get("specimen"):
        keep &= x.specimen.isin(C.SPECIMEN_GROUPS.get(f["specimen"], [f["specimen"]]))
    if f.get("drug") in C.DRUGS:
        keep &= x[f["drug"]].notna()
    if f.get("date_from"):
        keep &= x.sample_date >= pd.Timestamp(f["date_from"])
    if f.get("date_to"):
        keep &= x.sample_date <= pd.Timestamp(f["date_to"])
    return data.first_isolates(x[keep], f["rule"])


def _evidence_rows(ds, signal: dict, as_of: str) -> pd.DataFrame:
    """The isolates behind a signal, sampled on or before as_of: its listed isolate ids, else its filter when that
    counts isolates. Unit-level checks (completeness, the quiet line) list none."""
    ev = signal.get("evidence") or {}
    x = ds.isolates[ds.isolates.sample_date <= pd.Timestamp(as_of)]
    if ev.get("isolate_ids"):
        rows = x[x.isolate_id.isin(ev["isolate_ids"])]
    elif (ev.get("filter") or {}).get("rule") in ("readme_period", "30d"):
        rows = _filtered(x, ev["filter"])
    else:
        rows = x.iloc[:0]
    return rows.sort_values(["sample_date", "isolate_id"])


def _line_list(rows: pd.DataFrame) -> list[dict]:
    """Synthetic isolate ids only: no patient id or name leaves the server."""
    return [{"isolate_id": r.isolate_id, "date": r.sample_date.date().isoformat(), "ward": r.ward_code,
             "care_day": None if pd.isna(r.care_day_no) else int(r.care_day_no), "specimen": r.specimen,
             "organism": r.organism, "profile": r.profile} for r in rows.itertuples()]


def _epi_curve(rows: pd.DataFrame, f: dict, as_of: str) -> list[dict]:
    """Isolates per sample day, zero days included, over the filter's dates (widened to cover every row)."""
    if rows.empty:
        return []
    start = min(pd.Timestamp(f["date_from"]), rows.sample_date.min()) if f.get("date_from") else rows.sample_date.min()
    end = max(min(pd.Timestamp(f.get("date_to") or as_of), pd.Timestamp(as_of)), rows.sample_date.max())
    per_day = rows.sample_date.value_counts()
    return [{"date": d.date().isoformat(), "n": int(per_day.get(d, 0))} for d in pd.date_range(start, end)]


def _service(service_id: str) -> None:
    if service_id not in {s["id"] for s in cds.SERVICES}:
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
def meta() -> dict:
    return {"app_name": C.APP_NAME, "synthetic": True, "data_start": C.DATA_START, "data_end": C.DATA_END,
            "replay": {"first": REPLAY_FIRST.isoformat(), "last": C.DATA_END}, "demo_mondays": C.DEMO_MONDAYS,
            "tour_start_as_of": C.TOUR_START_AS_OF, "result_lag_days": C.RESULT_LAG_DAYS,
            "wards": [{"code": w, "label": label} for w, label in C.WARD_LABELS.items()],
            "roles": [{"key": k, "label": label} for k, label in C.ROLES.items()],
            "narrator": narrator.selected(), "second_opinion": jev.status(), "session_header": C.SESSION_HEADER}


@app.get("/api/filters")
def filters(ds: Ds) -> dict:
    return views.filters_catalog(ds)


# --------------------------------------------------------------------------- infection control: brief, replay, case file
@app.get("/api/brief")
def get_brief(ds: Ds, session: Session, as_of: AsOf, window: str = "4w", rule: str = "readme_period") -> dict:
    """The Monday brief, each item with this session's linked active alert and latest heads-up (or None)."""
    out = brief.build_brief(ds, as_of, window=window, rule=rule)
    alerts, heads_ups = store.alerts(session, as_of), store.heads_ups(session, as_of)
    for section in out["sections"]:
        for item in section["items"]:
            item["alert"] = next((a for a in reversed(alerts) if _linked(a, item)), None)
            item["heads_up"] = next((h for h in heads_ups if h["signal_id"] == item["id"]), None)
    return out


@app.get("/api/replay/weeks")
def replay_weeks(ds: Ds) -> list[dict]:
    return precompute.replay_weeks(ds)


@app.get("/api/feed")
def feed(ds: Ds, as_of: AsOf) -> dict:
    """The "continuously updated" ticker: cultures and isolates sampled in the week ending as_of, by unit. Counts only."""
    end = pd.Timestamp(as_of)
    cultures = data.window(ds.cultures, end, 7).ward_code.value_counts()
    isolates = data.window(ds.isolates, end, 7)
    flagged = isolates.groupby("ward_code")[list(FLAGS)].sum()
    n_isolates = isolates.ward_code.value_counts()
    units = [{"ward": w, "label": label, "cultures": int(cultures.get(w, 0)), "isolates": int(n_isolates.get(w, 0)),
              "flagged": {f.upper(): int(flagged.at[w, f]) for f in FLAGS if w in flagged.index and flagged.at[w, f]}}
             for w, label in C.WARD_LABELS.items()]
    return {"as_of": as_of, "monday": _monday(as_of), "from": (end - pd.Timedelta(days=6)).date().isoformat(),
            "to": as_of, "refreshed": "nightly", "note": cds.LAG_NOTE, "units": units,
            "totals": {"cultures": sum(u["cultures"] for u in units), "isolates": sum(u["isolates"] for u in units)}}


@app.get("/api/signals/{signal_id}")
def case_file(signal_id: str, ds: Ds, session: Session, as_of: AsOf) -> dict:
    """Everything behind one brief item: the signal, its line list and epi curve, seen-before matches, step-up
    evidence, and this session's linked alerts and heads-ups."""
    signal = _signal(ds, as_of, signal_id)
    rows = _evidence_rows(ds, signal, as_of)
    return {
        "as_of": as_of, "monday": _monday(as_of), "signal": signal,
        "line_list": {"n": len(rows), "rows": _line_list(rows.tail(LINE_LIST_MAX))},
        "epi_curve": _epi_curve(rows, signal["evidence"].get("filter") or {}, as_of),
        "seen_before": [s for s in _brief_items(ds, as_of) if s["kind"] == "seen_before"
                        and s["evidence"].get("cluster_id") == signal_id],
        "stepup": signal["evidence"].get("stepup"),
        "alerts": [a for a in store.alerts(session, as_of) if _linked(a, signal)],
        "heads_ups": store.heads_ups(session, as_of, signal_id),
        "note": f"{cds.LAG_NOTE} Synthetic isolate ids; no patient names or ids.",
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
        session, signal_id=body.signal_id, as_of=as_of, wards=body.wards or (brief.units_of(signal) if signal else []),
        drugs=body.drugs, message=body.message, approved_by_role=body.approved_by_role, expires_on=expires_on,
        organism=signal["organism"] if signal else None, specimen=signal["specimen"] if signal else None)


@app.get("/api/alerts")
def list_alerts(session: Session, as_of: AsOf) -> list[dict]:
    """Alerts active on the brief's Monday (as_of + 1)."""
    return store.alerts(session, as_of)


@app.post("/api/alerts/{alert_id}/revoke")
def revoke_alert(alert_id: str, body: Dated, session: Session) -> dict:
    return store.revoke_alert(session, alert_id, body.day())


@app.post("/api/heads-up", status_code=201)
def draft_heads_up(body: HeadsUpIn, request: Request, ds: Ds, session: Session) -> dict:
    """A heads-up for the ED, narrated from the signal's computed numbers. Stored as a draft; never sent."""
    as_of = body.day()
    signal = _signal(ds, as_of, body.signal_id)
    n = request.app.state.narrator.narrate(signal["template_id"], signal["slots"], audience="ed",
                                           language=body.language, client_ip=client_ip(request))
    draft = store.draft_heads_up(session, signal_id=signal["id"], as_of=as_of, text=n.text, audience="ed",
                                 provider=n.provider)
    return {**draft, "validated": n.validated, "fallback_reason": n.fallback_reason}


@app.post("/api/heads-up/{heads_up_id}/approve")
def approve_heads_up(heads_up_id: str, session: Session, body: RoleIn | None = None) -> dict:
    return store.approve_heads_up(session, heads_up_id, (body or RoleIn()).approved_by_role)


@app.get("/api/feedback")
@app.get("/api/order-feedback/summary")
def feedback_summary(session: Session, as_of: AsOf) -> list[dict]:
    """Infection control's view of order-card outcomes per source: counts only, no user or patient ids."""
    return store.feedback_summary(session, as_of)


@app.post("/api/narrate")
def narrate(body: NarrateIn, request: Request, ds: Ds) -> dict:
    signal = _signal(ds, body.day(), body.signal_id)
    return request.app.state.narrator.narrate(signal["template_id"], signal["slots"], audience=body.audience,
                                              language=body.language, client_ip=client_ip(request)).to_dict()


@app.post("/api/validate")
def validate(body: ValidateIn) -> dict:
    if body.mode == "skeleton":
        return validate_skeleton(body.text, list(body.slots)).to_dict()
    return validate_rendered(body.text, body.slots).to_dict()


# --------------------------------------------------------------------------- the ward doctor: My ward and orders
@app.get("/api/my-ward")
def my_ward(ds: Ds, session: Session, as_of: AsOf, ward: str | None = None, specimen: str = "blood_wound",
            organism: str | None = None, sex: str | None = None, age_band: str | None = None,
            setting: str | None = None, home_area: str | None = None, windows: str = "4w,12m",
            rule: str = "readme_period") -> dict:
    """Coverage on the unit(s), plus banners (active alerts and policy lines touching them) and the active signals."""
    view = views.my_ward(ds, as_of, ward, specimen_group=specimen, organism=organism, sex=sex, age_band=age_band,
                         setting=setting, windows=windows, rule=rule, home_area=home_area)
    alerts, states = store.alerts(session), policy_states(ds, as_of)
    banners = {b["id"]: b for w in _wards(ward) for b in cds.banners(as_of, w, alerts, states)}
    return {**view, "banners": list(banners.values()),
            "signals": brief.signals_for(ds, as_of, ward=_wards(ward) if ward else None, rule=rule)}


@app.get("/api/trend")
def trend(ds: Ds, as_of: AsOf, drug: str, ward: str | None = None, specimen: str = "blood_wound", weeks: int = 52,
          window: str = "4w", organism: str | None = None, rule: str = "readme_period", sex: str | None = None,
          age_band: str | None = None, setting: str | None = None, home_area: str | None = None) -> dict:
    return views.trend(ds, ward, specimen, drug, as_of, weeks, window, organism, rule, sex=sex, age_band=age_band,
                       setting=setting, home_area=home_area)


@app.post("/api/order-context")
def order_context(body: OrderIn, ds: Ds, session: Session) -> dict:
    as_of = body.day()
    return cds.order_context(ds, as_of, body.patient_id, body.unit, body.indication, body.drug, body.stage,
                             store.alerts(session), policy_states(ds, as_of))


@app.get("/api/patients/{patient_id}/history")
def patient_history(patient_id: str, ds: Ds, as_of: AsOf) -> dict:
    """The patient's isolates in the 12 months to as_of, newest first."""
    if not (ds.patients.patient_id == patient_id).any():
        raise store.NotFound(f"patient {patient_id} not found")
    return {"as_of": as_of, "window": "12m", "patient": cds.patient_info(ds, patient_id, as_of),
            "previous_results": cds.previous_results(ds, as_of, patient_id)}


@app.get("/api/demo/scenarios")
def demo_scenarios(ds: Ds, session: Session) -> list[dict]:
    """The scenario picker: each scenario with the state it shows at signing for this session."""
    alerts, out = store.alerts(session), []
    for s in C.DEMO_SCENARIOS:
        ctx = cds.order_context(ds, s["as_of"], s["patient_id"], s["unit"], s["indication"], s["drug"], "sign",
                                alerts, policy_states(ds, s["as_of"]))
        out.append({**s, "state": ctx["state"], "chip": ctx["chip"], "patient": ctx["patient"]})
    return out


@app.post("/api/order-feedback")
def order_feedback(body: OrderFeedbackIn, session: Session) -> dict:
    return store.log_order_feedback(session, card_key=body.card_key, source_id=body.source_id, state=body.state,
                                    outcome=body.outcome, as_of=body.day(), reason=body.reason,
                                    changed_to=body.changed_to)


# --------------------------------------------------------------------------- CDS Hooks (the EHR integration story)
@app.get("/cds-services")
def cds_discovery() -> dict:
    return {"services": cds.SERVICES}


@app.post("/cds-services/{service_id}")
def cds_hook(service_id: str, body: HookIn, request: Request, ds: Ds, session: Session) -> dict:
    """order-select returns at most info cards; order-sign may return a warning. Every returned card is logged as
    shown, because a later feedback call names only the card's uuid."""
    _service(service_id)
    parsed = cds.parse_hook_request(service_id, body.model_dump())
    parsed["as_of"] = parse_as_of(parsed["as_of"])
    cards = cds.hook_cards(ds, parsed, store.alerts(session), policy_states(ds, parsed["as_of"]))
    try:
        for c in cards:
            store.log_order_feedback(session, card_key=c["uuid"], source_id=c["extension"][f"{cds.SLUG}.source"]["id"],
                                     state=c["indicator"], outcome="shown", as_of=parsed["as_of"])
    except store.WriteLimitReached:
        log.warning("CDS cards returned without logging them as shown: the session's write limit is reached")
    return {"cards": [_absolute_links(c, request) for c in cards]}


@app.post("/cds-services/{service_id}/feedback")
def cds_feedback(service_id: str, body: HookFeedbackIn, session: Session) -> dict:
    """Only the override reason code is kept, never the user's comment."""
    _service(service_id)
    for item in body.feedback:
        store.log_cds_feedback(session, service_id=service_id, card_uuid=item.card, outcome=item.outcome,
                               override_reason=((item.overrideReason or {}).get("reason") or {}).get("code"),
                               accepted_suggestions=[s.get("id") for s in item.acceptedSuggestions])
    return {"logged": len(body.feedback)}


# --------------------------------------------------------------------------- robots and the static UI (last)
@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots() -> str:
    return ROBOTS_TXT


app.mount("/", StaticFiles(directory=C.ROOT / "web", html=True), name="web")
