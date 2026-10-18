"""The language layer: English (the default) and Finnish.

Deliberately simple. Every text the API returns is rendered from a template id and its slots (aei/templates*.py):
- `FI` (aei/templates_fi.py) holds the Finnish template for every template id, with exactly the same slots and formats
  (a test checks it);
- `LABELS` is the Finnish glossary, keyed by the English text: slot values that are labels (units, drugs, specimens,
  windows...) and fixed phrases (section titles, rules, the small print);
- numbers and dates are formatted for the language by `render.fmt` ("20,4 %", "29.3.2026", "29.3.", "11/24").
A cached signal keeps its template id and English slots, so `localize_signal` renders it in Finnish without
recomputing. A slot value missing from the glossary is shown as it is: unit codes, Latin organism names, antibiograms
and alert messages typed by a user. Organism names stay Latin; MRSA, ESBL, VRE and CPE stay acronyms.

Finnish wording follows THL and Finnish clinical microbiology: herkkä (S) / resistentti (R), "mahdollinen rypäs",
"tyypitystä suositellaan", "profiilivastaavuus, ei tyypitys", "aukko datassa, syy tuntematon", kosketusvarotoimet,
tavanomaiset varotoimet. No prediction language, and no number words: numbers come only from slots.
"""

from . import config as C
from .render import render
from .templates import TEMPLATES
from .templates_fi import FI

LANGS = ("en", "fi")

# --------------------------------------------------------------------------------------------- glossary
# Finnish drug names: (name, the allative used after "resistentti": "resistentti ampisilliinille")
DRUG_NAMES = {
    "Ampicillin": ("Ampisilliini", "ampisilliinille"),
    "Mecillinam": ("Mesillinaami", "mesillinaamille"),
    "Piperacillin-tazobactam": ("Piperasilliini-tatsobaktaami", "piperasilliini-tatsobaktaamille"),
    "Cefoxitin": ("Kefoksitiini", "kefoksitiinille"),
    "Cefuroxime": ("Kefuroksiimi", "kefuroksiimille"),
    "Ceftriaxone": ("Keftriaksoni", "keftriaksonille"),
    "Ceftazidime": ("Keftatsidiimi", "keftatsidiimille"),
    "Meropenem": ("Meropeneemi", "meropeneemille"),
    "Ciprofloxacin": ("Siprofloksasiini", "siprofloksasiinille"),
    "Trimethoprim": ("Trimetopriimi", "trimetopriimille"),
    "Nitrofurantoin": ("Nitrofurantoiini", "nitrofurantoiinille"),
    "Vancomycin": ("Vankomysiini", "vankomysiinille"),
    "Clindamycin": ("Klindamysiini", "klindamysiinille"),
    "Pivmecillinam": ("Pivmesillinaami", "pivmesillinaamille"),
    "Flucloxacillin": ("Flukloksasilliini", "flukloksasilliinille"),
}
_ORGANISMS = sorted({o for table in (C.INTRINSIC, C.NO_BREAKPOINT) for o in table})


def short_organism(name: str) -> str:
    """'Escherichia coli' -> 'E. coli'. Organism names stay Latin in every language."""
    genus, _, species = str(name).partition(" ")
    return f"{genus[0]}. {species}" if species else str(name)


def _drug_labels() -> dict:
    """Drug names, combinations and the phrases detectors build from a drug and an organism."""
    out = {}
    for en, (fi, allative) in DRUG_NAMES.items():
        out[en], out[en.lower()] = fi, fi.lower()
        out[f"{en} resistant"] = f"Resistentti {allative}"  # resistance_change.finding
        for org in map(short_organism, _ORGANISMS):
            out[f"{org} resistant to {en.lower()}"] = f"{org} resistentti {allative}"  # resistance_change.subject
            out[f"{org} {en.lower()}"] = f"{org}, {fi.lower()}"  # outlier pairs
    for a, b in C.COMBOS.values():
        en_a, en_b = C.DRUG_NAMES[a], C.DRUG_NAMES[b]
        out[f"{en_a} + {en_b.lower()}"] = f"{DRUG_NAMES[en_a][0]} + {DRUG_NAMES[en_b][0].lower()}"
    return out


