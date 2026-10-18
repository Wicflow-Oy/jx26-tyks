"""The language layer (aei/i18n.py): every template has a Finnish twin with the same slots, every label the data and
the screens use has a Finnish entry, Finnish text carries only slot numbers and no English, and ?lang=fi works on the
brief, My ward, the case file, the order screen and the CDS cards. Offline; caches go to a temp dir."""

import re
from itertools import product

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aei import api, brief, cds, cds_hooks, i18n, store, validator, views
from aei import config as C
from aei.coverage import LOCAL_SETTING_LABEL
from aei.detectors import thl
from aei.detectors.policy import policy_states
from aei.phenotype_rules import REASON_TEXT
from aei.render import fmt, slots_in
from aei.templates import TEMPLATES

MONDAYS = C.DEMO_MONDAYS
ICU_CLUSTER = "phe-7972cb3f12"  # ICU MRSA 2026 (tests/test_api.py)
# English words that must never reach a Finnish screen (organism names stay Latin; codes such as ICU stay codes)
ENGLISH = {
    "the",
    "and",
    "of",
    "with",
    "since",
    "is",
    "to",
    "at",
    "for",
    "from",
    "than",
    "this",
    "not",
    "no",
    "all",
    "patient",
    "patients",
    "resistant",
    "susceptible",
    "week",
    "weeks",
    "last",
    "unit",
    "units",
    "cluster",
    "typing",
    "advised",
    "resolved",
    "flagged",
    "usually",
    "expected",
    "sample",
    "sampled",
    "alert",
    "drug",
    "isolate",
    "isolates",
    "line",
    "local",
    "above",
    "below",
    "earlier",
    "before",
    "cultures",
    "result",
    "results",
    "check",
    "infection",
    "control",
    "ward",
    "hospital",
    "women",
    "men",
    "urine",
    "urinary",
    "wound",
    "blood",
    "outpatient",
    "shown",
    "tested",
    "screen",
    "positive",
    "case",
    "contact",
    "precautions",
    "standard",
    "room",
    "strain",
    "guidance",
    "possible",
    "unusual",
    "pattern",
    "profile",
    "match",
    "gap",
    "cause",
    "unknown",
    "quiet",
    "signals",
    "other",
    "every",
    "small",
    "enough",
    "interval",
    "population",
    "decision",
    "consider",
    "keep",
    "edit",
    "details",
    "note",
    "intrinsically",
    "breakpoint",
    "inferred",
    "reported",
    "previous",
    "happening",
    "lab",
    *(name.lower() for name in C.DRUG_NAMES.values()),
    "pivmecillinam",
    "flucloxacillin",
}
FORBIDDEN = ("prediction", "restricted", "treatment", "dosing", "comparison")  # validator term lists


def forbidden(text: str, categories=FORBIDDEN) -> list[str]:
    """Validator term-list hits (all languages' lists); "%" is fine in rendered text."""
    return [e for e in validator._term_errors(text, categories) if not e.startswith("number_symbol")]


def english_words(text: str) -> set[str]:
    return set(re.findall(r"[a-zåäö]+", text.lower())) & ENGLISH


def digit_runs(text: str) -> list[str]:
    return sorted(re.findall(r"\d+", text))


def prose(template: str) -> str:
    return validator.SLOT.sub(" ∎ ", template)


def stray_digits(template_id: str, slots: dict, lang: str, field: str, text: str) -> list[str]:
    """Digits in a rendered text that do not come from one of its slots (formatted as the template says)."""
    template = (i18n.FI if lang == "fi" else TEMPLATES)[template_id][field]
    formats = TEMPLATES[template_id].get("formats") or {}
    pieces = {
        fmt(i18n.label(slots[name], lang), kind or formats.get(name, "text"), lang) for name, kind in slots_in(template)
    }
    for piece in sorted(pieces, key=len, reverse=True):
        text = text.replace(piece, " ")
    return re.findall(r"\d", text)


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "CACHE_DIR", tmp_path_factory.mktemp("cache"))
        brief.clear_memory_cache()
        yield
    brief.clear_memory_cache()


@pytest.fixture(scope="module")
def briefs(ds, cache):
    as_of = {m: str((pd.Timestamp(m) - pd.Timedelta(days=1)).date()) for m in MONDAYS}
    return {m: {lang: brief.build_brief(ds, as_of[m], lang=lang) for lang in i18n.LANGS} for m in MONDAYS}


