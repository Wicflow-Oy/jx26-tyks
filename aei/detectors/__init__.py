"""Detector registry: the brief runs every detector in `DETECTORS`, in order, through `run`.

Each module exposes `detect(ds, as_of, rule="readme_period") -> list[signal]` (strictly as-of); the detectors with a
window length (`WINDOWED`) also take the brief's window key. A detector that fails raises: the brief shows an error,
never a quiet week that is missing a detector. Every signal that passes through `run` gets a `title`: a short row
title rendered from its template's `title` and its slots, so the UI never parses `text` for one.
"""

import importlib

import pandas as pd

from .. import config as C
from ..render import render
from ..templates import TEMPLATES

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
WINDOWED = {"resistance_change", "outlier"}

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


def with_title(s: dict) -> dict:
    """Set s["title"] from the template's title and the signal's slots (numbers only via slots, like the text)."""
    t = TEMPLATES[s["template_id"]]
    s["title"] = render(t["title"], s["slots"], t.get("formats"))
    return s


def run(ds, as_of, rule: str = "readme_period", window: str = "4w", names=None) -> tuple[list[dict], dict]:
    """Run every registered detector (or `names`) for one as-of date. Returns (signals, {"ran": names})."""
    names = DETECTORS if names is None else names
    signals, seen = [], set()
    for name in names:
        detect = importlib.import_module(f"{__name__}.{name}").detect
        for s in detect(ds, as_of, rule=rule, **({"window": window} if name in WINDOWED else {})):
            if s["id"] in seen:
                continue
            seen.add(s["id"])
            s["section"] = s.get("section") or KIND_SECTION[s["kind"]]
            signals.append(with_title(s))
    return signals, {"ran": list(names)}


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
