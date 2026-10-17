"""The Monday brief (CONTRACTS.md section 5.2): every registered detector for one as-of Sunday, grouped into sections,
with status against the previous week, a unit / home-area map and priority counts.

- Detectors come only from the registry (`aei.detectors`), so the brief works while some are missing.
- Status: `new` if the id was not active at as_of - 7 days, `ongoing` if it was; signals active last week but not now are
  listed once as `resolved`.
- Per-week signals are cached in memory and in `config.CACHE_DIR/signals/{as_of}.json` (other rules/windows get a suffix).
  A cache file is used only when its fingerprint (detector sources, templates, config, data shape) matches.
- The data-quality section always carries a completeness line; the quiet section counts the units with no signal.
"""
import copy
import hashlib
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd

from . import config as C
from . import data
from . import detectors as registry
from . import signal as sig
from .render import render_id

log = logging.getLogger(__name__)

SECTIONS = [("unusual_patterns", "Unusual patterns"), ("changed", "What changed"), ("policy", "Policy lines"),
            ("seen_before", "Seen before"), ("data_quality", "Data quality"), ("quiet", "Quiet")]
PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2, "info": 3}
STATUS_ORDER = {"new": 0, "ongoing": 1, "resolved": 2}
FOOTER = "Every number links to its count and filter. Text narrated from computed numbers only."
CACHE_SCHEMA = "b2-signals-v1"
DEFAULT_RULE, DEFAULT_WINDOW = "readme_period", "4w"
NO_RESOLVED_KINDS = {"expert_rule"}  # weekly lab checks: no hits this week is not a "resolved" item

_MEM: dict = {}
_FP: dict = {}


# ---------------------------------------------------------------- dates and cache plumbing

def _day(as_of) -> str:
    return str(pd.Timestamp(str(as_of)[:10]).date())


def _cache_dir() -> Path:
    return Path(C.CACHE_DIR) / "signals"


def _cache_path(as_of: str, rule: str, window: str) -> Path:
    name = f"{as_of}.json" if (rule, window) == (DEFAULT_RULE, DEFAULT_WINDOW) else f"{as_of}__{rule}__{window}.json"
    return _cache_dir() / name


def fingerprint(ds) -> str:
    """Changes whenever a detector, template, shared module or the dataset shape changes (so stale caches are ignored)."""
    key = (registry.ds_key(ds), tuple(registry.DETECTORS))
    if key in _FP:
        return _FP[key]
    pkg = Path(__file__).resolve().parent
    files = [pkg / "detectors" / f"{n}.py" for n in registry.DETECTORS] + [pkg / "detectors" / "__init__.py"]
    files += [pkg / f for f in ("templates.py", "templates_trends.py", "templates_outbreak.py", "signal.py", "render.py",
                                "config.py", "stats.py", "data.py", "brief.py")]
    h = hashlib.sha256(CACHE_SCHEMA.encode())
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes() if f.exists() else b"<missing>")
    h.update(f"{len(ds.isolates)}|{len(ds.cultures)}|{ds.isolates.sample_date.max()}".encode())
    _FP[key] = h.hexdigest()[:16]
    return _FP[key]


def _read_cache(path: Path, fp: str):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if d.get("fingerprint") != fp or not isinstance(d.get("signals"), list):
        return None
    return d


def _write_cache(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, default=str)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("could not write the signals cache: %s", type(e).__name__)


def clear_memory_cache() -> None:
    _MEM.clear()
    _FP.clear()


def week_signals(ds, as_of, rule: str = DEFAULT_RULE, window: str = DEFAULT_WINDOW, cache: bool = True) -> tuple[list, dict]:
    """Raw detector output for one as-of date: (signals, {"ran", "skipped"}). Memory -> disk -> compute."""
    as_of = _day(as_of)
    fp = fingerprint(ds)
    key = (registry.ds_key(ds), as_of, rule, window, fp)
    if key in _MEM:
        return _MEM[key]
    path = _cache_path(as_of, rule, window)
    d = _read_cache(path, fp) if cache else None
    if d is not None:
        res = (d["signals"], d.get("detectors", {"ran": [], "skipped": []}))
    else:
        signals, report = registry.run(ds, as_of, rule=rule, window=window)
        signals = [registry.plain(s) for s in signals]
        res = (signals, report)
        if cache:
            _write_cache(path, {"fingerprint": fp, "as_of": as_of, "rule": rule, "window": window,
                                "detectors": report, "signals": signals})
    _MEM[key] = res
    return res


