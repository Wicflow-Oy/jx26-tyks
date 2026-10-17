# Build contracts (v1, Sat 17 Oct 2026 evening)

Product name: `aei.config.APP_NAME` (placeholder "Strainwatch"; the team decides). Never hard-code the name elsewhere.
All data is synthetic. Python 3.12, pandas 3.0, FastAPI. Run everything with `.venv/Scripts/python.exe`.

**Ground rules for every workstream**
- Only edit the files your workstream owns (section 8). Shared files (`config.py`, `data.py`, `stats.py`, `render.py`, `signal.py`, `CONTRACTS.md`, `tests/conftest.py`) are read-only; ask the integrator for a change, or note it in your report.
- No git commits (the integrator commits). No network calls in tests. No real API calls anywhere unless an env key is set *and* the user runs it.
- Keys only from env vars: `ANTHROPIC_API_KEY`, `JEV_API_KEY` (+ `JEV_BASE_URL`). Never log them, never return them in an API response, and never write them to disk.
- Never write the CSVs or derived patient-level data into the repo. Caches go to `config.CACHE_DIR` (`.cache/`, gitignored).
- **Wording:** no prediction language on screen or in text ("predicts", "forecast", "odds", "probability that", "best choice", "recommended drug", "AI predicts"). Results are S/R (never "S/I/R"). Say "unusual pattern", "typing advised" and "profile match, not typing". Never say "decoy" or "outbreak confirmed". Say "data gap, cause unknown", never "zero resistance".
- **Dates are sample dates.** Results usually arrive ~2 days later (`config.RESULT_LAG_DAYS`); say so wherever lead time is shown.
- Reproducible: any Monte Carlo uses `stats.rng()` (fixed seed).

## 1. Data (`aei/data.py`, done)
`data.load() -> Dataset(isolates, cultures, patients)`, cached. `isolates` has one row per isolate with these columns:
- the original columns;
- `week` (0 = week of Mon 2 Oct 2023);
- `week_start`, `year`, `care_day_no` (admission day = 1; NaN for outpatients), `hosp_onset` (care day ≥3), `age_band`;
- drug columns AMP..CLI (`"S"`/`"R"`/NaN);
- `profile` (`"AMP:R MEC:S ..."` in `config.DRUGS` order), `n_R`;
- `first_year`, `first_30d`.

Helpers:
- `window(df, as_of, days)`: rows with `as_of - days < sample_date <= as_of`.
- `first_isolates(df, rule)`, where `rule` is `"readme_period"` (default; first per patient × organism × specimen inside the rows given) or `"30d"`.
- `week_end(week)` and `week_of(date)`.

Goldens: 24,571 isolates; 46,792 cultures; `first_year` 21,387; `first_30d` 23,769.

**Inpatient/outpatient** is `ward_type` (check the values in the data; PHC-N/PHC-S are primary care, ED is its own unit). **Specimen groups:** `config.SPECIMEN_GROUPS`.

## 2. Time model (everyone)
- **`as_of`** = the last data day, a Sunday (`YYYY-MM-DD`). The brief is dated **`as_of + 1 day`** (Monday). The API accepts `as_of` (Sunday) or `monday` (converted to `as_of = monday - 1 day`).
- **Strict as-of:** nothing sampled after `as_of` may influence any number, signal, alert or banner for that date. Alerts approved after `as_of + 1` are invisible at that date.
- **Windows** (`config.WINDOWS`) end on `as_of` inclusive: `4w` = 28 days, `4m` = 112, `12m` = 364. "Prior 52 weeks" = the 364 days ending the day before the window starts.
- **The replay slider** moves `as_of` one week at a time over the range `data.week_end(55)`..`config.DATA_END` (52 weeks of history are needed before the first replay week). The UI passes one global `as_of` to every view, so the brief, My ward and the order screen always agree.
- **Counting rule** param `rule` ∈ {`readme_period`, `30d`}, default `readme_period`, applied to the rows inside each window.

