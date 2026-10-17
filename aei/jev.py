"""Optional second opinion from TypeSafe AI's Jev (jev-1.13.0), behind an adapter (CONTRACTS.md section 6).

It is shown only on infection-control inbox items and never in prescribing or order cards: `cds.py` must not import
this module (a test checks). It is switched on only when env `JEV_API_KEY` is set AND `.cache/jev_calibration.json`
holds a passing report for this exact model and question set. Otherwise every call returns None.

What is known vs guessed (sources: context/analysis/tyks/research/w31-ai-layer.md section 1.2, a summarised read of
docs.typesafe.ai on 17 Oct 2026; dossier section 9.9):
- Known from the vendor docs: `POST https://api.typesafe.ai/v1/systemone`, header `Authorization: Bearer <key>`, and a
  JSON body `{"model", "state", "questions"}`. `questions` maps our own ids to typed questions (`choice`, `score` or
  `noul`). A Noul answer is one number, P(yes) in [0, 1], with no confidence field. Pin `jev-1.13.0`, not an alias.
  Jev is unreliable at counting, arithmetic and dates, so the state holds engine-computed bands and a few small counts,
  and never dates.
- GUESSED: the response envelope. The research did not record an example response, so `parse_answers` accepts the
  answers at the top level or under "answers"/"results"/"outputs", each either a bare number or an object with
  "noul"/"probability"/"p"/"value". Check it with one recorded call before relying on it.
- Not established: EU hosting (no EU region documented), data retention terms, rate limits. Synthetic data only.

Calibration (`calibrate`) measures the Brier score, ECE (10 equal-width bins) and n of Jev's `related_cluster` Noul
against simulated ground truth, with fixed pass thresholds (constants below). The spike-in CSV from analysis script 27e
(`spikein_allmethods_results.csv`, 1,350 rows) holds positives only, so `quiet_windows` builds negatives from the
unmodified synthetic data. See SPIKEIN_MISSING for what the CSV lacks.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from . import config

log = logging.getLogger(__name__)

# --- the request -----------------------------------------------------------------------------------------------
JEV_MODEL = "jev-1.13.0"
QUESTION_SET_VERSION = "aei-jev-q1"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
ENDPOINT_PATH = "/v1/systemone"
TIMEOUT_S = 2.0
LABEL = "Second opinion (Jev, experimental). Not used in prescribing alerts."
DISPLAY_QUESTION = "Forward to the ED?"
DISPLAY_QUESTION_ID = "forward_to_ed"
CALIBRATED_QUESTION_ID = "related_cluster"  # the question with simulated ground truth
QUESTIONS = {
    DISPLAY_QUESTION_ID: {
        "type": "noul",
        "instructions": "Should infection control forward this surveillance signal to the emergency department as a "
                        "heads-up this week?",
        "criteria": {"true": "A plausible cluster of a marker organism that ED staff may meet in arriving patients",
                     "false": "A weak or coincidental match, a single case, or a pattern confined to one ward's stay"},
    },
    CALIBRATED_QUESTION_ID: {
        "type": "noul",
        "instructions": "Do the matching cases most likely share a common source or chain?",
        "criteria": {"true": "Same rare antibiogram, several patients, short time spread, one ward",
                     "false": "Coincidence, a common antibiogram, or an artefact"},
    },
}
SUPPORTED_KINDS = ("phenotype_cluster",)  # the kind the spike-in calibration describes; other kinds get None
YES_AT, NO_AT = 0.66, 0.34                 # Noul middle values go to human review ("unclear")
CONTEXT = ("Hospital infection-control surveillance on synthetic ward-level data. All values were computed by code; "
           "do not recompute them.")
STATE_FIELDS = ("signal_type", "organism", "ward_type", "patients_in_signal", "patients_with_matching_antibiogram",
                "identical_share_band", "background_frequency_band", "priority")
_FIELD_SOURCE = {"signal_type": None, "organism": "organism", "ward_type": "ward", "patients_in_signal": "n_patients",
                 "patients_with_matching_antibiogram": "n_share", "identical_share_band": "n_share",
                 "background_frequency_band": "background_rate", "priority": "priority"}

# --- calibration ---------------------------------------------------------------------------------------------
CALIBRATION_FILE = "jev_calibration.json"
ECE_BINS = 10
MAX_ECE = 0.05          # research w31 section 4.5 proposal
MAX_BRIER = 0.15
MIN_N = 1000            # answered clusters
MIN_PER_CLASS = 200     # a set of positives only cannot show calibration (an "always yes" provider would score 0)
MAX_MISSING_SHARE = 0.05

SPIKEIN_TYPES = {"MRSA": ("Staphylococcus aureus", "mrsa"), "ESBL E. coli": ("Escherichia coli", "esbl"),
                 "ESBL K. pneumoniae": ("Klebsiella pneumoniae", "esbl")}
SPIKEIN_DESIGN = {"spread_days": 21, "noise_share": 0.10, "horizon_days": 35}  # 27e: injected over 21 days, 10% flips
SPIKEIN_MISSING = (
    "every row is an injected cluster (label 1); there are no un-injected (label 0) windows",
    "ward and start day are not saved by 27e (48_spikein_outlier.csv has them, but for a separate draw)",
    "the cloned antibiogram and the per-cluster share of identical isolates (10% one-drug noise) are not saved",
    "the evidence at the alert date (background patients in the window, care days, onset) is not saved",
)
INPATIENT_WARDS = ("ICU", "MED-A", "MED-B", "SURG", "URO", "GER")
REAL_EVENTS = (("ICU", "Staphylococcus aureus", "2026-02-01", "2026-05-01"),  # excluded from quiet windows, as in 27e
               ("URO", "Escherichia coli", "2025-05-01", "2025-08-01"))


def default_spikein_csv() -> Path:
    return config.ROOT.parents[1] / "context" / "analysis" / "tyks" / "out" / "spikein_allmethods_results.csv"


def calibration_path() -> Path:
    return Path(config.CACHE_DIR) / CALIBRATION_FILE


def cache_dir() -> Path:
    return Path(config.CACHE_DIR) / "jev"


def key_set() -> bool:
    return config.env("JEV_API_KEY") is not None


def read_calibration(path=None) -> dict | None:
    try:
        report = json.loads(Path(path or calibration_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def calibration_ok(report: dict | None) -> bool:
    return (isinstance(report, dict) and report.get("passed") is True and report.get("provider") == "jev"
            and report.get("model") == JEV_MODEL and report.get("question_set_version") == QUESTION_SET_VERSION)


def status(calibration_file=None) -> str:
    """For /api/meta: "configured" only when the key is set and the calibration passed."""
    return "configured" if key_set() and calibration_ok(read_calibration(calibration_file)) else "not_configured"


# --- state (English keys, engine-computed bands, no ids, no dates) ----------------------------------------------
def ward_type(code: str | None) -> str:
    if not code:
        return "unknown"
    if code == "ICU":
        return "intensive_care"
    if code == "ED":
        return "emergency_department"
    if code.startswith("PHC"):
        return "primary_care"
    return "inpatient_ward"


def _int_or_unknown(v):
    try:
        return int(v) if v is not None and not isinstance(v, bool) else "unknown"
    except (TypeError, ValueError):
        return "unknown"


def _share_band(n_share, n) -> str:
    if not isinstance(n_share, (int, float)) or not isinstance(n, (int, float)) or n <= 0:
        return "unknown"
    s = n_share / n
    return "all" if s >= 1 else ("most" if s >= 0.75 else ("about_half" if s >= 0.4 else "few"))


def _background_band(bg) -> str:
    if not isinstance(bg, (int, float)) or isinstance(bg, bool) or not math.isfinite(bg):
        return "unknown"
    if bg < 0.02:
        return "rare_under_2_percent"
    if bg < 0.05:
        return "uncommon_2_to_5_percent"
    return "common_5_to_15_percent" if bg < 0.15 else "very_common_15_percent_or_more"


def signal_state(signal: dict) -> dict:
    slots = signal.get("slots") or {}
    n, n_share = slots.get("n_patients"), slots.get("n_share")
    bg = slots.get("bg_share", slots.get("background_rate"))
    return {"context": CONTEXT, "signal_type": signal.get("kind") or "unknown", "organism": signal.get("organism") or "unknown",
            "ward_type": ward_type(signal.get("ward")), "patients_in_signal": _int_or_unknown(n),
            "patients_with_matching_antibiogram": _int_or_unknown(n_share), "identical_share_band": _share_band(n_share, n),
            "background_frequency_band": _background_band(bg), "priority": signal.get("priority") or "unknown"}


def mask_state(state: dict, fields) -> dict:
    """Keep only the fields the calibration had; the rest become "unknown", so production matches calibration."""
    keep = set(fields) | {"context"}
    return {k: (v if k in keep else "unknown") for k, v in state.items()}


def request_key(body: dict) -> str:
    raw = json.dumps({"body": body, "question_set_version": QUESTION_SET_VERSION}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _prob(v) -> float | None:
    if isinstance(v, dict):
        v = next((v[k] for k in ("noul", "probability", "p", "value") if k in v), None)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) and 0.0 <= v <= 1.0 else None


def parse_answers(raw) -> dict | None:
    """GUESSED envelope (see module docstring). Returns {"model", "noul": {question id: P(yes)}} or None."""
    if not isinstance(raw, dict):
        return None
    answers = next((raw[k] for k in ("answers", "results", "outputs") if isinstance(raw.get(k), dict)), raw)
    noul = {qid: _prob(answers.get(qid)) for qid in QUESTIONS}
    if noul[DISPLAY_QUESTION_ID] is None and noul[CALIBRATED_QUESTION_ID] is None:
        return None
    model = raw.get("model")
    return {"model": model if isinstance(model, str) else None, "noul": noul}


# --- HTTP client -----------------------------------------------------------------------------------------------
class JevError(Exception):
    """A short reason code only: never a key, a request body or a raw response body."""


class JevHttpClient:
    """GUESSED HTTP client. The request shape follows the vendor docs as summarised in research (w31 section 1.2);
    the response envelope is unverified. Never logs or returns the key."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, *, timeout: float = TIMEOUT_S,
                 transport=None):
        key = api_key or config.env("JEV_API_KEY")
        if not key:
            raise JevError("no_key")
        url = (base_url or config.env("JEV_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        parts = urlsplit(url)
        if parts.scheme != "https" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise JevError("base_url_not_https")
        self._key = key
        self.base_url = url
        self.timeout = timeout
        self._transport = transport

    def __repr__(self) -> str:
        return f"JevHttpClient(base_url={self.base_url!r})"

    def ask(self, body: dict) -> dict:
        import httpx
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport, follow_redirects=False) as c:
                r = c.post(self.base_url + ENDPOINT_PATH, json=body,
                           headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise JevError(f"transport:{type(e).__name__}") from None
        if r.status_code != 200:
            raise JevError(f"http:{r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise JevError("invalid_json") from None


# --- adapter -----------------------------------------------------------------------------------------------------
@runtime_checkable
class SecondOpinion(Protocol):
    def assess(self, signal: dict) -> dict | None: ...


class JevAdapter:
    """Record/replay adapter. Env `JEV_MODE`: `replay` (default; a cache miss returns None, no network) or `record`
    (call Jev on a miss and store the parsed answer under `.cache/jev/`). `require_calibration=False` is only for
    running `calibrate` itself."""
    name = "jev"
    model = JEV_MODEL

    def __init__(self, client=None, *, mode: str | None = None, path=None, calibration_file=None,
                 require_calibration: bool = True):
        self.mode = (mode or config.env("JEV_MODE", "replay")).lower()
        if self.mode not in ("replay", "record"):
            raise ValueError("JEV_MODE must be replay or record")
        self._client = client
        self.path = Path(path) if path is not None else cache_dir()
        self.calibration_file = calibration_file
        self.require_calibration = require_calibration

    def _get_client(self):
        if self._client is None and key_set():
            try:
                self._client = JevHttpClient()
            except JevError as e:
                log.warning("jev client not built (%s)", e)
        return self._client

    def _load(self, key: str) -> dict | None:
        try:
            entry = json.loads((self.path / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return entry if isinstance(entry, dict) and isinstance(entry.get("noul"), dict) else None

    def _store(self, key: str, answers: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        entry = {**answers, "key": key, "recorded": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")}
        fd, tmp = tempfile.mkstemp(dir=self.path, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entry, fh, indent=1)
        os.replace(tmp, self.path / f"{key}.json")

    def assess(self, signal: dict) -> dict | None:
        report, fields = None, STATE_FIELDS
        if self.require_calibration:
            report = read_calibration(self.calibration_file)
            if not (key_set() and calibration_ok(report)):
                return None
            fields = report.get("state_fields") or STATE_FIELDS
        if not isinstance(signal, dict) or signal.get("kind") not in SUPPORTED_KINDS:
            return None
        body = {"model": JEV_MODEL, "state": mask_state(signal_state(signal), fields), "questions": QUESTIONS}
        key = request_key(body)
        answers, cached = self._load(key), True
        if answers is None:
            client = self._get_client() if self.mode == "record" else None
            if client is None:
                return None
            try:
                answers = parse_answers(client.ask(body))
            except Exception as e:  # noqa: BLE001 - a second opinion must never break the inbox
                log.warning("jev call failed (%s)", e if isinstance(e, JevError) else type(e).__name__)
                return None
            if answers is None:
                log.warning("jev response not understood (envelope guess may be wrong)")
                return None
            self._store(key, answers)
            cached = False
        noul = answers["noul"]
        p = _prob(noul.get(DISPLAY_QUESTION_ID))
        answer = None if p is None else ("yes" if p >= YES_AT else ("no" if p <= NO_AT else "unclear"))
        return {"provider": "jev", "mode": "noul", "question": DISPLAY_QUESTION, "answer": answer, "score": p,
                "related_cluster": _prob(noul.get(CALIBRATED_QUESTION_ID)), "model": answers.get("model") or JEV_MODEL,
                "cached": cached, "label": LABEL,
                "calibration": None if report is None else {k: report.get(k) for k in
                                                            ("passed", "brier", "ece", "n", "question", "created")}}


def get_second_opinion() -> JevAdapter:
    return JevAdapter()


# --- simulated clusters ------------------------------------------------------------------------------------------
def _num(v, cast):
    try:
        return cast(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def load_spikein_clusters(path=None) -> list[dict]:
    """The simulated spike-in clusters (27e: 1,350 rows, 150 per type x size 4-6) as cluster descriptions, label 1.

    Also reads 48_spikein_outlier.csv (ward and start day `s`, no background share). Fields the CSV lacks are None;
    see SPIKEIN_MISSING."""
    path = Path(path or config.env("AEI_SPIKEIN_CSV") or default_spikein_csv())
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for i, r in enumerate(rows):
        if r.get("type") not in SPIKEIN_TYPES:
            raise ValueError(f"{path.name} row {i}: unknown type {r.get('type')!r}")
        org, marker = SPIKEIN_TYPES[r["type"]]
        out.append({"id": f"spk-{path.stem}-{i:04d}", "source": path.name, "label": 1, "type": r["type"],
                    "organism": org, "marker": marker, "ward": r.get("ward") or None,
                    "start_day": _num(r.get("s", r.get("start_day")), int), "n_patients": int(float(r["k"])),
                    "n_share": None, "share_identical": None, "spread_days": SPIKEIN_DESIGN["spread_days"],
                    "third_case_day": _num(r.get("third", r.get("third_case_day")), int),
                    "background_rate": _num(r.get("bg", r.get("bg_share")), float),
                    "phenotype_delay_days": _num(r.get("phenotype", r.get("pheno")), float)})
    return out


def _overlaps_real(ward: str, organism: str, a: int, b: int, start) -> bool:
    import pandas as pd
    for w, o, d0, d1 in REAL_EVENTS:
        lo, hi = (pd.Timestamp(d0) - start).days, (pd.Timestamp(d1) - start).days
        if w == ward and o == organism and not (b < lo or a > hi):
            return True
    return False


def quiet_windows(isolates, *, window_days: int = 28, step_days: int = 28, min_patients: int = 2,
                  learn_days: int = 210, margin_days: int = 30) -> list[dict]:
    """Negatives (label 0) from the unmodified synthetic data: non-overlapping windows on the inpatient wards where at
    least `min_patients` marker patients (MRSA, ESBL E. coli, ESBL K. pneumoniae) share one antibiogram by chance.
    Windows within `margin_days` of the two real events are skipped (as in 27e). Assumes the rest of the data holds
    no spread events; the MED-B 2024 look-alike is kept, labelled 0. Not matched one-to-one to the spike-ins."""
    import pandas as pd
    start = pd.Timestamp(config.DATA_START)
    x = isolates[["sample_date", "ward_code", "organism", "patient_id", "profile", "mrsa", "esbl"]].copy()
    x["day"] = (x["sample_date"] - start).dt.days
    x["panel"] = x["profile"].str.replace(r":[SR]", "", regex=True)
    max_day = int(x["day"].max())
    out = []
    for tname, (org, marker) in SPIKEIN_TYPES.items():
        o = x[x["organism"] == org]
        mk = o[o[marker] == 1]
        for ward in INPATIENT_WARDS:
            w = mk[mk["ward_code"] == ward]
            for end in range(learn_days + window_days, max_day + 1, step_days):
                a = end - window_days
                if _overlaps_real(ward, org, a - margin_days, end + margin_days, start):
                    continue
                g = w[(w["day"] > a) & (w["day"] <= end)].sort_values(["day", "patient_id"]).drop_duplicates("patient_id")
                if len(g) < min_patients:
                    continue
                counts = g.groupby("profile").size().sort_values(ascending=False, kind="stable")
                top, c = counts.index[0], int(counts.iloc[0])
                if c < min_patients:
                    continue
                sel = g[g["profile"] == top]
                h = o[(o["panel"] == sel["panel"].iloc[0]) & (o["day"] <= a) & (o["day"] > a - 364)]
                out.append({"id": f"quiet-{tname.replace(' ', '_').replace('.', '')}-{ward}-{end}", "source": "quiet_window",
                            "label": 0, "type": tname, "organism": org, "marker": marker, "ward": ward,
                            "start_day": int(sel["day"].min()), "n_patients": c, "n_share": c,
                            "n_marker_patients": len(g), "share_identical": c / len(g),
                            "spread_days": int(sel["day"].max() - sel["day"].min()), "third_case_day": None,
                            "background_rate": float((h["profile"] == top).mean()) if len(h) else None,
                            "phenotype_delay_days": None})
    return out


def available_fields(clusters) -> list[str]:
    """State fields that every cluster can fill. The others are masked for all, so neither class gives itself away
    by which fields it has."""
    clusters = list(clusters)
    return [f for f in STATE_FIELDS
            if _FIELD_SOURCE[f] is None or all(c.get(_FIELD_SOURCE[f]) is not None for c in clusters)]


def cluster_signal(cluster: dict, fields=STATE_FIELDS) -> dict:
    """A cluster description as a signal-like dict for `assess`; fields outside `fields` are left empty."""
    def keep(field, value):
        return value if field in fields else None
    return {"kind": "phenotype_cluster", "ward": keep("ward_type", cluster.get("ward")),
            "organism": keep("organism", cluster.get("organism")), "priority": keep("priority", cluster.get("priority")),
            "slots": {"n_patients": keep("patients_in_signal", cluster.get("n_patients")),
                      "n_share": keep("patients_with_matching_antibiogram", cluster.get("n_share")),
                      "background_rate": keep("background_frequency_band", cluster.get("background_rate"))}}


# --- metrics -----------------------------------------------------------------------------------------------------
def brier_score(y, p) -> float | None:
    return sum((pi - yi) ** 2 for yi, pi in zip(y, p)) / len(y) if len(y) else None


def expected_calibration_error(y, p, bins: int = ECE_BINS) -> tuple[float | None, list[dict]]:
    """ECE with `bins` equal-width bins on [0, 1] (p = 1 goes in the top bin), plus the reliability table."""
    if not len(y):
        return None, []
    groups = [[] for _ in range(bins)]
    for yi, pi in zip(y, p):
        groups[min(int(pi * bins), bins - 1)].append((yi, pi))
    table, ece = [], 0.0
    for b, g in enumerate(groups):
        if not g:
            continue
        mean_p = sum(pi for _, pi in g) / len(g)
        rate = sum(yi for yi, _ in g) / len(g)
        ece += len(g) / len(y) * abs(rate - mean_p)
        table.append({"bin": [b / bins, (b + 1) / bins], "n": len(g), "mean_score": round(mean_p, 4),
                      "observed_rate": round(rate, 4)})
    return ece, table


def calibrate(provider, clusters, *, path=None, write: bool = True) -> dict:
    """Score `provider` on labelled clusters and write the pass/fail report (default `.cache/jev_calibration.json`).

    `provider.assess(signal)` must return a dict with `related_cluster` (else `score`) in [0, 1], or None (counted as
    missing). For Jev use `JevAdapter(require_calibration=False, mode="record")`. Pass needs all of: n >= MIN_N,
    each class >= MIN_PER_CLASS, missing share <= MAX_MISSING_SHARE, ECE <= MAX_ECE, Brier <= MAX_BRIER, and a Brier
    below the base-rate forecast's."""
    clusters = list(clusters)
    fields = available_fields(clusters)
    y, p, missing = [], [], 0
    for c in clusters:
        out = provider.assess(cluster_signal(c, fields))
        score = None if not isinstance(out, dict) else _prob(out.get("related_cluster", out.get("score")))
        if score is None:
            missing += 1
            continue
        y.append(int(c["label"]))
        p.append(score)
    n, n_pos = len(y), sum(y)
    brier = brier_score(y, p)
    base = n_pos / n if n else None
    brier_base = base * (1 - base) if base is not None else None
    skill = (1 - brier / brier_base) if brier is not None and brier_base else None
    ece, table = expected_calibration_error(y, p)
    missing_share = missing / len(clusters) if clusters else 1.0
    reasons = []
    if n < MIN_N:
        reasons.append(f"n {n} < {MIN_N}")
    if n_pos < MIN_PER_CLASS or n - n_pos < MIN_PER_CLASS:
        reasons.append(f"classes {n_pos} positive / {n - n_pos} negative; need >= {MIN_PER_CLASS} each")
    if missing_share > MAX_MISSING_SHARE:
        reasons.append(f"missing answers {missing_share:.1%} > {MAX_MISSING_SHARE:.0%}")
    if ece is None or ece > MAX_ECE:
        reasons.append(f"ECE {ece} > {MAX_ECE}")
    if brier is None or brier > MAX_BRIER:
        reasons.append(f"Brier {brier} > {MAX_BRIER}")
    if skill is None or skill <= 0:
        reasons.append("no Brier skill over the base rate")
    report = {"provider": getattr(provider, "name", type(provider).__name__), "model": getattr(provider, "model", None),
              "question_set_version": QUESTION_SET_VERSION, "question": CALIBRATED_QUESTION_ID, "state_fields": fields,
              "n_clusters": len(clusters), "n": n, "n_missing": missing, "n_positive": n_pos, "n_negative": n - n_pos,
              "base_rate": base, "brier": brier, "brier_base_rate": brier_base, "brier_skill": skill, "ece": ece,
              "ece_bins": ECE_BINS, "reliability": table,
              "thresholds": {"max_ece": MAX_ECE, "max_brier": MAX_BRIER, "min_n": MIN_N, "min_per_class": MIN_PER_CLASS,
                             "max_missing_share": MAX_MISSING_SHARE},
              "passed": not reasons, "reasons": reasons, "sources": sorted({str(c.get("source")) for c in clusters}),
              "note": "Simulated spike-in clusters and chance windows of the synthetic data; not real outbreaks.",
              "created": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")}
    if write:
        target = Path(path or calibration_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        os.replace(tmp, target)
    return report
