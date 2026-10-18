"""The default narrator: the fixed template text, deterministic and English only."""

from __future__ import annotations

from .base import Narration, check_request, template_narration


class TemplateNarrator:
    name = "template"
    model = None
    prompt_version = "template"

    def narrate(
        self,
        template_id: str,
        slots: dict,
        *,
        audience: str = "infection_control",
        language: str = "en",
        client_ip: str | None = None,
    ) -> Narration:
        """The same English text for every audience and language; `Narration.language` says "en"."""
        check_request(template_id, audience, language)
        return template_narration(template_id, slots)