# ---------------------------------------------------------------- units touched by a signal

def _as_list(v) -> list:
    if v is None:
        return []
    return [v] if isinstance(v, str) else [w for w in v if isinstance(w, str)]


def units_of(s: dict) -> list[str]:
    """Units a signal touches: its `ward` (str or list), else a ward list in its evidence filter. Lab-wide expert-rule
    checks touch no unit (they are result checks, not unit signals)."""
    if s.get("kind") == "expert_rule":
        return []
    wards = _as_list(s.get("ward"))
    if not wards:
        wards = _as_list(((s.get("evidence") or {}).get("filter") or {}).get("ward"))
    return [w for w in wards if w in C.WARD_LABELS]


def _with_status(signals_now: list, signals_prev: list) -> list:
    prev_ids = {s["id"] for s in signals_prev}
    now_ids = set()
    out = []
    for s in signals_now:
        s = copy.deepcopy(s)
        s["status"] = "ongoing" if s["id"] in prev_ids else "new"
        now_ids.add(s["id"])
        out.append(s)
    for s in signals_prev:
        if s["id"] not in now_ids and s.get("kind") not in NO_RESOLVED_KINDS:
            s = copy.deepcopy(s)
            s["last_active"] = s.get("as_of")
            s["status"] = "resolved"
            out.append(s)
    return out


def _sort_key(s: dict):
    return (STATUS_ORDER.get(s.get("status"), 9) == 2, PRIORITY_ORDER.get(s.get("priority"), 9),
            STATUS_ORDER.get(s.get("status"), 9), str(s.get("ward") or ""), s.get("id", ""))


def _signals_at(ds, as_of, rule, window, cache=True) -> tuple[list, dict]:
    as_of = _day(as_of)
    prev = _day(pd.Timestamp(as_of) - pd.Timedelta(days=7))
    now, report = week_signals(ds, as_of, rule, window, cache)
    before, _ = week_signals(ds, prev, rule, window, cache)
    return _with_status(now, before), report


def signals_for(ds, as_of, ward=None, rule: str = DEFAULT_RULE, window: str = DEFAULT_WINDOW) -> list[dict]:
    """Active (new or ongoing) signals at `as_of` touching a unit (str or list of codes); all active signals if None."""
    sigs, _ = _signals_at(ds, as_of, rule, window)
    active = [s for s in sigs if s["status"] != "resolved"]
    if ward is None:
        return sorted(active, key=_sort_key)
    wanted = set(_as_list(ward))
    return sorted([s for s in active if wanted & set(units_of(s))], key=_sort_key)


# ---------------------------------------------------------------- map, quiet line, counts

def _unit_state(sigs: list) -> str:
    if any(s.get("section") in ("unusual_patterns", "seen_before") or s.get("priority") == "P1" for s in sigs):
        return "signal"
    if any(s.get("kind") == "completeness" for s in sigs):
        return "no_data"
    if sigs:
        return "changed"
    return "quiet"


def _build_map(ds, active: list) -> dict:
    units = []
    for w, label in C.WARD_LABELS.items():
        ss = [s for s in active if w in units_of(s)]
        units.append({"ward": w, "label": label, "state": _unit_state(ss), "signal_ids": [s["id"] for s in ss]})
    areas = []
    for a in sorted(ds.isolates.home_area.dropna().unique()):
        ss = [s for s in active if s.get("home_area") == a]
        areas.append({"area": str(a), "state": _unit_state(ss), "signal_ids": [s["id"] for s in ss]})
    return {"units": units, "home_areas": areas}


def _structural_item(kind: str, key: dict, as_of: str, template_id: str, slots: dict, evidence: dict, section: str):
    """Brief lines that are not detector signals (the quiet line). Same shape as a signal, priority info."""
    return {"id": sig.signal_id(kind, key), "kind": kind,
            "priority": "info", "status": "ongoing", "section": section, "as_of": as_of, "ward": None, "home_area": None,
            "specimen": None, "organism": None, "drug": None, "first_sample_date": None, "template_id": template_id,
            "slots": slots, "text": render_id(template_id, slots), "advice": None, "evidence": evidence, "key": key}


