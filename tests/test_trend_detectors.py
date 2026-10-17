"""Workstream B2: trend detectors (policy, resistance_change, outlier, expert_rules, completeness) and the registry.
Offline and deterministic; uses the session `ds` fixture. Goldens from CONTRACTS.md section 5.2 and analysis 35/39/40/44/51/52."""
import ast
import logging
import re
import sys
import time
import types
from pathlib import Path

import pandas as pd
import pytest

from aei import config as C
from aei import data, render, templates
from aei import detectors as registry
from aei.detectors import completeness, expert_rules, outlier, policy, resistance_change
from aei.templates_trends import TEMPLATES as TREND_TEMPLATES

MINE = [policy, resistance_change, outlier, expert_rules, completeness]
DEMO_AS_OF = [str((pd.Timestamp(m) - pd.Timedelta(days=1)).date()) for m in C.DEMO_MONDAYS]
DIGITS = re.compile(r"\d+")
FILTER_KEYS = {"ward", "specimen", "organism", "drug", "date_from", "date_to", "rule"}
BANNED = ["predict", "forecast", "odds", "probability", "best choice", "recommended drug", "ai predicts", "likely to",
          "will rise", "s/i/r", "decoy", "outbreak confirmed"]


# ---------------------------------------------------------------- helpers shared with test_brief.py

def rendered_slot_digits(s: dict) -> set[str]:
    t = templates.TEMPLATES[s["template_id"]]
    vals = []
    for name, kind in render.slots_in(t["text"]):
        kind = kind or t.get("formats", {}).get(name, "text")
        vals.append(render.fmt(s["slots"][name], kind))
    return set(DIGITS.findall(" ".join(vals)))


def check_text(s: dict) -> None:
    """Every digit run in the text is a rendered slot value; the text is exactly the template rendering; wording rules."""
    assert render.render_id(s["template_id"], s["slots"]) == s["text"]
    allowed = rendered_slot_digits(s)
    for d in DIGITS.findall(s["text"]):
        assert d in allowed, (d, s["text"])
    low = s["text"].lower() + " " + str(s.get("advice") or "").lower()
    for w in BANNED:
        assert w not in low, (w, s["text"])
    assert "zero resistance" not in low.replace("not zero resistance", "")


def truncated(ds, as_of) -> data.Dataset:
    end = pd.Timestamp(as_of)
    return data.Dataset(isolates=ds.isolates[ds.isolates.sample_date <= end].copy(),
                        cultures=ds.cultures[ds.cultures.sample_date <= end].copy(), patients=ds.patients)


def comparable(sigs: list) -> list:
    return sorted((s["id"], s["text"], repr(s["slots"])) for s in sigs)


# ---------------------------------------------------------------- policy line (trimethoprim)

def tmp_women_primary_care(ds, end) -> tuple[int, int]:
    """51_codex_fixes_check by hand: tested urinary E. coli from women in primary care, first per patient in the
    52 weeks ending `end`; returns (resistant, tested)."""
    x = ds.isolates
    pop = x[(x.organism == "Escherichia coli") & (x.specimen == "urine") & x.ward_code.isin(["PHC-N", "PHC-S"])
            & (x.sex == "F") & x.TMP.notna()]
    w = data.window(pop, end, 364).sort_values(["sample_date", "isolate_id"]).drop_duplicates("patient_id")
    return int((w.TMP == "R").sum()), len(w)


