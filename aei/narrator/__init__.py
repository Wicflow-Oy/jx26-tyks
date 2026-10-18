"""Narration: a model writes number-free skeletons; code renders and validates them (CONTRACTS.md sections 6, 10).

`get_narrator()` picks one by env AEI_NARRATOR:
- template: the fixed English templates. The default outside public mode.
- replay: skeletons recorded earlier under .cache/narration, the template on a miss; no network. The default in
  public mode (AEI_PUBLIC=1), so the demo works with no key.
- anthropic: live Claude calls behind the spend and rate guard, reusing and recording the replay cache.
"""

from __future__ import annotations

from .. import config
from .anthropic_llm import AnthropicNarrator, key_set
from .base import AUDIENCES, LANGUAGES, Narration, Narrator
from .cached import CachedNarrator, cache_key
from .guard import GUARD, Guard
from .template import TemplateNarrator

NARRATORS = ("template", "replay", "anthropic")


def selected() -> str:
    choice = config.env("AEI_NARRATOR") or ("replay" if config.PUBLIC else "template")
    if choice not in NARRATORS:
        raise ValueError(f"AEI_NARRATOR must be one of {NARRATORS}, not {choice!r}")
    return choice


def get_narrator() -> Narrator:
    choice = selected()
    if choice == "template":
        return TemplateNarrator()
    return CachedNarrator(AnthropicNarrator(), record=choice == "anthropic")


def health() -> dict:
    """The narrator part of /api/health: names, a boolean and the spend, never a key."""
    return {"narrator": selected(), "key_set": key_set(), **GUARD.status()}


__all__ = [
    "AUDIENCES",
    "GUARD",
    "LANGUAGES",
    "NARRATORS",
    "AnthropicNarrator",
    "CachedNarrator",
    "Guard",
    "Narration",
    "Narrator",
    "TemplateNarrator",
    "cache_key",
    "get_narrator",
    "health",
    "key_set",
    "selected",
]
