"""The one evidence object every detector, the brief, the API and the order card share. See CONTRACTS.md section 3."""

import hashlib
import json

KINDS = (
    "phenotype_cluster",
    "thl_rule",
    "count_stepup",
    "ward_outlier",
    "resistance_change",
    "policy_line",
    "seen_before",
    "expert_rule",
    "completeness",
)
PRIORITIES = ("P1", "P2", "P3", "info")


def signal_id(kind: str, key: dict) -> str:
    """Stable id: same kind + key (ward, organism, profile, first sample date...) -> same id in every week's replay."""
    raw = json.dumps({"kind": kind, **key}, sort_keys=True, default=str)
    return f"{kind[:3]}-{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def make_signal(
    kind: str,
    key: dict,
    *,
    priority: str,
    as_of,
    template_id: str,
    slots: dict,
    evidence: dict,
    ward=None,
    home_area=None,
    specimen=None,
    organism=None,
    drug=None,
    first_sample_date=None,
    status: str = "new",
    section: str | None = None,
    advice: str | None = None,
) -> dict:
    """Build a signal dict. `slots` holds every number the text uses; `evidence` is how to recount them."""
    from .render import render_id

    assert kind in KINDS and priority in PRIORITIES, (kind, priority)
    for k in ("filter", "counts", "method"):
        assert k in evidence, f"evidence needs {k}"
    return {
        "id": signal_id(kind, key),
        "kind": kind,
        "priority": priority,
        "status": status,
        "section": section,
        "as_of": str(as_of)[:10],
        "ward": ward,
        "home_area": home_area,
        "specimen": specimen,
        "organism": organism,
        "drug": drug,
        "first_sample_date": None if first_sample_date is None else str(first_sample_date)[:10],
        "template_id": template_id,
        "slots": slots,
        "text": render_id(template_id, slots),
        "advice": advice,
        "evidence": evidence,
        "key": key,
    }
