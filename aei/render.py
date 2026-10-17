"""Code renders every number. Templates hold {slot} or {slot:format} placeholders; formats are fixed here.

Formats:  pct0 -> "74%"   pct1 -> "20.4%"   ci0 -> "61-85" (a (lo, hi) pair of proportions)
          int -> "1,350"  date -> "9 Mar 2026"  short_date -> "9 Mar"  xofn -> "11 of 24" (an (x, n) pair)
          text -> str(value) (names, ward labels; never a number)
"""
import re

import pandas as pd

_SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)(?::([a-z0-9_]+))?\}")


def fmt(value, kind: str) -> str:
    if value is None:
        return "not available"
    if kind == "pct0":
        return f"{round(100 * float(value)):.0f}%"
    if kind == "pct1":
        return f"{100 * float(value):.1f}%"
    if kind == "ci0":
        lo, hi = value
        return f"{round(100 * lo):.0f}–{round(100 * hi):.0f}"
    if kind == "ci1":
        lo, hi = value
        return f"{100 * lo:.1f}–{100 * hi:.1f}"
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

