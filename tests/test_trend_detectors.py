"""Trend detectors (policy, resistance_change, outlier, expert_rules, completeness) and the registry.
Offline and deterministic; uses the session `ds` fixture. Goldens from CONTRACTS.md section 5.2."""

import re
import sys
import time
import types

import pandas as pd
import pytest

from aei import config as C
from aei import data, render, stats, templates, templates_outbreak, templates_ui, validator
from aei import detectors as registry
from aei.detectors import completeness, expert_rules, outlier, policy, resistance_change
from aei.templates_trends import MAX_OUTLIER_PAIRS
from aei.templates_trends import TEMPLATES as TREND_TEMPLATES

MINE = [policy, resistance_change, outlier, expert_rules, completeness]
DEMO_AS_OF = [str((pd.Timestamp(m) - pd.Timedelta(days=1)).date()) for m in C.DEMO_MONDAYS]
DIGITS = re.compile(r"\d+")
FILTER_KEYS = {"ward", "specimen", "organism", "drug", "date_from", "date_to", "rule"}
BANNED = [
    "predict",
    "forecast",
    "odds",
    "probability",
    "best choice",
    "recommended drug",
    "ai predicts",
    "likely to",
    "will rise",
    "s/i/r",
    "decoy",
    "outbreak confirmed",
]


# ---------------------------------------------------------------- helpers shared with test_brief.py


def rendered_slot_digits(s: dict, field: str = "text") -> set[str]:
    t = templates.TEMPLATES[s["template_id"]]
    vals = []
    for name, kind in render.slots_in(t[field]):
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


def check_title(s: dict) -> None:
    """The row title is its template's title rendered from the signal's slots; digits only from slots; wording rules."""
    t = templates.TEMPLATES[s["template_id"]]
    assert s["title"] == render.render(t["title"], s["slots"], t.get("formats"))
    allowed = rendered_slot_digits(s, "title")
    assert all(d in allowed for d in DIGITS.findall(s["title"])), s["title"]
    assert not any(w in s["title"].lower() for w in BANNED + ["zero resistance"]), s["title"]


def check_title_template(tid: str) -> None:
    """A title template has no literal digit and passes the narrator's skeleton check (prediction, restricted and
    number words, comparisons), with its own slots allowed."""
    t = templates.TEMPLATES[tid]
    skeleton = re.sub(r"\{([a-z_][a-z0-9_]*):[a-z0-9_]+\}", r"{\1}", t["title"])
    names = {name for name, _ in render.slots_in(t["title"])}
    assert not re.search(r"\d", render.SLOT.sub("", t["title"])), tid
    res = validator.validate_skeleton(skeleton, names)
    assert res.ok, (tid, res.errors)


def truncated(ds, as_of) -> data.Dataset:
    end = pd.Timestamp(as_of)
    return data.Dataset(
        isolates=ds.isolates[ds.isolates.sample_date <= end].copy(),
        cultures=ds.cultures[ds.cultures.sample_date <= end].copy(),
        patients=ds.patients,
    )


def comparable(sigs: list) -> list:
    return sorted((s["id"], s["text"], repr(s["slots"])) for s in sigs)


# ---------------------------------------------------------------- policy line (trimethoprim)


def tmp_women_primary_care(ds, end) -> tuple[int, int]:
    """The policy line by hand: tested urinary E. coli from women in primary care, first per patient in the
    52 weeks ending `end`; returns (resistant, tested)."""
    x = ds.isolates
    pop = x[
        (x.organism == "Escherichia coli")
        & (x.specimen == "urine")
        & x.ward_code.isin(["PHC-N", "PHC-S"])
        & (x.sex == "F")
        & x.TMP.notna()
    ]
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
    assert "local_guide_alternative" not in st  # a line never names another drug
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


