"""Narrators: the template default, Claude skeletons with every fallback path, replay and the live-call guard.

A fake client stands in for the Anthropic SDK, so no test touches the network or needs a key.
"""

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import anthropic
import httpx2
import numpy as np
import pytest

from aei import config, narrator, templates
from aei.narrator import (
    AnthropicNarrator,
    CachedNarrator,
    Guard,
    TemplateNarrator,
    cache_key,
)
from aei.narrator.anthropic_llm import SYSTEM_PROMPT
from aei.render import render_id

TEMPLATE = "ob_phenotype_marker__ok"  # the ICU MRSA cluster card of 29 Mar 2026
SLOTS = {
    "ward": "ICU",
    "organism_label": "MRSA",
    "n_patients": 13,
    "pattern": "FOX:R VAN:S CLI:R",
    "first_date": "2026-03-03",
    "n_share": 12,
    "expected_low": 0,
    "expected_high": 1,
    "observed_year_before": 0,
    "bg": [3, 34],
    "bg_label": "MRSA",
    "bg_share": 3 / 34,
}
GOOD = (
    "{ward}: unusual pattern, {organism_label} in {n_patients} patients since {first_date}; {n_share} of {n_patients} "
    "share an antibiogram ({pattern}). Typing advised."
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "AEI_NARRATOR", "AEI_MODEL", "AEI_LLM_BACKEND", "AEI_PRICE_TABLE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setattr(config, "PUBLIC", False)


class FakeClient:
    """Mimics `anthropic.Anthropic().messages.create` and records each request."""

    def __init__(self, text=GOOD, stop_reason="end_turn", error=None):
        self.text, self.stop_reason, self.error = text, stop_reason, error
        self.requests = []
        self.messages = self

    def create(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.text)],
        )


def live(client, **guard):
    return AnthropicNarrator(client, guard=Guard(**guard))


def test_template_narrator_is_the_rendered_template():
    n = TemplateNarrator().narrate(TEMPLATE, SLOTS, language="fi")
    assert n.text == render_id(TEMPLATE, SLOTS)
    assert (n.provider, n.validated, n.fallback_reason, n.language) == ("template", True, None, "en")


def test_unknown_audience_or_template_is_a_caller_error():
    with pytest.raises(ValueError):
        TemplateNarrator().narrate(TEMPLATE, SLOTS, audience="patients")
    with pytest.raises(KeyError):
        TemplateNarrator().narrate("no_such_template", SLOTS)


def test_model_skeleton_is_rendered_by_code():
    n = live(FakeClient()).narrate(TEMPLATE, SLOTS, audience="ed")
    assert n.provider == "anthropic" and n.validated and n.fallback_reason is None
    assert n.skeleton == GOOD
    assert n.text.startswith("ICU: unusual pattern, MRSA in 13 patients since 3 Mar; 12 of 13")


def test_request_follows_the_api_rules():
    client = FakeClient()
    nar = live(client)
    nar.narrate(TEMPLATE, SLOTS)
    nar.narrate(TEMPLATE, {**SLOTS, "n_patients": 14}, audience="ward", language="sv")
    first, second = client.requests
    for banned in ("temperature", "top_p", "top_k", "tools", "tool_choice", "thinking"):
        assert banned not in first
    assert first["model"] == "claude-haiku-5-5"
    assert first["system"] == second["system"] == SYSTEM_PROMPT  # stable, so it never varies per request


@pytest.mark.parametrize(
    "client, reason",
    [
        (FakeClient(stop_reason="max_tokens"), "stop_reason:max_tokens"),
        (FakeClient(stop_reason="refusal"), "stop_reason:refusal"),
        (FakeClient(text=GOOD.replace("{n_patients} patients", "13 patients")), "skeleton_invalid"),
        (FakeClient(text=GOOD + " Give {dose}."), "skeleton_invalid"),
        (FakeClient(text=GOOD + " The odds are rising."), "skeleton_invalid"),
        (
            FakeClient(error=anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))),
            "api_error:APIConnectionError",
        ),
    ],
)
def test_every_failure_falls_back_to_the_template(client, reason):
    n = live(client).narrate(TEMPLATE, SLOTS)
    assert (n.provider, n.fallback_reason, n.text) == ("template", reason, render_id(TEMPLATE, SLOTS))
    assert n.validated


