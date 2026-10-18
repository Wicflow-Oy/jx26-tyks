"""Claude as a narrator that writes only skeletons (CONTRACTS.md sections 6 and 10).

Environment (read through config.env, where an empty value counts as unset):
- AEI_MODEL: default claude-haiku-5-5.
- AEI_LLM_BACKEND: anthropic (default; needs ANTHROPIC_API_KEY), or an EU route:
  bedrock (AnthropicBedrockMantle in AWS_REGION, default eu-central-1, AWS credentials) or
  vertex (AnthropicVertex with ANTHROPIC_VERTEX_PROJECT_ID, region CLOUD_ML_REGION, default eu).

Request rules (verified API facts for the 5.5 models): no temperature/top_p/top_k (a 400), no tools and so no forced
tool_choice, no thinking parameter, and one stable system prompt. The client is built on first use and only when
credentials exist. Every live call first passes the spend and rate guard. Any stop_reason other than "end_turn"
(a refusal, max_tokens) and any API error fall back to the template. Logs carry reason codes only, never prompts or keys.
The model sees computed slots only (labels, counts, dates), never a patient or isolate id: a slot that looks like one
stops the call before anything is sent.
"""

from __future__ import annotations

import json
import logging
import re

import anthropic

from .. import config
from ..render import render_id
from .base import (
    Narration,
    check_request,
    narrate_skeleton,
    plain_skeleton,
    slot_names,
    template_narration,
)
from .guard import GUARD, Guard

log = logging.getLogger(__name__)

PROMPT_VERSION = "narrator-2"  # part of the replay cache key: change it whenever SYSTEM_PROMPT or user_prompt changes
DEFAULT_MODEL = "claude-haiku-5-5"
BACKENDS = ("anthropic", "bedrock", "vertex")
MAX_TOKENS = 4096  # adaptive thinking (on by default on Haiku 5.5) counts toward this; a skeleton is ~100 tokens
EFFORT = "low"  # a short rewrite needs little reasoning; keeps latency and cost down
TIMEOUT_S = 10.0

AUDIENCE_STYLE = {
    "infection_control": "one or two factual sentences for the infection-control team's weekly brief",
    "ward": "one short sentence for a banner shown to ward staff",
    "ed": (
        "a two- or three-sentence heads-up draft for the emergency department, reviewed by infection control before "
        "anything is sent"
    ),
}
# The dataset's synthetic patient ids (P001948) and culture/isolate ids (C0000003-1)
IDENTIFIER = re.compile(r"\bP\d{6}\b|\bC\d{7}(?:-\d+)?\b")
LANGUAGE_NAMES = {
    "en": "English",
    "fi": "Finnish (plain clinical Finnish)",
    "sv": "Swedish (Finland-Swedish clinical usage)",
}

SYSTEM_PROMPT = f"""You write short narration for {config.APP_NAME}, a weekly antimicrobial-resistance surveillance \
tool used by a hospital's infection-control team. All data is synthetic.

You receive one finding that code has already computed: a reference skeleton, the reference sentence with its values \
filled in, and the slot names you may use. Rewrite the finding for the requested audience and language as a skeleton: \
plain prose in which every number, count, percentage, date, ward, organism, drug and antibiogram appears only as a \
{{slot_name}} placeholder. Code fills in the values afterwards and checks your text; text that breaks a rule is \
discarded and a fixed template is shown instead.

Rules:
- Use only the listed slot names, written exactly as {{slot_name}}, with no format suffix.
- Never write digits or number words in any language ("one", "three", "kolme", "tre", "half", "twice", "double", \
"percent", "both", "a couple of"). Write "a shared antibiogram", not "one antibiogram". "Several", "few" and "first" \
are fine.
- Do not compute or compare numbers in words ("doubled", "rose by", "times higher", "percentage points", "most of"). \
Put the slot values side by side instead.
- Describe what was observed. No prediction or recommendation language: no "predict", "forecast", "odds", \
"likely to", "probability", "will rise", "best choice" or "recommended drug".
- Never write "outbreak", "confirmed", "decoy", "clone", "same strain", "S/I/R" or "zero resistance". Say "unusual \
pattern" or "possible cluster", "typing advised", and "profile match, not typing". Results are S or R. A unit with no \
results has a "data gap, cause unknown".
- No doses, no prescribing instructions and no patient identifiers.
- Plain text only: no markdown, quotation marks, lists or preamble. Return only the skeleton.

Audiences:
- infection_control: {AUDIENCE_STYLE["infection_control"]}.
- ward: {AUDIENCE_STYLE["ward"]}.
- ed: {AUDIENCE_STYLE["ed"]}.

Slot values are filled in by code and may stay in English."""


