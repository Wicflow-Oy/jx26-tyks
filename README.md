# Tyks x Mylab build (working name in `aei/config.py` → `APP_NAME`, placeholder "Strainwatch")

A weekly antimicrobial-resistance brief for hospital infection control, with three parts:
- a ward doctor's "My ward" view;
- anomaly detection on every screen;
- a prescribing-moment context card.

It runs on the synthetic Tyks dataset only.

- **Spec:** `CONTRACTS.md` (data, time model, the evidence object, every module and endpoint, the doctor's view, public deployment).
- **Deploy:** `deploy/README.md` (UpCloud, Helsinki; compose project `jx-tyks`). Nothing is deployed until the team lead confirms the box, DNS and SSH.
- **Status:** built in parallel workstreams on Sat 17 Oct. See "What works" below; it is updated at each integration.

## Run locally
```bash
.venv/Scripts/python.exe -m pytest -q
```
```bash
.venv/Scripts/python.exe -m uvicorn aei.api:app --host 127.0.0.1 --port 8765
```
The data is read from `AEI_DATA_DIR`, which defaults to `../../context/data/synthetic_microbiology_dataset`. Caches go to `.cache/` (gitignored). No key is needed; set `ANTHROPIC_API_KEY` only to record live narration.

## Data terms (open question)
- The dataset README states **no licence**; it only says that all data is synthetic.
- The CSVs and patient-level derivations are never committed, and the app never offers them for download. It shows aggregates and synthetic line lists.
- Whether the data may appear in a public repo, video or app is an **open organiser question**. Keep this repo private until it's answered.

## Open questions for a doctor (the team lead to check)
1. **Which 3 facts** matter most on the prescribing card? Today the card shows: what's happening (the alert or line), your drug on this unit (R of n, last 4 weeks vs 12 months) and the local-guide alternatives with their numbers.
2. **Should the patient's own previous results come first,** above the unit numbers? Today they do, when present.
3. **How many interruptions per shift are acceptable?** Today a warning appears only at "sign", and only for an approved alert covering this unit and drug, or the patient's own resistant isolate in the last 12 months.
4. **Wording:** does "possible cluster" or "outbreak" work better? Today the app says "possible cluster" or "unusual pattern", with "typing advised", and never "outbreak confirmed".
5. **Community units:** for ED and primary care, are the patient's home-area numbers the right comparison?
6. **The local guide table** in `config.LOCAL_GUIDE_EXAMPLE` and the empirical-use lines in `config.EMPIRICAL_LINES` are examples, labelled on screen "example, to be set by Tyks". Which lines does Tyks actually use?

## What works / mocked / cut
This section is filled in at the Phase 3 test pass: it will say what is verified on the build, what is mocked (the EHR order form, CDS Hooks host, heads-up delivery and Jev) and what was cut.
