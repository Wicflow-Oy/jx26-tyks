"""Every text template, in English: the ED heads-up here, and by area the outbreak detectors (templates_outbreak.py),
the trend detectors and the brief (templates_trends.py), and the order layer and My ward (templates_ui.py). The
Finnish twin of every id is in templates_fi.py.

Each template: {"text": "... {slot:format} ...", "title": optional row title}. Numbers ONLY through slots.
Wording rules: no prediction language ("predicts", "forecast", "odds", "best choice", "recommended drug"); results
are S/R; say "unusual pattern" and "typing advised"; never "decoy" or "outbreak confirmed"; a unit that sent no
cultures is "data gap, cause unknown", never a statement about resistance.
"""

from . import config as C
from .templates_outbreak import TEMPLATES as OUTBREAK
from .templates_trends import TEMPLATES as TRENDS
from .templates_ui import TEMPLATES as UI

TEMPLATES = {
    # The emergency department's heads-up (audience "ed"; drafted for infection control to review, never sent from
    # here): drug names in full, never panel codes, and no patient identifiers. Built by ed_heads_up below.
    "ed_cluster": {
        "text": (
            "Heads-up from infection control: possible {organism_label} cluster on {ward_label} ({ward}). "
            "{n_patients:int} patients since {first_date:short_date}; {n_share:int} of {n_patients:int} share the same "
            "antibiogram: {pattern}. Under investigation; typing advised. Dates are sample dates."
        )
    },
    "ed_case": {
        "text": (
            "Heads-up from infection control: {marker_label} ({organism_label}) in a {specimen} sample on {ward_label} "
            "({ward}), sampled {sample_date:short_date}. Alert organism under THL guidance."
        )
    },
}
_ED_CLUSTER = ("organism_label", "n_patients", "n_share", "first_date", "pattern")
_ED_CASE = ("marker_label", "organism_label", "specimen", "sample_date")

TEMPLATES |= OUTBREAK | TRENDS | UI


def antibiogram_names(profile: str, lang: str = "en") -> str:
    """'FOX:R VAN:S CLI:R' -> 'cefoxitin R, vancomycin S, clindamycin R' (Finnish: 'kefoksitiini R, ...')."""
    from .i18n import label  # aei.i18n imports this module for its templates

    return ", ".join(
        f"{label(C.DRUG_NAMES[d], lang).lower()} {r}" for d, r in (token.split(":") for token in profile.split())
    )


def ed_heads_up(signal: dict, lang: str = "en") -> tuple[str, dict]:
    """The template id and slots for the ED heads-up on one brief item: a cluster with a shared antibiogram, or a
    single THL case, gets an ED template; any other item keeps its own. An antibiogram slot is always drug names, in
    the language the heads-up is written in."""
    slots = dict(signal["slots"])
    if "pattern" in slots:
        slots["pattern"] = antibiogram_names(slots["pattern"], lang)
    where = {"ward": signal["ward"], "ward_label": C.WARD_LABELS.get(signal["ward"], signal["ward"])}
    for template_id, names in (("ed_cluster", _ED_CLUSTER), ("ed_case", _ED_CASE)):
        if signal["ward"] and set(names) <= set(slots):
            return template_id, where | {k: slots[k] for k in names}
    return signal["template_id"], slots
