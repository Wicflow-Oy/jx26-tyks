"""Deterministic checks on narrated text (CONTRACTS.md section 6). Pure, offline, milliseconds.

The language model only writes a *skeleton*: short prose with {slot} placeholders and no numbers. Code renders the
numbers. Two checks guard that flow:

- `validate_skeleton(text, allowed_slots)` runs on the model's skeleton, before rendering.
- `validate_rendered(text, slots)` runs after rendering: every number in the text must be a formatted slot value.

Every term list is a module constant below, so the policy can be reviewed in one place. Patterns are regular
expressions matched with word boundaries against the NFKC-normalised, casefolded text (so full-width letters such as
"ｓｅｖｅｎ" cannot dodge the lists). All three languages' lists apply to every text, whatever its language.

Policy decisions (reviewable):
- Vague quantifiers that state no number are ALLOWED: "few", "several", "some", "many", "more", "fewer", "all",
  "no", "muutama", "useita", "några", "flera". Quantifiers that encode a number or a share are REJECTED: "a couple",
  "pair", "both", "majority", "most of", "nearly all", "pari", "molemmat", "suurin osa", "ett par", "båda",
  "de flesta".
- Ordinals: "first" / "ensimmäinen" / "första" and "last" are allowed (the templates say "First sample"). Other
  ordinals ("second", "third", "kolmas", "tredje"...) and fractions ("a third", "kolmannes", "tredjedel") are rejected.
- Swedish "en" / "ett" are NOT number words here: they are the indefinite article, and rejecting them would reject
  nearly every Swedish sentence. "en av", "ett av", "en enda" and "ett par" are rejected instead. Finnish "toinen"
  and Swedish "andra" (both mean "other" as well as "second") are allowed for the same reason. This deviates from the
  CONTRACTS.md section 6 list, which names en/ett.
- "outbreak" is rejected in every form, not only "outbreak confirmed": the product says "unusual pattern" or
  "possible cluster" (research w31, section 2.9). "confirmed", "clone"/"same strain" (a typing claim; say "profile
  match, not typing") and "intermediate" (results are S/R) are rejected too.
- Hidden format or control characters (zero-width spaces, bidi marks) are rejected outright.
- Format specs in a skeleton ("{rate:pct0}") are rejected: formats are fixed by the template, in code.

Known limits: the validator checks numbers, the listed terms, slots and form. It cannot check that number-free prose
is true ("most patients were on one ward" is caught; "the pattern is spreading" is not). ASCII Roman numerals
("III") and look-alike letters from other scripts are not detected.
"""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass, field
from numbers import Integral, Real

from .render import fmt

MAX_SKELETON_CHARS = 700

