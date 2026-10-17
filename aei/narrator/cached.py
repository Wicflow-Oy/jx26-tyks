"""Record/replay of model skeletons (CONTRACTS.md section 6): one JSON file per request in config.CACHE_DIR/narration.

The key is the sha256 of (provider, model, prompt_version, template_id, slots, audience, language). An entry stores
the skeleton only, never final text: on replay the skeleton is validated and rendered again with the current slots, so
a stale or edited cache file can never put a number on screen. Replay never calls the network; a miss returns the
template. Record mode calls the inner narrator on a miss and stores the result if it is a validated model narration.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import config
from .base import (
    Narration,
    Narrator,
    check_request,
    narrate_skeleton,
    template_narration,
)


def _plain(value):
    """JSON fallback, so numpy and pandas values hash like the plain values the API receives."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def cache_key(provider: str, model: str | None, prompt_version: str, template_id: str, slots: dict, audience: str,
              language: str) -> str:
    raw = json.dumps([provider, model, prompt_version, template_id, slots, audience, language], sort_keys=True,
                     default=_plain, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CachedNarrator:
    """Wraps a model narrator. `record=False` (replay) never calls it; `record=True` calls it on a cache miss."""

    def __init__(self, inner: Narrator, path: Path | None = None, *, record: bool = False):
        self.inner = inner
        self.path = Path(path) if path is not None else Path(config.CACHE_DIR) / "narration"
        self.record = record
        self.name, self.model, self.prompt_version = inner.name, inner.model, inner.prompt_version

    def _file(self, template_id: str, slots: dict, audience: str, language: str) -> Path:
        key = cache_key(self.name, self.model, self.prompt_version, template_id, slots, audience, language)
        return self.path / f"{key}.json"

    def narrate(self, template_id: str, slots: dict, *, audience: str = "infection_control", language: str = "en",
                client_ip: str | None = None) -> Narration:
        check_request(template_id, audience, language)
        file = self._file(template_id, slots, audience, language)
        if file.exists():
            try:
                skeleton = json.loads(file.read_text(encoding="utf-8")).get("skeleton")
            except (OSError, ValueError, AttributeError):
                skeleton = None  # an unreadable entry is handled like one that fails validation
            narration = narrate_skeleton(skeleton, template_id, slots, provider=self.name, language=language)
            if narration.fallback_reason:  # unreadable, or no longer passes the current validator
                narration.fallback_reason = "cache_invalid"
            return narration
        if not self.record:
            return template_narration(template_id, slots, fallback_reason="cache_miss")
        narration = self.inner.narrate(template_id, slots, audience=audience, language=language, client_ip=client_ip)
        if narration.provider == self.name and narration.fallback_reason is None:
            self._store(file, template_id, audience, language, narration.skeleton)
        return narration

    def _store(self, file: Path, template_id: str, audience: str, language: str, skeleton: str) -> None:
        entry = {"provider": self.name, "model": self.model, "prompt_version": self.prompt_version,
                 "template_id": template_id, "audience": audience, "language": language, "skeleton": skeleton}
        self.path.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(file)  # atomic, so a concurrent reader never sees half a file