## 3. The evidence object (`aei/signal.py`, done)
Every detector returns `list[dict]` built with `signal.make_signal(...)`:
```
{ "id": "phe-1a2b3c4d5e"        # stable across replay weeks: kind + key
  "kind": phenotype_cluster | thl_rule | count_stepup | ward_outlier | resistance_change | policy_line
          | seen_before | expert_rule | completeness
  "priority": P1 | P2 | P3 | info,   "status": new | ongoing | resolved,
  "section": unusual_patterns | changed | policy | seen_before | data_quality | quiet,
  "as_of", "ward", "home_area", "specimen", "organism", "drug", "first_sample_date",
  "template_id", "slots": {every number and label the text uses},
  "text": rendered by code from templates.TEMPLATES[template_id] + slots,
  "advice": "Typing advised" | "Lab check" | "Review the empirical UTI guidance" | null,
  "evidence": { "filter": {ward, specimen, organism, drug, date_from, date_to, rule},   # re-runnable
                "counts": {...}, "method": "phenotype cluster, rarity gate ...", "params": {...},
                "isolate_ids": [...]  (optional; never patient names, synthetic ids only) },
  "key": {...} }
```
- **Status:** `new` if the signal's id was not active at `as_of - 7 days`; `ongoing` if it was; `resolved` signals are listed for one week after they stop firing.
- **Numbers only via slots.** A test asserts that every digit run in `text` comes from a slot value.

## 4. Coverage and My ward (`aei/coverage.py`, `aei/views.py`; workstream A)
### 4.1 Coverage cell
`coverage.cell(rows, drug, prior_rows=None, hosp_rows=None) -> dict` for a single drug or a combo key ("MEM+VAN"):
```
{ "drug": "MEM", "label": "Meropenem", "aware": "Watch",
  "observed": {"covered": 11, "tested": 24, "pct": 0.458, "ci": [0.27, 0.65]},     # Jeffreys
  "estimate": {"pct": 0.74, "ci": [0.61, 0.85], "method": "observed" | "stabilised"},
  "state": ok | low_n | not_enough_data,        # stats.n_state(tested)
  "eligible": true, "tested_share": 0.97,       # >= config.ELIGIBLE_MIN_TESTED_SHARE of the organism mix
  "changed": {"changed": true, "p": 1e-4, "direction": "down"} | null,   # stats.change_test on NOT-covered counts
  "below_local_setting": true }                 # estimate.pct < 0.80 (local setting, set by stewardship)
```
- **Coverage semantics:** port 11_fixes / 36b exactly. An isolate counts as covered if S. `INTRINSIC`/`NO_BREAKPOINT` pairs count as not covered. A combo is covered if any member is covered. Untested non-intrinsic pairs are excluded from `tested`.
- **Estimate rule:**
  - `ok`: observed (with its Jeffreys interval);
  - `low_n`: stabilised, using `stats.pooled_estimate`/`pooled_interval` toward the unit's prior 52 weeks with k = `POOLING_K`;
  - `not_enough_data`: no percentage (`estimate.pct` = null).

  The **observed x of n is always present**, so "74% stabilised" never sits unexplained next to "11 of 24".
- `FOX` is never shown as a therapy option (`HIDDEN_AS_OPTION`). Urine-only drugs (`URINE_ONLY`) are shown only for urine.
- **Ineligible drugs** (tested on fewer than 90%) are hidden from the table and listed under `not_shown` with a reason, e.g. "Ciprofloxacin not shown: untested on S. aureus (most of this ward's isolates)".