# ---------------------------------------------------------------------------------------------------------------
# Term lists. Each entry is a regex fragment, matched as \b(?:fragment)\b on normalised text.
# ---------------------------------------------------------------------------------------------------------------
NUMBER_WORDS = {
    "en": (
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
        "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
        r"hundreds?", r"thousands?", r"millions?", r"billions?", r"dozens?",
        "half", "halves", r"quarters?", r"thirds?", "second", "fourth", "fifth", "sixth", "seventh", "eighth",
        "ninth", "tenth", "eleventh", "twelfth", r"\w+teenth", r"\w+tieth", "hundredth", "thousandth",
        "twice", "thrice", r"doubles?", r"triples?", r"quadruples?",
        "percent", r"per\s+cent", r"percentages?", "pct",
    ),
    "fi": (
        r"nolla\w*", "yksi", "yksitoista", r"yksittäi\w*", "yhden", "yhtä", "yhdelle", "yhdeltä", "yhdellä", "yhdestä",
        r"kaksi\w*", r"kahde\w*", "kahta", "kahtena", r"kolm\w*", r"nelj\w*", r"viisi\w*", r"viide\w*", "viittä",
        r"kuusi\w*", r"kuude\w*", "kuutta", r"seitsem\w*", r"yhdeks\w*", r"kymme\w*",
        "sata", "sataa", r"sadan\w*", "satoja", r"sadas\w*", r"tuhat\w*", r"tuhann\w*", r"tuhans\w*", r"miljoon\w*",
        "puoli", "puolet", "puolta", r"puolikas\w*", r"puolittu\w*", r"puoliintu\w*",
        r"prosent\w*",
    ),
    "sv": (
        r"noll\w*", r"två\w*", "tre", r"tredje\w*", r"tretton\w*", r"trettio\w*",
        r"fyra\w*", r"fyrti\w*", r"fjärde\w*", r"fjorton\w*", "fem", r"femte\w*", r"femton\w*", r"femti\w*",
        "sex", r"sexton\w*", r"sexti\w*", r"sjätte\w*", "sju", r"sjunde\w*", r"sjutton\w*", r"sjutti\w*",
        r"åtta\w*", r"åttio\w*", r"åttonde\w*", r"arton\w*", "nio", r"nionde\w*", r"nitton\w*", r"nitti\w*",
        "tio", r"tionde\w*", r"tiotal\w*", "elva", "elfte", r"tolv\w*", "tolfte", r"tjugo\w*",
        r"hundra\w*", r"tusen\w*", r"miljon\w*", r"dussin\w*",
        r"halv\w*", "hälften", r"dubbel\w*", r"dubbla\w*", r"trippel\w*", r"procent\w*",
    ),
}
QUANTITY_TERMS = {  # quantifiers that encode a number or a share
    "en": (r"couples?", r"pairs?", "both", r"majority", r"minority", r"most\s+of", r"(?:nearly|almost)\s+all",
           r"the\s+bulk\s+of"),
    "fi": (r"pari\w*", r"molem\w*", "kumpikin", r"enemmistö\w*", r"vähemmistö\w*", r"suurin\s+osa\w*",
           r"valtaosa\w*", r"(?:lähes|melkein)\s+kaik\w*"),
    "sv": (r"ett\s+par", r"båda", r"bägge\w*", r"majoritet\w*", r"minoritet\w*", r"de\s+flesta", "flertalet",
           r"nästan\s+alla", r"en\s+av", r"ett\s+av", r"en\s+enda", r"ett\s+enda"),
}
COMPARISON_TERMS = {  # numbers computed in words: the engine computes, the model only references
    "en": (r"doubled", r"doubling", r"tripled", r"tripling", r"quadrupled", r"halved", r"halving", r"\w*fold",
           r"times\s+(?:higher|lower|more|less|greater|as|the|over)", r"percentage\s+points?",
           r"points?\s+(?:higher|lower|up|down)",
           r"(?:increase|decrease|rise|drop|fall|jump|reduction)\s+of",
           r"(?:rose|fell|dropped|increased|decreased|grew|climbed|jumped|declined|went\s+up|went\s+down)\s+by"),
    "fi": (r"\w*kertai\w*", r"\w*kertaistu\w*", "verran",
           r"kertaa\s+(?:enemmän|suurempi|korkeampi|vähemmän|pienempi|niin)"),
    "sv": (r"\w*faldig\w*", r"fördubbl\w*", r"tredubbl\w*", r"halver\w*",
           r"(?:ökade|minskade|steg|sjönk|föll|växte)\s+med",
           r"gånger\s+(?:högre|lägre|fler|färre|mer|mindre|så|större)"),
}
PREDICTION_TERMS = {
    "en": (r"predict\w*", r"forecast\w*", "odds", r"probabilit\w*", "probable", "probably", "likelihood",
           r"(?:un)?likely\s+to", r"chances?\s+(?:of|that)",
           r"will\s+(?:rise|increase|spread|grow|continue|worsen|double|peak|fall|decrease)",
           r"(?:is|are)\s+going\s+to", r"expected\s+to\s+(?:rise|increase|spread|grow|continue|worsen)",
           r"best\s+(?:choice|option|drug|antibiotic|treatment)", r"drug\s+of\s+choice",
           r"recommended\s+(?:drug|antibiotic|treatment|therapy)"),
    "fi": (r"ennust\w*", r"todennäköi\w*", r"paras\s+(?:valinta|vaihtoehto|lääke)",
           r"suositel\w*\s+(?:lääke\w*|antibiooti\w*|hoito\w*)",
           r"tulee\s+(?:nousemaan|lisääntymään|leviämään|kasvamaan)"),
    "sv": (r"förutsä\w*", r"förutspå\w*", r"prognos\w*", r"sannolik\w*",
           r"bästa\s+(?:valet|val|alternativ\w*|läkemedl\w*|antibiotik\w*)",
           r"rekommendera\w*\s+(?:läkemedel\w*|antibiotik\w*|behandling\w*)",
           r"kommer\s+att\s+(?:öka|stiga|spridas|sprida|växa|fortsätta|förvärras)"),
}
RESTRICTED_TERMS = {
    "en": (r"decoys?", r"outbreaks?", r"epidemics?", "confirmed", r"s\s*/\s*i\s*/\s*r", "intermediate",
           r"zero\s+resistance", r"no\s+resistance", r"same\s+(?:strain|clone)", r"clon(?:e|es|al|ality|ed)"),
    "fi": (r"epidemia\w*", r"taudinpurk\w*", r"vahvistettu\w*", r"varmistettu\w*", r"klooni\w*", r"sama\s+kanta\w*",
           r"harhautu\w*", r"syötti\w*"),
    "sv": (r"utbrott\w*", r"epidemi(?:n|er|erna|sk\w*)?", r"bekräftad\w*", "bekräftat", r"klon\w*", r"samma\s+stam\w*",
           r"lockbete\w*", r"bulvan\w*", r"ingen\s+resistens", r"intermediär\w*"),
}
DOSING_TERMS = {
    "en": ("mg", "mcg", "µg", "μg", "ug", "g", "kg", "ml", "iu", "mmol", r"doses?", "dosing", r"dosages?",
           r"g\s*/\s*(?:day|d|kg)", r"per\s+kg", r"(?:once|twice|thrice|times|x)\s+(?:a\s+|per\s+)?(?:daily|day)",
           r"every\s+\w+\s+hours"),
    "fi": (r"annos\w*", r"annost\w*", r"(?:kertaa|kerran|kahdesti)\s+(?:päivässä|vuorokaudessa)", "vrk"),
    "sv": (r"dos(?:en|er|erna|ering\w*)?", r"(?:gång|gånger)\s+(?:dagligen|per\s+dag|om\s+dagen)"),
}
TREATMENT_TERMS = {  # prescribing instructions: the local guide, not the narrator, names alternatives
    "en": (r"switch\s+(?:to|the\s+patient)", r"change\s+to", r"start\s+(?:treatment|antibiotics?|therapy)",
           "prescribe", "administer", r"treat\s+(?:with|the\s+patient)", r"give\s+(?:the\s+patient|antibiotics?)"),
    "fi": ("vaihda", "määrää", r"aloita\s+(?:hoito|antibiootti|lääkitys)\w*"),
    "sv": (r"byt\s+till", r"ordinera\w*", r"sätt\s+in", r"börja\s+(?:behandling|med\s+antibiotika)\w*"),
}
NUMBER_SYMBOLS = "%‰‱±½¼¾⅓⅔"
MARKUP_CHARS = "<>*#`|"
IDENTIFIER_PATTERNS = (r"\bP-[0-9A-F]{4,}\b", r"@", r"https?://", r"\bwww\.")  # matched on the raw text

