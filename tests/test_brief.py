"""Workstream B2: the Monday brief (CONTRACTS.md section 5.2). Offline and deterministic; caches go to a temp dir.
Parts that depend on workstream B1's detectors (phenotype / thl / seen_before) skip until those modules load."""
import json
import re
import time

import pandas as pd
import pytest

from aei import brief, data, render, templates
from aei import config as C
from aei import detectors as registry
from aei import signal as sig
from aei.detectors import policy, resistance_change

DIGITS = re.compile(r"\d+")
BANNED = ["predict", "forecast", "odds", "probability", "best choice", "recommended drug", "ai predicts", "likely to",
          "will rise", "s/i/r", "decoy", "outbreak confirmed"]
B2_DETECTORS = ["resistance_change", "outlier", "policy", "expert_rules", "completeness"]
SECTION_KEYS = ["unusual_patterns", "changed", "policy", "seen_before", "data_quality", "quiet"]


def as_of_for(monday: str) -> str:
    return str((pd.Timestamp(monday) - pd.Timedelta(days=1)).date())


def items(b: dict, section: str | None = None) -> list:
    return [it for s in b["sections"] if section in (None, s["key"]) for it in s["items"]]


def structural(it: dict) -> bool:
    return it["kind"] == "quiet" or it.get("template_id") == "completeness_ok"


def check_text(s: dict) -> None:
    t = templates.TEMPLATES[s["template_id"]]
    assert render.render_id(s["template_id"], s["slots"]) == s["text"]
    vals = [render.fmt(s["slots"][n], k or t.get("formats", {}).get(n, "text")) for n, k in render.slots_in(t["text"])]
    allowed = set(DIGITS.findall(" ".join(vals)))
    for d in DIGITS.findall(s["text"]):
        assert d in allowed, (d, s["text"])
    low = s["text"].lower() + " " + str(s.get("advice") or "").lower()
    for w in BANNED:
        assert w not in low, (w, s["text"])
    assert "zero resistance" not in low.replace("not zero resistance", "")


def clear_all():
    brief.clear_memory_cache()
    resistance_change._CACHE.clear()
    policy._RATES.clear()
    policy._POP.clear()


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CACHE_DIR", tmp_path)
    brief.clear_memory_cache()
    yield tmp_path
    brief.clear_memory_cache()


@pytest.fixture(scope="module")
def briefs(ds, tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "CACHE_DIR", tmp_path_factory.mktemp("cache"))
        brief.clear_memory_cache()
        out = {m: brief.build_brief(ds, as_of_for(m)) for m in C.DEMO_MONDAYS}
    brief.clear_memory_cache()
    return out


def need(*names):
    missing = [n for n in names if registry.load(n) is None]
    if missing:
        pytest.skip(f"workstream B1 detector(s) not available yet: {missing}")


# ---------------------------------------------------------------- shape, map, counts, quiet

def test_brief_shape(briefs):
    for monday, b in briefs.items():
        assert b["as_of"] == as_of_for(monday) and b["monday"] == monday
        assert b["app_name"] == C.APP_NAME and b["synthetic"] is True and b["window"] == "4w" and b["rule"] == "readme_period"
        assert b["header"]["title"] == "Monday brief" and b["header"]["data_to"] == b["as_of"]
        assert b["header"]["refreshed"] == "nightly"
        assert [s["key"] for s in b["sections"]] == SECTION_KEYS
        assert all(s["title"] for s in b["sections"])
        assert b["footer"] == brief.FOOTER
        assert set(B2_DETECTORS) <= set(b["detectors"]["ran"])
        json.dumps(b)  # serialisable for the API