@pytest.fixture
def seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE_DB", tmp_path / "state.sqlite")
    store.reset()
    store.seed_demo()
    return store.alerts("visitor-dddd-0004")


# --------------------------------------------------------------------------- the dictionaries
def test_every_template_has_a_finnish_template_with_the_same_slots_and_formats():
    assert set(i18n.FI) == set(TEMPLATES)
    for tid, en in TEMPLATES.items():
        fi = i18n.FI[tid]
        assert set(fi) == {f for f in ("text", "title") if f in en}, tid
        for field in fi:
            assert set(slots_in(fi[field])) == set(slots_in(en[field])), (tid, field)


def test_finnish_templates_add_no_number_and_no_forbidden_term():
    """Literal digits only where the English template has the same ones; no number words, prediction, restricted,
    prescribing or dosing terms (validator lists, all languages)."""
    for tid, en in TEMPLATES.items():
        for field, text in i18n.FI[tid].items():
            assert digit_runs(prose(text)) == digit_runs(prose(en[field])), (tid, field)
            assert forbidden(prose(text), ("number_word", *FORBIDDEN)) == [], (tid, field)
            assert ":short_date}." not in text, (tid, field)  # "5.7." ends the sentence itself


def test_glossary_keeps_the_numbers_and_adds_no_forbidden_term():
    for en, fi in i18n.LABELS.items():
        assert digit_runs(fi) == digit_runs(en), en
        assert forbidden(fi) == [], en
        assert "—" not in fi


def test_the_finnish_wording_uses_the_agreed_clinical_terms():
    fi = " ".join(t for template in i18n.FI.values() for t in template.values()) + " ".join(i18n.LABELS.values())
    for term in (
        "mahdollinen rypäs",
        "Tyypitystä suositellaan",
        "Profiilivastaavuus, ei tyypitys",
        "Aukko datassa, syy tuntematon",
        "Kosketusvarotoimet",
        "Tavanomaiset varotoimet",
        "epidemiaselvitys",
        "ESBL-tuottaja",
        "kefoksitiiniseulonta",
        "näytteenottopäivä",
        "Ensimmäinen",
        "herkäksi (S)",
        "resistentti",
        "osasto",
    ):
        assert term in fi, term
    for avoided in ("S/I/R", "ennust", "todennäköi", "epidemia ", "vahvistettu"):
        assert avoided not in fi, avoided


def test_every_label_the_screens_use_has_a_finnish_entry():
    labels = [
        *C.WARD_LABELS.values(),
        *C.DRUG_NAMES.values(),
        *(n for _, n, _ in C.ORDER_DRUGS),
        *(i["label"] for i in C.INDICATIONS.values()),
        *(i["label"].lower() for i in C.INDICATIONS.values()),
        *C.ROLES.values(),
        *C.WINDOW_LABELS.values(),
        *cds.WINDOW_TEXT.values(),
        *C.KEEP_REASONS,
        *views.SETTINGS.values(),
        *views.SEXES.values(),
        *views.SPECIMEN_LABELS.values(),
        *views.RULE_LABELS.values(),
        *cds.COUNTING_RULES.values(),
        *cds.SPECIMEN_WORDS.values(),
        *REASON_TEXT.values(),
        *(r["text"] for r in C.EXPERT_RULES),
        *(s["message"] for s in C.DEMO_ALERT_SEEDS),
        *(line[k] for line in C.POLICY_LINES for k in ("label", "message")),
        *C.ATC_NOTES.values(),
        *(title for _, title in brief.SECTIONS),
        brief.FOOTER,
        LOCAL_SETTING_LABEL,
        "Centre",
        "East",
        "North",
        "South",
        "West",
        cds.ASK,
        cds.SIGN_NOTE,
        cds.SMALL_PRINT,
        cds.LAG_NOTE,
        cds.DETAILS_LABEL,
        cds.EDIT_LABEL,
        cds.METHOD,
        api.CDS_HOOKS_NOTE,
        api.SYNTHETIC_NOTE,
        *(
            thl.action_text(m, o, out)
            for m, o, out in product(
                ("mrsa", "esbl", "cpe", "vre"),
                ("Klebsiella pneumoniae", "Escherichia coli", "Citrobacter freundii"),
                (False, True),
            )
        ),
    ]
    assert [x for x in labels if x not in i18n.LABELS] == []