def test_policy_peak_golden(ds):
    (st,) = policy.policy_states(ds, "2026-06-21")
    assert (st["x"], st["n"]) == (160, 786) == tmp_women_primary_care(ds, "2026-06-21")
    assert render.fmt(st["rate"], "pct1") == "20.4%"
    assert st["active"] and st["crossed_on"] == "2026-06-21" and st["threshold"] == 0.20
    assert st["counting_rule"] == "readme_period" and st["window_days"] == 364
    lo, hi = st["interval"]
    assert lo < st["rate"] < hi
    assert st["local_guide_alternative"] == C.POLICY_LINES[0]["local_guide_alternative"]
    assert st["local_guide_alternative"]["text"] == "pivmecillinam (local guide)"
    # prior-year rate: the same rolling window ending 52 weeks earlier
    assert st["prior_as_of"] == "2025-06-22"
    assert (st["x_prior"], st["n_prior"]) == (122, 769) == tmp_women_primary_care(ds, "2025-06-22")
    assert render.fmt(st["rate_prior"], "pct1") == "15.9%"
    assert st["signal_id"] == policy.detect(ds, "2026-06-21")[0]["id"]


def test_policy_weeks_at_or_above_line_and_peak(ds):
    """51's scan range: every week end from 29 Sep 2024 to the end of the data."""
    states = {str(e.date()): policy.policy_states(ds, e)[0] for e in pd.date_range("2024-09-29", C.DATA_END, freq="7D")}
    assert [d for d, st in states.items() if st["active"]] == ["2026-06-21", "2026-06-28", "2026-07-12", "2026-07-19"]
    peak = max(states, key=lambda d: states[d]["rate"])
    assert peak == "2026-06-21" and (states[peak]["x"], states[peak]["n"]) == (160, 786)


def test_policy_latest_and_crossed_on_runs(ds):
    (last,) = policy.policy_states(ds, "2026-09-27")
    assert (last["x"], last["n"]) == (144, 789) and render.fmt(last["rate"], "pct1") == "18.3%"
    assert not last["active"] and last["crossed_on"] is None
    assert policy.policy_states(ds, "2026-06-28")[0]["crossed_on"] == "2026-06-21"
    assert policy.policy_states(ds, "2026-07-05")[0]["active"] is False
    assert policy.policy_states(ds, "2026-07-19")[0]["crossed_on"] == "2026-07-12"  # a new run after the 5 Jul dip


def test_policy_30d_rule_is_below_the_line(ds):
    (st,) = policy.policy_states(ds, "2026-06-21", rule="30d")
    assert render.fmt(st["rate"], "pct1") == "19.9%" and not st["active"]


def test_policy_states_fast(ds):
    policy._POP.clear()
    policy._RATES.clear()
    t = time.perf_counter()
    policy.policy_states(ds, "2026-07-19")
    assert time.perf_counter() - t <= 0.3


def test_policy_signal(ds):
    (s,) = policy.detect(ds, "2026-06-21")
    assert s["kind"] == "policy_line" and s["section"] == "policy" and s["priority"] == "P2"
    assert s["advice"] == "Review the empirical UTI guidance" == C.POLICY_LINES[0]["message"]
    assert s["slots"]["alternative"] == "pivmecillinam (local guide)"
    assert "20.4%" in s["text"] and "160 of 786" in s["text"] and "20%" in s["text"]
    assert s["evidence"]["filter"]["ward"] == ["PHC-N", "PHC-S"] and s["evidence"]["filter"]["sex"] == "F"
    assert policy.detect(ds, "2026-09-27") == []


# ---------------------------------------------------------------- expert rules

def test_expert_rule_goldens(ds):
    c = expert_rules.rule_counts(ds.isolates)
    assert c["esbl_ceph_s"] == {"checked": 517, "hits": 0}
    assert c["mrsa_fox_s"] == {"checked": 111, "hits": 0}
    _, h3 = expert_rules.masks(ds.isolates, "cro_r_amp_s")
    _, h4 = expert_rules.masks(ds.isolates, "cro_r_cxm_s")
    assert int((h3 | h4).sum()) == 109
    odd = ds.isolates[h3 | h4].organism.value_counts().to_dict()
    assert odd == {"Escherichia coli": 64, "Klebsiella pneumoniae": 45}  # 40_esbl_flag's split of the 109