def _quiet_item(as_of: str, units: list) -> dict:
    quiet = [u["ward"] for u in units if u["state"] == "quiet"]
    n_units = len(units)
    evidence = {"filter": {"ward": quiet, "specimen": None, "organism": None, "drug": None,
                           "date_from": as_of, "date_to": as_of, "rule": None},
                "counts": {"quiet_units": len(quiet), "units": n_units},
                "method": "units with no active signal this week (map state quiet)", "params": {}}
    if quiet:
        slots = {"quiet": [len(quiet), n_units], "units_text": ", ".join(quiet)}
        return _structural_item("quiet", {"week": as_of}, as_of, "trend_quiet", slots, evidence, "quiet")
    return _structural_item("quiet", {"week": as_of}, as_of, "trend_quiet_none", {"n_units": n_units}, evidence, "quiet")


def _counts(active: list) -> dict:
    out = {p: 0 for p in PRIORITY_ORDER}
    for s in active:
        if s.get("priority") in out:
            out[s["priority"]] += 1
    return out


# ---------------------------------------------------------------- the brief

def build_brief(ds, as_of, window: str = DEFAULT_WINDOW, rule: str = DEFAULT_RULE, cache: bool = True) -> dict:
    """The Monday brief for data up to `as_of` (a Sunday); dated as_of + 1 day. Strictly as-of."""
    if rule not in ("readme_period", "30d"):
        raise ValueError(f"unknown counting rule {rule}")
    if window not in C.WINDOWS:
        raise ValueError(f"unknown window {window}")
    as_of = _day(as_of)
    sigs, report = _signals_at(ds, as_of, rule, window, cache)
    active = [s for s in sigs if s["status"] != "resolved"]
    counts = _counts(active)
    mp = _build_map(ds, active)
    by_section = {k: [] for k, _ in SECTIONS}
    for s in sorted(sigs, key=_sort_key):
        sec = s.get("section")
        if sec not in by_section or sec == "quiet":
            sec = registry.KIND_SECTION.get(s.get("kind"), "unusual_patterns")
        by_section[sec].append(s)
    gaps = [s for s in by_section["data_quality"] if s["kind"] == "completeness"]
    if not any(s["status"] != "resolved" for s in gaps):
        from .detectors import completeness
        line = completeness.status_line(ds, as_of)
        line["status"] = "new" if gaps else "ongoing"  # "new" right after a gap resolves
        by_section["data_quality"].insert(0, line)
    by_section["quiet"] = [_quiet_item(as_of, mp["units"])]
    return {
        "as_of": as_of, "monday": _day(pd.Timestamp(as_of) + pd.Timedelta(days=1)), "app_name": C.APP_NAME,
        "synthetic": True, "window": window, "rule": rule,
        "header": {"title": "Monday brief", "data_to": as_of, "refreshed": "nightly",
                   "result_lag_days": C.RESULT_LAG_DAYS,
                   "dates_note": "Dates are sample dates; results usually arrive a couple of days later."},
        "sections": [{"key": k, "title": t, "items": by_section.get(k, [])} for k, t in SECTIONS],
        "map": mp, "counts": counts, "detectors": report, "footer": FOOTER,
    }


# ---------------------------------------------------------------- precompute

def _weeks_arg(weeks) -> list[str]:
    if weeks in (None, "all"):
        first, last = data.week_end(54), pd.Timestamp(C.DATA_END)
        return [_day(d) for d in pd.date_range(first, last, freq="7D")]
    if weeks == "demo":
        out = []
        for m in C.DEMO_MONDAYS:
            a = pd.Timestamp(m) - pd.Timedelta(days=1)
            out += [_day(a - pd.Timedelta(days=7)), _day(a)]
        return sorted(set(out))
    out = []
    for w in weeks:
        out.append(_day(data.week_end(int(w))) if isinstance(w, int) else _day(w))
    return out


def precompute(ds, weeks="all", rule: str = DEFAULT_RULE, window: str = DEFAULT_WINDOW) -> list[dict]:
    """Compute and cache per-week signals. `weeks`: "all" (the replay range plus the week before it), "demo", or an
    iterable of as-of dates / week numbers. Returns [{as_of, monday, n_signals, n_p1, seconds}] in date order."""
    out = []
    for a in _weeks_arg(weeks):
        t = time.perf_counter()
        sigs, _ = week_signals(ds, a, rule, window, cache=True)
        out.append({"as_of": a, "monday": _day(pd.Timestamp(a) + pd.Timedelta(days=1)), "n_signals": len(sigs),
                    "n_p1": sum(1 for s in sigs if s.get("priority") == "P1"),
                    "seconds": round(time.perf_counter() - t, 3)})
    return out