def test_every_label_the_demo_briefs_use_has_a_finnish_entry(briefs):
    """Text slot values are either in the glossary or language-neutral: unit codes, Latin organism names (with their
    marker), antibiograms, lists of codes and dates."""
    neutral = re.compile(
        r"^(?:[A-Z]{2,5}(?:-[A-Z])?(?:, [A-Z]{2,5}(?:-[A-Z])?)*|(?:[A-Z]{3,4} )?[A-Z]\. [a-z]+"
        r"|(?:[A-Z]{3}:[SR] ?)+|MRSA|\d{4}-\d{2}-\d{2})$"
    )
    for monday, by_lang in briefs.items():
        for s in by_lang["en"]["sections"]:
            for it in s["items"]:
                template = TEMPLATES[it["template_id"]]
                for name, kind in {*slots_in(template["text"]), *slots_in(template.get("title", ""))}:
                    value = it["slots"][name]
                    if (kind or "text") == "text" and isinstance(value, str):
                        assert value in i18n.LABELS or neutral.match(value), (monday, it["template_id"], name, value)


# --------------------------------------------------------------------------- rendering
def test_finnish_numbers_and_dates():
    assert [
        fmt(v, k, "fi")
        for v, k in [
            (0.204, "pct1"),
            (10 / 16, "pct0"),
            (1 / 24571, "pct1"),
            ((0.61049, 0.8495), "ci1"),
            (1350, "int"),
            ("2026-03-29", "date"),
            ("2026-03-09", "short_date"),
            ((11, 24), "xofn"),
            (None, "int"),
        ]
    ] == ["20,4 %", "63 %", "<0,1 %", "61,0–85,0", "1 350", "29.3.2026", "9.3.", "11/24", "ei tietoa"]
    assert (
        i18n.render_id("trend_quiet", {"quiet": [7, 9], "units_text": "ED, ICU"}, "fi")
        == "Ei signaaleja 7/9 yksikössä (ED, ICU)."
    )


def test_finnish_demo_briefs_have_no_english_and_every_digit_comes_from_a_slot(briefs):
    for monday, by_lang in briefs.items():
        en, fi = by_lang["en"], by_lang["fi"]
        assert fi["counts"] == en["counts"] and fi["map"]["home_areas"] == en["map"]["home_areas"]
        fixed = [
            fi["header"]["title"],
            fi["header"]["dates_note"],
            fi["footer"],
            *(s["title"] for s in fi["sections"]),
            *(u["label"] for u in fi["map"]["units"]),
        ]
        assert english_words(" ".join(fixed)) == set(), monday
        for s_en, s_fi in zip(en["sections"], fi["sections"]):
            for a, b in zip(s_en["items"], s_fi["items"], strict=True):
                assert (b["id"], b["status"], b["priority"], b["slots"]) == (
                    a["id"],
                    a["status"],
                    a["priority"],
                    a["slots"],
                )
                for field in ("text", "title"):
                    assert english_words(b[field]) == set(), (monday, b["template_id"], b[field])
                    assert stray_digits(b["template_id"], b["slots"], "fi", field, b[field]) == [], (monday, b[field])
                    assert ".." not in b[field], b[field]
                    assert forbidden(b[field]) == [], b[field]
                assert b["advice"] is None or english_words(b["advice"]) == set()


def test_the_icu_cluster_reads_as_finnish_clinical_text(briefs):
    item = next(i for s in briefs["2026-03-09"]["fi"]["sections"] for i in s["items"] if i["id"] == ICU_CLUSTER)
    assert item["title"] == "ICU: mahdollinen rypäs (MRSA)" and item["advice"] == "Tyypitystä suositellaan"
    assert item["text"] == (
        "ICU: poikkeava löydöskuvio. MRSA: 3 potilasta 3.3. alkaen; 3/3 potilaalla sama herkkyysprofiili (FOX:R VAN:S "
        "CLI:R). Odotettu määrä, jos tämän herkkyysprofiilin osuus olisi sama kuin koko sairaalassa: 0–2 potilasta "
        "vuodessa tässä yksikössä (havaittu edeltävänä vuonna: 0). Edeltävänä vuonna koko sairaalassa tämä "
        "herkkyysprofiili oli 3/34 potilaalla, joilla on MRSA (9 %). Tyypitystä suositellaan."
    )


