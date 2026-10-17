"""EUCAST expert-rule consistency checks (config.EXPERT_RULES), ported from 40_esbl_flag and 52_seen_before_expert_rules.

Row-level lab checks on every isolate (no deduplication: each implausible report is one result to check):
  esbl_ceph_s  ESBL-flagged but S to cefuroxime or ceftriaxone (the flag implies R)      golden 0 of 517
  mrsa_fox_s   MRSA-flagged S. aureus reported cefoxitin S (MRSA implies FOX R)            golden 0 of 111
  cro_r_amp_s  E. coli ceftriaxone R with ampicillin S
  cro_r_cxm_s  E. coli / K. pneumoniae ceftriaxone R with cefuroxime S
The last two together are the 109 implausible rows of 40/52. The brief lists hits sampled in the last 7 days.
"""
import logging

import pandas as pd

from .. import config as C
from .. import signal as sig
from . import day, plain, ts

log = logging.getLogger(__name__)
DAYS = 7
METHOD = "EUCAST expected-phenotype consistency check on reported S/R results (40_esbl_flag, 52_seen_before_expert_rules)"


def _orgs(df, rule):
    return df.organism.isin(rule["organisms"]) if rule.get("organisms") else pd.Series(True, index=df.index)


# rule id -> (checked mask, hit mask) on an isolate table
_CHECKS = {
    "esbl_ceph_s": lambda df: (df.esbl == 1, (df.CXM == "S") | (df.CRO == "S")),
    "mrsa_fox_s": lambda df: (df.mrsa == 1, df.FOX == "S"),
    "cro_r_amp_s": lambda df: (df.CRO == "R", df.AMP == "S"),
    "cro_r_cxm_s": lambda df: (df.CRO == "R", df.CXM == "S"),
}


def masks(df: pd.DataFrame, rule_id: str) -> tuple[pd.Series, pd.Series]:
    """(checked, hit) boolean masks for one config rule; hit implies checked."""
    rule = next(r for r in C.EXPERT_RULES if r["id"] == rule_id)
    checked, hit = _CHECKS[rule_id](df)
    checked = checked & _orgs(df, rule)
    return checked, checked & hit


def rule_counts(df: pd.DataFrame) -> dict:
    """{rule_id: {"checked": n, "hits": n}} for the rows given (all isolates for the goldens)."""
    out = {}
    for r in C.EXPERT_RULES:
        if r["id"] not in _CHECKS:
            log.warning("expert rule %s has no check implemented; skipped", r["id"])
            continue
        c, h = masks(df, r["id"])
        out[r["id"]] = {"checked": int(c.sum()), "hits": int(h.sum())}
    return out


def detect(ds, as_of, rule: str = "readme_period", days: int = DAYS) -> list[dict]:
    end = ts(as_of)
    w = ds.isolates[(ds.isolates.sample_date > end - pd.Timedelta(days=days)) & (ds.isolates.sample_date <= end)]
    out = []
    for r in C.EXPERT_RULES:
        if r["id"] not in _CHECKS:
            continue
        checked, hit = masks(w, r["id"])
        h = w[hit].sort_values(["sample_date", "isolate_id"])
        if h.empty:
            continue
        units = list(dict.fromkeys(h.ward_code))
        n = len(h)
        slots = plain({"rule_text": r["text"], "n_results": n, "results_word": "result" if n == 1 else "results",
                       "period_label": "this week" if days == 7 else "in this window", "units_text": ", ".join(units)})
        evidence = plain({
            "filter": {"ward": units, "specimen": None, "organism": r.get("organisms"), "drug": None,
                       "date_from": day(end - pd.Timedelta(days=days - 1)), "date_to": day(end), "rule": "all_isolates"},
            "counts": {"hits": n, "checked": int(checked.sum()), "by_unit": h.ward_code.value_counts().to_dict()},
            "method": METHOD,
            "params": {"rule_id": r["id"], "window_days": days},
            "isolate_ids": h.isolate_id.astype(str).tolist(),
        })
        out.append(sig.make_signal(
            "expert_rule", {"rule": r["id"]}, priority="P3", as_of=day(end), template_id="trend_expert_rule",
            slots=slots, evidence=evidence, ward=None, first_sample_date=str(h.sample_date.min().date()),
            section="data_quality", advice="Lab check"))
    return out
