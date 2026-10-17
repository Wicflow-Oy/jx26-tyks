"""Coverage cells for My ward (CONTRACTS.md section 4.1). Ported from the analysis scripts 11_fixes, 26_trace and 36b.

Coverage semantics (11_fixes / 26_trace `s_col`, kept exactly):
- an isolate is covered when it is S to the drug; a combination ("MEM+VAN") is covered when any member is covered;
- EUCAST intrinsic (`config.INTRINSIC`) and "no breakpoint" (`config.NO_BREAKPOINT`) pairs count as tested and NOT covered;
- S. aureus cefuroxime, ceftriaxone, piperacillin-tazobactam and meropenem follow the cefoxitin screen, and S. aureus
  ampicillin is not reported (penicillinase unknown); E. faecalis piperacillin-tazobactam and meropenem follow ampicillin;
- any other untested pair is excluded from `tested`.

Estimate rule (by `stats.n_state` of the tested count):
- `ok` (>= 30): the observed share with its Jeffreys interval;
- `low_n` (10..29): the stabilised estimate, i.e. the 36b "window WISCA". Each organism's window share is pooled with
  k = POOLING_K pseudo-isolates toward the hospital-wide as-of rate for that organism (same specimen group), and the
  organism mix is a Dirichlet over the window counts plus 5 pseudo-isolates of the hospital mix. Median and 2.5/97.5
  percentiles of COVERAGE_DRAWS draws from a fresh `stats.rng()` (so every cell is reproducible on its own);
- `not_enough_data` (< 10): no percentage at all. The observed x of n is always present.

The "changed" flag runs `stats.change_test` on NOT-covered counts against the unit's prior 52 weeks, in both directions
(more not-covered = coverage down; fewer = coverage up), each at `config.CHANGE_ALPHA`.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as C
from . import stats

KEYS = tuple(C.DRUGS) + tuple(C.COMBOS)          # every single drug and combination a cell can be built for
KEY_INDEX = {k: i for i, k in enumerate(KEYS)}
RAW_INDEX = {d: i for i, d in enumerate(C.DRUGS)}
FLAGS = ("esbl", "mrsa", "vre", "cpe")
MIX_PSEUDO = 5                                     # hospital-mix pseudo-isolates in the organism-mix prior (26_trace)
LOCAL_SETTING = float(getattr(C, "LOCAL_COVERAGE_SETTING", 0.80))
LOCAL_SETTING_LABEL = "local setting, set by stewardship"

_SA, _EF = "Staphylococcus aureus", "Enterococcus faecalis"
_SA_FOLLOW_FOX = ("CXM", "CRO", "TZP", "MEM")
_EF_FOLLOW_AMP = ("TZP", "MEM")


def parts(key: str) -> tuple[str, ...]:
    """Member drugs of a key: ("MEM",) or ("MEM", "VAN")."""
    if key in C.COMBOS:
        return tuple(C.COMBOS[key])
    if key in C.DRUG_NAMES:
        return (key,)
    raise ValueError(f"unknown drug {key}")


def label(key: str) -> str:
    names = [C.DRUG_NAMES[d] for d in parts(key)]
    return " + ".join([names[0]] + [n.lower() for n in names[1:]])


def aware(key: str) -> str:
    groups: list[str] = []
    for d in parts(key):
        g = C.AWARE.get(d, "unknown")
        if g not in groups:
            groups.append(g)
    return "+".join(groups)


def short_organism(name: str) -> str:
    """'Staphylococcus aureus' -> 'S. aureus'."""
    bits = str(name).split()
    return f"{bits[0][0]}. {' '.join(bits[1:])}" if len(bits) > 1 else str(name)


def never_covered(organism: str, drug: str) -> bool:
    return drug in C.INTRINSIC.get(organism, ()) or drug in C.NO_BREAKPOINT.get(organism, ())


def _s_values(df: pd.DataFrame, drug: str) -> np.ndarray:
    """1.0 covered, 0.0 not covered, NaN untested, for one drug, honouring the 26_trace rules (vectorised `s_col`)."""
    col = df[drug]
    v = np.where(col.notna().to_numpy(), (col == "S").to_numpy(dtype=float), np.nan)
    org = df["organism"].to_numpy()
    if drug in _SA_FOLLOW_FOX:
        m = org == _SA
        v[m] = (df["FOX"] == "S").to_numpy(dtype=float)[m]
    if drug == "AMP":
        v[org == _SA] = np.nan
    if drug in _EF_FOLLOW_AMP:
        m = org == _EF
        v[m] = (df["AMP"] == "S").to_numpy(dtype=float)[m]
    for o in np.unique(org):
        if never_covered(o, drug):
            v[org == o] = 0.0
    return v


def indicator_matrix(df: pd.DataFrame) -> np.ndarray:
    """(rows x KEYS) coverage indicators; a combination is the NaN-aware max of its members."""
    single = {d: _s_values(df, d) for d in C.DRUGS}
    cols = [single[k] if k in single else np.fmax.reduce([single[p] for p in parts(k)]) for k in KEYS]
    return np.column_stack(cols) if len(df) else np.zeros((0, len(KEYS)))


def raw_matrix(df: pd.DataFrame) -> np.ndarray:
    """(rows x DRUGS) lab-reported results: 1.0 S, 0.0 R, NaN untested (no coverage rules; for the antibiogram)."""
    if not len(df):
        return np.zeros((0, len(C.DRUGS)))
    return np.column_stack([np.where(df[d].notna().to_numpy(), (df[d] == "S").to_numpy(dtype=float), np.nan) for d in C.DRUGS])


@dataclass(frozen=True)
class Counts:
    """Per-organism counts of one set of (already deduplicated) isolates. Arrays share the row order of `orgs`."""
    orgs: tuple
    n: np.ndarray        # (O,) isolates (all arrays int64)
    cov: np.ndarray      # (O, KEYS) covered
    tst: np.ndarray      # (O, KEYS) tested (incl. intrinsic / no-breakpoint pairs, which count as not covered)
    s_raw: np.ndarray    # (O, DRUGS) reported S
    t_raw: np.ndarray    # (O, DRUGS) reported S or R
    flags: np.ndarray    # (O, FLAGS) marker counts

    @property
    def total(self) -> int:
        return int(self.n.sum())

    def __add__(self, other: "Counts") -> "Counts":
        assert self.orgs == other.orgs
        return Counts(self.orgs, self.n + other.n, self.cov + other.cov, self.tst + other.tst,
                      self.s_raw + other.s_raw, self.t_raw + other.t_raw, self.flags + other.flags)


def counts_from_arrays(orgs: tuple, org_code: np.ndarray, ind: np.ndarray, raw: np.ndarray, flags: np.ndarray) -> Counts:
    """Aggregate row-level arrays (org_code indexes `orgs`) into per-organism Counts."""
    one_hot = np.zeros((len(org_code), len(orgs)))
    one_hot[np.arange(len(org_code)), org_code] = 1.0
    e = one_hot.T

    def i64(a):
        return np.rint(a).astype(np.int64)

    return Counts(orgs, i64(one_hot.sum(axis=0)), i64(e @ np.nan_to_num(ind)), i64(e @ (~np.isnan(ind))),
                  i64(e @ np.nan_to_num(raw)), i64(e @ (~np.isnan(raw))), i64(e @ flags))


def counts_of(rows: pd.DataFrame, orgs: tuple | None = None) -> Counts:
    """Counts of a DataFrame of isolate rows (the caller applies the window and the counting rule)."""
    orgs = tuple(sorted(rows["organism"].unique())) if orgs is None else orgs
    code = {o: i for i, o in enumerate(orgs)}
    org_code = np.array([code[o] for o in rows["organism"]], dtype=int)
    flags = rows[list(FLAGS)].to_numpy(dtype=float) if len(rows) else np.zeros((0, len(FLAGS)))
    return counts_from_arrays(orgs, org_code, indicator_matrix(rows), raw_matrix(rows), flags)


def stabilised(win: Counts, ref: Counts, key: str, k: float = C.POOLING_K, sims: int = C.COVERAGE_DRAWS,
               rng: np.random.Generator | None = None) -> dict | None:
    """36b window WISCA for one key: window shares pooled per organism toward the reference (hospital as-of) rate.

    Returns {"pct", "ci", "excluded_share"} or None when no organism in the reference is tested for the key."""
    j = KEY_INDEX[key]
    keep = ref.tst[:, j] > 0
    if not keep.any():
        return None
    rng = stats.rng() if rng is None else rng
    ph = (ref.cov[keep, j] + 0.5) / (ref.tst[keep, j] + 1)
    wc, wt = win.cov[keep, j], win.tst[keep, j]
    a = wc + k * ph + 1e-6
    b = (wt - wc) + k * (1 - ph) + 1e-6
    theta = rng.beta(a[:, None], b[:, None], size=(int(keep.sum()), sims))
    hn = ref.n[keep]
    pis = rng.dirichlet(win.n[keep] + hn / hn.sum() * MIX_PSEUDO, sims)
    cov = (pis * theta.T).sum(axis=1)
    return {"pct": float(np.median(cov)), "ci": [float(np.percentile(cov, 2.5)), float(np.percentile(cov, 97.5))],
            "excluded_share": float(1 - hn.sum() / ref.n.sum())}


def untested(win: Counts, key: str) -> list[tuple[str, int]]:
    """Organisms with isolates that have no usable result for the key, largest first: [(organism, n_untested)]."""
    j = KEY_INDEX[key]
    gap = win.n - win.tst[:, j]
    out = [(o, int(g)) for o, g in zip(win.orgs, gap) if g > 0]
    return sorted(out, key=lambda t: (-t[1], t[0]))


def _changed(covered: int, tested: int, prior: Counts | None, anchor: Counts | None, j: int) -> dict | None:
    if prior is None or tested <= 0:
        return None
    n_p = int(prior.tst[:, j].sum())
    if n_p <= 0:
        return None
    x_p = n_p - int(prior.cov[:, j].sum())
    anchor = prior if anchor is None else anchor
    n_h = int(anchor.tst[:, j].sum())
    x_h = n_h - int(anchor.cov[:, j].sum())
    x_w = tested - covered
    up = stats.change_test(x_w, tested, x_p, n_p, x_h, n_h, direction="up")      # more not-covered: coverage down
    dn = stats.change_test(x_w, tested, x_p, n_p, x_h, n_h, direction="down")    # fewer not-covered: coverage up
    if up["changed"]:
        changed, p, direction = True, up["p"], "down"
    elif dn["changed"]:
        changed, p, direction = True, dn["p"], "up"
    else:
        changed, p, direction = False, min(up["p"], dn["p"]), None
    return {"changed": changed, "p": float(p), "direction": direction, "prior_pct": float(1 - up["prior"]),
            "prior": {"covered": n_p - x_p, "tested": n_p}}


def cell_from_counts(win: Counts, key: str, prior: Counts | None = None, hosp: Counts | None = None,
                     hosp_prior: Counts | None = None, *, rng: np.random.Generator | None = None) -> dict:
    """The contract cell from precomputed Counts (the fast path used by views).

    win: the window; prior: the unit's prior 52 weeks; hosp: hospital-wide as-of reference (same specimen group) for the
    stabilised estimate; hosp_prior: hospital-wide prior 52 weeks, the change test's anchor (falls back to hosp)."""
    j = KEY_INDEX[key]
    covered, tested, n_iso = int(win.cov[:, j].sum()), int(win.tst[:, j].sum()), win.total
    state = stats.n_state(tested)
    observed = {"covered": covered, "tested": tested, "pct": None, "ci": None}
    if state != "not_enough_data":
        observed["pct"] = covered / tested
        observed["ci"] = list(stats.jeffreys_interval(covered, tested))
    estimate = {"pct": None, "ci": None, "method": None}
    if state == "ok":
        estimate = {"pct": observed["pct"], "ci": observed["ci"], "method": "observed"}
    elif state == "low_n":
        ref = hosp if hosp is not None else (win + prior if prior is not None else win)
        s = stabilised(win, ref, key, rng=rng)
        estimate = ({"pct": observed["pct"], "ci": observed["ci"], "method": "observed"} if s is None else
                    {"pct": s["pct"], "ci": s["ci"], "method": "stabilised", "k": C.POOLING_K})
    share = tested / n_iso if n_iso else None
    return {
        "drug": key, "label": label(key), "aware": aware(key),
        "n_isolates": n_iso, "observed": observed, "estimate": estimate, "state": state,
        "eligible": None if share is None else bool(share >= C.ELIGIBLE_MIN_TESTED_SHARE - 1e-12),
        "tested_share": share,
        "changed": _changed(covered, tested, prior, hosp_prior if hosp_prior is not None else hosp, j),
        "below_local_setting": None if estimate["pct"] is None else bool(estimate["pct"] < LOCAL_SETTING),
    }