@pytest.mark.parametrize("stage", cds.STAGES)
@pytest.mark.parametrize("scenario", C.DEMO_SCENARIOS, ids=[s["key"] for s in C.DEMO_SCENARIOS])
def test_finnish_order_layer_has_no_english_and_every_digit_comes_from_a_slot(ds, seeds, monkeypatch, scenario, stage):
    calls, real = [], i18n.render_id

    def spy(template_id, slots, lang="en", field="text"):
        out = real(template_id, slots, lang, field)
        calls.append((template_id, slots, lang, field, out))
        return out

    monkeypatch.setattr(cds, "render_id", spy)
    s = scenario
    states = policy_states(ds, s["as_of"])
    en, fi = (
        cds.order_context(
            ds, s["as_of"], s["patient_id"], s["unit"], s["indication"], s["drug"], stage, seeds, states, lang
        )
        for lang in i18n.LANGS
    )
    assert {k: fi[k] for k in ("state", "card_key", "source", "interruptive")} == {
        k: en[k] for k in ("state", "card_key", "source", "interruptive")
    }
    assert [ln.get("numbers") for ln in fi["lines"]] == [ln.get("numbers") for ln in en["lines"]]
    card = cds_hooks.card(fi, None, "fi")
    texts = [fi[k] for k in ("chip", "headline", "ask", "rule", "note", "small_print", "drug_name") if fi[k]]
    texts += [ln["text"] for ln in fi["lines"]] + fi["notes"] + [h["reason_text"] for h in fi["previous_results"]]
    texts += [
        fi["actions"]["keep"]["label"],
        fi["actions"]["edit"]["label"],
        fi["actions"]["details"]["label"],
        *fi["actions"]["keep"]["reasons"],
    ]
    texts += [card["summary"], card["detail"], *(o["display"] for o in card["overrideReasons"])] if card else []
    assert english_words(" ".join(texts)) == set()
    assert forbidden(" ".join(texts)) == []
    assert ".." not in " ".join(texts)
    for template_id, slots, lang, field, out in calls:
        if lang == "fi":
            assert stray_digits(template_id, slots, lang, field, out) == [], out


