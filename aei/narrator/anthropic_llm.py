"""Claude as a narrator that only writes skeletons (CONTRACTS.md sections 6 and 10).

Environment, read through `config.env`, where an empty value counts as unset:
- `AEI_MODEL`: default `claude-haiku-5-5`.
- `AEI_LLM_BACKEND`: `anthropic` (default; needs `ANTHROPIC_API_KEY`), `bedrock` or `vertex`, for the EU route.
  - `bedrock`: `AnthropicBedrockMantle` in `AWS_REGION` (default `eu-central-1`). The model id comes from
    `AEI_BEDROCK_MODEL`, else `eu.anthropic.<AEI_MODEL>` (an EU inference profile). That id format is a guess to verify.
    Credentials come from AWS env vars or a profile.
  - `vertex`: `AnthropicVertex` with `ANTHROPIC_VERTEX_PROJECT_ID`, region `CLOUD_ML_REGION` (default `eu`), and Google
    application-default credentials.
- `AEI_EFFORT`: `output_config.effort`, default `low`. Set it to `none` to omit the field.

Request rules (verified API facts): no temperature/top_p/top_k (a 400 on 5.5 models), no tools and no tool_choice,
no `thinking` parameter, and one stable system prompt carrying PROMPT_VERSION. The client is built lazily and only when
credentials exist. Every live call first passes the guard (daily spend cap, per-key rate limit). When the guard says no,
the narrator replays the cache, then uses the template, with fallback_reason "spend_cap" or "rate_limited". Any
stop_reason other than "end_turn" (including "refusal"), and any API error, falls back to the template. Logs carry
reason codes only: never prompts, keys or raw API error bodies.
"""
from __future__ import annotations

import dataclasses
import logging

from .. import config
from ..render import render_id
from . import cached as _cached
from . import guard as _guard
from .base import (
    LANGUAGE_NAMES,
    Narration,
    check_request,
    narrate_skeleton,
    plain_skeleton,
    template_fallback,
    template_slots,
)

log = logging.getLogger(__name__)

PROMPT_VERSION = "aei-narrator-1 (2026-10-17)"
DEFAULT_MODEL = "claude-haiku-5-5"
BACKENDS = ("anthropic", "bedrock", "vertex")
DEFAULT_BEDROCK_REGION = "eu-central-1"
DEFAULT_VERTEX_REGION = "eu"
DEFAULT_BASE_URL = "https://api.anthropic.com"
MAX_TOKENS = 4096  # thinking (adaptive, on by default on Haiku 5.5) counts toward this; a skeleton is ~100 tokens
TIMEOUT_S = 8.0
MAX_RETRIES = 1

AUDIENCE_BRIEFS = {
    "infection_control": "one or two factual sentences for the infection-control team's weekly brief",
    "ward": "one short sentence for a banner shown to ward staff",
    "ed": ("a short heads-up draft for the emergency department, two or three sentences; infection control reviews and "
           "approves it before anything is sent"),
}

SYSTEM_PROMPT = f"""You write short narration for {config.APP_NAME}, a weekly antimicrobial-resistance surveillance tool \
used by a hospital infection-control team. All data is synthetic.

You receive one finding that code has already computed: a reference skeleton, the reference sentence with its values \
filled in, and the slot names you may use. Rewrite the finding for the requested audience and language as a skeleton: \
plain prose in which every number, count, percentage, date, ward, organism, drug and antibiogram appears only as a \
{{slot_name}} placeholder. Code fills in the values afterwards and checks your text. Text that breaks a rule is \
discarded and a fixed template is shown instead.

Rules:
- Use only the listed slot names, written exactly as {{slot_name}}, with no format suffix.
- Never write digits or number words in any language: not "three", "kolme", "tre", "half", "a third", "twice", \
"double", "percent", "both" or "a couple of". Vague words such as "several" or "few" are fine, and so is "first".
- Do not compute or compare numbers in words ("doubled", "rose by", "times higher", "percentage points", "most of"). \
Put the slot values side by side instead.
- Describe what was observed. No prediction or recommendation language: no "predict", "forecast", "odds", \
"likely to", "probability", "will rise", "best choice" or "recommended drug".
- Never write "outbreak", "confirmed", "decoy", "clone", "same strain", "S/I/R" or "zero resistance". Say \
"unusual pattern" or "possible cluster", "typing advised", and "profile match, not typing". Results are S or R. A unit \
with no results has a "data gap, cause unknown".
- No doses, no prescribing instructions and no patient identifiers.
- Plain text only: no markdown, quotation marks, lists or preamble. Return only the skeleton.

Audiences:
- infection_control: {AUDIENCE_BRIEFS["infection_control"]}.
- ward: {AUDIENCE_BRIEFS["ward"]}.
- ed: {AUDIENCE_BRIEFS["ed"]}.

Languages: en is English, fi is Finnish (plain clinical Finnish), sv is Swedish (Finland-Swedish clinical usage). Slot \
values are filled in by code and may stay in English.

Prompt version: {PROMPT_VERSION}"""


def _aws_credentials_present() -> bool:
    names = ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_BEARER_TOKEN_BEDROCK", "AWS_WEB_IDENTITY_TOKEN_FILE",
             "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    return any(config.env(n) for n in names)


def credentials_available(backend: str | None = None) -> bool:
    """Whether a live client could be built. Never returns or logs the credential itself."""
    backend = backend or config.env("AEI_LLM_BACKEND", "anthropic")
    if backend == "anthropic":
        return config.env("ANTHROPIC_API_KEY") is not None
    if backend == "bedrock":
        return _aws_credentials_present()
    if backend == "vertex":
        return config.env("ANTHROPIC_VERTEX_PROJECT_ID") is not None
    return False