_THL_STRAIN = "kanta THL:n referenssilaboratorioon"
_THL_AGREE = " (tälle lajille sovittava etukäteen)"
LABELS = _drug_labels() | {
    # units, areas and people
    "Emergency department": "Päivystys",
    "Internal medicine A": "Sisätautiosasto A",
    "Internal medicine B": "Sisätautiosasto B",
    "Surgery": "Kirurgian osasto",
    "Urology": "Urologian osasto",
    "Intensive care unit": "Teho-osasto",
    "Geriatrics": "Geriatrian osasto",
    "Health centre North": "Terveysasema Pohjoinen",
    "Health centre South": "Terveysasema Etelä",
    "Centre": "Keskusta",
    "East": "Itä",
    "North": "Pohjoinen",
    "South": "Etelä",
    "West": "Länsi",
    "Women": "Naiset",
    "Men": "Miehet",
    "women": "naiset",
    "men": "miehet",
    "Inpatient wards": "Vuodeosastot",
    "Outpatient (emergency department and health centres)": "Avohoito (päivystys ja terveysasemat)",
    "Infection control": "Infektioiden torjunta",
    "infection control": "infektioiden torjunta",
    "Ward doctor": "Osastolääkäri",
    "Laboratory result": "Laboratoriotulos",
    "all units": "kaikki yksiköt",
    "this unit": "tämä yksikkö",
    "the selected units": "valitut yksiköt",
    "this unit's": "tämän yksikön",
    "the selected": "valittujen yksiköiden",
    # specimens and indications
    "urine": "virtsa",
    "blood": "veri",
    "wound": "haava",
    "urinary": "virtsa",
    "Urine": "Virtsa",
    "Blood and wound": "Veri ja haava",
    "Blood": "Veri",
    "Wound": "Haava",
    "Urinary tract infection": "Virtsatieinfektio",
    "Bloodstream infection": "Verenkiertoinfektio",
    "Wound infection": "Haavainfektio",
    "urinary tract infection": "virtsatieinfektio",
    "bloodstream infection": "verenkiertoinfektio",
    "wound infection": "haavainfektio",
    "all organisms": "kaikki mikrobit",
    "other organisms": "muut mikrobit",
    # windows and counting rules
    "Last 4 weeks": "Viimeiset 4 viikkoa",
    "Last 16 weeks": "Viimeiset 16 viikkoa",
    "Last 52 weeks": "Viimeiset 52 viikkoa",
    "last 4 weeks": "viimeiset 4 viikkoa",
    "last 52 weeks": "viimeiset 52 viikkoa",
    "First isolate per patient, organism and specimen in the period (dataset README)": (
        "Ensimmäinen isolaatti potilasta, mikrobia ja näytettä kohden jaksolla (aineiston README)"
    ),
    "First isolate per patient, organism and specimen in 30 days": (
        "Ensimmäinen isolaatti potilasta, mikrobia ja näytettä kohden 30 päivän aikana"
    ),
    "first isolate per patient in the window": "ensimmäinen isolaatti potilasta kohden aikaikkunassa",
    "first isolate per patient in 30 days": "ensimmäinen isolaatti potilasta kohden 30 päivän aikana",
    "local setting, set by stewardship": "paikallinen raja, mikrobilääkehoidon ohjauksen asettama",
    # the Monday brief
    "Monday brief": "Maanantaikatsaus",
    "nightly": "öisin",
    "Unusual patterns": "Poikkeavat löydöskuviot",
    "What changed": "Mitä muuttui",
    "Policy lines": "Paikalliset rajat",
    "Seen before": "Nähty aiemmin",
    "Data quality": "Datan laatu",
    "Quiet": "Ei signaaleja",
    "Dates are sample dates; results usually arrive a couple of days later.": (
        "Päivämäärät ovat näytteenottopäiviä; tulokset valmistuvat yleensä muutaman päivän kuluttua."
    ),
    "Each item opens its case file with the counts and the filter. Texts are filled in from computed numbers only.": (
        "Jokainen kohta avaa tapauksen tiedot laskentoineen ja suodattimineen. Tekstit täytetään vain lasketuista "
        "luvuista."
    ),
    "Typing advised": "Tyypitystä suositellaan",
    "Lab check": "Laboratorion tarkistus",
    # slot values of brief items
    "hospital-onset": "sairaalasyntyinen",
    "outpatient sample": "avohoidon näyte",
    "early in the stay, not hospital-onset": "hoitojakson alussa, ei sairaalasyntyinen",
    "result": "tulos",
    "results": "tulosta",
    "this week": "tällä viikolla",
    "in this window": "tällä aikavälillä",
    "MRSA (cefoxitin screen positive)": "MRSA (kefoksitiiniseulonta positiivinen)",
    "MRSA among S. aureus": "S. aureus on MRSA",
    "urinary E. coli": "E. coli (virtsa)",
    "women in primary care": "naiset perusterveydenhuollossa",
    "above": "ylitetty",
    "at": "saavutettu",
    # THL Ohjaus 2/2020 actions (detectors/thl.py action_text)
    (
        "Contact precautions; screen exposed patients; new MRSA strains go to the THL reference lab (spa typing); "
        "check ward overlap."
    ): (
        "Kosketusvarotoimet; altistuneiden potilaiden seulonta; uudet MRSA-kannat THL:n referenssilaboratorioon "
        "(spa-tyypitys); tarkista osastojaksojen päällekkäisyys."
    ),
    "Contact precautions; screen exposed patients (same room or unit); check the past year on the unit.": (
        "Kosketusvarotoimet; altistuneiden potilaiden seulonta (sama huone tai yksikkö); tarkista yksikön edellisen "
        "vuoden löydökset."
    ),
    (
        "Standard precautions; contact precautions by risk assessment; epidemic check: same antibiogram? same room or "
        "ward days?"
    ): (
        "Tavanomaiset varotoimet; kosketusvarotoimet riskinarvion perusteella; epidemiaselvitys: sama "
        "herkkyysprofiili? samat huone- tai osastopäivät?"
    ),
    (
        "Standard precautions at the outpatient unit; contact precautions if admitted; new MRSA strains go to the THL "
        "reference lab (spa typing)."
    ): (
        "Tavanomaiset varotoimet avohoitoyksikössä; kosketusvarotoimet, jos potilas otetaan osastolle; uudet "
        "MRSA-kannat THL:n referenssilaboratorioon (spa-tyypitys)."
    ),
    (
        "Standard precautions at the outpatient unit; contact precautions if admitted, by risk assessment; epidemic "
        "check: same antibiogram?"
    ): (
        "Tavanomaiset varotoimet avohoitoyksikössä; kosketusvarotoimet riskinarvion perusteella, jos potilas otetaan "
        "osastolle; epidemiaselvitys: sama herkkyysprofiili?"
    ),
    **{
        (
            f"Single room with own WC, contact precautions, screen exposed patients, look-back over the past year; strain to "
            f"the THL reference lab{agree_en}."
        ): (
            f"Oma huone ja oma WC, kosketusvarotoimet, altistuneiden potilaiden seulonta, "
            f"takautuva selvitys edellisen vuoden ajalta; {_THL_STRAIN}{agree_fi}."
        )
        for agree_en, agree_fi in (("", ""), (" (agree in advance for this species)", _THL_AGREE))
    },
    **{
        (
            f"Flag as carrier; single room with own WC and contact precautions if admitted; look-back over the past year; "
            f"strain to the THL reference lab{agree_en}."
        ): (
            f"Kantajamerkintä potilastietoihin; oma huone ja oma WC sekä "
            f"kosketusvarotoimet, jos potilas otetaan osastolle; takautuva "
            f"selvitys edellisen vuoden ajalta; {_THL_STRAIN}{agree_fi}."
        )
        for agree_en, agree_fi in (("", ""), (" (agree in advance for this species)", _THL_AGREE))
    },
    # phenotype consistency checks (config.EXPERT_RULES)
    "ESBL producer reported S to cefuroxime or ceftriaxone": (
        "ESBL-tuottaja vastattu herkäksi (S) kefuroksiimille tai keftriaksonille"
    ),
    "MRSA-flagged S. aureus reported cefoxitin S": "MRSA-merkitty S. aureus, kefoksitiini vastattu herkäksi (S)",
    "Ceftriaxone R with ampicillin S or cefuroxime S (E. coli, Klebsiella spp., P. mirabilis)": (
        "Keftriaksoni R, mutta ampisilliini S tai kefuroksiimi S (E. coli, Klebsiella spp., P. mirabilis)"
    ),
    "Piperacillin-tazobactam R with ampicillin S (E. coli, P. mirabilis)": (
        "Piperasilliini-tatsobaktaami R, mutta ampisilliini S (E. coli, P. mirabilis)"
    ),
    # the case file's THL rule card and competing explanations (detectors/thl.py, detectors/explanations.py)
    "THL guidance: epidemic check (several findings above the usual level on one unit)": (
        "THL:n ohje: epidemiaselvitys (useita löydöksiä samassa yksikössä tavanomaista enemmän)"
    ),
    "Shown with the phenotype cluster instead of as a separate card.": (
        "Näytetään fenotyyppiryppään yhteydessä erillisen kortin sijaan."
    ),
    "Competing explanations rated from counts only. Phenotype is not genotype; typing advised.": (
        "Kilpailevat selitykset on arvioitu vain lukumääristä. Fenotyyppi ei ole genotyyppi; tyypitystä suositellaan."
    ),
    "strong": "vahva",
    "moderate": "kohtalainen",
    "weak": "heikko",
    "plausible": "uskottava",
    "possible": "mahdollinen",
    "unlikely": "epäuskottava",
    "check": "tarkistettava",
    "contributes (index imported?)": "osatekijä (indeksitapaus tuotu?)",
    # policy lines (config.POLICY_LINES)
    "Trimethoprim for uncomplicated UTI in women": "Trimetopriimi naisten komplisoitumattomaan virtsatieinfektioon",
    "Review the empirical UTI guidance": "Tarkista virtsatieinfektion empiirisen hoidon ohje",
    # how a result was read (phenotype_rules.REASON_TEXT)
    "no EUCAST breakpoint for this species": "lajille ei ole EUCAST-raja-arvoa",
    "intrinsic resistance (EUCAST)": "luontainen resistenssi (EUCAST)",
    "inferred: MRSA, cefoxitin screen positive": "päätelty: MRSA, kefoksitiiniseulonta positiivinen",
    "reported": "laboratorion vastaama",
    "inferred: MSSA, cefoxitin screen negative": "päätelty: MSSA, kefoksitiiniseulonta negatiivinen",
    "inferred from ampicillin": "päätelty ampisilliinin tuloksesta",
    "local rule: ESBL producers reported R": "paikallinen sääntö: ESBL-tuottajat vastataan resistenteiksi (R)",
    "not tested": "ei testattu",
    "read from the cefoxitin screen": "luettu kefoksitiiniseulonnasta",
    # the order layer (cds.py)
    "resistant": "resistenttejä",
    "not covered": "kattamatta",
    "an approved alert applies to this unit, drug and indication": (
        "hyväksytty hälytys koskee tätä yksikköä, lääkettä ja indikaatiota"
    ),
    "an approved alert on this unit does not apply to this order": "yksikön hyväksytty hälytys ei koske tätä määräystä",
    "a local policy line for this drug is at or above its threshold": (
        "tämän lääkkeen paikallinen raja on saavutettu tai ylitetty"
    ),
    "this population's observed resistance is at, above or close to a local line for this drug": (
        "tämän potilasjoukon havaittu resistenssi on lääkkeen paikallisella rajalla, sen yli tai lähellä sitä"
    ),
    "No data: no number is shown for this drug in this population.": (
        "Ei dataa: tälle lääkkeelle ei näytetä lukua tässä potilasjoukossa."
    ),
    "Quiet: no alert, no local line near, and no acquired resistance in this patient's previous isolates.": (
        "Ei huomautettavaa: ei hälytystä, ei paikallista rajaa lähellä eikä hankinnaista resistenssiä potilaan "
        "aiemmissa isolaateissa."
    ),
    "Consider whether this drug still fits. The decision is yours.": (
        "Harkitse, sopiiko tämä lääke edelleen. Päätös on sinun."
    ),
    "It will ask again when the order is signed.": "Kysymys toistetaan, kun määräys allekirjoitetaan.",
    "Observed unit-level information about past results. The doctor decides.": (
        "Havaittua yksikkötason tietoa aiemmista tuloksista. Lääkäri päättää."
    ),
    f"Dates are sample dates; results usually arrive about {C.RESULT_LAG_DAYS} days later.": (
        f"Päivämäärät ovat näytteenottopäiviä; tulokset valmistuvat yleensä noin {C.RESULT_LAG_DAYS} päivää myöhemmin."
    ),
    "All drugs on My ward": "Kaikki lääkkeet Oma osasto -näkymässä",
    "Edit the order": "Muokkaa määräystä",
    "Synthetic isolate ids; no patient names or ids.": (
        "Synteettiset isolaattitunnisteet; ei potilaiden nimiä tai tunnisteita."
    ),
    "Discussed with infectious diseases": "Konsultoitu infektiolääkäriä",
    "Patient-specific reason": "Potilaskohtainen syy",
    "Previous result supports it": "Aiempi tulos tukee valintaa",
    "Other": "Muu syy",
    "Note:": "Huomautus:",
    "What is happening:": "Mitä on meneillään:",
    "This drug in this population:": "Tämä lääke tässä potilasjoukossa:",
    "Amoxicillin is read from the ampicillin result (EUCAST infers amoxicillin from ampicillin).": (
        "Amoksisilliinin tulos luetaan ampisilliinin tuloksesta (EUCAST päättelee amoksisilliinin ampisilliinista)."
    ),
    (
        "first isolate per patient x organism x specimen; effective S/R from the shared phenotype rules (EUCAST "
        "breakpoints, expected resistant phenotypes and expert rules, and this laboratory's ESBL reporting rule); no "
        "number for a drug with a result on fewer than 90% of the population's isolates; Jeffreys 95% interval"
    ): (
        "ensimmäinen isolaatti potilasta, mikrobia ja näytettä kohden; vaikuttava S/R yhteisistä fenotyyppisäännöistä "
        "(EUCAST-raja-arvot, odotetut resistenssifenotyypit ja asiantuntijasäännöt sekä tämän laboratorion "
        "ESBL-vastaussääntö); ei lukua lääkkeelle, jolla on tulos alle 90 %:lla potilasjoukon isolaateista; Jeffreysin "
        "95 %:n luottamusväli"
    ),
    (
        "Standards-based route for an EHR that supports HL7 CDS Hooks 2.0 (order-select, order-sign). Simulated in "
        "this prototype: no EHR is connected."
    ): (
        "Standardipohjainen reitti potilastietojärjestelmälle, joka tukee HL7 CDS Hooks 2.0 -rajapintaa (order-select, "
        "order-sign). Simuloitu tässä prototyypissä: potilastietojärjestelmää ei ole kytketty."
    ),
    # the demo scenarios (config.DEMO_SCENARIOS) and the CDS Hooks discovery (cds.SERVICES)
    "the approved URO ESBL alert applies to ceftriaxone": "hyväksytty URO:n ESBL-hälytys koskee keftriaksonia",
    "primary-care women's trimethoprim above the local 20% line": (
        "perusterveydenhuollon naisten trimetopriimi yli paikallisen 20 %:n rajan"
    ),
    "the approved ICU MRSA alert applies to beta-lactams": "hyväksytty ICU:n MRSA-hälytys koskee beetalaktaameja",
    "no alert, no line near, previous isolate susceptible": "ei hälytystä, ei rajaa lähellä, aiempi isolaatti herkkä",
    "this patient's E. coli of 16 Jan 2026 was trimethoprim R": (
        "potilaan E. coli -löydös 16. tammikuuta 2026 oli trimetopriimi R"
    ),
    f"{C.APP_NAME} unit resistance context": f"{C.APP_NAME}: yksikön resistenssitilanne",
    f"{C.APP_NAME} unit resistance check": f"{C.APP_NAME}: yksikön resistenssitarkistus",
    (
        "When an antibiotic is selected, flags it with passive information from approved infection-control alerts, "
        "local lines and the unit's observed counts. Never interrupts at selection and never names another drug."
    ): (
        "Kun antibiootti valitaan, liittää siihen taustatiedon hyväksytyistä infektioiden torjunnan hälytyksistä, "
        "paikallisista rajoista ja yksikön havaituista lukumääristä. Ei koskaan keskeytä valintaa eikä nimeä toista "
        "lääkettä."
    ),
    (
        "Before an antibiotic order is signed, asks once when an approved alert applies to this unit and drug, or the "
        "patient's own recent isolate had acquired resistance to it. The doctor decides."
    ): (
        "Ennen antibioottimääräyksen allekirjoitusta kysyy kerran, jos hyväksytty hälytys koskee tätä yksikköä ja "
        "lääkettä tai potilaan omassa tuoreessa isolaatissa oli hankinnainen resistenssi sille. Lääkäri päättää."
    ),
    # the demo seeds' alert messages (config.DEMO_ALERT_SEEDS), as infection control would write them in Finnish
    (
        "Possible ESBL E. coli cluster, URO: 6 patients sampled 30 May to 8 Jun with one antibiogram. Usually about "
        "1 ESBL E. coli patient a month. Under investigation."
    ): (
        "Mahdollinen ESBL E. coli -rypäs, URO: 6 potilasta, näytteet 30. toukokuuta – 8. kesäkuuta, sama "
        "herkkyysprofiili. "
        "Tavallisesti noin 1 ESBL E. coli -potilas kuukaudessa. Selvitys käynnissä."
    ),
    (
        "Unusual MRSA pattern, ICU: 3 patients sampled 3 to 8 Mar with one antibiogram. MRSA is resistant to every "
        "beta-lactam on this panel. Under investigation; typing advised."
    ): (
        "Poikkeava MRSA-löydöskuvio, ICU: 3 potilasta, näytteet 3.–8. maaliskuuta, sama herkkyysprofiili. MRSA on "
        "resistentti "
        "kaikille tämän paneelin beetalaktaameille. Selvitys käynnissä; tyypitystä suositellaan."
    ),
}


