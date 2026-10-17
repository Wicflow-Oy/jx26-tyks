# Handoff: the Tyks x Mylab build, from the team lead's machine to the operator (Sat 17 Oct, ~20:30)

You own this build from now on. Nobody else writes to this repo, so there are no merge fights. The submission deadline is **Sun 18 Oct 11:00**. Aim to have it working, deployed and frozen by **~09:30**.

## 1. Set up (10 min)
```bash
git clone https://github.com/Wicflow-Oy/jx26-tyks.git
git clone https://github.com/Wicflow-Oy/jx26-tyks-context.git   # data + research, private
cd jx26-tyks
python3.12 -m venv .venv                          # Python 3.12; on Windows use .venv\Scripts\ below
.venv/bin/pip install -r requirements.txt pytest ruff
.venv/bin/python -m pytest -q                     # 8 tests on main
```
- The dataset is found automatically when `jx26-tyks-context` sits next to this repo (or set `AEI_DATA_DIR`).
- **API key:** the team lead creates one for this app. Put it in `.env.local` as `ANTHROPIC_API_KEY=…` (gitignored). The app also works with no key: in replay or template narration mode it never calls the model.

## 2. What exists
| Where | State |
|---|---|
| `main` | Scaffold and **the spec**: `CONTRACTS.md` (read it fully; it's the real build plan). Also config, data loader, stats, the evidence object, the Dockerfile, `deploy/` and `DEPLOY.md` (your server runbook). 8 tests pass; lint is clean. |
| `wip/unfinished-modules` | Workstreams A, B1, B2 and C plus most of D, written in parallel and cut off by a usage limit: coverage and views, all detectors, the Monday brief, the narrator and number validator, the Jev adapter, the store and the CDS order card. **110 tests pass** (checked from a fresh clone merged with main). After the merge, ruff reports 24 issues, all auto-fixable. Not yet wired together. Workstreams A and B2 finished; B1, C and D were cut off mid-task. **Check these:** `aei/store.py` was mid-rewrite for per-session storage (CONTRACTS §10); `aei/jev.py` is a first draft; `tests/test_outbreak_detectors.py` (B1's tests) is missing. |
| Missing | `aei/api.py` (FastAPI, endpoints in CONTRACTS §7 and §7b), `aei/precompute.py`, and the **whole UI** (`web/`). There's no design yet; see §5. |

**First move:**
```bash
git checkout -b integrate main
git merge wip/unfinished-modules
ruff check --fix .
pytest -q
```
Review the diff for anything that doesn't match the contracts, then merge into `main`.

## 3. The product (what we promised in the pre-submission)
It's a weekly antibiotic-resistance tool for one hospital's wards. Three views share one "as of" date and a replay slider.
1. **Ward doctor, "My ward" (P0).** It's the brief's literal ask: *"a doctor wants to see up-to-date information on the susceptibility profile of bacteria in their own ward… the previous four weeks as well as annual results… filter by dataset parameters."*
   - The last 4 weeks next to 12 months.
   - Filters: ward, specimen, organism, sex, age band and setting.
   - R of n with an interval, and "not enough data" when n is small.
2. **Infection control, the Monday brief (P0, the home screen for that role).** What changed this week:
   - possible clusters, with the shared-antibiogram evidence;
   - THL-rule alerts (CPE, VRE, ESBL);
   - trend and policy-line crossings (trimethoprim at 20%);
   - "seen before" matches;
   - expert-rule QC;
   - silent wards.
   Each item opens a case file. The team can approve an alert and draft a heads-up to the ER. Nothing is ever sent.
3. **The replay (P0).** "Continuously updated" shown live: step week by week and watch the ICU MRSA cluster appear in March 2026.
4. **The doctor's view at the moment of prescribing (P1, if time).**
   - A mocked order form, with a card that updates as the drug changes: quiet, no data, info, or a warning at sign.
   - Fired only by approved alerts, policy lines or the patient's own previous resistant result.
   - CDS Hooks endpoints are the integration story. The full rules are in CONTRACTS §7b, and the 5 demo scenarios are in `config.DEMO_SCENARIOS`.
5. **Jev second opinion (P2, optional).** Only if a TypeSafe key exists and it passes calibration. Never in the order card.

**Judging, 4 × 25%:**
- understanding of the challenge;
- suitability to the description and insight ("not a basic BI dashboard"; "continuously updated", "highly usable and versatile");
- usability;
- **detects deviations and anomalies**.

## 4. What the Tyks microbiologist told us (read `jx26-tyks-context/docs/partner-talk-digest.md`)
- **Two users:**
  - the ED doctor, who decides fast with old data;
  - infection control, which has time and spreads the word.
  The tool's leverage is through infection control.
- **Weekly is enough.**
- **Prediction is a "shady area":** show observed numbers with honest uncertainty, never "AI predicts".
- **His own example:** trimethoprim at 20% → switch to pivmecillinam. Our data crosses that line.
- **History matters:** he likes trends, maps (ward-level is fine), the EUCAST expert rules (ESBL implies cephalosporins R) and "seen before".
- He wants to write a small international paper on the ideas. Offer him the method.

**The wording rules are in CONTRACTS.md (top):**
- no prediction language;
- "possible cluster / typing advised";
- S/R only;
- sample dates, with results about 2 days later.

## 5. Design (do this first for the UI, keep it short)
No design round happened for Tyks.
- Make or choose one direction quickly: clinical, calm, readable at a glance, desktop first, and it must work at 375 px.
- It must look like a finished product, not a BI dashboard.
- Polish: loading, empty and error states; one set of design tokens; keyboard accessible; smooth but not showy motion.
- A "Prototype · synthetic data" label on every screen.
- No login: a role switch "Infection control | Ward doctor", plus "Start tour" (4–5 steps) starting at `TOUR_START_AS_OF`.
- Show the team lead a screenshot before building everything.

## 6. Rules
- `docs/ENGINEERING.md`:
  - **clean, organised, understandable, working**, not over-engineered;
  - a README a judge gets in 5 minutes;
  - **no AI attribution anywhere** (no Co-Authored-By Claude, no "Generated with Claude Code");
  - push only green commits.
- `docs/HOSTING.md` plus `DEPLOY.md`: you deploy on the UpCloud box.
  - It also runs other internal services, so treat it as production: run the read-only preflight first and touch only the `jx-tyks` project.
  - noindex; rate limits; a $20/day LLM cap; no request-body logging.
- **Synthetic data only.** Never commit the CSVs. The dataset has no stated licence, so keep the repo private.
- **Fair play:** say "our detector flags…". Never ask the judges to confirm the planted signals.

## 7. Open items
- **Name:** `config.APP_NAME` is "Strainwatch" (a placeholder). Decide with the team lead.
  - The Junction platform has our pre-submission draft as **"AEI: The Monday Brief"**. Update the name and description there when the product is real.
  - The pre-submission text is in `jx26-tyks-context/docs/presubmission-tyks-paste.txt`.
- **Hostname:** a placeholder until the name is set (see `docs/HOSTING.md`). the team lead adds the DNS record.
- **Doctor questions** (README): ask a GP or the Tyks microbiologist which 3 facts matter on the order card.
- **Video:** after the product works. the team lead coordinates.

## 8. Starter prompt for your Claude Code (paste as the first message, opened in the parent folder holding both repos)
```text
You are taking over the Tyks x Mylab hackathon build (JunctionX Turku 2026; deadline Sun 18 Oct 11:00, freeze ~09:30).
Two repos sit side by side: ./jx26-tyks (product code) and ./jx26-tyks-context (dataset + research, read-only).
Read, in order: jx26-tyks/docs/HANDOFF.md, jx26-tyks/CONTRACTS.md (the spec), jx26-tyks/docs/ENGINEERING.md,
jx26-tyks-context/docs/partner-talk-digest.md, and the "★" section at the top of jx26-tyks-context/docs/dossier-tyks-mylab.md.

Then:
1. Set up the venv, run the tests on main, merge the branch wip/unfinished-modules into a new branch "integrate",
   run ruff --fix and pytest, and report what fails or deviates from CONTRACTS.md.
2. Build aei/api.py and aei/precompute.py exactly to CONTRACTS.md §7, §7b and §10, with tests.
3. Propose ONE UI direction (clinical, calm, finished-product quality, desktop first, works at 375 px) as a single
   static mockup of the Monday brief and My ward. Wait for my OK, then build the UI in web/ against the API:
   My ward, the Monday brief with case files, the replay slider, the role switch and the tour. Then, if there's time,
   the doctor's order view.
4. Keep the code clean, small and understandable for a judge. No over-engineering. Offline tests only.
   No AI attribution in commits, README or code. Push only green commits to main.
Use parallel subagents for independent files (CONTRACTS.md §8 has the ownership split) and integrate centrally.
Ask me before anything that touches the server, creates accounts or spends money.
```
