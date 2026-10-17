"""Narrator interface and the shared skeleton pipeline (CONTRACTS.md section 6).

A model only writes a skeleton: prose with {slot} placeholders and no numbers. `narrate_skeleton` then runs
validate_skeleton -> render (code fills every number, in the template's own formats) -> validate_rendered. Any failure
returns the deterministic template text with `fallback_reason` set. The template fallback is English only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable

from ..render import render, render_id, slots_in
from ..templates import TEMPLATES
from ..validator import template_literals, validate_rendered, validate_skeleton

AUDIENCES = ("infection_control", "ward", "ed")
LANGUAGES = ("en", "fi", "sv")
LANGUAGE_NAMES = {"en": "English", "fi": "Finnish", "sv": "Swedish"}
TEMPLATE_LANGUAGE = "en"


@dataclass(frozen=True)
class Narration:
    """`text` is final (numbers rendered by code); `skeleton` is the text with {slot} placeholders.

    Fields beyond the contract's five: `language` is the language of `text` (English when a fi/sv request fell back to
    the template), `model` the model that wrote the skeleton, `errors` the validator codes behind a fallback, and
    `cached` whether the skeleton came from the replay cache."""
    text: str
    skeleton: str
    provider: str
    validated: bool
    fallback_reason: str | None = None
    language: str = TEMPLATE_LANGUAGE
    model: str | None = None
    errors: tuple[str, ...] = ()
    cached: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["errors"] = list(self.errors)
        return d


@runtime_checkable
class Narrator(Protocol):
    name: str            # provider id used in Narration.provider and in cache keys
    model: str | None
    prompt_version: str

    def narrate(self, template_id: str, slots: dict, *, audience: str = "infection_control", language: str = "en",
                client_key: str | None = None) -> Narration:
        """`client_key` (the caller's IP in the API) scopes live-call rate limits; narrators without live calls ignore it."""
        ...


def check_request(template_id: str, audience: str, language: str) -> None:
    if template_id not in TEMPLATES:
        raise KeyError(f"unknown template_id {template_id!r}")
    if audience not in AUDIENCES:
        raise ValueError(f"unknown audience {audience!r}; expected one of {AUDIENCES}")
    if language not in LANGUAGES:
        raise ValueError(f"unknown language {language!r}; expected one of {LANGUAGES}")


def template_text(template_id: str) -> str:
    return TEMPLATES[template_id]["text"]


def template_formats(template_id: str) -> dict[str, str]:
    """Slot -> render format exactly as `render_id` applies it: placeholder format, else the template's `formats`,
    else "text"."""
    t = TEMPLATES[template_id]
    out = dict(t.get("formats") or {})
    for name, kind in slots_in(t["text"]):
        if kind:
            out[name] = kind
        out.setdefault(name, "text")
    return out


def template_slots(template_id: str) -> list[str]:
    return list(dict.fromkeys(name for name, _ in slots_in(template_text(template_id))))


def plain_skeleton(template_id: str) -> str:
    """The template with format specs removed ("{n:int}" -> "{n}"): what a model is shown as the reference skeleton."""
    import re
    return re.sub(r"\{([a-z_][a-z0-9_]*):[a-z0-9_]+\}", r"{\1}", template_text(template_id))


def render_template(template_id: str, slots: dict) -> tuple[str, bool]:
    """Deterministic text and whether it passes validate_rendered (fixed template literals such as "52 weeks" allowed)."""
    text = render_id(template_id, slots)
    check = validate_rendered(text, slots, formats=template_formats(template_id),
                              allowed_literals=template_literals(template_text(template_id)))
    return text, check.ok


def template_fallback(template_id: str, slots: dict, *, reason: str | None, errors=(), language: str = "en") -> Narration:
    text, ok = render_template(template_id, slots)
    if reason is None and language != TEMPLATE_LANGUAGE:
        reason = "no_model_for_language"
    return Narration(text=text, skeleton=template_text(template_id), provider="template", validated=ok,
                     fallback_reason=reason, language=TEMPLATE_LANGUAGE, errors=tuple(errors))


def narrate_skeleton(skeleton: str, template_id: str, slots: dict, *, language: str, provider: str,
                     model: str | None = None, cached: bool = False) -> Narration:
    """Validate a model skeleton, render it with the template's formats, validate the result; else the template."""
    check = validate_skeleton(skeleton, template_slots(template_id))
    if not check.ok:
        return template_fallback(template_id, slots, reason="skeleton_invalid", errors=check.errors)
    formats = template_formats(template_id)
    try:
        text = render(skeleton, slots, formats)
    except (KeyError, ValueError, TypeError):
        return template_fallback(template_id, slots, reason="render_failed")
    rendered = validate_rendered(text, slots, formats=formats)
    if not rendered.ok:
        return template_fallback(template_id, slots, reason="rendered_invalid", errors=rendered.errors)
    return Narration(text=text, skeleton=skeleton, provider=provider, validated=True, fallback_reason=None,
                     language=language, model=model, cached=cached)