# --------------------------------------------------------------------------- the API
@pytest.fixture
def client(cache, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setattr(C, "PUBLIC", False)
    for name in ("AEI_NARRATOR", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    api.LIMITER.hits.clear()
    with TestClient(api.app, headers={C.SESSION_HEADER: "visitor-eeee-0005"}) as c:
        yield c


def test_lang_defaults_to_english_and_rejects_others(client):
    assert client.get("/api/brief?as_of=2026-03-08").json()["header"]["title"] == "Monday brief"
    r = client.get("/api/brief?as_of=2026-03-08&lang=sv")
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"


def test_brief_and_case_file_in_finnish(client):
    b = client.get("/api/brief?as_of=2026-03-08&lang=fi").json()
    assert b["header"]["title"] == "Maanantaikatsaus"
    assert [s["title"] for s in b["sections"]] == [
        "Poikkeavat löydöskuviot",
        "Mitä muuttui",
        "Paikalliset rajat",
        "Nähty aiemmin",
        "Datan laatu",
        "Ei signaaleja",
    ]
    icu = next(i for s in b["sections"] for i in s["items"] if i["id"] == ICU_CLUSTER)
    assert icu["title"] == "ICU: mahdollinen rypäs (MRSA)"
    assert icu["alert"]["message"].startswith("Poikkeava MRSA-löydöskuvio, ICU: 3 potilasta")
    assert {ps["drug_label"] for ps in b["policy_states"]} == {"Trimetopriimi"}
    case = client.get(f"/api/signals/{ICU_CLUSTER}?as_of=2026-03-08&lang=fi").json()
    assert case["signal"]["text"] == icu["text"] and english_words(case["note"]) == set()
    assert case["line_list"] == client.get(f"/api/signals/{ICU_CLUSTER}?as_of=2026-03-08").json()["line_list"]


def test_case_file_evidence_in_finnish(client):
    """The THL rule card and the competing explanations the case file shows; rating codes stay as they are."""
    case = client.get(f"/api/signals/{ICU_CLUSTER}?as_of=2026-03-29&lang=fi").json()
    ev = case["signal"]["evidence"]
    hyp = ev["competing_explanations"]["hypotheses"]
    assert (hyp[0]["label"], hyp[0]["rating"], hyp[0]["rating_label"]) == ("Leviäminen yksikössä", "strong", "vahva")
    texts = [
        ev["competing_explanations"]["note"],
        ev["thl_rule"]["text"],
        ev["thl_rule"]["action"],
        *(f"{h['label']} {h['rating_label']} {h['evidence']}" for h in hyp),
    ]
    assert english_words(" ".join(texts)) == set()


def test_scenarios_and_cds_discovery_in_finnish(client):
    why = [s["why"] for s in client.get("/api/demo/scenarios?lang=fi").json()]
    services = client.get("/cds-services?lang=fi").json()["services"]
    assert english_words(" ".join(why + [f"{s['title']} {s['description']}" for s in services])) == set()


def test_my_ward_in_finnish(client):
    q = "/api/my-ward?as_of=2026-03-15&ward=ICU&specimen=blood_wound"
    en, fi = client.get(q).json(), client.get(q + "&lang=fi").json()
    assert fi["footer"] == "In vitro -kattavuus: tämä yksikkö. Ei lääkemääräys; paikallinen hoito-ohje ensin."
    assert [r["cells"] for r in fi["rows"]] == [r["cells"] for r in en["rows"]]
    assert [n["code"] for n in fi["not_shown"]] == [n["code"] for n in en["not_shown"]]
    texts = (
        [n["reason"] for n in fi["not_shown"]]
        + [b["text"] for b in fi["banners"]]
        + [r["label"] for r in fi["rows"]]
        + [s["text"] for s in fi["signals"]]
        + [w["label"] for w in fi["windows"]]
    )
    assert english_words(" ".join(texts)) == set()
    assert fi["banners"][0]["text"].startswith("Nostanut esiin 9.3.2026: infektioiden torjunta. Poikkeava MRSA")
    assert fi["banners"][0]["text"].endswith("Voimassa 23.3. asti.")
    assert "Kefoksitiini: ei näytetä; MRSA-seulontatesti, ei hoitovaihtoehto" in texts


def test_order_context_and_cds_card_in_finnish(client):
    body = {
        "as_of": "2026-03-15",
        "patient_id": "P003851",
        "unit": "ICU",
        "indication": "wound",
        "drug": "CXM",
        "stage": "sign",
    }
    ctx = client.post("/api/order-context?lang=fi", json=body).json()
    assert ctx["state"] == "warning" and ctx["drug_name"] == "Kefuroksiimi"
    assert ctx["ask"] == "Harkitse, sopiiko tämä lääke edelleen. Päätös on sinun."
    assert ctx["headline"] == (
        "Mahdollinen rypäs (MRSA), Teho-osasto. Hälytyksen herkkyysprofiili: kefuroksiimi R (päätelty: MRSA, "
        "kefoksitiiniseulonta positiivinen)."
    )
    hook = {
        "hookInstance": "h-1",
        "hook": "order-sign",
        "context": {
            "patientId": "P003851",
            "extension": {
                f"{cds.SLUG}.unit": "ICU",
                f"{cds.SLUG}.indication": "wound",
                f"{cds.SLUG}.as_of": "2026-03-15",
            },
            "draftOrders": {
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "MedicationRequest",
                            "id": "m1",
                            "medicationCodeableConcept": {
                                "coding": [{"system": cds_hooks.ATC_SYSTEM, "code": "J01DC02"}]
                            },
                        }
                    }
                ],
            },
        },
    }
    cards = client.post(f"/cds-services/{cds.SLUG}-order-sign?lang=fi", json=hook).json()["cards"]
    assert (
        cards[0]["summary"] == ctx["chip"] and cards[0]["links"][0]["label"] == "Kaikki lääkkeet Oma osasto -näkymässä"
    )
    assert english_words(cards[0]["summary"] + " " + cards[0]["detail"]) == set()
    assert [o["code"] for o in cards[0]["overrideReasons"]][1:] == [
        "discussed_with_infectious_diseases",
        "patient_specific_reason",
        "previous_result_supports_it",
        "other",
    ]


def test_heads_up_and_picker_in_finnish(client):
    r = client.post("/api/heads-up?lang=fi", json={"signal_id": ICU_CLUSTER, "as_of": "2026-03-29"})
    assert r.status_code == 201 and r.json()["text"] == (
        "Tiedoksi infektioiden torjunnasta. Teho-osasto (ICU): mahdollinen rypäs (MRSA). 13 potilasta 3.3. alkaen; "
        "12/13 potilaalla sama herkkyysprofiili: kefoksitiini R, vankomysiini S, klindamysiini R. Selvitys käynnissä; "
        "tyypitystä suositellaan. Päivämäärät ovat näytteenottopäiviä."
    )
    assert [d["name"] for d in client.get("/api/order-drugs?indication=uti&lang=fi").json()][:3] == [
        "Pivmesillinaami",
        "Nitrofurantoiini",
        "Trimetopriimi",
    ]
    assert {w["label"] for w in client.get("/api/filters?lang=fi").json()["wards"]} >= {"Teho-osasto", "Päivystys"}
