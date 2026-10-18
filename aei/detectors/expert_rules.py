"""Phenotype consistency checks on reported results (config.EXPERT_RULES), ported from 40_esbl_flag and
52_seen_before_expert_rules and widened per the clinical review (EUCAST Expert Rules v3.3).

Row-level lab checks on every isolate (no deduplication: each implausible report is one result to check):
  esbl_ceph_s         ESBL-flagged but S to cefuroxime or ceftriaxone (local reporting rule)        golden 0 of 517
  mrsa_fox_s          MRSA-flagged S. aureus reported cefoxitin S                                  golden 0 of 111
  cro_r_amp_or_cxm_s  ceftriaxone R with ampicillin S or cefuroxime S, in the species with EUCAST
                      cefuroxime breakpoints; one check, so an isolate failing both is one result   golden 139
  tzp_r_amp_s         piperacillin-tazobactam R with ampicillin S (Expert Rules v3.3 rule 1)        golden 276
The brief lists the hits sampled in the last 7 days, one item per rule.
"""

import logging

import pandas as pd

from .. import config as C
from .. import signal as sig
from ..data import to_json
from . import iso, ts

log = logging.getLogger(__name__)
DAYS = 7


def _orgs(df, rule):
    return df.organism.isin(rule["organisms"]) if rule.get("organisms") else pd.Series(True, index=df.index)


# rule id -> (checked mask, hit mask) on an isolate table
_CHECKS = {
    "esbl_ceph_s": lambda df: (df.esbl == 1, (df.CXM == "S") | (df.CRO == "S")),
    "mrsa_fox_s": lambda df: (df.mrsa == 1, df.FOX == "S"),
    "cro_r_amp_or_cxm_s": lambda df: (df.CRO == "R", (df.AMP == "S") | (df.CXM == "S")),
    "tzp_r_amp_s": lambda df: (df.TZP == "R", df.AMP == "S"),
}


def method(rule: dict) -> str:
    return f"{C.EXPERT_RULES_LABEL} on reported S/R results; {rule['basis']}"


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
        slots = to_json(
            {
                "rule_text": r["text"],
                "n_results": n,
                "results_word": "result" if n == 1 else "results",
                "period_label": "this week" if days == 7 else "in this window",
                "units_text": ", ".join(units),
            }
        )
        evidence = to_json(
            {
                "filter": {
                    "ward": units,
                    "specimen": None,
                    "organism": r.get("organisms"),
                    "drug": None,
                    "date_from": iso(end - pd.Timedelta(days=days - 1)),
                    "date_to": iso(end),
                    "rule": "all_isolates",
                },
                "counts": {"hits": n, "checked": int(checked.sum()), "by_unit": h.ward_code.value_counts().to_dict()},
                "method": method(r),
                "params": {"rule_id": r["id"], "window_days": days},
                "isolate_ids": h.isolate_id.astype(str).tolist(),
            }
        )
        out.append(
            sig.make_signal(
                "expert_rule",
                {"rule": r["id"]},
                priority="P3",
                as_of=iso(end),
                template_id="trend_expert_rule",
                slots=slots,
                evidence=evidence,
                ward=None,
                first_sample_date=str(h.sample_date.min().date()),
                section="data_quality",
                advice="Lab check",
            )
        )
    return out
