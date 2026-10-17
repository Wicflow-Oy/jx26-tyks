"""The narrator interface and the one skeleton pipeline every provider shares (CONTRACTS.md section 6).

A model writes only a skeleton: prose with {slot} placeholders and no numbers. `narrate_skeleton` checks it
(validate_skeleton), lets code fill in every number in the template's own formats (render), and checks the result
(validate_rendered). Any failure returns the fixed template text with `fallback_reason` set, so a number on screen
always comes from a computed slot.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Protocol

from ..render import render, render_id, slots_in
from ..templates import TEMPLATES
from ..validator import template_literals, validate_rendered, validate_skeleton

AUDIENCES = ("infection_control", "ward", "ed")
LANGUAGES = ("en", "fi", "sv")


@dataclass
class Narration:
    text: str                            # final text; every number rendered by code
    skeleton: str                        # the text with {slot} placeholders
    provider: str                        # "template", or the model provider that wrote the skeleton
    validated: bool                      # `text` passed validate_rendered
    fallback_reason: str | None = None   # why the template text replaced a model narration
    language: str = "en"                 # language of `text`: the templates are English only
    errors: list[str] = field(default_factory=list)  # validator errors behind a fallback

    def to_dict(self) -> dict:
        return asdict(self)


class Narrator(Protocol):
    name: str                  # provider id, part of the replay cache key
    model: str | None
    prompt_version: str

    def narrate(self, template_id: str, slots: dict, *, audience: str = "infection_control", language: str = "en",
                client_ip: str | None = None) -> Narration:
        """`client_ip` scopes the live-call rate limit; narrators that make no live calls ignore it."""
        ...


def check_request(template_id: str, audience: str, language: str) -> None:
    if template_id not in TEMPLATES:
        raise KeyError(f"unknown template_id {template_id!r}")
    if audience not in AUDIENCES:
        raise ValueError(f"audience must be one of {AUDIENCES}")
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {LANGUAGES}")


def slot_names(template_id: str) -> list[str]:
    return list(dict.fromkeys(name for name, _ in slots_in(TEMPLATES[template_id]["text"])))


def slot_formats(template_id: str) -> dict[str, str]:
    """Slot -> render format exactly as render_id applies it, so a model skeleton renders numbers like the template."""
    template = TEMPLATES[template_id]
    formats = dict(template.get("formats") or {})
    for name, kind in slots_in(template["text"]):
        formats[name] = kind or formats.get(name, "text")
    return formats


def plain_skeleton(template_id: str) -> str:
    """The template with its format specs removed ("{n:int}" -> "{n}"): the reference a model is shown."""
    return re.sub(r"\{([a-z_][a-z0-9_]*):[a-z0-9_]+\}", r"{\1}", TEMPLATES[template_id]["text"])


def template_narration(template_id: str, slots: dict, *, fallback_reason: str | None = None,
                       errors=()) -> Narration:
    template = TEMPLATES[template_id]["text"]
    text = render_id(template_id, slots)
    # Fixed words of a reviewed template ("52 weeks", "not zero resistance") are allowed; slot numbers must match.
    check = validate_rendered(text, slots, formats=slot_formats(template_id),
                              allowed_literals=template_literals(template))
    return Narration(text=text, skeleton=template, provider="template", validated=check.ok,
                     fallback_reason=fallback_reason, errors=list(errors))


def narrate_skeleton(skeleton: str | None, template_id: str, slots: dict, *, provider: str, language: str) -> Narration:
    """Validate a model skeleton, render it, validate the result; on any failure, the template."""
    check = validate_skeleton(skeleton, slot_names(template_id))
    if not check.ok:
        return template_narration(template_id, slots, fallback_reason="skeleton_invalid", errors=check.errors)
    formats = slot_formats(template_id)
    text = render(skeleton, slots, formats)
    check = validate_rendered(text, slots, formats=formats)
    if not check.ok:
        return template_narration(template_id, slots, fallback_reason="rendered_invalid", errors=check.errors)
    return Narration(text=text, skeleton=skeleton, provider=provider, validated=True, language=language)