def test_map_units_and_home_areas(ds, briefs):
    areas = sorted(ds.isolates.home_area.dropna().unique())
    assert len(areas) == 5
    for b in briefs.values():
        units = b["map"]["units"]
        assert [u["ward"] for u in units] == list(C.WARD_LABELS) and len(units) == 9
        assert all(u["label"] == C.WARD_LABELS[u["ward"]] for u in units)
        assert [a["area"] for a in b["map"]["home_areas"]] == areas
        ids = {it["id"] for it in items(b) if it["status"] != "resolved"}
        for u in units + b["map"]["home_areas"]:
            assert u["state"] in {"signal", "changed", "quiet", "no_data"}
            assert set(u["signal_ids"]) <= ids
            assert (u["state"] == "quiet") == (not u["signal_ids"])


def test_counts_match_active_items(briefs):
    for b in briefs.values():
        want = {"P1": 0, "P2": 0, "P3": 0, "info": 0}
        for it in items(b):
            if it["status"] != "resolved" and not structural(it):
                want[it["priority"]] += 1
        assert b["counts"] == want


def test_quiet_line_counts_quiet_units(briefs):
    for b in briefs.values():
        (q,) = items(b, "quiet")
        n_quiet = sum(u["state"] == "quiet" for u in b["map"]["units"])
        if n_quiet:
            assert q["slots"]["quiet"] == [n_quiet, 9]
            assert f"{n_quiet} of 9 units" in q["text"]
        else:
            assert q["template_id"] == "trend_quiet_none"


def test_quiet_is_eight_of_nine_when_only_icu_has_items(ds, tmp_cache, monkeypatch):
    fake = sig.make_signal("resistance_change", {"ward": "ICU", "organism": "x", "drug": "FOX"}, priority="P2",
                           as_of="2026-03-08", template_id="trend_resistance_change",
                           slots={"ward_label": "Intensive care unit", "organism_label": "S. aureus",
                                  "drug_label": "Cefoxitin", "counts": [3, 8], "rate": 0.375, "window_weeks": 4,
                                  "rate_prior": 0.01, "counts_prior": [1, 70], "prior_weeks": 52},
                           evidence={"filter": {}, "counts": {}, "method": "test"}, ward="ICU", section="changed")

    def fake_week(ds_, as_of, rule="readme_period", window="4w", cache=True):
        return ([fake] if as_of == "2026-03-08" else []), {"ran": ["fake"], "skipped": []}

    monkeypatch.setattr(brief, "week_signals", fake_week)
    b = brief.build_brief(ds, "2026-03-08")
    (q,) = items(b, "quiet")
    assert q["slots"]["quiet"] == [8, 9] and q["text"].startswith("No signals on 8 of 9 units")
    assert "ICU" not in q["slots"]["units_text"]
    icu = next(u for u in b["map"]["units"] if u["ward"] == "ICU")
    assert icu["state"] == "changed" and icu["signal_ids"] == [fake["id"]]
    assert b["counts"] == {"P1": 0, "P2": 1, "P3": 0, "info": 0}
    assert items(b, "changed")[0]["status"] == "new"
    dq = items(b, "data_quality")
    assert dq and dq[0]["text"] == "All 9 units sent data this week."


def test_data_quality_always_has_a_completeness_line(briefs):
    for b in briefs.values():
        dq = items(b, "data_quality")
        assert any(it["kind"] == "completeness" and it["status"] != "resolved" for it in dq)


def test_every_item_text_is_slot_rendered_and_worded(briefs):
    for b in briefs.values():
        for it in items(b):
            check_text(it)
            assert it["section"] in SECTION_KEYS


# ---------------------------------------------------------------- the five demo Mondays (B2 parts)

def test_demo_uro_week_b2(briefs):
    b = briefs["2025-06-09"]
    ch = items(b, "changed")
    assert any(it["kind"] == "resistance_change" and it["ward"] == "URO" and it["drug"] == "CRO" for it in ch)
    assert next(u for u in b["map"]["units"] if u["ward"] == "URO")["state"] != "quiet"


