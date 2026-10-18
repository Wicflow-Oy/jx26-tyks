// Interval bar (the policy meter): a 0–max track, the interval band, the value dot and a labelled line.
// Decorative: the row it sits in carries the numbers in words.

import { h } from "../dom.js";
import { pct } from "../format.js";

/**
 * intervalBar({ value: 0.177, interval: [0.152, 0.205], line: 0.2, lineLabel: "20% line", max: 0.4 })
 * All values are shares (0..1). The dot turns --p2 when the value is at or over the line.
 */
export function intervalBar({ value, interval, line, lineLabel, max = 0.4 }) {
  const x = (share) => `${Math.min(100, Math.max(0, (share / max) * 100)).toFixed(1)}%`;
  const hasLine = line != null;
  return h(
    "span",
    { "aria-hidden": "true" },
    h(
      "span",
      { class: "ibar" },
      h("span", { class: "track" }),
      Array.isArray(interval) &&
        h("span", {
          class: "band",
          style: { left: x(interval[0]), width: `calc(${x(interval[1])} - ${x(interval[0])})` },
        }),
      hasLine && h("span", { class: "line", style: { left: x(line) } }),
      hasLine && lineLabel && h("span", { class: "lab", style: { left: x(line) } }, lineLabel),
      value != null && h("span", { class: ["val", hasLine && value >= line && "over"], style: { left: x(value) } }),
    ),
    h("span", { class: "ibar-axis" }, h("span", null, pct(0)), h("span", null, pct(max))),
  );
}
