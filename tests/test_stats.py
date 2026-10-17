"""Tests for the shared statistical primitives in aei/stats.py (pure functions; no data needed)."""
import math

import numpy as np
import pytest
from scipy import stats as st

from aei import config as C
from aei import stats


def test_jeffreys_matches_beta_quantiles():
    lo, hi = stats.jeffreys_interval(11, 24)
    assert lo == pytest.approx(st.beta.ppf(0.025, 11.5, 13.5))
    assert hi == pytest.approx(st.beta.ppf(0.975, 11.5, 13.5))
    assert round(100 * lo) == 27 and round(100 * hi) == 65  # the ICU meropenem "11 of 24" cell


def test_jeffreys_edges():
    assert stats.jeffreys_interval(0, 0) == (0.0, 1.0)
    lo, hi = stats.jeffreys_interval(0, 20)
    assert lo == 0.0 and 0 < hi < 0.2
    lo, hi = stats.jeffreys_interval(20, 20)
    assert hi == 1.0 and 0.8 < lo < 1
    lo90, hi90 = stats.jeffreys_interval(5, 10, level=0.90)
    lo95, hi95 = stats.jeffreys_interval(5, 10)
    assert lo95 < lo90 < 0.5 < hi90 < hi95


@pytest.mark.parametrize("n,state", [(0, "not_enough_data"), (9, "not_enough_data"), (10, "low_n"), (29, "low_n"),
                                     (30, "ok"), (5000, "ok")])
def test_n_state_boundaries(n, state):
    assert stats.n_state(n) == state


def test_prior_rate_shrinks_toward_hospital():
    ph = (5 + 0.5) / (100 + 1)
    assert stats.prior_rate(0, 0, 5, 100) == pytest.approx(ph)
    assert stats.prior_rate(20, 100, 5, 100) == pytest.approx((20 + 10 * ph) / 110)
    assert stats.prior_rate(20, 100, 5, 100, m=0) == pytest.approx(0.2)


def test_change_test_matches_beta_binomial_by_hand():
    prior = stats.prior_rate(4, 177, 300, 4000)
    s = min(177 + 10, 200)
    a, b = prior * s, (1 - prior) * s
    r = stats.change_test(13, 24, 4, 177, 300, 4000)
    assert r["prior"] == pytest.approx(prior) and r["expected"] == pytest.approx(prior * 24)
    assert r["p"] == pytest.approx(st.betabinom.sf(12, 24, a, b))
    assert r["changed"] is True
    dn = stats.change_test(13, 24, 4, 177, 300, 4000, direction="down")
    assert dn["p"] == pytest.approx(st.betabinom.cdf(13, 24, a, b)) and dn["changed"] is False


def test_change_test_prior_strength_is_capped():
    # with n_prior far above 200 the predictive spread stops shrinking: same p for 1,000 and 100,000 prior isolates
    # (hospital anchor chosen so both priors are exactly 10%)
    p1 = stats.change_test(8, 40, 100, 1000, 1000, 10004)
    p2 = stats.change_test(8, 40, 10000, 100000, 1000, 10004)
    assert p1["prior"] == pytest.approx(0.1) and p2["prior"] == pytest.approx(0.1)
    assert p1["p"] == pytest.approx(p2["p"], rel=1e-9)
    p_weak = stats.change_test(8, 40, 10, 100, 1000, 10004)["p"]
    assert p_weak > p1["p"]  # a weaker prior (110 pseudo-isolates) is less surprised


def test_change_test_quiet_and_empty():
    assert stats.change_test(0, 0, 10, 100, 10, 100) == {"p": 1.0, "changed": False, "prior": pytest.approx(stats.prior_rate(10, 100, 10, 100)), "expected": 0.0}
    r = stats.change_test(2, 20, 10, 100, 100, 1000)
    assert r["changed"] is False and r["p"] > C.CHANGE_ALPHA


def test_pooled_estimate_and_interval():
    est = stats.pooled_estimate(11, 24, 0.98)
    assert est == pytest.approx((11 + C.POOLING_K * 0.98) / (24 + C.POOLING_K))
    lo, hi = stats.pooled_interval(11, 24, 0.98)
    a, b = 11 + C.POOLING_K * 0.98, 13 + C.POOLING_K * 0.02
    assert lo == pytest.approx(st.beta.ppf(0.025, a, b)) and hi == pytest.approx(st.beta.ppf(0.975, a, b))
    assert lo < est < hi
    assert stats.pooled_estimate(5, 10, 0.5, k=0) == pytest.approx(0.5)


def test_poisson_sf():
    assert stats.poisson_sf(0, 3.0) == 1.0
    assert stats.poisson_sf(1, 2.0) == pytest.approx(1 - math.exp(-2.0))
    assert stats.poisson_sf(5, 1.0) == pytest.approx(1 - sum(math.exp(-1) / math.factorial(k) for k in range(5)))


def test_rng_is_reproducible():
    a = stats.rng().beta(2, 3, 5)
    b = stats.rng().beta(2, 3, 5)
    assert np.array_equal(a, b)
    assert not np.array_equal(stats.rng(1).random(3), stats.rng(2).random(3))
