"""Shared statistical primitives (pure functions, no pandas). Ported from analysis scripts 06c/33b/39."""
import numpy as np
from scipy import stats as st

from . import config as C


def jeffreys_interval(x: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Jeffreys interval for a binomial proportion x/n; (0, 1) when n == 0."""
    if n <= 0:
        return 0.0, 1.0
    a = (1 - level) / 2
    lo = 0.0 if x == 0 else float(st.beta.ppf(a, x + 0.5, n - x + 0.5))
    hi = 1.0 if x == n else float(st.beta.ppf(1 - a, x + 0.5, n - x + 0.5))
    return lo, hi


def n_state(n: int) -> str:
    """'not_enough_data' (n < 10), 'low_n' (10..29) or 'ok' (>= 30)."""
    if n < C.SMALL_N_NONE:
        return "not_enough_data"
    return "low_n" if n < C.SMALL_N_LOW else "ok"


def prior_rate(x_prior: int, n_prior: int, x_hosp: int, n_hosp: int, m: float = 10) -> float:
    """Unit-level prior rate for the 52 weeks before the window, shrunk toward the hospital-wide rate (39_resistance_hybrid)."""
    ph = (x_hosp + 0.5) / (n_hosp + 1)
    return (x_prior + m * ph) / (n_prior + m)


def change_test(x_w: int, n_w: int, x_prior: int, n_prior: int, x_hosp: int, n_hosp: int,
                alpha: float = C.CHANGE_ALPHA, direction: str = "up") -> dict:
    """Beta-binomial predictive test: is x_w of n_w surprising against the unit's own prior 52 weeks?

    Counts are of the event being monitored (resistant isolates for resistance, NOT-covered for coverage), so
    direction="up" asks "more events than expected". Returns {"p": float, "changed": bool, "prior": float,
    "expected": float}. The prior's strength is capped at 200 pseudo-isolates (39_resistance_hybrid)."""
    prior = prior_rate(x_prior, n_prior, x_hosp, n_hosp)
    if n_w <= 0:
        return {"p": 1.0, "changed": False, "prior": prior, "expected": 0.0}
    s = min(n_prior + 10, 200)
    a, b = prior * s, (1 - prior) * s
    p = float(st.betabinom.sf(x_w - 1, n_w, a, b)) if direction == "up" else float(st.betabinom.cdf(x_w, n_w, a, b))
    return {"p": p, "changed": p < alpha, "prior": prior, "expected": prior * n_w}


def pooled_estimate(x_w: int, n_w: int, prior: float, k: float = C.POOLING_K) -> float:
    """Window estimate pulled toward the prior with k pseudo-isolates (the 'stabilised estimate')."""
    return (x_w + k * prior) / (n_w + k)


def pooled_interval(x_w: int, n_w: int, prior: float, k: float = C.POOLING_K, level: float = 0.95) -> tuple[float, float]:
    """Equal-tailed interval of Beta(x_w + k*prior, n_w - x_w + k*(1-prior))."""
    a, b = x_w + k * prior, n_w - x_w + k * (1 - prior)
    q = (1 - level) / 2
    return float(st.beta.ppf(q, a, b)), float(st.beta.ppf(1 - q, a, b))


def poisson_sf(k: int, mu: float) -> float:
    """P(X >= k) for X ~ Poisson(mu)."""
    return float(st.poisson.sf(k - 1, mu)) if k > 0 else 1.0


def rng(seed: int = 20261017) -> np.random.Generator:
    """Fixed-seed generator: every Monte Carlo result in the app is reproducible."""
    return np.random.default_rng(seed)