def test_expert_rules_week(ds):
    sigs = expert_rules.detect(ds, "2026-06-21")
    assert sigs and all(s["section"] == "data_quality" and s["advice"] == "Lab check" for s in sigs)
    end = pd.Timestamp("2026-06-21")
    for s in sigs:
        ids = s["evidence"]["isolate_ids"]
        rows = ds.isolates[ds.isolates.isolate_id.astype(str).isin(ids)]
        assert len(rows) == s["slots"]["n_results"] == len(ids)
        assert rows.sample_date.max() <= end and rows.sample_date.min() > end - pd.Timedelta(days=7)
        assert s["ward"] is None  # lab-wide check, units listed in the text


# ---------------------------------------------------------------- completeness

def test_completeness_phcs_gap(ds):
    (s,) = completeness.detect(ds, "2025-12-14")
    assert s["ward"] == "PHC-S" and s["priority"] == "P2" and s["section"] == "data_quality"
    assert s["slots"]["expected"] == 51 and s["evidence"]["counts"]["cultures_this_week"] == 0
    assert s["evidence"]["filter"]["date_from"] == "2025-12-08" and s["evidence"]["filter"]["date_to"] == "2025-12-14"
    assert "Data gap, cause unknown; not zero resistance" in s["text"]


def test_completeness_only_gap_in_replay(ds):
    weeks = pd.date_range(data.week_end(55), C.DATA_END, freq="7D")
    flagged = [(str(w.date()), s["ward"]) for w in weeks for s in completeness.detect(ds, w)]
    assert flagged == [("2025-12-14", "PHC-S")]


def test_completeness_ok_line(ds):
    s = completeness.status_line(ds, "2026-06-21")
    assert s["text"] == "All 9 units sent data this week." and s["priority"] == "info"


# ---------------------------------------------------------------- resistance change and ward outlier

def test_resistance_change_demo_cells(ds):
    icu = [s for s in resistance_change.detect(ds, "2026-03-08") if s["ward"] == "ICU"]
    assert [(s["organism"], s["drug"]) for s in icu] == [("Staphylococcus aureus", "FOX")]
    assert icu[0]["slots"]["counts"] == [3, 8] and icu[0]["priority"] == "P2" and icu[0]["section"] == "changed"
    uro = {(s["ward"], s["drug"]) for s in resistance_change.detect(ds, "2025-06-08")}
    assert ("URO", "CRO") in uro


def test_resistance_change_cell_counts(ds):
    """Window and prior counts recomputed by hand for one cell (README rule, tested isolates)."""
    t = resistance_change.cell_table(ds, "2026-03-08")
    r = t[(t.ward == "ICU") & (t.organism == "Staphylococcus aureus") & (t.drug == "FOX")].iloc[0]
    g = ds.isolates[(ds.isolates.organism == "Staphylococcus aureus") & ds.isolates.FOX.notna()]
    w = data.first_isolates(data.window(g, "2026-03-08", 28), "readme_period")
    w = w[w.ward_code == "ICU"]
    assert (r.x_w, r.n_w) == (int((w.FOX == "R").sum()), len(w))
    p = data.first_isolates(data.window(g, "2026-02-08", 364), "readme_period")
    p = p[p.ward_code == "ICU"]
    assert (r.x_p, r.n_p) == (int((p.FOX == "R").sum()), len(p))
    assert r.changed and r.p < C.CHANGE_ALPHA


def test_outlier_fires_on_the_two_clusters(ds):
    icu = outlier.detect(ds, "2026-03-08")
    assert [s["ward"] for s in icu] == ["ICU"] and icu[0]["priority"] == "P3" and icu[0]["section"] == "changed"
    assert icu[0]["slots"]["high"][0] >= outlier.MIN_HIGH_CELLS
    assert "S. aureus cefoxitin" in icu[0]["text"]
    uro_weeks = [a for a in ["2025-06-08", "2025-06-15", "2025-06-22", "2025-06-29"]
                 if any(s["ward"] == "URO" for s in outlier.detect(ds, a))]
    assert uro_weeks and uro_weeks[0] == "2025-06-15"