TERM_CATEGORIES = {  # error prefix -> term list; order is the order errors are reported in
    "number_word": NUMBER_WORDS,
    "quantity": QUANTITY_TERMS,
    "comparison": COMPARISON_TERMS,
    "prediction": PREDICTION_TERMS,
    "restricted": RESTRICTED_TERMS,
    "dosing": DOSING_TERMS,
    "treatment": TREATMENT_TERMS,
}

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)(?::([a-z0-9_]+))?\}")
_ABBREVIATIONS = re.compile(r"\b(?:e\.g|i\.e)\.", re.IGNORECASE)
_NUMBER_RUN = re.compile(r"\d+(?:[.,]\d+)*")
_COMPILED = {cat: re.compile(r"\b(?:" + "|".join(p for lang in lists.values() for p in lang) + r")\b")
             for cat, lists in TERM_CATEGORIES.items()}
_IDENTIFIERS = [re.compile(p) for p in IDENTIFIER_PATTERNS]


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": list(self.errors)}


def _result(errors: list[str]) -> ValidationResult:
    seen = list(dict.fromkeys(errors))  # keep order, drop duplicates
    return ValidationResult(ok=not seen, errors=seen)


def _normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).casefold()
    t = _ABBREVIATIONS.sub(" ", t)
    return re.sub(r"\s+", " ", t)


def _hidden_chars(text: str) -> list[str]:
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Co", "Cs") or (cat == "Cc" and ch not in "\n\t\r"):
            out.append(f"hidden_char:U+{ord(ch):04X}")
    return out


def _numerals(text: str) -> list[str]:
    """Digit runs (any script, \\d) and other numeric characters (Roman numerals, superscripts, vulgar fractions)."""
    out = [f"digit:{m.group(0)}" for m in _NUMBER_RUN.finditer(text)]
    for ch in text:
        if unicodedata.category(ch) in ("Nl", "No"):
            out.append(f"numeral:{ch}")
    return out


def _term_errors(text: str, categories=TERM_CATEGORIES) -> list[str]:
    norm = _normalise(text)
    errors = []
    for cat in categories:
        errors += [f"{cat}:{m.group(0)}" for m in _COMPILED[cat].finditer(norm)]
    errors += [f"number_symbol:{ch}" for ch in NUMBER_SYMBOLS if ch in norm]
    return errors


