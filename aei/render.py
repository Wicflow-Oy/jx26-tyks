"""Code renders every number. Templates hold {slot} or {slot:format} placeholders; formats are fixed here.

Formats:  pct0 -> "74%"   pct1 -> "20.4%"   ci0 -> "61-85" (a (lo, hi) pair of proportions)
          int -> "1,350"  date -> "9 Mar 2026"  short_date -> "9 Mar"  xofn -> "11 of 24" (an (x, n) pair)
          text -> str(value) (names, ward labels; never a number)

Percentages round half up, as a reader rounding 10 of 16 by hand does (62.5 -> 63; Python's round() gives 62). A
share above 0 never prints as "0%" and a share below 1 never as "100%": they print "<1%" and ">99%".
"""
import re
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

_SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)(?::([a-z0-9_]+))?\}")
_PLACES = {"pct0": 0, "pct1": 1, "ci0": 0, "ci1": 1}  # decimal places of the printed percent


def fmt(value, kind: str) -> str:
    if value is None:
        return "not available"
    if kind in ("pct0", "pct1"):
        return _percent(float(value), _PLACES[kind])
    if kind in ("ci0", "ci1"):
        lo, hi = value
        return f"{_half_up(lo, _PLACES[kind])}–{_half_up(hi, _PLACES[kind])}"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "date":
        d = pd.Timestamp(value)
        return f"{d.day} {d.strftime('%b %Y')}"
    if kind == "short_date":
        d = pd.Timestamp(value)
        return f"{d.day} {d.strftime('%b')}"
    if kind == "xofn":
        x, n = value
        return f"{int(x):,} of {int(n):,}"
    if kind == "text":
        return str(value)
    raise ValueError(f"unknown format {kind}")


def _half_up(share: float, places: int) -> Decimal:
    """100 * share rounded half up. str() gives the shortest decimal that round-trips, so 0.625 stays 0.625."""
    return (Decimal(str(float(share))) * 100).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _percent(share: float, places: int) -> str:
    pct, step = _half_up(share, places), Decimal(1).scaleb(-places)
    if share > 0 and pct == 0:
        return f"<{step}%"
    if share < 1 and pct == 100:
        return f">{100 - step}%"
    return f"{pct}%"


def slots_in(template: str) -> list[tuple[str, str | None]]:
    return _SLOT.findall(template)


def render(template: str, slots: dict, formats: dict | None = None) -> str:
    """Fill a template. Format comes from the placeholder ({x:pct0}), else formats[x], else 'text'.
    Raises KeyError when a slot is missing, so a template can never silently drop a number."""
    formats = formats or {}

    def sub(m):
        name, kind = m.group(1), m.group(2) or formats.get(m.group(1), "text")
        if name not in slots:
            raise KeyError(f"missing slot {name}")
        return fmt(slots[name], kind)

    return _SLOT.sub(sub, template)


def render_id(template_id: str, slots: dict) -> str:
    from .templates import TEMPLATES
    t = TEMPLATES[template_id]
    return render(t["text"], slots, t.get("formats"))