def test_policy_resolved_item_shows_last_flagged_and_now(ds):
    """The week after the line is crossed back, the item says what was flagged and what the rate is now."""
    (s,) = policy.detect(ds, "2026-07-05")
    assert s["status"] == "resolved" and s["advice"] is None
    assert s["text"] == (
        "Trimethoprim: urinary E. coli in women in primary care. Resolved. Last flagged week ending 28 Jun 2026: 20.1% "
        "resistant (158 of 787); now 19.7% (156 of 790, last 52 weeks), below the local 20% line."
    )
    assert (s["evidence"]["counts"]["resistant"], s["evidence"]["counts"]["tested"]) == (156, 790)
    assert policy.detect(ds, "2026-07-12")[0]["status"] == "new"  # back above the line: a new run
    assert policy.detect(ds, "2026-08-02") == []  # resolved items are listed for one week only


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
    assert "alternative" not in s["slots"] and "pivmecillinam" not in s["text"].lower()
    assert "20.4%" in s["text"] and "160 of 786" in s["text"] and "20%" in s["text"]
    assert s["evidence"]["filter"]["ward"] == ["PHC-N", "PHC-S"] and s["evidence"]["filter"]["sex"] == "F"
    assert policy.detect(ds, "2026-09-27") == []


# ---------------------------------------------------------------- expert rules


def test_expert_rule_goldens(ds):
    c = expert_rules.rule_counts(ds.isolates)
    assert c["esbl_ceph_s"] == {"checked": 517, "hits": 0}
    assert c["mrsa_fox_s"] == {"checked": 111, "hits": 0}
    # Re-pinned from 109 (two overlapping rules, E. coli and K. pneumoniae only): one merged check over every species
    # with EUCAST cefuroxime breakpoints. The 109 earlier hits are all inside it.
    _, cro = expert_rules.masks(ds.isolates, "cro_r_amp_or_cxm_s")
    assert c["cro_r_amp_or_cxm_s"]["hits"] == int(cro.sum()) == 139
    assert ds.isolates[cro].organism.value_counts().to_dict() == {
        "Escherichia coli": 64,
        "Klebsiella pneumoniae": 45,
        "Proteus mirabilis": 19,
        "Klebsiella oxytoca": 11,
    }
    assert c["tzp_r_amp_s"]["hits"] == 276  # EUCAST Expert Rules v3.3 rule 1
    assert set(c) == {r["id"] for r in C.EXPERT_RULES}


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
        assert s["evidence"]["method"].startswith(C.EXPERT_RULES_LABEL)
    assert len({s["evidence"]["params"]["rule_id"] for s in sigs}) == len(sigs)  # one item per rule


# ---------------------------------------------------------------- completeness


def test_completeness_phcs_gap(ds):
    (s,) = completeness.detect(ds, "2025-12-14")
    assert s["ward"] == "PHC-S" and s["priority"] == "P2" and s["section"] == "data_quality"
    assert s["slots"]["expected"] == 51 and s["evidence"]["counts"]["cultures_this_week"] == 0
    assert s["evidence"]["filter"]["date_from"] == "2025-12-08" and s["evidence"]["filter"]["date_to"] == "2025-12-14"
    # Re-pinned: a data gap says nothing about resistance, so the text no longer mentions it
    assert s["text"] == "Health centre South: no cultures this week (usually 51 a week). Data gap, cause unknown."


def test_completeness_only_gap_in_replay(ds):
    weeks = pd.date_range(data.week_end(55), C.DATA_END, freq="7D")
    listed = [(str(w.date()), s["ward"], s["status"]) for w in weeks for s in completeness.detect(ds, w)]
    assert listed == [("2025-12-14", "PHC-S", "new"), ("2025-12-21", "PHC-S", "resolved")]


def test_completeness_resolved_item_shows_this_weeks_cultures(ds):
    """The week after the gap PHC-S sent 48 cultures; the item says so instead of repeating 'no cultures'."""
    (s,) = completeness.detect(ds, "2025-12-21")
    assert s["text"] == (
        "Health centre South: data gap. Resolved. Last flagged week ending 14 Dec 2025: 0 cultures (usually 51 a "
        "week), cause unknown; now 48 cultures this week."
    )
    week = ds.cultures[(ds.cultures.sample_date > "2025-12-14") & (ds.cultures.sample_date <= "2025-12-21")]
    assert (week.ward_code == "PHC-S").sum() == 48


def test_completeness_ok_line(ds):
    s = completeness.status_line(ds, "2026-06-21")
    assert s["text"] == "All 9 units sent data this week." and s["priority"] == "info"


# ---------------------------------------------------------------- resistance change and ward outlier