def test_validator_errors_are_reported_on_fallback():
    n = live(FakeClient(text=GOOD + " Give {dose}.")).narrate(TEMPLATE, SLOTS)
    assert "unknown_slot:dose" in n.errors


@pytest.mark.parametrize("identifier", ["P001948", "C0000003-1"])
def test_a_patient_or_isolate_id_in_the_slots_never_reaches_the_model(identifier):
    client = FakeClient()
    n = live(client).narrate(TEMPLATE, {**SLOTS, "ward": f"ICU {identifier}"}, audience="ed")
    assert (n.provider, n.fallback_reason) == ("template", "identifier_in_slots") and client.requests == []


def test_ed_heads_up_uses_drug_names_built_from_slots():
    cluster = {
        "ward": "URO",
        "template_id": "ob_phenotype_marker",
        "slots": {
            "ward": "URO",
            "organism_label": "ESBL E. coli",
            "n_patients": 6,
            "n_share": 6,
            "first_date": "2025-05-30",
            "pattern": "AMP:R CXM:R CRO:R MEM:S",
            "expected_low": 0,
            "expected_high": 6,
        },
    }
    template_id, slots = templates.ed_heads_up(cluster)
    n = TemplateNarrator().narrate(template_id, slots, audience="ed")
    assert n.validated and n.text == (
        "Heads-up from infection control: possible ESBL E. coli cluster on Urology (URO). 6 patients since 30 May; 6 "
        "of 6 share the same antibiogram: ampicillin R, cefuroxime R, ceftriaxone R, meropenem S. Under investigation; "
        "typing advised. Dates are sample dates."
    )
    case = {
        "ward": "GER",
        "template_id": "ob_thl_single",
        "slots": {
            "marker_label": "VRE",
            "organism_label": "E. faecalis",
            "specimen": "wound",
            "sample_date": "2026-09-11",
        },
    }
    assert TemplateNarrator().narrate(*templates.ed_heads_up(case), audience="ed").text == (
        "Heads-up from infection control: VRE (E. faecalis) in a wound sample on Geriatrics (GER), sampled 11 Sep. "
        "Alert organism under THL guidance."
    )
    other = {"ward": "ICU", "template_id": "seen_before", "slots": {"pattern": "FOX:R VAN:S CLI:R"}}
    assert templates.ed_heads_up(other) == ("seen_before", {"pattern": "cefoxitin R, vancomycin S, clindamycin R"})


def test_no_key_means_no_client_and_no_call():
    nar = AnthropicNarrator(guard=Guard())
    n = nar.narrate(TEMPLATE, SLOTS)
    assert n.fallback_reason == "no_key" and n.provider == "template" and nar._client is None


def test_spend_cap_stops_live_calls():
    client = FakeClient()
    nar = live(client, cap_usd=0.0001)  # one fake call costs 1000 x 0.10 + 200 x 0.50 per million = $0.0002
    assert nar.narrate(TEMPLATE, SLOTS).fallback_reason is None
    n = nar.narrate(TEMPLATE, SLOTS)
    assert n.fallback_reason == "spend_cap" and len(client.requests) == 1


def test_spend_is_persisted_per_utc_day(tmp_path):
    day1, day2 = 1_790_000_000.0, 1_790_000_000.0 + 86_400
    Guard(clock=lambda: day1).record("claude-haiku-5-5", SimpleNamespace(input_tokens=1_000_000, output_tokens=0))
    assert Guard(clock=lambda: day1).spend_today() == pytest.approx(0.10)  # a new process sees the same total
    assert Guard(clock=lambda: day2).spend_today() == 0.0
    with closing(sqlite3.connect(config.STATE_DB)) as con:
        assert con.execute("SELECT count(*) FROM llm_spend").fetchone()[0] == 1


def test_price_table_is_env_overridable(monkeypatch):
    monkeypatch.setenv("AEI_PRICE_TABLE", json.dumps({"claude-haiku-5-5": [1.0, 2.0]}))
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
    assert Guard().cost("claude-haiku-5-5", usage) == pytest.approx(3.0)
    monkeypatch.setenv("AEI_PRICE_TABLE", "not json")
    with pytest.raises(ValueError, match="AEI_PRICE_TABLE"):
        Guard()


