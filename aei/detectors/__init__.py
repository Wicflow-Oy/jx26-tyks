"""Detector registry. The brief imports detectors only through here, so it works before every workstream lands.

`DETECTORS` lists module names inside `aei.detectors`. Each module exposes
`detect(ds, as_of, rule="readme_period") -> list[signal]` (strictly as-of). Modules are imported lazily; a missing
module, an import error or an exception inside `detect` is logged once as a warning and that detector is skipped.

Optional keyword arguments are passed only when a detector's signature accepts them:
  window  -- the brief window key ("4w"), for detectors with a window length;
  signals -- the signals produced so far this run (so `seen_before` can look at active clusters).
"""
import importlib
import inspect
import logging

import pandas as pd

from .. import config as C

log = logging.getLogger(__name__)

# Order matters: seen_before runs after the cluster detectors so it can read their signals.
DETECTORS = ["phenotype", "thl", "stepup", "seen_before",
             "resistance_change", "outlier", "policy", "expert_rules", "completeness"]

KIND_SECTION = {"phenotype_cluster": "unusual_patterns", "thl_rule": "unusual_patterns", "count_stepup": "unusual_patterns",
                "ward_outlier": "changed", "resistance_change": "changed", "policy_line": "policy",
                "seen_before": "seen_before", "expert_rule": "data_quality", "completeness": "data_quality"}

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


def run(ds, as_of, rule: str = "readme_period", window: str = "4w", names=None) -> tuple[list[dict], dict]:
    """Run every registered detector for one as-of date. Returns (signals, report{"ran", "skipped"})."""
    signals, ran, skipped, seen = [], [], [], set()
    for name in (DETECTORS if names is None else names):
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
            signals.append(s)
    return signals, {"ran": ran, "skipped": skipped}


# ---- small shared helpers for the trend detectors (labels, dates, JSON-safe values) ----

_DS_REFS: dict = {}


def ds_key(ds) -> tuple[int, int]:
    """Cache key for a dataset. Holds a reference to its tables so an id is never reused while cache entries exist."""
    k = (id(ds.isolates), id(ds.cultures))
    _DS_REFS.setdefault(k, (ds.isolates, ds.cultures))
    return k


def ts(as_of) -> pd.Timestamp:
    return pd.Timestamp(str(as_of)[:10])


def day(as_of) -> str:
    return str(ts(as_of).date())


def ward_label(code: str) -> str:
    return C.WARD_LABELS.get(code, code)


def drug_label(code: str) -> str:
    return C.DRUG_NAMES.get(code, code)


def organism_label(org: str) -> str:
    """'Escherichia coli' -> 'E. coli' (genus initial + species)."""
    parts = str(org).split()
    return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) >= 2 else str(org)


def window_days(window: str) -> int:
    return int(C.WINDOWS.get(window, C.WINDOWS["4w"]))


def plain(v):
    """Convert numpy/pandas scalars to plain Python so signals serialise to JSON."""
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, pd.Timestamp):
        return str(v.date())
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            return v.item()
        except (ValueError, AttributeError):
            return v
    return v