def validate_skeleton(text: str, allowed_slots) -> ValidationResult:
    """Check a model-written skeleton. `allowed_slots` is an iterable (or dict) of the slot names it may use."""
    if not isinstance(text, str) or not text.strip():
        return _result(["empty"])
    allowed = set(allowed_slots)
    errors = []
    if len(text) > MAX_SKELETON_CHARS:
        errors.append(f"too_long:{len(text)}")
    errors += _hidden_chars(text)
    for m in _PLACEHOLDER.finditer(text):
        name, spec = m.group(1), m.group(2)
        if spec is not None:
            errors.append(f"format_spec:{name}:{spec}")
        if name not in allowed:
            errors.append(f"unknown_slot:{name}")
    prose = _PLACEHOLDER.sub(" ∎ ", text)  # a neutral, non-word marker keeps phrase boundaries ("increase of ∎")
    if "{" in prose or "}" in prose:
        errors.append("malformed_placeholder")
    errors += _numerals(prose)
    errors += _term_errors(prose)
    for pat in _IDENTIFIERS:
        errors += [f"identifier:{m.group(0)}" for m in pat.finditer(prose)]
    errors += [f"markup:{ch}" for ch in MARKUP_CHARS if ch in prose]
    if "](" in prose:
        errors.append("markup:link")
    return _result(errors)


# ---------------------------------------------------------------------------------------------------------------
# Rendered text
# ---------------------------------------------------------------------------------------------------------------
def _is_iso_date(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ].*)?", value) is not None


def _candidate_kinds(value) -> tuple[str, ...]:
    """Every render format that could legitimately apply to a raw slot value (used when no format is known)."""
    if value is None or isinstance(value, bool):
        return ("text",)
    if isinstance(value, Integral):
        return ("int", "text")
    if isinstance(value, Real):
        kinds = ["text"]
        if 0.0 <= float(value) <= 1.0:
            kinds += ["pct0", "pct1"]
        if float(value).is_integer():
            kinds.append("int")
        return tuple(kinds)
    if isinstance(value, (tuple, list)) and len(value) == 2 and all(isinstance(v, Real) for v in value):
        kinds = ["text"]
        if all(isinstance(v, Integral) or float(v).is_integer() for v in value):
            kinds.append("xofn")
        if all(0.0 <= float(v) <= 1.0 for v in value):
            kinds += ["ci0", "ci1"]
        return tuple(kinds)
    if isinstance(value, _dt.date) or _is_iso_date(value):  # datetime and pd.Timestamp are date subclasses
        return ("date", "short_date", "text")
    return ("text",)


def _renderings(slots: dict, formats: dict | None) -> set[str]:
    out = set()
    for name, value in slots.items():
        kinds = (formats[name],) if formats and name in formats else _candidate_kinds(value)
        for kind in kinds:
            try:
                out.add(fmt(value, kind))
            except (TypeError, ValueError, OverflowError):
                continue
    return {r for r in out if r}


def _bounded(s: str) -> re.Pattern:
    """Match `s` only where it is not glued to other digits or letters ("4" must not match inside "44" or "4.5")."""
    pre = r"(?<!\d)(?<!\d[.,])" if s[0].isdigit() else (r"(?<!\w)" if s[0].isalnum() else "")
    post = r"(?!\d)(?![.,]\d)" if s[-1].isdigit() else (r"(?!\w)" if s[-1].isalnum() else "")
    return re.compile(pre + re.escape(s) + post)


def validate_rendered(text: str, slots: dict, *, formats: dict | None = None,
                      allowed_literals=()) -> ValidationResult:
    """Every number in `text` must be a formatted slot value.

    With `formats` (slot -> render format, as the template fixes them) a slot counts only in that format; without it,
    any format that fits the value's type counts ("20%" and "20.4%" both match 0.204). Formatted slot values are
    removed first (longest first, never inside a longer number); any digit, numeral, number word or number symbol
    left over is an error. `allowed_literals` are fixed strings of a reviewed template ("52 weeks" -> "52")."""
    if not isinstance(text, str):
        return _result(["empty"])
    rest = text
    pieces = sorted(_renderings(slots, formats) | {str(x) for x in allowed_literals if str(x)}, key=len, reverse=True)
    for piece in pieces:
        rest = _bounded(piece).sub(" ∎ ", rest)
    errors = [e.replace("digit:", "number_not_from_slot:", 1) for e in _numerals(rest)]
    errors += _term_errors(rest, categories=("number_word",))
    errors += _hidden_chars(text)
    return _result(errors)


def template_literals(template_text: str) -> list[str]:
    """Numbers and number words written into a fixed template's own text (outside its placeholders)."""
    prose = _PLACEHOLDER.sub(" ∎ ", template_text)
    found = [m.group(0) for m in _NUMBER_RUN.finditer(prose)]
    found += [m.group(0) for m in _COMPILED["number_word"].finditer(_normalise(prose))]
    return list(dict.fromkeys(found))
