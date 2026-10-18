// The dumbbell on one shared 0–100 axis: hollow ring = the year, filled dot = the recent window, grey band = its
// interval, a tick = the observed share when the dot is stabilised, and the dashed local-setting rule.
// Decorative: the row's accessible name carries the same numbers.

import { h } from "../../dom.js";
import { changeOf, shown } from "./cells.js";

const at = (share) => `${(share * 100).toFixed(1)}%`;

/** dumbbell({ recent, year, line }): recent and year are cells (either may be null); line is a share or null. */
export function dumbbell({ recent, year, line }) {
  const now = shown(recent);
  const before = shown(year);
  const change = changeOf(recent);
  return h(
    "span",
    { class: "db", "aria-hidden": "true" },
    line != null && h("span", { class: "rule", style: { left: at(line) } }),
    now?.ci && h("span", { class: "band", style: { left: at(now.ci[0]), width: at(now.ci[1] - now.ci[0]) } }),
    now &&
      before &&
      h("span", {
        class: ["conn", change],
        style: { left: at(Math.min(now.share, before.share)), width: at(Math.abs(now.share - before.share)) },
      }),
    before && h("span", { class: "d12", style: { left: at(before.share) } }),
    now?.stabilised &&
      recent.observed?.pct != null &&
      h("span", { class: "obs", style: { left: at(recent.observed.pct) } }),
    now && h("span", { class: "d4", style: { left: at(now.share) } }),
  );
}