**Goldens** (reproduce 36b_coverage_asof with 36b's counting rule first, then record the product-default values in the test):
- ICU blood+wound, as-of 2026-03-29, 4w, k=20 stabilised:
  - MEM 74 [61–85], TZP 73 [60–84], VAN 78 [62–91], n = 24;
  - observed MEM 11/24, TZP 11/24, VAN 20/24.
- URO urine, as-of 2025-06-29, 4w:
  - CRO 70 [60–78], CIP 70 [60–78], NIT 90 [83–95], n = 67;
  - observed CRO 40/65, CIP 35/60, NIT 61/67.

### 4.2 My ward view
`views.my_ward(ds, as_of, ward=None, specimen_group="blood_wound", organism=None, sex=None, age_band=None, setting=None, windows=("4w","12m"), rule="readme_period") -> dict`
- `ward` is a ward code, a list of codes, or None (all).
- `setting` ∈ {inpatient, outpatient, None}.
```
{ "as_of", "monday", "filters": {...echo...}, "windows": [{"key":"4w","from","to","n_isolates"}, ...],
  "rows": [ {"drug": "MEM", "label", "aware", "cells": {"4w": <cell>, "12m": <cell>}} ... ]   # config.DISPLAY_ORDER
  "not_shown": [{"drug", "reason"}],
  "organisms": {"4w": [{"organism", "n", "flags": {"mrsa": 13}}], "12m": [...]},
  "local_setting": {"value": 0.80, "label": "local setting, set by stewardship"},
  "small_n_examples": [...optional...],
  "footer": "In-vitro coverage on this unit. Not a prescription; local guide first." }
```
- `views.antibiogram(ds, as_of, ward, specimen_group, window, rule)` gives the per-organism % susceptible (R of n, interval, state) for the "organism" tab.
- `views.filters_catalog(ds)` lists the wards (code + label), specimen groups, organisms, sexes, age bands and settings.
- `views.trend(ds, ward, specimen_group, drug, as_of, weeks=52, window="4w", organism=None, rule=...)` gives a weekly series of the rolling-window cell (observed + estimate) for sparklines. It must take ≤1 s.
- **Performance:** `my_ward` ≤ 1.5 s cold on this laptop.
- `aei/aggregates.py` (optional, A) may precompute weekly counts to the cache to meet this.

## 5. Signals and the Monday brief (`aei/detectors/*`, `aei/brief.py`, `aei/templates.py`; workstream B)
### 5.1 Detectors
Each detector is `detect(ds, as_of, rule="readme_period") -> list[signal]` and is strictly as-of. Port the analysis implementations (script numbers in brackets):

| Module | What it finds | Section / priority |
|---|---|---|
| `phenotype.py` | Patients sharing one antibiogram on one ward (spec detector in `09_leadtime`; 26-week learning, rarity gate, panel-aware). Slots include n_patients, n_share, pattern, first_date and the expected-per-year range | unusual_patterns, P1 |
| `thl.py` | THL rule cards: any CPE; VRE; ESBL / MRSA same-ward clusters (`20_thl_register_chart`, `08_hidden`) | unusual_patterns, P1 for CPE/VRE |
| `stepup.py` | Count step-up Bayesian test (`47_outbreak_prob`). It is supporting evidence attached to a cluster or a P3 item, never a P1 on its own | unusual_patterns, P3 |
| `outlier.py` | Ward outlier count vs other wards (`44`/`48`) | changed, P3 |
| `resistance_change.py` | Organism × drug resistance on a ward, last 4 weeks vs the prior 52 weeks, via `stats.change_test` (`39_resistance_hybrid` pairs, `first_30d` there; use `rule`) | changed, P2 |
| `policy.py` | `config.POLICY_LINES`: rolling 52-week rate under the line's counting rule; fires while ≥ threshold. Exposes `policy_states(ds, as_of) -> list[dict]` with rate, x, n, interval, the prior-year rate, `crossed_on` (first week-end ≥ threshold in the current run), the threshold and `local_guide_alternative` | policy, P2 |
| `seen_before.py` | For each active cluster: earlier patients with the same profile, same ward vs elsewhere, with the profile's background share (`52`). Shows "not seen on ICU before" | seen_before, info |
| `expert_rules.py` | `config.EXPERT_RULES` hits in the window (`40`, `52`) | data_quality, P3 |
| `completeness.py` | Silent units, meaning no cultures this week vs expected (`35_data_gaps`) | data_quality, P2 |

### 5.2 Brief
`brief.build_brief(ds, as_of, window="4w", rule="readme_period") -> dict`:
```
{ "as_of", "monday", "app_name", "synthetic": true, "window", "rule",
  "header": {"title": "Monday brief", "data_to": as_of, "refreshed": "nightly"},
  "sections": [ {"key": "unusual_patterns", "title": "Unusual patterns", "items": [signal...]},
                {"key": "changed", ...}, {"key": "policy", ...}, {"key": "seen_before", ...},
                {"key": "data_quality", ...}, {"key": "quiet", "items": [...]} ],
  "map": {"units": [{"ward", "label", "state": signal|changed|quiet|no_data, "signal_ids": [...]}],
          "home_areas": [{"area", "state", "signal_ids"}]},
  "counts": {"P1": 1, "P2": 1, ...},
  "footer": "Every number links to its count and filter. Text narrated from computed numbers only." }
```
- `brief.signals_for(ds, as_of, ward=None) -> list[signal]` returns the active signals touching a unit (for banners and the map).
- **Performance:** a brief takes ≤ 3 s cold. If detectors are slow, precompute per-week signals into `.cache/signals/{as_of}.json` via `brief.precompute(ds, weeks)`.

**Goldens (signals):**
- **ICU MRSA 2026** (pattern `FOX:R VAN:S CLI:R`; first sample 3 Mar 2026). Patients by date:
  - as-of 2026-03-07: 3 patients, 3 share the top pattern;
  - 03-13: 5;
  - 03-20: 8;
  - 03-27: 13 (12 share).
- **URO ESBL E. coli 2025:** fires by 2025-06-04 with 4 identical patients.
- **MED-B ESBL look-alike 2024:** heterogeneous (3 antibiograms), ranked lower, and never called a decoy.
- **Trimethoprim, primary-care women, README rule, rolling 52 weeks:**
  - peak 20.4% (160/786) at the week ending 2026-06-21;
  - ≥ 20% at the weeks ending 06-21, 06-28, 07-12 and 07-19;
  - at 2026-09-27: 18.3% (144/789).
- **Seen before, ICU MRSA profile:**
  - before the cluster: 0 patients on ICU and 11 elsewhere (ED 4, SURG 4, MED-A 1, PHC-S 1, PHC-N 1);
  - back on ICU 2026-09-12;
  - the profile is 22.7% of 110 MRSA patients.
- **Expert rules:**
  - 0 of 517 ESBL-flagged isolates are S to CXM or CRO;
  - 0 of 111 MRSA are FOX-S;
  - 109 rows are CRO R with AMP S or CXM S (all isolates).
- **Data gap:** PHC-S sent no cultures 8–14 Dec 2025 (~51 expected).
- **A VRE card on GER** by the 14 Sep 2026 brief (check `08_hidden`).

## 6. Narrator, validator, Jev (`aei/narrator/*`, `aei/validator.py`, `aei/jev.py`; workstream C)
- `narrator.base.Narrator` (Protocol): `narrate(template_id: str, slots: dict, *, audience="infection_control", language="en") -> Narration`.
- `Narration` is a dataclass: `text` (final, numbers rendered by code), `skeleton` (the model's text with `{slot}` placeholders), `provider`, `validated`, `fallback_reason`.
- **Providers:**
  - `TemplateNarrator` (default; deterministic; uses `render_id`);
  - `AnthropicNarrator` (env `ANTHROPIC_API_KEY`; model env `AEI_MODEL`, default `claude-haiku-5-5`; backend env `AEI_LLM_BACKEND` ∈ anthropic|bedrock|vertex for the EU route, with lazy client construction).

    Constraints from the verified API facts:
    - **no** `temperature`/`top_p`/`top_k` (a 400 on 5.5 models);
    - **no** forced `tool_choice`;
    - don't pass `thinking`;
    - keep a stable system prompt;
    - anything other than `stop_reason == "end_turn"` falls back to the template.
  - `CachedNarrator(inner, path)`: record/replay JSON keyed by the sha256 of (provider, model, prompt_version, template_id, slots, audience, language). Env `AEI_NARRATOR` ∈ template|anthropic|replay picks one; `narrator.get_narrator()` is the factory.
- **The model writes skeletons:** prose with `{slot}` placeholders, and never digits. The flow is: validator on the skeleton → render → `validate_rendered`. Any failure falls back to the template with `fallback_reason`.
- `validator.validate_skeleton(text, allowed_slots) -> ValidationResult(ok, errors: list[str])` rejects:
  - digits (any `\d`);
  - number words in en/fi/sv (one..twenty, dozen, hundred, thousand, half, twice, double, triple, percent; yksi, kaksi..., sata, puolet; en/ett, två..., hundra, hälften);
  - computed comparisons ("doubled", "times higher", "x-fold", "percentage points", "increase of", "rose by", "fell by");
  - prediction terms (`predict`, `forecast`, `odds`, `likely to`, `probability`, `best choice`, `recommended drug`, `will rise`);
  - restricted terms (`decoy`, `outbreak confirmed`, `S/I/R`, `zero resistance`);
  - dosing (`mg`, `g/day`, `dose`, `dosing`, `twice daily`, `x daily`, `per kg`);
  - unknown slot names;
  - patient identifiers (`P-\d` cannot appear anyway, since digits are banned).
- `validator.validate_rendered(text, slots) -> ValidationResult`: every number in the text must equal a formatted slot value.
- **`jev.py`, an optional second opinion behind an adapter:**
  - `SecondOpinion.assess(signal) -> dict | None`;
  - `JevAdapter` (env `JEV_API_KEY`, `JEV_BASE_URL`) with record/replay, which returns `None` unless the key is set **and** `.cache/jev_calibration.json` exists with `passed: true`;
  - `calibrate(provider, clusters) -> report` (Brier score, ECE and n over the 1,350 simulated spike-in clusters, with fixed pass thresholds).

  Output: `{"provider": "jev", "mode": "choice"|"score"|"noul", "question": "Forward to the ED?", "answer", "score", "label": "Second opinion (Jev, experimental). Not used in prescribing alerts.", "calibration": {...}}`. It is used **only** on infection-control inbox items. It is never imported by `cds.py`; a test enforces this. Read `context/tyks-brainstorm-research.md` and the dossier on Jev (TypeSafe AI, jev-1.13.0, Choice/Score/Noul). If the HTTP shape is unknown, implement a clearly-marked `JevHttpClient` guess behind the adapter, plus the fake used in tests.

## 7. API, alerts, order check (`aei/api.py`, `aei/store.py`, `aei/cds.py`, `aei/precompute.py`; workstream D)
FastAPI app `aei.api:app`; run with `uvicorn aei.api:app --host 127.0.0.1 --port 8765`. Bind to localhost by default. The app serves `web/` statically at `/` (the UI arrives in Phase 3; ship a placeholder `web/index.html` that lists the endpoints).

| Method & path | Returns |
|---|---|
| `GET /api/meta` | app_name, synthetic, data_start/end, replay range (first/last as_of), demo_mondays, wards, roles, narrator provider name, `second_opinion: "configured"/"not_configured"` |
| `GET /api/filters` | `views.filters_catalog` |
| `GET /api/brief?as_of=&window=4w&rule=` | `brief.build_brief`, with each item enriched by `alert` (approved alert linked to it, if any) and `heads_up` state |
| `GET /api/my-ward?as_of=&ward=&specimen=&organism=&sex=&age_band=&setting=&rule=` | `views.my_ward` + `banners` (active approved alerts and policy states touching that unit) + `signals` (`brief.signals_for`) |
| `GET /api/trend?...` | `views.trend` |
| `GET /api/replay/weeks` | `[{as_of, monday, n_p1, n_signals}]` for slider tick marks (precomputed) |
| `GET /api/feed?as_of=` | the "continuously updated" ticker: isolates and results arriving in the week ending as_of, by unit (counts only), "refreshed nightly" |
| `GET /api/signals/{id}?as_of=` | case file: the signal, a line list (synthetic isolate id, date, ward, care day, profile; no names), an epi curve by day, seen-before matches, step-up evidence, and alerts |
| `POST /api/alerts` | approve an alert from a signal: `{signal_id, as_of, wards[], drugs[], message, approved_by_role, expires_on}`; `expires_on` defaults to monday + `ALERT_DEFAULT_EXPIRY_DAYS` |
| `GET /api/alerts?as_of=` | alerts active at as_of+1 |
| `POST /api/alerts/{id}/revoke` | revoke an alert |
| `POST /api/heads-up` | draft a heads-up from a signal: text by the narrator for audience "ed", status `draft` |
| `POST /api/heads-up/{id}/approve` | marks it `approved`. **Nothing is ever sent**; the response says `"delivery": "not sent (demo)"` |
| `GET /api/feedback?as_of=` | infection-control view of order-card outcomes (counts by card/outcome, no user ids) |
| `POST /api/narrate`, `POST /api/validate` | for the UI and tests |
| `GET /api/second-opinion/{signal_id}` | Jev or `{"status": "not_configured"}` |
| `GET /cds-services` | CDS Hooks discovery: `{services: [{hook: "order-select", id: "strainwatch-order-select", title, description, prefetch: {}}, {hook: "order-sign", id: "strainwatch-order-sign", ...}]}` |
| `POST /cds-services/{id}` | CDS Hooks request (see below), returning `{cards: [...]}` |
| `POST /cds-services/{id}/feedback` | CDS Hooks feedback, logged to the store |

**Order check (`cds.order_check(ds, as_of, unit, drug, indication, alerts, policy_states) -> list[card]`; pure, deterministic):**

*Request.* The request is CDS Hooks 2.0 shaped: `{hookInstance, hook, context: {userId, patientId, encounterId, draftOrders: FHIR Bundle with a MedicationRequest}}`.
- The drug comes from the MedicationRequest `medicationCodeableConcept.coding` ATC code, mapped through `config.ATC`.
- The demo carries unit and indication in `context.extension`: `{"strainwatch.unit": "ED", "strainwatch.indication": "urinary", "strainwatch.as_of": "2026-06-21"}`.

*Which cards are allowed.* Card sources are deterministic only: (a) an approved, unexpired alert for that unit; (b) a policy line currently ≥ threshold whose `order_units` include the unit and whose `order_indication` matches. **Never** narrator or Jev output, and never a patient-specific estimate.

*When it interrupts.*
- `indicator: "warning"` (interruptive) **only** when the ordered drug is the drug that alert or policy line concerns.
- Otherwise there is at most one `indicator: "info"` passive card per active alert on that unit.
- No card when nothing applies.

*Card content.*
- `summary` (≤140 characters), e.g. "Trimethoprim: 20.4% resistant (160 of 786, last 52 weeks), above local 20% line".
- `detail` (markdown): the 12-month-ago comparison, who flagged it and when (policy: "Local policy line set by infection control; crossed week ending 21 Jun 2026"; alert: "Flagged by infection control, 9 Mar 2026; expires 23 Mar"), the local-guide alternative, and the small print "Observed unit-level information, not a prediction for this patient. The doctor decides."
- `source: {label: APP_NAME + " · infection control"}`.
- `suggestions: [{label: "Change to pivmecillinam", uuid, actions: [{type: "update", description, resource: <MedicationRequest with the ATC code swapped>}]}]`.
- `overrideReasons: [{code: "keep", display: "Keep trimethoprim"}, ...]`.
- `links: [{label: "Details", url: "/#/signal/<id>?as_of=", type: "absolute"}, {label: "Open in Strainwatch (SMART)", url: "/smart/launch", type: "smart"}]`.
- `selectionBehavior: "at-most-one"`, `uuid`, plus our own `extension: {"strainwatch.rule": "...", "strainwatch.evidence": {...counts, filter...}}`.

*Feedback.* Keep / Change / Details map to CDS Hooks feedback `outcome: overridden | accepted` (+ `overrideReason`, `acceptedSuggestions`). The feedback is stored with card uuid, source id, outcome and timestamp; no user or patient id is stored.

**Store (`store.py`):** SQLite in `.cache/state.sqlite`, with tables alerts, heads_up, feedback and audit (append-only). `store.reset()` clears it for tests and the demo. `store.seed_demo()` adds the ICU MRSA alert (approved 2026-03-09 by "Infection control", wards [ICU], drugs [], expires 2026-03-23, message per CONTENT.md), marked `seed: true`. The trimethoprim card needs **no** seed: it comes from the policy line.

**Precompute (`precompute.py`):** the CLI `python -m aei.precompute [--weeks all|demo]` warms the caches (signals per week, replay weeks, the demo-Monday briefs) and prints timings.

**Security:**
- loopback bind;
- CORS off;
- no keys in responses;
- `POST` endpoints validate input with pydantic models;
- every text field rendered by the UI is plain text (the UI uses textContent).

## 8. File ownership
| Workstream | Owns (create/edit only these) |
|---|---|
| Integrator (main session) | `aei/config.py`, `aei/data.py`, `aei/stats.py`, `aei/render.py`, `aei/signal.py`, `CONTRACTS.md`, `tests/conftest.py`, `tests/test_data.py`, README.md, git |
| **A Coverage & views** | `aei/coverage.py`, `aei/views.py`, `aei/aggregates.py`, `tests/test_stats.py`, `tests/test_coverage.py`, `tests/test_views.py` |
| **B Detectors & brief** | `aei/detectors/*.py`, `aei/brief.py`, `aei/templates.py` (extend; keep existing ids), `tests/test_detectors.py`, `tests/test_brief.py`, `tests/test_signal_goldens.py` |
| **C Narrator, validator, Jev** | `aei/narrator/*.py`, `aei/validator.py`, `aei/jev.py`, `tests/test_validator.py`, `tests/test_narrator.py`, `tests/test_jev.py` |
| **D API, store, CDS, precompute** | `aei/api.py`, `aei/store.py`, `aei/cds.py`, `aei/precompute.py`, `web/index.html` (placeholder), `tests/test_api.py`, `tests/test_cds.py`, `tests/test_store.py` |

While other workstreams are unfinished, test against their contract with fakes or monkeypatching (D especially). The integrator wires everything together and runs the full suite. In your final report, list: files written, tests (pass/fail counts), anything mocked, any contract deviation, and open questions.

## 9. Analysis sources (read-only)
- Scripts: `C:\Users\user\code\junctionx-turku-2026\context\analysis\tyks\NN_*.py`.
- Outputs: `...\tyks\out\NN_*.txt`, `out/replay_asof.json`.
- The script index: `README.md` there.

The analysis used pickles from `common_build.py`; `aei.data.load()` produces the same table, with the extra columns `care_day_no` and `age_band`. Port the logic; don't import from the analysis folder.
