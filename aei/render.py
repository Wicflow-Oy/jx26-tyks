"""Code renders every number. Templates hold {slot} or {slot:format} placeholders; formats are fixed here.

Formats:  pct0 -> "74%"   pct1 -> "20.4%"   ci0 -> "61-85" (a (lo, hi) pair of proportions)
          int -> "1,350"  date -> "9 Mar 2026"  short_date -> "9 Mar"  xofn -> "11 of 24" (an (x, n) pair)
          dec1 -> "12.3"  dec2 -> "0.35" (an expected count or a ratio)  p -> "p = 0.012" or "p < 0.001"
          text -> str(value) (names, ward labels; never a number)
Finnish (lang="fi"): "74 %", "20,4 %", "61–85", "1 350", "9.3.2026", "9.3.", "11/24", "0,35", "p < 0,001", with a
no-break space before "%" and between thousands.

Percentages round half up, as a reader rounding 10 of 16 by hand does (62.5 -> 63; Python's round() gives 62). A
share above 0 never prints as "0%" and a share below 1 never as "100%": they print "<1%" and ">99%".
"""

import re
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)(?::([a-z0-9_]+))?\}")  # {name} or {name:format}
_PLACES = {"pct0": 0, "pct1": 1, "ci0": 0, "ci1": 1, "dec1": 1, "dec2": 2}  # decimal places printed
P_FLOOR = Decimal("0.001")  # smaller p-values print as "p < 0.001"
NBSP = "\u00a0"


def fmt(value, kind: str, lang: str = "en") -> str:
    fi = lang == "fi"
    if value is None:
        return "ei tietoa" if fi else "not available"
    if kind in ("pct0", "pct1"):
        return _percent(float(value), _PLACES[kind], fi)
    if kind in ("ci0", "ci1"):
        lo, hi = value
        return f"{_dec(_half_up(lo, _PLACES[kind]), fi)}–{_dec(_half_up(hi, _PLACES[kind]), fi)}"
    if kind == "int":
        return _int(value, fi)
    if kind in ("dec1", "dec2"):
        return _dec(_round(value, _PLACES[kind]), fi)
    if kind == "p":
        return f"p < {_dec(P_FLOOR, fi)}" if value < P_FLOOR else f"p = {_dec(_round(value, 3), fi)}"
    if kind in ("date", "short_date"):
        d = pd.Timestamp(value)
        if fi:
            return f"{d.day}.{d.month}.{d.year}" if kind == "date" else f"{d.day}.{d.month}."
        return f"{d.day} {d.strftime('%b %Y' if kind == 'date' else '%b')}"
    if kind == "xofn":
        x, n = value
        return f"{_int(x, fi)}/{_int(n, fi)}" if fi else f"{_int(x, fi)} of {_int(n, fi)}"
    if kind == "text":
        return str(value)
    raise ValueError(f"unknown format {kind}")


def _int(value, fi: bool) -> str:
    return f"{int(value):,}".replace(",", NBSP if fi else ",")


def _dec(number, fi: bool) -> str:
    return str(number).replace(".", ",") if fi else str(number)


def _round(number: float, places: int) -> Decimal:
    """Rounded half up. str() gives the shortest decimal that round-trips, so 0.625 stays 0.625."""
    return _quantize(Decimal(str(float(number))), places)


def _half_up(share: float, places: int) -> Decimal:
    """100 * share as a percent, rounded half up (the decimal is multiplied, so 0.625 is exactly 62.5)."""
    return _quantize(Decimal(str(float(share))) * 100, places)


def _quantize(number: Decimal, places: int) -> Decimal:
    return number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _percent(share: float, places: int, fi: bool = False) -> str:
    pct, step = _half_up(share, places), Decimal(1).scaleb(-places)
    sign = f"{NBSP}%" if fi else "%"
    if share > 0 and pct == 0:
        return f"<{_dec(step, fi)}{sign}"
    if share < 1 and pct == 100:
        return f">{_dec(100 - step, fi)}{sign}"
    return f"{_dec(pct, fi)}{sign}"


def slots_in(template: str) -> list[tuple[str, str | None]]:
    return SLOT.findall(template)


def render(template: str, slots: dict, formats: dict | None = None, lang: str = "en") -> str:
    """Fill a template. Format comes from the placeholder ({x:pct0}), else formats[x], else 'text'; numbers and dates
    in the locale of `lang`. Raises KeyError when a slot is missing, so a template can never silently drop a number."""
    formats = formats or {}

    def sub(m):
        name, kind = m.group(1), m.group(2) or formats.get(m.group(1), "text")
        if name not in slots:
            raise KeyError(f"missing slot {name}")
        return fmt(slots[name], kind, lang)

    return SLOT.sub(sub, template)


def render_id(template_id: str, slots: dict) -> str:
    from .templates import TEMPLATES

    t = TEMPLATES[template_id]
    return render(t["text"], slots, t.get("formats"))