def test_demo_phcs_data_gap(briefs):
    b = briefs["2025-12-15"]
    dq = items(b, "data_quality")
    gap = [it for it in dq if it["kind"] == "completeness"]
    assert len(gap) == 1 and gap[0]["ward"] == "PHC-S" and gap[0]["status"] == "new"
    assert gap[0]["text"] == "Health centre South: no results this week (usually 51). Data gap, cause unknown; not zero resistance."
    assert not any(it.get("template_id") == "completeness_ok" for it in dq)
    assert next(u for u in b["map"]["units"] if u["ward"] == "PHC-S")["state"] == "no_data"


def test_demo_icu_week_b2(briefs):
    b = briefs["2026-03-09"]
    ch = [it for it in items(b, "changed") if it["ward"] == "ICU" and it["status"] != "resolved"]
    assert {it["kind"] for it in ch} == {"resistance_change", "ward_outlier"}
    assert next(u for u in b["map"]["units"] if u["ward"] == "ICU")["state"] != "quiet"


def test_demo_trimethoprim_crossing(briefs):
    b = briefs["2026-06-22"]
    (p,) = items(b, "policy")
    assert p["kind"] == "policy_line" and p["status"] == "new" and p["priority"] == "P2"
    assert "20.4%" in p["text"] and "160 of 786" in p["text"] and "21 Jun 2026" in p["text"]
    assert p["advice"] == "Review the empirical UTI guidance" and p["slots"]["alternative"] == "pivmecillinam (local guide)"
    for w in ("PHC-N", "PHC-S"):
        u = next(u for u in b["map"]["units"] if u["ward"] == w)
        assert p["id"] in u["signal_ids"] and u["state"] in {"changed", "signal"}


def test_demo_september_week_b2(briefs):
    b = briefs["2026-09-14"]
    assert items(b, "quiet") and items(b, "data_quality")
    assert not items(b, "policy")


# ---------------------------------------------------------------- demo Mondays: the B1 parts (skip until B1 lands)

def _unusual(b, ward):
    return [it for it in items(b, "unusual_patterns") if it["ward"] == ward and it["status"] != "resolved"]


def test_demo_uro_esbl_cluster_b1(briefs):
    need("phenotype")
    assert _unusual(briefs["2025-06-09"], "URO")


def test_demo_icu_mrsa_three_patients_b1(briefs):
    need("phenotype")
    icu = _unusual(briefs["2026-03-09"], "ICU")
    assert any(it["slots"].get("n_patients") == 3 for it in icu)


def test_demo_seen_before_and_ger_vre_b1(briefs):
    need("seen_before", "thl")
    b = briefs["2026-09-14"]
    assert any(it["ward"] == "ICU" or "ICU" in it["text"] for it in items(b, "seen_before"))
    assert any("VRE" in it["text"] for it in _unusual(b, "GER"))


# ---------------------------------------------------------------- status, signals_for, rule, strict as-of

def test_status_new_ongoing_resolved(ds, tmp_cache):
    pid = policy.policy_states(ds, "2026-06-21")[0]["signal_id"]

    def status(as_of):
        b = brief.build_brief(ds, as_of)
        return [it["status"] for it in items(b, "policy") if it["id"] == pid]

    assert status("2026-06-14") == []
    assert status("2026-06-21") == ["new"]
    assert status("2026-06-28") == ["ongoing"]
    assert status("2026-07-05") == ["resolved"]
    assert status("2026-07-12") == ["new"]
    assert status("2026-08-02") == []


def test_signals_for(ds, tmp_cache):
    icu = brief.signals_for(ds, "2026-03-08", ward="ICU")
    assert icu and all("ICU" in brief.units_of(s) for s in icu)
    assert all(s["status"] in {"new", "ongoing"} for s in icu)
    phc = brief.signals_for(ds, "2026-06-21", ward="PHC-N")
    assert any(s["kind"] == "policy_line" for s in phc)
    both = brief.signals_for(ds, "2026-06-21", ward=["PHC-N", "GER"])
    assert {s["id"] for s in phc} <= {s["id"] for s in both}
    everything = brief.signals_for(ds, "2026-06-21")
    assert {s["id"] for s in both} <= {s["id"] for s in everything}
    assert not any(s["kind"] == "expert_rule" for s in phc)  # lab-wide checks are not unit banners


