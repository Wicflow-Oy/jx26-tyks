"""The default narrator: deterministic text from the fixed templates (render_id). English only."""
from __future__ import annotations

from .base import Narration, check_request, template_fallback


class TemplateNarrator:
    name = "template"
    label = "template"
    model = None
    prompt_version = "template"

    def narrate(self, template_id: str, slots: dict, *, audience: str = "infection_control", language: str = "en",
                client_key: str | None = None) -> Narration:
        """The same fixed text for every audience. For fi/sv it returns English with
        fallback_reason="no_model_for_language"."""
        check_request(template_id, audience, language)
        return template_fallback(template_id, slots, reason=None, language=language)