def key_set(backend: str | None = None) -> bool:
    """Whether credentials for the backend are present (for /api/health). Never returns the credential itself."""
    backend = backend or config.env("AEI_LLM_BACKEND", "anthropic")
    if backend == "bedrock":
        return any(config.env(n) for n in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_BEARER_TOKEN_BEDROCK"))
    if backend == "vertex":
        return config.env("ANTHROPIC_VERTEX_PROJECT_ID") is not None
    return config.env("ANTHROPIC_API_KEY") is not None


def _build_client(backend: str):
    if backend == "bedrock":
        region = config.env("AWS_REGION", "eu-central-1")
        return anthropic.AnthropicBedrockMantle(aws_region=region, max_retries=1, timeout=TIMEOUT_S)
    if backend == "vertex":
        return anthropic.AnthropicVertex(
            project_id=config.env("ANTHROPIC_VERTEX_PROJECT_ID"),
            region=config.env("CLOUD_ML_REGION", "eu"),
            max_retries=1,
            timeout=TIMEOUT_S,
        )
    return anthropic.Anthropic(api_key=config.env("ANTHROPIC_API_KEY"), max_retries=1, timeout=TIMEOUT_S)


def user_prompt(template_id: str, slots: dict, *, audience: str, language: str) -> str:
    return "\n".join(
        [
            f"audience: {audience} ({AUDIENCE_STYLE[audience]})",
            f"language: {LANGUAGE_NAMES[language]}",
            f"slots you may use: {', '.join('{' + name + '}' for name in slot_names(template_id))}",
            f"reference skeleton: {plain_skeleton(template_id)}",
            f"reference sentence (values filled in by code; do not copy them): {render_id(template_id, slots)}",
            "Write the skeleton now.",
        ]
    )


class AnthropicNarrator:
    name = "anthropic"
    prompt_version = PROMPT_VERSION

    def __init__(
        self, client=None, *, model: str | None = None, backend: str | None = None, guard: Guard | None = None
    ):
        self.model = model or config.env("AEI_MODEL", DEFAULT_MODEL)
        self.backend = backend or config.env("AEI_LLM_BACKEND", "anthropic")
        if self.backend not in BACKENDS:
            raise ValueError(f"AEI_LLM_BACKEND must be one of {BACKENDS}")
        self.guard = guard or GUARD
        self._client = client  # injected in tests; otherwise built on the first live call

    def _get_client(self):
        if self._client is None and key_set(self.backend):
            self._client = _build_client(self.backend)
        return self._client

    def _request_model(self) -> str:
        # Bedrock model ids carry an "anthropic." prefix; Anthropic and Vertex use the bare id.
        if self.backend == "bedrock" and not self.model.startswith("anthropic."):
            return f"anthropic.{self.model}"
        return self.model

    def narrate(
        self,
        template_id: str,
        slots: dict,
        *,
        audience: str = "infection_control",
        language: str = "en",
        client_ip: str | None = None,
    ) -> Narration:
        check_request(template_id, audience, language)
        if IDENTIFIER.search(json.dumps(slots, default=str)):
            return template_narration(template_id, slots, fallback_reason="identifier_in_slots")
        client = self._get_client()
        if client is None:
            return template_narration(template_id, slots, fallback_reason="no_key")
        refused = self.guard.check(client_ip)
        if refused:
            return template_narration(template_id, slots, fallback_reason=refused)
        try:
            response = client.messages.create(
                model=self._request_model(),
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                output_config={"effort": EFFORT},
                messages=[
                    {"role": "user", "content": user_prompt(template_id, slots, audience=audience, language=language)}
                ],
            )
        except anthropic.APIError as e:
            reason = f"api_error:{getattr(e, 'status_code', None) or type(e).__name__}"
            log.warning("narration fell back to the template (%s)", reason)
            return template_narration(template_id, slots, fallback_reason=reason)
        self.guard.record(self.model, response.usage)
        if response.stop_reason != "end_turn":
            log.warning("narration fell back to the template (stop_reason %s)", response.stop_reason)
            return template_narration(template_id, slots, fallback_reason=f"stop_reason:{response.stop_reason}")
        skeleton = "".join(block.text for block in response.content if block.type == "text").strip()
        return narrate_skeleton(skeleton, template_id, slots, provider=self.name, language=language)
