# Specification

Product name: `aei.config.APP_NAME` ("Strainwatch"). Never hard-code the name elsewhere. The Python package is `aei`,
the web app is `web/`, and the Docker Compose project and image are `jx-tyks` (`deploy/`).

All data is synthetic. Python 3.12, pandas 3.0, FastAPI. Run everything with the project venv (`.venv/bin/python`; on
Windows `.venv/Scripts/python.exe`). One formatter and linter: `ruff format` and `ruff check` (settings in
`pyproject.toml`, line length 120).

**Ground rules**
- Module responsibilities are listed in section 8. No network calls in tests. No real API calls anywhere unless an env
  key is set *and* the user runs it.
- Keys only from env vars (`ANTHROPIC_API_KEY`). Never log them, never return them in an API response, and never write
  them to disk.
- Never write the CSVs or derived patient-level data into the repo. Caches go to `config.CACHE_DIR` (`.cache/`,
  gitignored).
- **Wording:** no prediction language on screen or in text ("predicts", "forecast", "odds", "probability that", "best
  choice", "recommended drug", "AI predicts"). Results are S/R (never "S/I/R"). Say "unusual pattern", "typing advised"
  and "profile match, not typing". Never say "decoy" or "outbreak confirmed". Say "data gap, cause unknown", never "zero
  resistance".
- **Dates are sample dates.** Results usually arrive ~2 days later (`config.RESULT_LAG_DAYS`); say so wherever lead time
  is shown.
- **Percentages** come only from `render.fmt`: rounded half up (10 of 16 is "63%"), and a share above 0 or below 1 never
  prints as "0%" or "100%" ("<1%", ">99%").
- Reproducible: any Monte Carlo uses `stats.rng()` (fixed seed).

## 1. Data (`aei/data.py`)
`data.load() -> Dataset(isolates, cultures, patients)`, cached. `isolates` has one row per isolate with these columns:
- the original columns;
- `week` (0 = week of Mon 2 Oct 2023);
- `week_start`, `year`, `care_day_no` (admission day = 1; NaN for outpatients), `hosp_onset` (care day ≥3), `age_band`;
- drug columns AMP..CLI (`"S"`/`"R"`/NaN);
- `profile` (`"AMP:R MEC:S ..."` in `config.DRUGS` order), `n_R`;
- `first_year`, `first_30d`.

Helpers:
- `window(df, as_of, days)`: rows with `as_of - days < sample_date <= as_of`.
- `first_isolates(df, rule)`, where `rule` is `"readme_period"` (default; first per patient × organism × specimen inside
  the rows given) or `"30d"`.
- `week_end(week)` and `week_of(date)`.

Goldens: 24,571 isolates; 46,792 cultures; `first_year` 21,387; `first_30d` 23,769.

**Inpatient/outpatient** is `ward_type` (check the values in the data; PHC-N/PHC-S are primary care, ED is its own
unit). **Specimen groups:** `config.SPECIMEN_GROUPS`.

## 2. Time model
- **`as_of`** = the last data day, a Sunday (`YYYY-MM-DD`). The brief is dated **`as_of + 1 day`** (Monday). The API
  accepts `as_of` (Sunday) or `monday` (converted to `as_of = monday - 1 day`).
- **Strict as-of:** nothing sampled after `as_of` may influence any number, signal, alert or banner for that date.
  Alerts approved after `as_of + 1` are invisible at that date.
- **Windows** (`config.WINDOWS`) end on `as_of` inclusive: `4w` = 28 days, `4m` = 112, `12m` = 364. "Prior 52 weeks" =
  the 364 days ending the day before the window starts. On screen they are `config.WINDOW_LABELS`: "Last 4 weeks", "Last
  16 weeks", "Last 52 weeks" (never "months": 364 days is not 12 months).
- **The replay slider** moves `as_of` one week at a time over the range `data.week_end(55)`..`config.DATA_END` (52 weeks
  of history are needed before the first replay week). The UI passes one global `as_of` to every view, so the brief, My
  ward and the order screen always agree.
- **Counting rule** param `rule` ∈ {`readme_period`, `30d`}, default `readme_period`, applied to the rows inside each
  window.

## 3. The evidence object (`aei/signal.py`)
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
- **Status:** `new` if the signal's id was not active at `as_of - 7 days`; `ongoing` if it was; `resolved` signals are
  listed for one week after they stop firing.
- **Numbers only via slots.** A test asserts that every digit run in `text` comes from a slot value.

## 4. Coverage and My ward (`aei/coverage.py`, `aei/views.py`)
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
- **Coverage semantics:** an isolate is covered when its effective result (`phenotype_rules.effective`, section 7b) is
  S, and not covered when it is R; an untested pair is excluded from `tested`. A combo is covered if any member is
  covered.
- **Estimate rule:**
  - `ok`: observed (with its Jeffreys interval);
  - `low_n`: stabilised (a window WISCA estimate): each organism's window share pooled with k = `POOLING_K`
    pseudo-isolates toward the hospital-wide as-of rate for that organism and specimen group;
  - `not_enough_data`: no percentage (`estimate.pct` = null).

  The **observed x of n is always present**, so "74% stabilised" never sits unexplained next to "11 of 24".
- `FOX` is never shown as a therapy option (`HIDDEN_AS_OPTION`). Urine-only drugs (`URINE_ONLY`) are shown only for
  urine.
- **Ineligible drugs** (tested on fewer than 90%) are hidden from the table and listed under `not_shown` with a reason,
  e.g. "Ciprofloxacin not shown: untested on S. aureus (most of this ward's isolates)".

**Goldens** (product default, README counting rule):
- ICU blood+wound, as-of 2026-03-29, 4w, k=20 stabilised, n = 24:
  - MEM 72 [58–83], TZP 72 [59–83], VAN 78 [61–90] (the stabilised Beta has a Jeffreys half on each side, so no
    organism's share collapses to a point). An earlier analysis printed MEM 74 [61–85]; it counted ampicillin-S E.
    faecalis as covered by meropenem, which has no enterococcal EUCAST breakpoint;
  - observed MEM 11/24, TZP 11/24, VAN 20/24; 12m MEM 149/184.
- URO urine, as-of 2025-06-29, 4w (state `ok`, so observed), n = 69:
  - CRO 42/67 = 63 [51–74], NIT 63/69 = 91 [83–96]; CIP not shown (untested on 16% of isolates);
  - with the 30d rule: CRO 40/65, CIP 35/60, NIT 61/67, n = 67.

### 4.2 My ward view
`views.my_ward(ds, as_of, ward=None, specimen_group="blood_wound", organism=None, sex=None, age_band=None, setting=None,
windows=("4w","12m"), rule="readme_period") -> dict`
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
- `views.filters_catalog(ds)` lists the wards (code + label), specimen groups, organisms, sexes, age bands and settings.
- `views.trend(ds, ward, specimen_group, drug, as_of, weeks=52, window="4w", organism=None, rule=...)` gives a weekly
  series of the rolling-window cell (observed + estimate) for sparklines. It must take ≤1 s.
- **Performance:** `my_ward` ≤ 1.5 s cold on a laptop.
- `aei/aggregates.py` may precompute weekly counts to the cache to meet this.

## 5. Signals and the Monday brief (`aei/detectors/*`, `aei/brief.py`)
Templates: the base ids in `aei/templates.py`, the outbreak ids in `aei/templates_outbreak.py` and the trend ids in
`aei/templates_trends.py`, merged into one table. The brief runs the detectors only through the registry
(`aei/detectors/__init__.py`); a detector that fails raises, so a brief is never quietly missing one.
### 5.1 Detectors
Each detector is `detect(ds, as_of, rule="readme_period") -> list[signal]` and is strictly as-of; the detectors with a
window length also take `window`.

| Module | What it finds | Section / priority |
|---|---|---|
| `phenotype.py` | Patients sharing one antibiogram on one ward (26-week learning, rarity gate, panel-aware). Slots include n_patients, n_share, pattern, first_date and the expected-per-year range | unusual_patterns, P1 |
| `thl.py` | THL rule cards: any CPE; VRE; ESBL / MRSA same-ward clusters | unusual_patterns, P1 for CPE/VRE |
| `stepup.py` | Count step-up Bayesian test. It is supporting evidence attached to a cluster or a P3 item, never a P1 on its own | unusual_patterns, P3 |
| `outlier.py` | Ward outlier count vs other wards | changed, P3 |
| `resistance_change.py` | Organism × drug resistance on a ward, last 4 weeks vs the prior 52 weeks, via `stats.change_test`, under `rule` | changed, P2 |
| `policy.py` | `config.POLICY_LINES`: rolling 52-week rate under the line's counting rule; fires while ≥ threshold. Exposes `policy_states(ds, as_of) -> list[dict]` with rate, x, n, interval, the prior-year rate, `crossed_on` (first week-end ≥ threshold in the current run) and the threshold. A line names its own drug only, never another one | policy, P2 |
| `seen_before.py` | For each active cluster: earlier patients with the same profile, same ward vs elsewhere, with the profile's background share. Shows "not seen on ICU before" | seen_before, info |
| `explanations.py` | Not a detector: the competing explanations H1-H6 a cluster card carries in `evidence.competing_explanations`. Each hypothesis: `{id, label, rating, rating_label, evidence, template_id, slots}`; `rating` is a code (strong, moderate, weak, plausible, possible, unlikely, check, "contributes (index imported?)"), `label`, `rating_label` and `evidence` are text in the requested language; counts are x of n, never a percentage | - |
| `expert_rules.py` | `config.EXPERT_RULES` hits in the window | data_quality, P3 |
| `completeness.py` | Silent units, meaning no cultures this week vs expected | data_quality, P2 |

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
  "footer": "Each item opens its case file with the counts and the filter. Texts are filled in from computed numbers only." }
```
- `brief.signals_for(ds, as_of, ward=None) -> list[signal]` returns the active signals touching a unit (for banners and
  the map).
- **Performance:** a brief takes ≤ 3 s cold. If detectors are slow, precompute per-week signals into
  `.cache/signals/{as_of}.json` via `brief.precompute(ds, weeks)`.

**Goldens (signals):**
- **ICU MRSA 2026** (pattern `FOX:R VAN:S CLI:R`; first sample 3 Mar 2026). Patients by as-of Sunday:
  - 2026-03-08: 3 patients, 3 share the top pattern;
  - 03-15: 6;
  - 03-22: 9;
  - 03-29: 13 (12 share).
- **URO ESBL E. coli 2025:** fires by 2025-06-04 with 4 identical patients; 6 patients since 30 May by 2025-06-08.
- **MED-B ESBL look-alike 2024:** heterogeneous (3 antibiograms), ranked lower, and never called a decoy. Its episode
  (19–21 Sep 2024) falls before the replay range, so tests cover it; the demo cannot show it.
- **Trimethoprim, primary-care women, README rule, rolling 52 weeks:**
  - peak 20.4% (160/786) at the week ending 2026-06-21;
  - ≥ 20% at the weeks ending 06-21, 06-28, 07-12 and 07-19;
  - at 2026-09-27: 18.3% (144/789).
- **Seen before, ICU MRSA profile:**
  - before the cluster: 0 patients on ICU and 11 elsewhere (ED 4, SURG 4, MED-A 1, PHC-S 1, PHC-N 1);
  - back on ICU 2026-09-12;
  - the profile is 22.7% of 110 MRSA patients.
- **Phenotype consistency checks** (`config.EXPERT_RULES`, labelled "phenotype consistency checks (EUCAST expert rules +
  local rules)"; all isolates):
  - 0 of 517 ESBL-flagged isolates are reported S to CXM or CRO (local reporting rule);
  - 0 of 111 MRSA are FOX-S;
  - 139 rows are CRO R with AMP S or CXM S (E. coli, K. pneumoniae, K. oxytoca, P. mirabilis);
  - 276 rows are TZP R with AMP S (E. coli, P. mirabilis; EUCAST Expert Rules v3.3 rule 1).
- **Data gap:** PHC-S sent no cultures 8–14 Dec 2025 (~51 expected).
- **A VRE card on GER** by the 14 Sep 2026 brief.

## 6. Narrator and validator (`aei/narrator/*`, `aei/validator.py`)
- `narrator.base.Narrator` (Protocol): `narrate(template_id: str, slots: dict, *, audience="infection_control",
  language="en") -> Narration`.
- `Narration` is a dataclass: `text` (final, numbers rendered by code), `skeleton` (the model's text with `{slot}`
  placeholders), `provider`, `validated`, `fallback_reason`.
- **Providers:**
  - `TemplateNarrator` (default; deterministic; uses `render_id`);
  - `AnthropicNarrator` (env `ANTHROPIC_API_KEY`; model env `AEI_MODEL`, default `claude-haiku-5-5`; backend env
    `AEI_LLM_BACKEND` ∈ anthropic|bedrock|vertex for the EU route, with lazy client construction).

    Constraints from the verified API facts:
    - **no** `temperature`/`top_p`/`top_k` (a 400 on 5.5 models);
    - **no** forced `tool_choice`;
    - don't pass `thinking`;
    - keep a stable system prompt;
    - anything other than `stop_reason == "end_turn"` falls back to the template.
  - `CachedNarrator(inner, path)`: record/replay JSON keyed by the sha256 of (provider, model, prompt_version,
    template_id, slots, audience, language). Env `AEI_NARRATOR` ∈ template|anthropic|replay picks one;
    `narrator.get_narrator()` is the factory.
- **The model writes skeletons:** prose with `{slot}` placeholders, and never digits. The flow is: validator on the
  skeleton → render → `validate_rendered`. Any failure falls back to the template with `fallback_reason`.
- `validator.validate_skeleton(text, allowed_slots) -> ValidationResult(ok, errors: list[str])` rejects:
  - digits (any `\d`);
  - number words in en/fi/sv (one..twenty, dozen, hundred, thousand, half, twice, double, triple, percent; yksi,
    kaksi..., sata, puolet; en/ett, två..., hundra, hälften);
  - computed comparisons ("doubled", "times higher", "x-fold", "percentage points", "increase of", "rose by", "fell
    by");
  - prediction terms (`predict`, `forecast`, `odds`, `likely to`, `probability`, `best choice`, `recommended drug`,
    `will rise`);
  - restricted terms (`decoy`, `outbreak confirmed`, `S/I/R`, `zero resistance`);
  - dosing (`mg`, `g/day`, `dose`, `dosing`, `twice daily`, `x daily`, `per kg`);
  - unknown slot names;
  - patient identifiers (`P-\d` cannot appear anyway, since digits are banned).
- `validator.validate_rendered(text, slots) -> ValidationResult`: every number in the text must equal a formatted slot
  value.
## 7. API, alerts, order check (`aei/api.py`, `aei/store.py`, `aei/cds.py`, `aei/cds_hooks.py`, `aei/precompute.py`)
FastAPI app `aei.api:app`; run with `uvicorn aei.api:app --host 127.0.0.1 --port 8765`. Bind to localhost by default.
The app serves `web/` statically at `/`.

| Method & path | Returns |
|---|---|
| `GET /api/meta` | app_name, synthetic, data_start/end, replay range (first/last as_of), demo_mondays, `tour_start_as_of`, wards, roles, `indications` [{key, label, specimen}], `cds_hooks` {discovery, note: simulated, no EHR connected}, narrator provider name |
| `GET /api/filters` | `views.filters_catalog` |
| `GET /api/brief?as_of=&window=4w&rule=` | `brief.build_brief`, with each item enriched by `alert` (approved alert linked to it, if any) and `heads_up` state, plus `policy_states` (every policy line's state, crossed or not) |
| `GET /api/my-ward?as_of=&ward=&specimen=&organism=&sex=&age_band=&setting=&rule=` | `views.my_ward` + `banners` (active approved alerts and policy states touching that unit) + `signals` (`brief.signals_for`) |
| `GET /api/trend?...` | `views.trend` |
| `GET /api/replay/weeks` | `[{as_of, monday, n_p1, n_signals}]` for slider tick marks (precomputed) |
| `GET /api/signals/{id}?as_of=` | case file: the signal, a line list (synthetic isolate id, date, ward, care day, profile; no names), an epi curve by day, seen-before matches, step-up evidence, and alerts |
| `POST /api/alerts` | approve an alert from a signal: `{signal_id, as_of, wards[], drugs[], indications[], message, approved_by_role, expires_on}`; `indications` empty = every indication; `expires_on` defaults to monday + `ALERT_DEFAULT_EXPIRY_DAYS`. The alert keeps the signal's `profile` (flagged antibiogram), `marker` and `resistant_to` |
| `GET /api/alerts?as_of=&include_expired=` | alerts active at as_of+1; with `include_expired=1`, every alert approved by then. Each row has `expired` and `revoked_on` as known that Monday (case timeline "Approved 9 Mar · expired 23 Mar") |
| `POST /api/alerts/{id}/revoke` | revoke an alert (API only; no screen uses it) |
| `POST /api/heads-up` | draft a heads-up from a signal: text by the narrator for audience "ed" from `templates.ed_heads_up` (slots only; drug names, never panel codes), status `draft` |
| `POST /api/heads-up/{id}/approve` | marks it `approved`. **Nothing is ever sent**; the response says `"delivery": "not sent (demo)"` |
| `GET /api/order-feedback/summary?as_of=` | infection-control view of order-card outcomes (counts by card/outcome, no user ids) |
| `GET /cds-services?lang=` | CDS Hooks discovery: `{services: [{hook: "order-select", id: "strainwatch-order-select", title, description, prefetch: {}}, {hook: "order-sign", id: "strainwatch-order-sign", ...}]}` |
| `POST /cds-services/{id}` | CDS Hooks request (see below), returning `{cards: [...]}` |
| `POST /cds-services/{id}/feedback` | CDS Hooks feedback, logged to the store |

**Order check (`cds_hooks.order_check(ds, as_of, unit, drug, indication, alerts, policy_states) -> list[card]`; pure,
deterministic; the CDS Hooks adapter over `cds.order_context`):**

*Request.* The request is CDS Hooks 2.0 shaped: `{hookInstance, hook, context: {userId, patientId, encounterId,
draftOrders: FHIR Bundle with a MedicationRequest}}`.
- The drug comes from the MedicationRequest `medicationCodeableConcept.coding` ATC code, mapped through `config.ATC`.
- The demo carries unit and indication in `context.extension`: `{"strainwatch.unit": "ED", "strainwatch.indication":
  "urinary", "strainwatch.as_of": "2026-06-21"}`.

*Which cards are allowed.* The same rules as section 7b: a card only for an `info` or `warning` order context. Sources
are deterministic only (approved alerts, the patient's own acquired R, policy and local lines); **never** narrator
output, and never a patient-specific estimate. order-select returns at most info; order-sign may warn.

*Card content.* `summary` (≤140 characters, e.g. "Possible ESBL E. coli cluster on URO: the flagged antibiogram is R to
ceftriaxone"); `detail` (markdown): the patient's previous results first, then "What is happening" (headline + the alert
message with who flagged it and when, or the line and when it was crossed), "This drug in this population" (R of n, 4
weeks vs 52 weeks, intervals), "Consider whether this drug still fits. The decision is yours.", the lag note and the
small print "Observed unit-level information about past results. The doctor decides."; `source: {label: APP_NAME + " ·
infection control"}`; `overrideReasons` (keep + `config.KEEP_REASONS`); `links: [{label: "All drugs on My ward", url:
<My ward for unit/specimen/organism>, type: "absolute"}]`; `extension: {"strainwatch.rule", "strainwatch.source",
"strainwatch.evidence"}`. **No `suggestions` and no `selectionBehavior`: the card never names another drug** (the doctor
makes an informed choice).

*Feedback.* Keep maps to CDS Hooks `outcome: overridden` + `overrideReason`. The feedback is stored with card uuid,
source id, outcome and timestamp; no user or patient id is stored.

**Store (`store.py`):** SQLite in `.cache/state.sqlite`, with tables alerts, heads_up, feedback and audit (append-only).
`store.reset()` clears it for tests and the demo. `store.seed_demo()` adds `config.DEMO_ALERT_SEEDS` (section 7b),
marked `seed: true`. Alert rows carry `wards, drugs, indications, resistant_to, profile, marker, organism, specimen,
message, approved_on, expires_on, revoked_on`. The trimethoprim card needs **no** seed: it comes from the policy line.

**Precompute (`precompute.py`):** the CLI `python -m aei.precompute [--weeks all|demo]` warms the caches (signals per
week, replay weeks, the demo-Monday briefs) and prints timings.

**Security:**
- loopback bind;
- CORS off;
- no keys in responses;
- `POST` endpoints validate input with pydantic models;
- every text field rendered by the UI is plain text (the UI uses textContent).

## 7b. Doctor's view: order context (the layer never recommends a drug)
A mocked order form: a synthetic patient (`patient_id`; sex, age and home area from the data), the unit, the indication
(`config.INDICATIONS`: uti / bloodstream / wound, each mapped to a specimen) and the drug (`GET
/api/order-drugs?indication=`: the `config.ORDER_DRUGS` with a reported result on that specimen). The layer updates live
as the drug changes (`aei/cds.py`, pure and deterministic).

**Principle:** the layer flags the drug the doctor entered and **never names another one**: no local-guide alternatives,
no "Change to X", no suggestions. It says what is going on, this drug's numbers in this population, and one neutral
sentence. The doctor keeps the order (with a reason), edits it, or opens My ward to look at every drug.

**The function:** `cds.order_context(ds, as_of, patient_id, unit, indication, drug, stage="select"|"sign", alerts,
policy_states) -> dict`
```
{ "state": "quiet" | "no_data" | "notice" | "info" | "warning",  "stage", "interruptive": bool,
  "chip": "No active alerts · URO · data to 21 Jun",       # one line in every state; for info/warning the short summary
  "headline": "Possible ESBL E. coli cluster on Urology. The flagged antibiogram is R to ceftriaxone.",  # info/warning, else null
  "ask": "Consider whether this drug still fits. The decision is yours.",   # info/warning, else null; at select + " It will ask again when the order is signed."
  "rule": "<plain sentence of which rule fired>",
  "previous_results": [ {"date", "unit", "specimen", "organism", "flags": ["ESBL"], "drug_result": "R", "reason", "reported_result", "reason_text"} ],  # shown FIRST; reported_result is the laboratory's own S/R when a species rule counts it differently (C. freundii cefuroxime S -> R), else null
  "notes": ["Trimethoprim: EUCAST lists P. aeruginosa as intrinsically resistant (this patient's wound isolate of 31 Dec 2025)."],
  "lines": [ {"key": "happening", "text", "source": {"kind": "alert"|"own_history"|"policy"|"local_line", "id", "flagged_by", "flagged_on"}},  # info/warning
             {"key": "your_drug", "text", "numbers": {r, n, pct, ci, state, window, r12, n12, pct12, ci12, state12} | null, "not_shown"} ],  # not for a notice; pct/ci (pct12/ci12) are null when state (state12) is not_enough_data
  "actions": {"keep": {"label": "Keep ceftriaxone", "reasons": config.KEEP_REASONS in the request language}, "edit": {"label": "Edit the order"},
              "details": {"label": "All drugs on My ward", "link": "/#/ward?ward=URO&specimen=urine&organism=Escherichia%20coli&as_of=..."}},
  "source": {kind, id, signal_id} | null, "card_key", "evidence": {population, counts, not_shown, reasons, method}, "note", "small_print" }
```

**The rules (deterministic; never model output; never a patient-level probability):**
- **Population:** the unit's own isolates for the indication's specimen; for `COMMUNITY_UNITS` (ED, PHC-N, PHC-S) those
  units' isolates from patients in the patient's home area; uti also matches sex; with a `reference_organism` (uti: E.
  coli) R of n of that organism, else not-covered of tested over the organism mix. Windows 4w and 12m (52 weeks). Small
  n: `stats.n_state`. Effective results come from `phenotype_rules.effective` (shared with My ward): `no_breakpoint`,
  `intrinsic`, `inferred_mrsa`, `reported`, `inferred_mssa`, `inferred_ampicillin`, `local_esbl_rule`, `untested` (first
  match wins; the only reported results overruled are 517 C. freundii cefuroxime S). No number for a urine-only drug
  outside urine, a drug the reference organism is intrinsically R to, or a drug with a result on fewer than 90% of the
  population's isolates.
- **Warning** (interruptive) **only at `stage="sign"`**, and only if (a) an approved alert active at `as_of + 1` lists
  this unit (`wards`), this drug (`drugs`) and this indication (`indications`; empty = all); or (b) this patient's own
  isolate in the 52 weeks to `as_of` has an acquired R to this drug (reason `reported`, `inferred_mrsa` or
  `local_esbl_rule`). An `intrinsic` or `no_breakpoint` R is a property of the species: a passive note, never a warning.
  At `stage="select"` the same case is `info`, and `ask` adds "It will ask again when the order is signed."
- **Info** (passive): a policy line at or above its threshold whose population and `order_units` match the order; or,
  where infection control set a line for this indication and drug (`config.EMPIRICAL_LINES`: only urinary trimethoprim,
  20%), the population's 52-week resistance on 30 or more isolates is at or above it or within `INFO_MARGIN` (3 points)
  below. No default line for any other drug.
- **Notice:** an active alert on the unit that does not apply to this drug or indication: a one-line chip ("Possible
  MRSA cluster on ICU. The alert does not apply to vancomycin."), no numbers, no card.
- **no_data:** no number for this drug in this population (fewer than 10 isolates with a result in 52 weeks, or a reason
  above), and nothing else applies. It looks different from quiet.
- **Quiet** otherwise. Across the 5 scenario patients x 3 indications x 13 order drugs at select: 51 quiet, 49 no data,
  50 notices, 45 info, 0 warnings (`tests/test_cds.py`).
- **Headline from data only:** an alert's title comes from its own fields ("Possible {marker} {organism} cluster" when
  it carries a shared antibiogram, "{marker} {organism} alert" otherwise), then "The flagged antibiogram is R to X"
  (with how it was read when not reported, e.g. "inferred: MRSA, cefoxitin screen positive") or "The alert applies to
  X". "Applies to" is an alert's scope; "covered" is only drug against organism.
- **Never** "AI recommends", never a block, never a named alternative and never a patient-level probability. `cds.py`
  and `cds_hooks.py` never import the narrator. An alert's message names no drug either: it is shown on
  the order screen.

**Logging and feedback:**
- `POST /api/order-feedback {session, card_key, source_id, state, outcome: shown|keep|edit|change|details, reason?,
  changed_to?}`; `reason` is one of the listed keep reasons, in English or Finnish (`edit`: back to the order; `change`:
  the doctor then picked another drug). Every displayed info/warning logs a `shown` event once per order draft.
- `GET /api/order-feedback/summary?as_of=` returns per source shown, edited, changed, kept, details and keep reasons
  ("shown 14 times, changed 6"). This is an infection-control view; no user or patient id is stored.

**Endpoints:**
- `POST /api/order-context` (body: the inputs above) → `order_context`.
- `GET /api/order-drugs?indication=` → `[{drug, name, atc, aware}]`.
- `GET /api/patients/{id}/history?as_of=` gives the previous results (12 months).
- `GET /api/demo/scenarios` gives `config.DEMO_SCENARIOS`, each with the computed state at sign, for the scenario
  picker.
- **CDS Hooks endpoints stay the standards-based integration route** for an EHR that supports CDS Hooks 2.0:
  order-select returns at most info cards, order-sign may warn, under the same rules. Simulated in this prototype; no
  EHR is connected.

**Demo scenarios:** `config.DEMO_SCENARIOS`, expected states quiet / info / warning; `tests/test_cds.py` asserts all
five. The uro-esbl patient is a woman (P001948), like 10 of the 11 clone patients.

**Seeds:** `store.seed_demo()` inserts `config.DEMO_ALERT_SEEDS`. Each carries `profile` (the flagged antibiogram),
`marker`, `resistant_to` (its reported R plus what the marker implies) and `drugs` = exactly those, and `indications`.
URO ESBL, approved 9 Jun 2025: AMP, CXM, CRO, CIP, TMP; uti and bloodstream (urosepsis). ICU MRSA, approved 9 Mar 2026:
every beta-lactam plus CLI; bloodstream and wound (the cluster's isolates). Seeds are visible to every session; their
messages are checked against the raw data (`tests/test_against_source.py`).

## 8. Module map
| Module | Responsibility |
|---|---|
| `aei/config.py` | The one place for the product name, windows, thresholds, drug lists, local lines, demo scenarios and env settings |
| `aei/data.py` | Loads the CSVs into the isolate table (section 1); date windows and first-isolate rules |
| `aei/stats.py` | Jeffreys intervals, small-n states, the change test, pooled estimates, the fixed-seed generator |
| `aei/phenotype_rules.py` | Effective S/R for one isolate and drug, and why (section 7b); shared by My ward and the order check |
| `aei/coverage.py`, `aei/aggregates.py` | One coverage cell (section 4.1); in-memory row arrays that keep cells fast |
| `aei/views.py` | My ward, the filter catalogue and trend series (section 4.2) |
| `aei/signal.py` | The evidence object every detector returns (section 3) |
| `aei/detectors/` | The registry (`__init__.py`) and one module per detector (section 5.1) |
| `aei/brief.py` | The Monday brief: sections, status, unit map, counts, per-week cache, case-file rows (section 5.2) |
| `aei/cds.py`, `aei/cds_hooks.py` | The order context for one order (section 7b) and its CDS Hooks 2.0 cards (section 7) |
| `aei/templates.py`, `aei/templates_outbreak.py`, `aei/templates_trends.py`, `aei/templates_ui.py` | Every English text as a template; numbers only through slots |
| `aei/templates_fi.py`, `aei/i18n.py` | The Finnish twin of every template, the Finnish glossary and `lang` handling |
| `aei/render.py` | Number and date formats; renders a template with its slots |
| `aei/narrator/`, `aei/validator.py` | Optional model wording (template, replay, Claude) with its spend and rate guard; the checks on its output (section 6) |
| `aei/store.py` | SQLite demo state per session: alerts, heads-ups, feedback, audit log (sections 7, 9) |
| `aei/api.py`, `aei/precompute.py` | The FastAPI app and its guards (sections 7, 7b, 9); the cache-warming CLI |
| `web/` | The static UI: HTML, CSS and ES modules, no build step |
| `tests/` | Offline tests per module, plus `tests/test_against_source.py` (headline numbers re-derived from the raw CSVs) |

## 9. Public deployment (visitors use it on their own devices)
- **Host:** one container behind a reverse proxy (see `DEPLOY.md`), 1 GB memory, no ports published to the internet.
- **No login.** The role switch "Infection control | Ward doctor" sits at the top. A guided start: replay at
  `config.TOUR_START_AS_OF` (just before the ICU cluster), plus "Start tour" (4–5 steps). There's a visible "Prototype ·
  synthetic data" label on every screen.
- **Headers:** `X-Robots-Tag: noindex, nofollow` on every response, `<meta name="robots" content="noindex">`, and
  `/robots.txt` disallowing everything. No analytics or trackers.
- **Logging:** request bodies and query strings are never logged; uvicorn runs with `--no-access-log`, and the app logs
  only errors without bodies.
- **Sessions:** the browser sends a random `X-Demo-Session` id (in sessionStorage). Approvals, heads-ups and order
  feedback are stored per session, plus the seeds visible to all, so visitors don't see each other's clicks. Each
  session is capped at `MAX_WRITES_PER_SESSION`. The state DB is at `config.STATE_DB` (ephemeral `/tmp` in the container
  is fine).
- **Rate limits:** per IP (from `X-Forwarded-For`, trusting the proxy), with `RATE_LIMIT_PER_MIN` for all API calls and
  `LLM_RATE_LIMIT_PER_MIN`/`_PER_DAY` for live model calls. Exceeding a limit returns a 429 with a friendly message;
  live narration falls back to cached text.
- **LLM spend cap:** `DAILY_SPEND_USD` (default $20/day). The cost is estimated from response `usage` × a price table
  (an env-overridable constant), and the counter is persisted in the state DB per UTC day. At the cap, narration uses
  replay, then the template, with `fallback_reason="spend_cap"`.
- **The default in public mode** (`AEI_PUBLIC=1`) is `AEI_NARRATOR=replay`: precomputed narration for every demo-week
  item, with the template on a miss. The demo works with no key at all.
- **Health:** `GET /api/health` → `{ok, app_name, data_loaded, narrator, key_set: bool, spend_today_usd, cap_usd}`. It
  never shows a key.
- **Responsive:** desktop first, but it works at 375 px (phone) and 768 px (tablet).
- **Polish:** loading, empty and error states; keyboard-accessible; one set of design tokens; no placeholder text
  reachable by a visitor.
- **Data:** the dataset README states no licence; it says only that all data is synthetic. The app shows aggregates and
  synthetic line lists but never offers the raw CSVs for download.
