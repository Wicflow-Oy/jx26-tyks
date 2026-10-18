"""Detector registry. The brief imports detectors only through here, so one missing detector never breaks it.

`DETECTORS` lists module names inside `aei.detectors`. Each module exposes
`detect(ds, as_of, rule="readme_period") -> list[signal]` (strictly as-of). Modules are imported lazily; a missing
module, an import error or an exception inside `detect` is logged once as a warning and that detector is skipped.
Every signal that passes through `run` gets a `title`: a short row title rendered from its template's `title` and its
slots, so the UI never parses `text` for one.

Optional keyword arguments are passed only when a detector's signature accepts them:
  window  -- the brief window key ("4w"), for detectors with a window length;
  signals -- the signals produced so far this run (so `seen_before` can look at active clusters).
"""

import importlib
import inspect
import logging

import pandas as pd

from .. import config as C
from ..render import render
from ..templates import TEMPLATES

log = logging.getLogger(__name__)

# Order matters: seen_before runs after the cluster detectors so it can read their signals.
DETECTORS = [
    "phenotype",
    "thl",
    "stepup",
    "seen_before",
    "resistance_change",
    "outlier",
    "policy",
    "expert_rules",
    "completeness",
]

KIND_SECTION = {
    "phenotype_cluster": "unusual_patterns",
    "thl_rule": "unusual_patterns",
    "count_stepup": "unusual_patterns",
    "ward_outlier": "changed",
    "resistance_change": "changed",
    "policy_line": "policy",
    "seen_before": "seen_before",
    "expert_rule": "data_quality",
    "completeness": "data_quality",
}

_MODULES: dict = {}
_WARNED: set = set()


def _warn_once(name: str, reason: str) -> None:
    if (name, reason) not in _WARNED:
        _WARNED.add((name, reason))
        log.warning("detector %s skipped: %s", name, reason)


def load(name: str):
    """Import `aei.detectors.<name>` lazily; None (with a logged warning) when missing or broken."""
    if name in _MODULES:
        return _MODULES[name]
    try:
        mod = importlib.import_module(f"{__name__}.{name}")
    except Exception as e:  # noqa: BLE001 -- any failure means "skip this detector", never "break the brief"
        _warn_once(name, f"{type(e).__name__}: {e}")
        return None
    if not callable(getattr(mod, "detect", None)):
        _warn_once(name, "module has no detect()")
        return None
    _MODULES[name] = mod
    return mod


def available() -> list[str]:
    return [n for n in DETECTORS if load(n) is not None]


def _valid(sig) -> bool:
    return isinstance(sig, dict) and all(k in sig for k in ("id", "kind", "priority", "text", "slots", "evidence"))


def with_title(s: dict) -> dict:
    """Set s["title"] from the template's title and the signal's slots (numbers only via slots, like the text)."""
    t = TEMPLATES[s["template_id"]]
    s["title"] = render(t["title"], s["slots"], t.get("formats"))
    return s


def run(ds, as_of, rule: str = "readme_period", window: str = "4w", names=None) -> tuple[list[dict], dict]:
    """Run every registered detector for one as-of date. Returns (signals, report{"ran", "skipped"})."""
    signals, ran, skipped, seen = [], [], [], set()
    for name in DETECTORS if names is None else names:
        mod = load(name)
        if mod is None:
            skipped.append({"name": name, "reason": "not available"})
            continue
        params = inspect.signature(mod.detect).parameters
        kw = {}
        if "window" in params:
            kw["window"] = window
        if "signals" in params:
            kw["signals"] = list(signals)
        try:
            out = mod.detect(ds, as_of, rule=rule, **kw) or []
        except Exception as e:  # noqa: BLE001
            _warn_once(name, f"detect failed: {type(e).__name__}: {e}")
            skipped.append({"name": name, "reason": f"failed: {type(e).__name__}"})
            continue
        ran.append(name)
        for s in out:
            if not _valid(s):
                _warn_once(name, "returned a malformed signal (dropped)")
                continue
            if s["id"] in seen:
                continue
            seen.add(s["id"])
            if not s.get("section"):
                s["section"] = KIND_SECTION.get(s["kind"], "unusual_patterns")
            signals.append(with_title(s))
    return signals, {"ran": ran, "skipped": skipped}


# ---- small shared helpers for the detectors (dates, labels) ----

_DS_REFS: dict = {}


def ds_key(ds) -> tuple[int, int]:
    """Cache key for a dataset. Holds a reference to its tables so an id is never reused while cache entries exist."""
    k = (id(ds.isolates), id(ds.cultures))
    _DS_REFS.setdefault(k, (ds.isolates, ds.cultures))
    return k


def ts(as_of) -> pd.Timestamp:
    return pd.Timestamp(str(as_of)[:10])


def iso(as_of) -> str:
    """'2026-03-29' for a date, a timestamp or a date string."""
    return str(ts(as_of).date())


def ward_label(code: str) -> str:
    return C.WARD_LABELS.get(code, code)


def drug_label(code: str) -> str:
    return C.DRUG_NAMES.get(code, code)


def window_days(window: str) -> int:
    return int(C.WINDOWS.get(window, C.WINDOWS["4w"]))
