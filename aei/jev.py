"""Optional second opinion from Jev (TypeSafe AI, jev-1.13.0) behind an adapter (CONTRACTS.md section 6). Priority P2.

Inert by default: `JevAdapter.assess` returns None unless env JEV_API_KEY is set AND .cache/jev_calibration.json,
written by `calibrate`, says "passed": true for this model. It asks one yes/no question (a Jev "Noul": P(yes) in
[0, 1]) about phenotype clusters in the infection-control inbox. It never reaches prescribing: cds.py does not import
this module, and a test checks that.

Jev is unreliable with counts, arithmetic and dates (the vendor's own limits page), so the state it gets holds only a
few small engine-computed counts and labels: no dates, no patient ids.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
from pathlib import Path
from typing import Protocol

from . import config

log = logging.getLogger(__name__)

JEV_MODEL = "jev-1.13.0"  # pinned: thresholds tuned on one version do not carry over to the next
DEFAULT_BASE_URL = "https://api.typesafe.ai"
LABEL = "Second opinion (Jev, experimental). Not used in prescribing alerts."
QUESTION = "Forward to the ED?"
QUESTION_ID = "forward_to_ed"
QUESTIONS = {
    QUESTION_ID: {
        "type": "noul",
        "instructions": (
            "Do these cases look like a related cluster that the emergency department should hear about this week?"
        ),
        "criteria": {
            "true": "Several patients on one unit share a rare antibiogram within a short time",
            "false": "A single case, a common antibiogram, or a coincidental match",
        },
    }
}
SUPPORTED_KINDS = ("phenotype_cluster",)  # the only kind the simulated clusters calibrate
YES_AT, NO_AT = 0.66, 0.34  # the vendor leaves middle values to human review

# Fixed pass thresholds for `calibrate`. Both classes are required: on positives only, "always yes" would score 0.
MAX_BRIER, MAX_ECE, MIN_N, MIN_PER_CLASS = 0.15, 0.05, 1000, 100
ECE_BINS = 10


class SecondOpinion(Protocol):
    def assess(self, signal: dict) -> dict | None: ...


def key_set() -> bool:
    return config.env("JEV_API_KEY") is not None


def calibration_file() -> Path:
    return Path(config.CACHE_DIR) / "jev_calibration.json"


def read_calibration() -> dict | None:
    try:
        report = json.loads(calibration_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) and report.get("model") == JEV_MODEL else None


def status() -> str:
    """For /api/meta: "configured" only when the key is set and the calibration passed."""
    report = read_calibration()
    return "configured" if key_set() and report is not None and report.get("passed") is True else "not_configured"


class JevHttpClient:
    """A GUESS at the HTTP API. Known from the vendor docs (research w31, section 1.2): POST {base}/v1/systemone with
    `Authorization: Bearer <key>` and the JSON body {"model", "state", "questions"}. Not known: the response envelope.
    This guesses {"answers": {<question id>: {"noul": p}}}; check it with one recorded call before relying on it."""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 5.0):
        if not base_url.startswith("https://"):
            raise ValueError("JEV_BASE_URL must be an https URL")
        self._key = api_key
        self.url = base_url.rstrip("/") + "/v1/systemone"
        self.timeout = timeout

    def noul(self, body: dict) -> float:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return float(json.load(response)["answers"][QUESTION_ID]["noul"])


def jev_state(signal: dict) -> dict:
    slots = signal.get("slots") or {}

    def count(name):
        return None if slots.get(name) is None else int(slots[name])

    return {
        "finding": signal.get("kind"),
        "organism": signal.get("organism"),
        "unit": signal.get("ward"),
        "priority": signal.get("priority"),
        "patients": count("n_patients"),
        "patients_sharing_antibiogram": count("n_share"),
    }


class JevAdapter:
    """Replay first, then record: every answer is stored under .cache/jev and reused, so a demo replays offline."""

    name = "jev"
    model = JEV_MODEL

    def __init__(self, client=None, *, require_calibration: bool = True):
        self._client = client  # injected in tests; otherwise built from env on the first call
        self.require_calibration = require_calibration  # False only while `calibrate` measures Jev itself

    def assess(self, signal: dict) -> dict | None:
        report = read_calibration()
        if not key_set() or (self.require_calibration and not (report and report.get("passed") is True)):
            return None
        if signal.get("kind") not in SUPPORTED_KINDS:
            return None
        body = {"model": JEV_MODEL, "state": jev_state(signal), "questions": QUESTIONS}
        p = self._replay_or_ask(body)
        if p is None:
            return None
        return {
            "provider": "jev",
            "mode": "noul",
            "question": QUESTION,
            "answer": "yes" if p >= YES_AT else "no" if p <= NO_AT else "unclear",
            "score": p,
            "label": LABEL,
            "calibration": {k: report.get(k) for k in ("brier", "ece", "n", "passed")} if report else None,
        }

    def _replay_or_ask(self, body: dict) -> float | None:
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
        file = Path(config.CACHE_DIR) / "jev" / f"{key}.json"
        if file.exists():
            return json.loads(file.read_text(encoding="utf-8"))["noul"]
        client = self._client or JevHttpClient(config.env("JEV_API_KEY"), config.env("JEV_BASE_URL", DEFAULT_BASE_URL))
        try:
            p = client.noul(body)
        except (OSError, ValueError, KeyError, TypeError) as e:  # network, HTTP status, or the guessed envelope
            log.warning("Jev call failed (%s)", type(e).__name__)
            return None
        if not 0.0 <= p <= 1.0:
            log.warning("Jev answer outside [0, 1] ignored")
            return None
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({"noul": p}), encoding="utf-8")
        return p


def calibrate(provider: SecondOpinion, clusters) -> dict:
    """Score `provider` on labelled simulated clusters, write the report to .cache/jev_calibration.json and return it.

    `clusters`: dicts {"signal": <signal-like dict>, "label": 1 for a real cluster, 0 for a chance match}. For Jev
    itself, pass `JevAdapter(require_calibration=False)`. Unanswered clusters are left out of n."""
    y, p = [], []
    for cluster in clusters:
        answer = provider.assess(cluster["signal"])
        if answer is not None and answer.get("score") is not None:
            y.append(int(cluster["label"]))
            p.append(float(answer["score"]))
    n, n_pos = len(y), sum(y)
    brier = sum((pi - yi) ** 2 for yi, pi in zip(y, p)) / n if n else None
    ece = expected_calibration_error(y, p)
    passed = (
        n >= MIN_N
        and min(n_pos, n - n_pos) >= MIN_PER_CLASS
        and brier is not None
        and brier <= MAX_BRIER
        and ece is not None
        and ece <= MAX_ECE
    )
    report = {
        "model": getattr(provider, "model", None),
        "brier": brier,
        "ece": ece,
        "n": n,
        "n_positive": n_pos,
        "passed": passed,
        "thresholds": {"max_brier": MAX_BRIER, "max_ece": MAX_ECE, "min_n": MIN_N, "min_per_class": MIN_PER_CLASS},
    }
    calibration_file().parent.mkdir(parents=True, exist_ok=True)
    calibration_file().write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def expected_calibration_error(y: list[int], p: list[float], bins: int = ECE_BINS) -> float | None:
    """Mean |observed rate - mean score| over equal-width score bins, weighted by bin size."""
    if not y:
        return None
    groups: dict[int, list[tuple[int, float]]] = {}
    for yi, pi in zip(y, p):
        groups.setdefault(min(int(pi * bins), bins - 1), []).append((yi, pi))
    return sum(abs(sum(yi for yi, _ in g) - sum(pi for _, pi in g)) for g in groups.values()) / len(y)
