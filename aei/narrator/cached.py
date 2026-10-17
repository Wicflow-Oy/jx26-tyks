"""Record/replay of model skeletons: one JSON file per request under `config.CACHE_DIR / "narration"`.

The key is the sha256 of (provider, model, prompt_version, template_id, slots, audience, language). A cache entry
stores the skeleton only, never the final text. On replay, the skeleton is validated and rendered again with the
current slots and code, so a stale or edited cache file can never put a number on screen. Replay never calls the
network: a miss, or an entry that fails validation, returns the template with fallback_reason "cache_miss" or
"cache_invalid". Record mode returns a cached entry when there is one, and otherwise calls the inner narrator and
stores its result if it is a validated model narration.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from .. import config
from . import guard as _guard
from .base import (
    AUDIENCES,
    Narration,
    check_request,
    narrate_skeleton,
    template_fallback,
)

MODES = ("replay", "record")


def default_cache_dir() -> Path:
    return Path(config.CACHE_DIR) / "narration"


def _canon(o):
    if hasattr(o, "item") and callable(o.item):  # numpy scalars
        return o.item()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def cache_key(provider: str, model: str | None, prompt_version: str, template_id: str, slots: dict,
              audience: str, language: str) -> str:
    raw = json.dumps({"provider": provider, "model": model, "prompt_version": prompt_version,
                      "template_id": template_id, "slots": slots, "audience": audience, "language": language},
                     sort_keys=True, default=_canon, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _key_for(narrator, template_id, slots, audience, language) -> str:
    return cache_key(narrator.name, narrator.model, narrator.prompt_version, template_id, slots, audience, language)


def lookup(narrator, template_id: str, slots: dict, *, audience: str, language: str,
           path: Path | None = None) -> tuple[Narration | None, str]:
    """Replay one request for `narrator` (its name/model/prompt_version form the key).
    Returns (narration, "hit") or (None, "miss" | "invalid")."""
    f = Path(path or default_cache_dir()) / f"{_key_for(narrator, template_id, slots, audience, language)}.json"
    if not f.exists():
        return None, "miss"
    try:
        entry = json.loads(f.read_text(encoding="utf-8"))
        skeleton = entry["skeleton"]
        if not isinstance(skeleton, str) or entry.get("template_id") != template_id:
            return None, "invalid"
    except (OSError, ValueError, KeyError, TypeError):
        return None, "invalid"
    n = narrate_skeleton(skeleton, template_id, slots, language=language, provider=str(entry.get("provider")),
                         model=entry.get("model"), cached=True)
    return (n, "hit") if n.fallback_reason is None else (None, "invalid")


def store(narrator, template_id: str, slots: dict, *, audience: str, language: str, narration: Narration,
          path: Path | None = None) -> Path:
    d = Path(path or default_cache_dir())
    d.mkdir(parents=True, exist_ok=True)
    key = _key_for(narrator, template_id, slots, audience, language)
    entry = {"key": key, "provider": narration.provider, "model": narration.model,
             "prompt_version": narrator.prompt_version, "template_id": template_id, "audience": audience,
             "language": language, "skeleton": narration.skeleton,
             "created": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")}
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(entry, fh, ensure_ascii=False, indent=1)
    target = d / f"{key}.json"
    os.replace(tmp, target)
    return target


class CachedNarrator:
    def __init__(self, inner, path=None, mode: str = "replay"):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.inner = inner
        self.path = Path(path) if path is not None else default_cache_dir()
        self.mode = mode

    name = property(lambda self: self.inner.name)
    model = property(lambda self: self.inner.model)
    prompt_version = property(lambda self: self.inner.prompt_version)
    label = property(lambda self: "replay" if self.mode == "replay" else getattr(self.inner, "label", self.inner.name))

    def key(self, template_id: str, slots: dict, *, audience: str = "infection_control", language: str = "en") -> str:
        return _key_for(self.inner, template_id, slots, audience, language)

    def narrate(self, template_id: str, slots: dict, *, audience: str = "infection_control", language: str = "en",
                client_key: str | None = None) -> Narration:
        check_request(template_id, audience, language)
        hit, status = lookup(self.inner, template_id, slots, audience=audience, language=language, path=self.path)
        if hit is not None:
            return hit
        if self.mode == "replay":
            return template_fallback(template_id, slots, reason="cache_miss" if status == "miss" else "cache_invalid")
        n = self.inner.narrate(template_id, slots, audience=audience, language=language, client_key=client_key)
        if n.fallback_reason is None and n.provider == self.inner.name and n.provider != "template" and not n.cached:
            store(self.inner, template_id, slots, audience=audience, language=language, narration=n, path=self.path)
        return n


def precompute_items(items, narrator, *, audiences=None, languages=None) -> dict:
    """Fill the replay cache, e.g. for every demo-week brief item and heads-up draft.

    `items`: signals or dicts with "template_id" and "slots" (optional "audience", "language"). `audiences` and
    `languages`, when given, are crossed with every item instead. `narrator` should wrap a live narrator; a replay-mode
    CachedNarrator is switched to record mode on the same cache. Per-key rate limits are skipped here, but the daily
    spend cap still applies. Returns counts only, never text."""
    if isinstance(narrator, CachedNarrator):
        nar = narrator if narrator.mode == "record" else CachedNarrator(narrator.inner, narrator.path, mode="record")
    else:
        nar = CachedNarrator(narrator, mode="record")
    counts = Counter()
    reasons = Counter()
    with _guard.batch():
        for item in items:
            auds = audiences or (item.get("audience") or AUDIENCES[0],)
            langs = languages or (item.get("language") or "en",)
            for aud in auds:
                for lang in langs:
                    n = nar.narrate(item["template_id"], item["slots"], audience=aud, language=lang)
                    counts["requests"] += 1
                    if n.fallback_reason is not None:
                        reasons[n.fallback_reason] += 1
                    elif n.cached:
                        counts["already_cached"] += 1
                    else:
                        counts["recorded"] += 1
    return {"requests": counts["requests"], "recorded": counts["recorded"], "already_cached": counts["already_cached"],
            "fallback": dict(reasons)}