def test_resistance_change_demo_cells(ds):
    icu = [s for s in resistance_change.detect(ds, "2026-03-08") if s["ward"] == "ICU"]
    assert [(s["organism"], s["drug"]) for s in icu] == [("Staphylococcus aureus", "FOX")]
    assert icu[0]["slots"]["counts"] == [3, 8] and icu[0]["priority"] == "P2" and icu[0]["section"] == "changed"
    # A positive cefoxitin screen is MRSA, and 3 of 8 is too few for a percentage
    assert icu[0]["text"] == (
        "Intensive care unit · MRSA (cefoxitin screen positive): 3 of 8 S. aureus in the last 4 weeks vs 1 of 70 (1%) "
        "in the 52 weeks before. Changed; watch next week."
    )
    rows = ds.isolates[ds.isolates.isolate_id.isin(icu[0]["evidence"]["isolate_ids"])]
    assert len(rows) == 8 and (rows.FOX == "R").sum() == 3 and set(rows.ward_code) == {"ICU"}
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


@pytest.mark.parametrize("as_of", ["2026-03-15", "2026-03-29", "2025-06-22"])
def test_resistance_change_shows_no_percentage_below_ten(ds, as_of):
    """Below 10 isolates no percentage, 10 to 29 tagged "small n" (config.SMALL_N_NONE / SMALL_N_LOW)."""
    for s in resistance_change.detect(ds, as_of):
        if s["status"] == "resolved":
            continue
        n, n_prior = s["slots"]["counts"][1], s["slots"]["counts_prior"][1]
        assert s["template_id"] == f"trend_resistance_change__{stats.n_state(n)}__{stats.n_state(n_prior)}"
        now = s["text"].split(" in the last ")[0]
        assert ("%" in now) == (n >= C.SMALL_N_NONE) and ("small n" in now) == (C.SMALL_N_NONE <= n < C.SMALL_N_LOW)


def test_resistance_change_resolved_item(ds):
    """A cell flagged last week and not this week says so, with last week's and this week's counts."""
    (s,) = [s for s in resistance_change.detect(ds, "2026-03-08") if s["status"] == "resolved"]
    assert s["text"] == (
        "Health centre South · Ceftriaxone resistant. Resolved. Last flagged week ending 1 Mar 2026: 3 of 9 K. "
        "pneumoniae; now 2 of 10 in the last 4 weeks."
    )
    assert len(s["evidence"]["isolate_ids"]) == 10


def test_outlier_needs_enough_isolates_per_cell(ds):
    """The ICU MRSA weeks no longer fire, because their third 'high' cell was P. mirabilis ciprofloxacin
    1 of 2 (8 and 15 Mar) or E. coli mecillinam 1 of 1 (29 Mar). Two cells of one clone (cefoxitin and clindamycin
    on the same S. aureus isolates) are not three results above range."""
    for as_of in ["2026-03-08", "2026-03-15", "2026-03-29"]:
        t = outlier.ward_cells(ds, as_of)
        icu = t[(t.ward == "ICU") & (t.p_mid < outlier.MIDP_ALPHA)]
        assert len(icu) == outlier.MIN_HIGH_CELLS and set(icu[icu.high].drug) == {"FOX", "CLI"}
        assert not any(s["ward"] == "ICU" for s in outlier.detect(ds, as_of))
    uro_weeks = [
        a
        for a in ["2025-06-08", "2025-06-15", "2025-06-22", "2025-06-29"]
        if any(s["ward"] == "URO" for s in outlier.detect(ds, a))
    ]
    assert uro_weeks and uro_weeks[0] == "2025-06-15"


def test_outlier_names_each_cell_and_lists_its_isolates(ds):
    """Every high cell is named with its count, and the case file lists only those cells' isolates."""
    (s,) = outlier.detect(ds, "2025-06-15")
    assert s["ward"] == "URO" and s["priority"] == "P3" and s["section"] == "changed"
    assert s["text"] == (
        "Urology: resistance above the usual range in 4 of 7 organism–drug pairs in the last 4 weeks. Resistant of "
        "tested: E. coli ceftriaxone 11 of 35; E. coli ciprofloxacin 12 of 35; E. coli cefuroxime 12 of 35; E. coli "
        "trimethoprim 13 of 35. Other units: 2 of 75 pairs. Unusual pattern across several results."
    )
    cells = s["evidence"]["counts"]["cells"]
    assert all(c["tested"] >= outlier.MIN_TESTED or c["resistant"] >= outlier.MIN_RESISTANT for c in cells)
    rows = ds.isolates[ds.isolates.isolate_id.isin(s["evidence"]["isolate_ids"])]
    assert len(rows) == 35 and set(rows.ward_code) == {"URO"} and set(rows.organism) == {"Escherichia coli"}