def cell(rows: pd.DataFrame, drug: str, prior_rows: pd.DataFrame | None = None, hosp_rows: pd.DataFrame | None = None,
         *, hosp_prior_rows: pd.DataFrame | None = None) -> dict:
    """Coverage cell for one drug or combination key ("MEM+VAN") from isolate DataFrames (CONTRACTS 4.1).

    rows: the window's isolates, already filtered and deduplicated under the counting rule;
    prior_rows: the same unit's prior 52 weeks (for "changed"); hosp_rows: hospital-wide isolates of the same specimen
    group up to as-of (the stabilised estimate's reference); hosp_prior_rows: hospital-wide prior 52 weeks (the change
    test's anchor; defaults to hosp_rows)."""
    parts(drug)
    frames = [f for f in (rows, prior_rows, hosp_rows, hosp_prior_rows) if f is not None]
    orgs = tuple(sorted(set().union(*[set(f["organism"].unique()) for f in frames])))

    def cnt(f):
        return None if f is None else counts_of(f, orgs)

    return to_json(cell_from_counts(cnt(rows), drug, cnt(prior_rows), cnt(hosp_rows), cnt(hosp_prior_rows)))


def to_json(obj):
    """Plain Python types only: numpy scalars -> int/float, NaN/inf -> None, tuples -> lists, timestamps -> dates."""
    if isinstance(obj, dict):
        return {str(k): to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_json(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if not np.isfinite(f) else f
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    return obj