def build_user_prompt(template_id: str, slots: dict, *, audience: str, language: str) -> str:
    return "\n".join([
        f"audience: {audience} ({AUDIENCE_BRIEFS[audience]})",
        f"language: {language} ({LANGUAGE_NAMES[language]})",
        f"finding type: {template_id}",
        f"slots you may use: {', '.join('{' + s + '}' for s in template_slots(template_id))}",
        f"reference skeleton: {plain_skeleton(template_id)}",
        f"reference sentence (values filled in by code; never copy them): {render_id(template_id, slots)}",
        "Write the skeleton now.",
    ])


class AnthropicNarrator:
    name = "anthropic"
    label = "anthropic"
    prompt_version = PROMPT_VERSION

    def __init__(self, client=None, *, model: str | None = None, backend: str | None = None, guard=None,
                 replay_path=None, timeout: float = TIMEOUT_S):
        self.model = model or config.env("AEI_MODEL", DEFAULT_MODEL)
        self.backend = (backend or config.env("AEI_LLM_BACKEND", "anthropic")).lower()
        if self.backend not in BACKENDS:
            raise ValueError(f"AEI_LLM_BACKEND must be one of {BACKENDS}")
        self._client = client          # injected (tests) or built lazily
        self._client_failed = False
        self._guard = guard
        self.replay_path = replay_path
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"AnthropicNarrator(model={self.model!r}, backend={self.backend!r})"

    @property
    def guard(self):
        return self._guard or _guard.get_guard()

    @property
    def request_model(self) -> str:
        if self.backend == "bedrock":
            return config.env("AEI_BEDROCK_MODEL") or f"eu.anthropic.{self.model}"
        return self.model

    def _get_client(self):
        if self._client is not None or self._client_failed:
            return self._client
        if not credentials_available(self.backend):
            return None
        try:
            import anthropic
            if self.backend == "anthropic":
                self._client = anthropic.Anthropic(api_key=config.env("ANTHROPIC_API_KEY"), max_retries=MAX_RETRIES,
                                                   base_url=config.env("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL))
            elif self.backend == "bedrock":
                region = config.env("AWS_REGION") or config.env("AWS_DEFAULT_REGION") or DEFAULT_BEDROCK_REGION
                self._client = anthropic.AnthropicBedrockMantle(aws_region=region, max_retries=MAX_RETRIES)
            else:
                self._client = anthropic.AnthropicVertex(project_id=config.env("ANTHROPIC_VERTEX_PROJECT_ID"),
                                                         region=config.env("CLOUD_ML_REGION", DEFAULT_VERTEX_REGION),
                                                         max_retries=MAX_RETRIES)
        except Exception as e:  # noqa: BLE001 - construction problems must never break narration
            log.warning("narrator client not built (%s)", type(e).__name__)
            self._client_failed = True
            self._client = None
        return self._client

    def _request(self, template_id: str, slots: dict, audience: str, language: str) -> dict:
        req = {"model": self.request_model, "max_tokens": MAX_TOKENS, "system": SYSTEM_PROMPT,
               "messages": [{"role": "user", "content": build_user_prompt(template_id, slots, audience=audience,
                                                                          language=language)}],
               "timeout": self.timeout}
        effort = config.env("AEI_EFFORT", "low").lower()
        if effort != "none":
            req["output_config"] = {"effort": effort}
        return req

    def _denied(self, template_id, slots, audience, language, reason) -> Narration:
        hit, _ = _cached.lookup(self, template_id, slots, audience=audience, language=language, path=self.replay_path)
        if hit is not None:
            return dataclasses.replace(hit, fallback_reason=reason)
        return template_fallback(template_id, slots, reason=reason)

    def narrate(self, template_id: str, slots: dict, *, audience: str = "infection_control", language: str = "en",
                client_key: str | None = None) -> Narration:
        check_request(template_id, audience, language)
        client = self._get_client()
        if client is None:
            return template_fallback(template_id, slots, reason="no_credentials")
        ok, why = self.guard.allow(client_key)
        if not ok:
            log.info("narrator live call skipped (%s)", why)
            return self._denied(template_id, slots, audience, language, why)
        try:
            resp = client.messages.create(**self._request(template_id, slots, audience, language))
        except Exception as e:  # noqa: BLE001 - any API or transport failure falls back
            status = getattr(e, "status_code", None)
            reason = f"api_error:{status}" if status else f"api_error:{type(e).__name__}"
            log.warning("narrator fallback (%s)", reason)
            return template_fallback(template_id, slots, reason=reason)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self.guard.record(getattr(resp, "model", None) or self.model, usage)
        stop = getattr(resp, "stop_reason", None)
        if stop != "end_turn":
            reason = "refusal" if stop == "refusal" else f"stop_reason:{stop}"
            log.warning("narrator fallback (%s)", reason)
            return template_fallback(template_id, slots, reason=reason)
        skeleton = "".join(getattr(b, "text", "") for b in (getattr(resp, "content", None) or [])
                           if getattr(b, "type", None) == "text").strip()
        if not skeleton:
            return template_fallback(template_id, slots, reason="empty_response")
        n = narrate_skeleton(skeleton, template_id, slots, language=language, provider=self.name,
                             model=getattr(resp, "model", None) or self.model)
        if n.fallback_reason:
            log.warning("narrator fallback (%s)", n.fallback_reason)
        return n


def key_set() -> bool:
    """For /api/health: is a credential for the configured backend present? (Never the key itself.)"""
    return credentials_available()


