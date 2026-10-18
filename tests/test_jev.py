"""The optional Jev second opinion stays inert without a key and a passing calibration, and never reaches cds.py."""

import ast
import json
from pathlib import Path

import pytest

from aei import config, jev

SIGNAL = {
    "kind": "phenotype_cluster",
    "organism": "Staphylococcus aureus",
    "ward": "ICU",
    "priority": "P1",
    "slots": {"n_patients": 13, "n_share": 12, "first_date": "2026-03-03"},
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("JEV_BASE_URL", raising=False)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)


class FakeJev:
    def __init__(self, p=0.8):
        self.p, self.bodies = p, []

    def noul(self, body):
        self.bodies.append(body)
        return self.p


def write_calibration(**report):
    jev.calibration_file().write_text(
        json.dumps({"model": jev.JEV_MODEL, "brier": 0.1, "ece": 0.03, "n": 1350, **report}), encoding="utf-8"
    )


def test_inert_without_key_even_when_calibrated():
    write_calibration(passed=True)
    client = FakeJev()
    assert jev.JevAdapter(client).assess(SIGNAL) is None
    assert client.bodies == [] and jev.status() == "not_configured"


@pytest.mark.parametrize("calibration", [None, {"passed": False}, {"passed": True, "model": "jev-latest"}])
def test_inert_with_key_but_no_passing_calibration(monkeypatch, calibration):
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    if calibration is not None:
        write_calibration(**calibration)
    assert jev.JevAdapter(FakeJev()).assess(SIGNAL) is None
    assert jev.status() == "not_configured"


def test_configured_answer_shape_and_replay(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    write_calibration(passed=True)
    client = FakeJev(p=0.8)
    out = jev.JevAdapter(client).assess(SIGNAL)
    assert out == {
        "provider": "jev",
        "mode": "noul",
        "question": "Forward to the ED?",
        "answer": "yes",
        "score": 0.8,
        "label": "Second opinion (Jev, experimental). Not used in prescribing alerts.",
        "calibration": {"brier": 0.1, "ece": 0.03, "n": 1350, "passed": True},
    }
    state = client.bodies[0]["state"]
    assert "first_date" not in json.dumps(state) and state["patients"] == 13  # no dates reach Jev
    assert jev.JevAdapter(FakeJev(p=0.1)).assess(SIGNAL)["score"] == 0.8  # replayed from .cache/jev, not asked again
    assert jev.status() == "configured"


def test_only_clusters_are_assessed(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    write_calibration(passed=True)
    assert jev.JevAdapter(FakeJev()).assess({**SIGNAL, "kind": "policy_line"}) is None


def test_http_client_refuses_plain_http():
    with pytest.raises(ValueError, match="https"):
        jev.JevHttpClient("test-key", "http://api.typesafe.ai")


class ScoreProvider:
    """A second-opinion provider whose score is a function of the simulated truth."""

    model = jev.JEV_MODEL

    def __init__(self, score):
        self.score = score

    def assess(self, signal):
        return {"score": self.score(signal["truth"])}


def clusters(n_pos=700, n_neg=700):
    return [{"signal": {"truth": y}, "label": y} for y in [1] * n_pos + [0] * n_neg]


def test_calibration_passes_a_calibrated_provider_and_writes_the_report():
    report = jev.calibrate(ScoreProvider(lambda truth: 0.97 if truth else 0.03), clusters())
    assert report["n"] == 1400 and report["passed"]
    assert report["brier"] == pytest.approx(0.0009) and report["ece"] == pytest.approx(0.03)
    assert json.loads(jev.calibration_file().read_text())["passed"] is True


def test_calibration_fails_a_miscalibrated_provider():
    report = jev.calibrate(ScoreProvider(lambda truth: 0.6 if truth else 0.4), clusters())  # ranks well, placed badly
    assert not report["passed"] and report["ece"] == pytest.approx(0.4)


def test_calibration_needs_both_classes():
    report = jev.calibrate(ScoreProvider(lambda truth: 1.0), clusters(n_neg=0))
    assert report["brier"] == 0 and not report["passed"]  # "always yes" on positives only must not pass


def test_ece_matches_a_hand_count():
    # bin 0.1-0.2: scores 0.1, 0.1 with outcomes 0, 1 -> |0.5 - 0.1| x 2/4; bin 0.9-1.0: 0.9, 0.9 with 1, 1 -> 0.1 x 2/4
    assert jev.expected_calibration_error([0, 1, 1, 1], [0.1, 0.1, 0.9, 0.9]) == pytest.approx(0.25)


def test_cds_imports_neither_the_narrator_nor_jev():
    tree = ast.parse(Path(config.ROOT, "aei", "cds.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {node.module or ""} | {alias.name for alias in node.names}
    assert not [name for name in imported if "narrator" in name or "jev" in name], imported