# ---------------------------------------------------------------- shared properties of every B2 detector

@pytest.mark.parametrize("as_of", DEMO_AS_OF + ["2025-12-14", "2026-06-28"])
def test_text_numbers_come_from_slots(ds, as_of):
    for m in MINE:
        for s in m.detect(ds, as_of):
            check_text(s)
            assert s["as_of"] == as_of
            for k in ("filter", "counts", "method"):
                assert k in s["evidence"]
            assert FILTER_KEYS <= set(s["evidence"]["filter"]), s["kind"]  # re-runnable filter (CONTRACTS section 3)
    check_text(completeness.status_line(ds, as_of))


def test_templates_have_no_literal_digits():
    used = set(TREND_TEMPLATES) | {"completeness_gap", "completeness_ok"}
    for tid in used:
        literal = render._SLOT.sub("", templates.TEMPLATES[tid]["text"])
        assert not re.search(r"\d", literal), tid


def test_trend_templates_never_redefine_base_ids():
    src = (Path(templates.__file__)).read_text(encoding="utf-8")
    base = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TEMPLATES" for t in node.targets):
            base = {k.value for k in node.value.keys}
    assert base and "policy_line" in base
    assert not base & set(TREND_TEMPLATES)
    assert all(tid.startswith("trend_") for tid in TREND_TEMPLATES)
    for tid, t in TREND_TEMPLATES.items():
        assert templates.TEMPLATES[tid] is t


@pytest.mark.parametrize("as_of", ["2025-06-08", "2026-03-08", "2026-06-21"])
def test_detectors_are_strictly_as_of(ds, as_of):
    cut = truncated(ds, as_of)
    for m in MINE:
        assert comparable(m.detect(ds, as_of)) == comparable(m.detect(cut, as_of)), m.__name__
    assert policy.policy_states(ds, as_of) == policy.policy_states(cut, as_of)


def test_detectors_speed(ds):
    t = time.perf_counter()
    for m in MINE:
        m.detect(ds, "2026-01-18")
    assert time.perf_counter() - t < 1.0


# ---------------------------------------------------------------- registry

def test_registry_lists_all_detectors():
    assert registry.DETECTORS == ["phenotype", "thl", "stepup", "seen_before",
                                  "resistance_change", "outlier", "policy", "expert_rules", "completeness"]
    for name in ["resistance_change", "outlier", "policy", "expert_rules", "completeness"]:
        assert registry.load(name) is not None


def test_registry_skips_missing_and_failing(ds, monkeypatch, caplog):
    broken = types.ModuleType("aei.detectors.zz_broken")

    def detect(ds, as_of, rule="readme_period"):
        raise RuntimeError("boom")

    broken.detect = detect
    monkeypatch.setitem(sys.modules, "aei.detectors.zz_broken", broken)
    with caplog.at_level(logging.WARNING, logger="aei.detectors"):
        sigs, rep = registry.run(ds, "2026-06-21", names=["zz_missing", "zz_broken", "policy"])
    assert rep["ran"] == ["policy"] and len(sigs) == 1
    assert {s["name"] for s in rep["skipped"]} == {"zz_missing", "zz_broken"}
    assert any("zz_missing" in r.getMessage() for r in caplog.records)
    assert any("zz_broken" in r.getMessage() for r in caplog.records)


def test_registry_passes_optional_kwargs(ds, monkeypatch):
    seen = {}
    mod = types.ModuleType("aei.detectors.zz_kwargs")

    def detect(ds, as_of, rule="readme_period", window="4w", signals=None):
        seen.update(rule=rule, window=window, n=len(signals))
        return []

    mod.detect = detect
    monkeypatch.setitem(sys.modules, "aei.detectors.zz_kwargs", mod)
    registry.run(ds, "2026-06-21", rule="30d", window="4m", names=["policy", "zz_kwargs"])
    assert seen == {"rule": "30d", "window": "4m", "n": 1}