# --------------------------------------------------------------------------------------------- rendering
def check(lang: str) -> str:
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {list(LANGS)}")
    return lang


def label(text, lang: str = "en"):
    """The Finnish label or phrase for an English one; anything not in the glossary is returned as it is."""
    return LABELS.get(text, text) if lang == "fi" and isinstance(text, str) else text


def join(names: list[str], lang: str = "en") -> str:
    """ "A, B and C" / "A, B ja C"."""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + (" ja " if lang == "fi" else " and ") + names[-1]


def render_id(template_id: str, slots: dict, lang: str = "en", field: str = "text") -> str:
    """Render a template ("text" or "title") in `lang`. In Finnish, text slot values go through the glossary."""
    template = TEMPLATES[template_id]
    if lang == "en":
        return render(template[field], slots, template.get("formats"))
    slots = {k: label(v, lang) for k, v in slots.items()}
    return render(FI[template_id][field], slots, template.get("formats"), lang)


def localize_signal(s: dict, lang: str) -> dict:
    """A brief item in `lang`: text and title re-rendered from its template id and slots; the evidence a case file
    shows (THL action and rule card, competing explanations) re-rendered or taken from the glossary. Nothing is
    recomputed. Codes, slots, counts and the technical method strings stay as they are."""
    if lang == "en":
        return s
    out = {**s, "text": render_id(s["template_id"], s["slots"], lang), "advice": label(s.get("advice"), lang)}
    if "title" in s:
        out["title"] = render_id(s["template_id"], s["slots"], lang, "title")
    ev = dict(s.get("evidence") or {})
    if isinstance(ev.get("action"), str):
        ev["action"] = label(ev["action"], lang)
    if ev.get("thl_rule"):
        ev["thl_rule"] = {**ev["thl_rule"], **{k: label(ev["thl_rule"][k], lang) for k in ("text", "action", "note")}}
    if ev.get("competing_explanations"):
        ce = ev["competing_explanations"]
        ev["competing_explanations"] = {
            **ce,
            "note": label(ce.get("note"), lang),
            "hypotheses": [
                {
                    **h,
                    "label": render_id(h["template_id"], h["slots"], lang, "title"),
                    "rating_label": label(h["rating"], lang),
                    "evidence": render_id(h["template_id"], h["slots"], lang),
                }
                for h in ce["hypotheses"]
            ],
        }
    out["evidence"] = ev
    return out
