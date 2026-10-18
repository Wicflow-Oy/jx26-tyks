"""Number formats (aei/render.py): percentages round half up and never print 0% or 100% for a share that is not."""

import pytest

from aei.render import fmt, render


@pytest.mark.parametrize(
    ("x", "n", "pct0", "pct1"),
    [
        (10, 16, "63%", "62.5%"),  # the ICU cefoxitin 10 of 16; Python's round() gives 62
        (2, 16, "13%", "12.5%"),
        (57, 200, "29%", "28.5%"),  # 0.285 is 0.28499... as a float
        (160, 786, "20%", "20.4%"),  # the trimethoprim policy line
        (1, 200, "1%", "0.5%"),
        (1, 435, "<1%", "0.2%"),
        (1, 2000, "<1%", "0.1%"),
        (1, 24571, "<1%", "<0.1%"),
        (434, 435, ">99%", "99.8%"),
        (1999, 2000, ">99%", ">99.9%"),
        (0, 435, "0%", "0.0%"),
        (435, 435, "100%", "100.0%"),
    ],
)
def test_percentages_round_half_up_and_never_hide_a_resistant_isolate(x, n, pct0, pct1):
    assert (fmt(x / n, "pct0"), fmt(x / n, "pct1")) == (pct0, pct1)


def test_intervals_round_half_up():
    assert fmt((0.125, 0.625), "ci0") == "13–63"
    assert fmt((0.61049, 0.8495), "ci1") == "61.0–85.0"


def test_decimals_and_p_values_round_half_up():
    assert (fmt(0.125, "dec2"), fmt(51.35, "dec1"), fmt(0.0125, "p"), fmt(0.0004, "p")) == (
        "0.13",
        "51.4",
        "p = 0.013",
        "p < 0.001",
    )
    assert (fmt(0.125, "dec2", "fi"), fmt(0.0004, "p", "fi")) == ("0,13", "p < 0,001")


def test_render_fills_slots_and_never_drops_one():
    assert (
        render("{counts:xofn} resistant ({rate:pct0})", {"counts": (10, 16), "rate": 10 / 16})
        == "10 of 16 resistant (63%)"
    )
    with pytest.raises(KeyError):
        render("{rate:pct0}", {})
