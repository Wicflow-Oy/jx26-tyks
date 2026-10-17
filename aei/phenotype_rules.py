"""Effective S/R for one isolate and one drug: the reported result, else deterministic expert rules.

Order: intrinsic resistance (config.INTRINSIC) -> reported result -> MRSA implies beta-lactam R -> ESBL implies
penicillin/cephalosporin R. Returns (result or None, reason). Reasons are shown on screen ("inferred from MRSA")."""
import pandas as pd
from . import config as C


def _get(row, key, default=None):
    try:
        v = row[key]
    except (KeyError, IndexError):
        return default
    return default if v is None or (isinstance(v, float) and v != v) else v


def effective_result(row, drug: str) -> tuple[str | None, str]:
    org = _get(row, "organism")
    if org in C.INTRINSIC and drug in C.INTRINSIC[org]:
        return "R", "intrinsic"
    v = _get(row, drug)
    if isinstance(v, str):
        return v, "reported"
    if int(_get(row, "mrsa", 0)) == 1 and drug in C.BETA_LACTAMS:
        return "R", "inferred from MRSA"
    if int(_get(row, "esbl", 0)) == 1 and drug in C.ESBL_IMPLIED_R:
        return "R", "inferred from ESBL"
    return None, "not tested"


def effective_column(df: pd.DataFrame, drug: str) -> pd.Series:
    """Vectorised effective_result()[0] for a frame of isolates ("S"/"R"/None)."""
    out = df[drug].astype(object).where(df[drug].notna(), None) if drug in df else pd.Series(None, index=df.index, dtype=object)
    out[df.organism.map(lambda o: drug in C.INTRINSIC.get(o, set()))] = "R"
    if drug in C.BETA_LACTAMS:
        out[out.isna() & (df.mrsa == 1)] = "R"
    if drug in C.ESBL_IMPLIED_R:
        out[out.isna() & (df.esbl == 1)] = "R"
    return out