def test_outlier_templates_cover_every_pair():
    assert len(resistance_change.PAIRS) <= MAX_OUTLIER_PAIRS


def test_cefoxitin_reads_as_mrsa(ds):
    """A positive cefoxitin screen is MRSA, in the change item, its title and an outlier's cell name."""
    assert resistance_change.finding("Staphylococcus aureus", "FOX") == "MRSA (cefoxitin screen positive)"
    assert resistance_change.subject("Staphylococcus aureus", "FOX") == "MRSA among S. aureus"
    assert resistance_change.subject("Escherichia coli", "TMP") == "E. coli resistant to trimethoprim"
    cell = types.SimpleNamespace(organism="Staphylococcus aureus", drug="FOX")
    assert outlier._pair(cell) == "MRSA (cefoxitin screen positive)"
    (s,) = [s for s in resistance_change.detect(ds, "2026-03-08") if s["ward"] == "ICU"]
    assert (
        render.render(templates.TEMPLATES[s["template_id"]]["title"], s["slots"])
        == "ICU: more MRSA among S. aureus than usual"
    )


# ---------------------------------------------------------------- shared properties of every B2 detector


@pytest.mark.parametrize("as_of", DEMO_AS_OF + ["2025-12-14", "2025-12-21", "2026-06-28", "2026-07-05"])
def test_text_numbers_come_from_slots(ds, as_of):
    for m in MINE:
        for s in m.detect(ds, as_of):
            check_text(s)
            assert s["as_of"] == as_of
            for k in ("filter", "counts", "method"):
                assert k in s["evidence"]
            assert FILTER_KEYS <= set(s["evidence"]["filter"]), s["kind"]  # re-runnable filter (CONTRACTS section 3)
            check_title(registry.with_title(s))
    check_text(completeness.status_line(ds, as_of))


def test_templates_have_no_literal_digits_and_worded_titles():
    for tid in TREND_TEMPLATES:
        literal = render.SLOT.sub("", templates.TEMPLATES[tid]["text"])
        assert not re.search(r"\d", literal), tid
        check_title_template(tid)


def test_template_modules_never_share_an_id():
    """Each area keeps its own prefix, so merging the modules into templates.TEMPLATES never overwrites an id."""
    parts = [templates_outbreak.TEMPLATES, TREND_TEMPLATES, templates_ui.TEMPLATES]
    ids = [tid for part in parts for tid in part]
    assert len(set(ids)) == len(ids) and len(templates.TEMPLATES) == len(ids) + len({"ed_cluster", "ed_case"})
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
    assert registry.DETECTORS == [
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
    assert registry.WINDOWED <= set(registry.DETECTORS)


def test_a_failing_detector_raises(ds, monkeypatch):
    """No quiet-looking brief with a detector missing: the error reaches the API and the UI's error state."""
    broken = types.ModuleType("aei.detectors.zz_broken")

    def detect(ds, as_of, rule="readme_period"):
        raise RuntimeError("boom")

    broken.detect = detect
    monkeypatch.setitem(sys.modules, "aei.detectors.zz_broken", broken)
    with pytest.raises(RuntimeError, match="boom"):
        registry.run(ds, "2026-06-21", names=["policy", "zz_broken"])


def test_registry_passes_the_window_to_windowed_detectors(ds, monkeypatch):
    seen = {}
    mod = types.ModuleType("aei.detectors.zz_window")

    def detect(ds, as_of, rule="readme_period", window="4w"):
        seen.update(rule=rule, window=window)
        return []

    mod.detect = detect
    monkeypatch.setitem(sys.modules, "aei.detectors.zz_window", mod)
    monkeypatch.setattr(registry, "WINDOWED", {"zz_window"})
    registry.run(ds, "2026-06-21", rule="30d", window="4m", names=["zz_window"])
    assert seen == {"rule": "30d", "window": "4m"}
