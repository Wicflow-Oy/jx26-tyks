// Horizontal bars by unit (cultures this week, seen-before patients by unit), with the count at the end of each row.

import { h } from "../dom.js";
import { int } from "../format.js";

/**
 * Horizontal bars by unit: unitBars([["ED", 65], ["ICU", 11]], { label }) with the count at the end of each row.
 * The bar widths are relative to the largest value; label names the list for screen readers.
 */
export function unitBars(entries, { label } = {}) {
  const max = Math.max(1, ...entries.map(([, n]) => n ?? 0));
  return h(
    "ul",
    { class: "bars", "aria-label": label },
    entries.map(([unit, n]) =>
      h(
        "li",
        { class: "b" },
        h("span", { class: "u" }, unit),
        h(
          "span",
          { class: "track", "aria-hidden": "true" },
          h("span", { class: "fill", style: { width: `${((n ?? 0) / max) * 100}%` } }),
        ),
        h("span", { class: "num" }, int(n ?? 0)),
      ),
    ),
  );
}