def test_rule_and_window_params(ds, tmp_cache):
    b = brief.build_brief(ds, "2026-03-08", rule="30d")
    assert b["rule"] == "30d" and (tmp_cache / "signals" / "2026-03-08__30d__4w.json").exists()
    with pytest.raises(ValueError):
        brief.build_brief(ds, "2026-03-08", rule="first_ever")
    with pytest.raises(ValueError):
        brief.build_brief(ds, "2026-03-08", window="9w")


def test_brief_is_strictly_as_of(ds, tmp_cache):
    as_of = "2026-03-08"
    end = pd.Timestamp(as_of)
    cut = data.Dataset(isolates=ds.isolates[ds.isolates.sample_date <= end].copy(),
                       cultures=ds.cultures[ds.cultures.sample_date <= end].copy(), patients=ds.patients)
    full = brief.build_brief(ds, as_of, cache=False)
    trunc = brief.build_brief(cut, as_of, cache=False)
    assert [(it["id"], it["status"], it["text"]) for it in items(full)] == \
           [(it["id"], it["status"], it["text"]) for it in items(trunc)]
    assert full["map"] == trunc["map"] and full["counts"] == trunc["counts"]


# ---------------------------------------------------------------- cache and precompute

def test_precompute_writes_and_brief_reads_cache(ds, tmp_cache, monkeypatch):
    rows = brief.precompute(ds, ["2026-06-14", "2026-06-21"])
    assert [r["as_of"] for r in rows] == ["2026-06-14", "2026-06-21"]
    assert rows[1]["monday"] == "2026-06-22" and rows[1]["n_signals"] >= 1
    path = tmp_cache / "signals" / "2026-06-21.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["fingerprint"] == brief.fingerprint(ds) and payload["as_of"] == "2026-06-21"
    brief.clear_memory_cache()

    def boom(*a, **k):
        raise AssertionError("detectors should not run when the cache is warm")

    monkeypatch.setattr(registry, "run", boom)
    b = brief.build_brief(ds, "2026-06-21")
    assert items(b, "policy")[0]["status"] == "new"


def test_stale_cache_is_ignored(ds, tmp_cache):
    path = tmp_cache / "signals" / "2026-06-21.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"fingerprint": "stale", "signals": [{"id": "x"}]}), encoding="utf-8")
    sigs, _ = brief.week_signals(ds, "2026-06-21")
    assert all(s["id"] != "x" for s in sigs) and any(s["kind"] == "policy_line" for s in sigs)
    assert json.loads(path.read_text(encoding="utf-8"))["fingerprint"] == brief.fingerprint(ds)


def test_precompute_weeks_arguments():
    demo = brief._weeks_arg("demo")
    assert "2026-06-21" in demo and "2026-06-14" in demo and len(demo) == 10
    allw = brief._weeks_arg("all")
    assert allw[0] == str(data.week_end(54).date()) and allw[-1] == C.DATA_END
    assert brief._weeks_arg([126]) == ["2026-03-08"]


# ---------------------------------------------------------------- performance

def test_brief_cold_b2_detectors_under_three_seconds(ds, tmp_cache, monkeypatch):
    monkeypatch.setattr(registry, "DETECTORS", list(B2_DETECTORS))
    clear_all()
    t = time.perf_counter()
    brief.build_brief(ds, "2026-03-08")
    assert time.perf_counter() - t <= 3.0


def test_brief_from_precomputed_cache_under_three_seconds(ds, tmp_cache):
    brief.precompute(ds, ["2026-06-14", "2026-06-21"])
    clear_all()
    t = time.perf_counter()
    brief.build_brief(ds, "2026-06-21")
    assert time.perf_counter() - t <= 3.0
