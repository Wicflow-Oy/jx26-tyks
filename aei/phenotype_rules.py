"""Effective S/R: the result that My ward and the order view count for one isolate and one drug, and why.

Rules, first match wins. A EUCAST rule that says "report R" comes before the reported result; an inference for an
untested pair comes after it, so it never replaces a result the laboratory reported.

  no_breakpoint        EUCAST gives no breakpoint for the species (config.NO_BREAKPOINT): R.
  intrinsic            EUCAST Expected Resistant Phenotypes v1.2 pair (config.INTRINSIC): R.
  inferred_mrsa        S. aureus, cefoxitin screen positive: every beta-lactam on this panel R.
  reported             the laboratory's S or R.
  inferred_mssa        S. aureus, cefoxitin screen negative: cefuroxime, ceftriaxone, piperacillin-tazobactam and
                       meropenem S. Ampicillin stays untested: penicillinase production is not in the data.
  inferred_ampicillin  E. faecalis piperacillin-tazobactam follows ampicillin.
  local_esbl_rule      ESBL producer: cefuroxime and ceftriaxone R (this laboratory's rule, see config.LOCAL_ESBL_R).
  untested             none of the above; left out of every count.
"""
import numpy as np
import pandas as pd

from . import config as C

SA, EF = "Staphylococcus aureus", "Enterococcus faecalis"
# EUCAST Staphylococcus expert rule 1 (Nov 2025), both directions; ceftaroline and ceftobiprole are the exceptions
# and are not on this panel. The cefoxitin screen itself stays a reported result.
MRSA_R = C.BETA_LACTAMS - {"FOX"}
MSSA_S = {"CXM", "CRO", "TZP", "MEM"}
# EUCAST v16.1 Enterococcus notes 2 and 3: ampicillin-S isolates have no beta-lactam resistance mechanism, and
# tazobactam adds nothing. Meropenem has no enterococcal breakpoint, so it is in config.NO_BREAKPOINT instead.
EF_FROM_AMP = {"TZP"}

REASONS = ("no_breakpoint", "intrinsic", "inferred_mrsa", "reported", "inferred_mssa", "inferred_ampicillin",
           "local_esbl_rule", "untested")
REASON_TEXT = {  # on screen after the result, e.g. "cefuroxime R (inferred: MRSA, cefoxitin screen positive)"
    "no_breakpoint": "no EUCAST breakpoint for this species",
    "intrinsic": "intrinsic resistance (EUCAST)",
    "inferred_mrsa": "inferred: MRSA, cefoxitin screen positive",
    "reported": "reported",
    "inferred_mssa": "inferred: MSSA, cefoxitin screen negative",
    "inferred_ampicillin": "inferred from ampicillin",
    "local_esbl_rule": "local rule: ESBL producers reported R",
    "untested": "not tested",
}


def effective(isolates: pd.DataFrame, drug: str) -> tuple[pd.Series, pd.Series]:
    """(result, reason) for every isolate and one lab drug code: result "S", "R" or None; reason one of REASONS.

    `isolates` needs `organism`; drug columns, `esbl` and `mrsa` are read when present (a missing one = not tested)."""
    x = isolates
    org = x["organism"]
    reported, fox, amp = _column(x, drug), _column(x, "FOX"), _column(x, "AMP")
    mrsa = (org == SA) & ((fox == "R") | (_column(x, "mrsa") == 1))
    mssa = (org == SA) & (fox == "S") & ~mrsa
    rules = [  # (applies, result, reason) in the order of the module docstring
        (_species_pair(org, C.NO_BREAKPOINT, drug), "R", "no_breakpoint"),
        (_species_pair(org, C.INTRINSIC, drug), "R", "intrinsic"),
        (mrsa & (drug in MRSA_R), "R", "inferred_mrsa"),
        (reported.notna(), reported, "reported"),
        (mssa & (drug in MSSA_S), "S", "inferred_mssa"),
        ((org == EF) & amp.notna() & (drug in EF_FROM_AMP), amp, "inferred_ampicillin"),
        ((_column(x, "esbl") == 1) & (drug in C.LOCAL_ESBL_R), "R", "local_esbl_rule"),
    ]
    applies = [np.asarray(a, dtype=bool) for a, _, _ in rules]
    result = np.select(applies, [np.asarray(r, dtype=object) for _, r, _ in rules], default=None)
    reason = np.select(applies, [why for _, _, why in rules], default="untested")
    return pd.Series(result, index=x.index, dtype=object), pd.Series(reason, index=x.index, dtype=object)


def _column(x: pd.DataFrame, name: str) -> pd.Series:
    return x[name] if name in x else pd.Series(None, index=x.index, dtype=object)


def _species_pair(org: pd.Series, table: dict, drug: str) -> pd.Series:
    return org.isin([o for o, drugs in table.items() if drug in drugs])