def test_rate_limit_per_ip_per_minute_and_day():
    now = [1_790_000_000.0]
    guard = Guard(per_min=2, per_day=3, clock=lambda: now[0])
    assert [guard.check("10.0.0.1") for _ in range(3)] == [None, None, "rate_limit"]
    assert guard.check("10.0.0.2") is None  # another visitor has their own budget
    now[0] += 61
    assert guard.check("10.0.0.1") is None
    now[0] += 61
    assert guard.check("10.0.0.1") == "rate_limit"  # the daily limit of 3
    assert guard.check(None) is None  # internal calls (precompute) count toward the spend cap only


def test_rate_limited_narration_falls_back():
    client = FakeClient()
    nar = live(client, per_min=1)
    assert nar.narrate(TEMPLATE, SLOTS, client_ip="10.0.0.1").fallback_reason is None
    assert nar.narrate(TEMPLATE, SLOTS, client_ip="10.0.0.1").fallback_reason == "rate_limit"
    assert len(client.requests) == 1


def test_record_then_replay_round_trip(tmp_path):
    client = FakeClient()
    recorded = CachedNarrator(live(client), tmp_path, record=True).narrate(TEMPLATE, SLOTS, audience="ed")
    offline = AnthropicNarrator(FakeClient(error=AssertionError("replay must not call the model")))
    replayed = CachedNarrator(offline, tmp_path).narrate(TEMPLATE, SLOTS, audience="ed")
    assert replayed.text == recorded.text and replayed.provider == "anthropic"
    assert len(client.requests) == 1
    entry = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert entry["skeleton"] == GOOD and "text" not in entry  # only the number-free skeleton is stored


def test_replay_miss_and_tampered_cache_fall_back(tmp_path):
    replay = CachedNarrator(AnthropicNarrator(), tmp_path)
    assert replay.narrate(TEMPLATE, SLOTS, audience="ward").fallback_reason == "cache_miss"
    CachedNarrator(live(FakeClient()), tmp_path, record=True).narrate(TEMPLATE, SLOTS)
    entry_file = next(tmp_path.glob("*.json"))
    entry = json.loads(entry_file.read_text(encoding="utf-8"))
    entry_file.write_text(json.dumps({**entry, "skeleton": "{ward_label}: 99 patients"}), encoding="utf-8")
    n = replay.narrate(TEMPLATE, SLOTS)
    assert n.fallback_reason == "cache_invalid" and "99" not in n.text


def test_cache_key_covers_every_input_and_ignores_numpy_types():
    def key(**change):
        args = {
            "provider": "anthropic",
            "model": "claude-haiku-5-5",
            "prompt_version": "narrator-1",
            "template_id": TEMPLATE,
            "slots": SLOTS,
            "audience": "infection_control",
            "language": "en",
            **change,
        }
        return cache_key(**args)

    base = key()
    for change in (
        {"provider": "other"},
        {"model": "claude-sonnet-5-5"},
        {"prompt_version": "narrator-2"},
        {"template_id": "ob_stepup"},
        {"slots": {**SLOTS, "n_patients": 14}},
        {"audience": "ed"},
        {"language": "fi"},
    ):
        assert key(**change) != base, change
    # precompute passes numpy counts, the API passes JSON ints: both must find the same entry
    assert key(slots={**SLOTS, "n_patients": np.int64(13)}) == base


@pytest.mark.parametrize(
    "env, public, kind, records",
    [
        (None, False, TemplateNarrator, None),
        (None, True, CachedNarrator, False),
        ("template", True, TemplateNarrator, None),
        ("replay", False, CachedNarrator, False),
        ("anthropic", False, CachedNarrator, True),
    ],
)
def test_get_narrator_reads_env(monkeypatch, env, public, kind, records):
    monkeypatch.setattr(config, "PUBLIC", public)
    if env:
        monkeypatch.setenv("AEI_NARRATOR", env)
    nar = narrator.get_narrator()
    assert isinstance(nar, kind)
    if records is not None:
        assert nar.record is records and isinstance(nar.inner, AnthropicNarrator)


def test_get_narrator_rejects_unknown_values(monkeypatch):
    monkeypatch.setenv("AEI_NARRATOR", "gpt")
    with pytest.raises(ValueError, match="AEI_NARRATOR"):
        narrator.get_narrator()


def test_health_never_contains_the_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    health = narrator.health()
    assert health["key_set"] is True and "sk-test" not in json.dumps(health)
