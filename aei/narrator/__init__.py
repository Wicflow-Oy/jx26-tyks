"""Narration: a model writes number-free skeletons, code renders and validates (CONTRACTS.md sections 6 and 10).

`get_narrator()` reads env `AEI_NARRATOR` (through `config.env`, so an empty value counts as unset):
- `template`: deterministic templates, English only. The default unless the app runs in public mode.
- `replay`: cached model skeletons under `.cache/narration`, falling back to the template on a miss, with no network.
  The default in public mode (`AEI_PUBLIC=1`).
- `anthropic`: live Claude calls behind the spend and rate guard, recording each validated result to the replay cache
  and reusing cached results. Live calls happen only when credentials for `AEI_LLM_BACKEND` are set.
"""
from __future__ import annotations

import logging

from .. import config
from .anthropic_llm import PROMPT_VERSION, AnthropicNarrator, credentials_available
from .base import AUDIENCES, LANGUAGES, Narration, Narrator
from .cached import CachedNarrator, cache_key, precompute_items
from .guard import Guard, get_guard, set_guard
from .template import TemplateNarrator

log = logging.getLogger(__name__)

NARRATORS = ("template", "replay", "anthropic")


def public_mode() -> bool:
    return config.env("AEI_PUBLIC", "1" if getattr(config, "PUBLIC", False) else "0") == "1"


def get_narrator(name: str | None = None) -> Narrator:
    choice = (name or config.env("AEI_NARRATOR") or ("replay" if public_mode() else "template")).lower()
    if choice == "template":
        return TemplateNarrator()
    if choice == "replay":
        return CachedNarrator(AnthropicNarrator(), mode="replay")
    if choice == "anthropic":
        return CachedNarrator(AnthropicNarrator(), mode="record")
    log.warning("unknown AEI_NARRATOR value; using the template narrator")
    return TemplateNarrator()


def health(narrator: Narrator | None = None) -> dict:
    """The narrator part of /api/health: names and booleans only, never a key."""
    narrator = narrator or get_narrator()
    status = get_guard().status()
    return {"narrator": getattr(narrator, "label", narrator.name), "key_set": credentials_available(),
            "spend_today_usd": status["spend_today_usd"], "cap_usd": status["cap_usd"]}


__all__ = ["AUDIENCES", "LANGUAGES", "NARRATORS", "PROMPT_VERSION", "AnthropicNarrator", "CachedNarrator", "Guard",
           "Narration", "Narrator", "TemplateNarrator", "cache_key", "credentials_available", "get_guard",
           "get_narrator", "health", "precompute_items", "public_mode", "set_guard"]
