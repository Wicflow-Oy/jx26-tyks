"""The number and wording guard on narrated text (CONTRACTS.md section 6)."""

import pytest

from aei.validator import template_literals, validate_rendered, validate_skeleton

SLOTS = ["ward_label", "organism_label", "n_patients", "n_share", "pattern", "first_date", "rate"]


@pytest.mark.parametrize(
    "skeleton",
    [
        "{ward_label}: {organism_label} in {n_patients} patients share an antibiogram ({pattern}). Typing advised.",
        "{ward_label}: unusual pattern since {first_date}; {n_share} of {n_patients} patients. Profile match, not typing.",
        "{ward_label}: epätavallinen löydös, {organism_label} {n_patients} potilaalla. Tyypitys suositeltava.",
        # Swedish "ett"/"en" are the indefinite article here, not the number one.
        "{ward_label}: ett ovanligt mönster av {organism_label} hos {n_patients} patienter. Typning rekommenderas.",
    ],
)
def test_clean_skeletons_pass(skeleton):
    assert validate_skeleton(skeleton, SLOTS).ok


@pytest.mark.parametrize(
    "skeleton, error",
    [
        ("{n_patients} patients, 3 since Monday", "digit:3"),
        ("Patient P-0012 on {ward_label}", "digit:0012"),
        ("three patients on {ward_label}", "number_word:three"),
        ("a dozen patients", "number_word:dozen"),
        ("half of the patients", "number_word:half"),
        ("twice as many", "number_word:twice"),
        ("over a hundred results", "number_word:hundred"),
        ("{rate} percent resistant", "number_word:percent"),
        ("kolme potilasta osastolla {ward_label}", "number_word:kolme"),
        ("yksi potilas", "number_word:yksi"),
        ("puolet potilaista", "number_word:puolet"),
        ("sata tulosta", "number_word:sata"),
        ("tre patienter på {ward_label}", "number_word:tre"),
        ("två patienter", "number_word:två"),
        ("hälften av patienterna", "number_word:hälften"),
        ("hundra resultat", "number_word:hundra"),
    ],
)
def test_numbers_rejected(skeleton, error):
    result = validate_skeleton(skeleton, SLOTS)
    assert not result.ok and error in result.errors


@pytest.mark.parametrize(
    "skeleton, category",
    [
        ("Resistance doubled on {ward_label}", "comparison"),
        ("{rate} is three times higher", "comparison"),
        ("an x-fold rise", "comparison"),
        ("up by several percentage points", "comparison"),
        ("an increase of {rate}", "comparison"),
        ("resistance rose by {rate}", "comparison"),
        ("resistance fell by {rate}", "comparison"),
        ("This predicts spread to other wards", "prediction"),
        ("the forecast for {ward_label}", "prediction"),
        ("the odds of resistance", "prediction"),
        ("cases are likely to increase", "prediction"),
        ("the probability of a cluster", "prediction"),
        ("meropenem is the best choice", "prediction"),
        ("the recommended drug is meropenem", "prediction"),
        ("resistance will rise", "prediction"),
        ("the earlier pattern was a decoy", "restricted"),
        ("outbreak confirmed on {ward_label}", "restricted"),
        ("results as S/I/R", "restricted"),
        ("zero resistance on {ward_label}", "restricted"),
        ("give a dose of vancomycin", "dosing"),
        ("adjust dosing", "dosing"),
        ("vancomycin mg", "dosing"),
        ("g/day", "dosing"),
        ("x daily", "dosing"),
        ("per kg", "dosing"),
    ],
)
def test_banned_wording_rejected(skeleton, category):
    result = validate_skeleton(skeleton, SLOTS)
    assert not result.ok
    assert any(e.startswith(category + ":") for e in result.errors), result.errors


def test_unknown_slot_and_format_spec_rejected():
    assert "unknown_slot:dose" in validate_skeleton("{ward_label} {dose}", SLOTS).errors
    assert "format_spec:rate:pct0" in validate_skeleton("{rate:pct0} resistant", SLOTS).errors


def test_hidden_characters_cannot_split_a_number_word():
    assert not validate_skeleton("th\u200bree patients", SLOTS).ok


def test_empty_skeleton_rejected():
    assert validate_skeleton("   ", SLOTS).errors == ["empty"]


def test_rendered_numbers_must_come_from_slots():
    slots = {"n": 13, "m": 12, "rate": 0.204, "first": "2026-03-03"}
    assert validate_rendered("ICU: 13 patients, 12 of 13 share it; 20.4% since 3 Mar", slots).ok
    assert validate_rendered("ICU: 13 patients, 20% resistant", slots).ok  # pct0 is a valid rendering of 0.204
    assert validate_rendered("ICU: 14 patients", slots).errors == ["number_not_from_slot:14"]
    assert not validate_rendered("ICU: 13 patients, about a dozen", slots).ok


def test_slot_number_never_matches_inside_a_longer_number():
    assert validate_rendered("44 patients", {"n": 4}).errors == ["number_not_from_slot:44"]


def test_fixed_formats_are_strict():
    assert not validate_rendered("20% resistant", {"rate": 0.204}, formats={"rate": "pct1"}).ok
    assert validate_rendered("20.4% resistant", {"rate": 0.204}, formats={"rate": "pct1"}).ok


def test_template_literals_are_allowed_only_when_passed():
    template = "{rate:pct1} resistant (last 52 weeks)"
    assert template_literals(template) == ["52"]
    assert not validate_rendered("20.4% resistant (last 52 weeks)", {"rate": 0.204}).ok
    assert validate_rendered(
        "20.4% resistant (last 52 weeks)", {"rate": 0.204}, allowed_literals=template_literals(template)
    ).ok
