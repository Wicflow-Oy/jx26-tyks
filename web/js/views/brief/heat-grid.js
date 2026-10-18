// The ward heat map over time: one row per hospital unit, one column per week (the as-of week last). Each cell takes
// the colour of that unit's most serious open item that week and prints its glyph, so colour is never the only
// signal. A cell opens that week.

import { h } from "../../dom.js";
import { dateShort } from "../../format.js";
import { t } from "../../i18n.js";
import { unitStatus } from "../../signals.js";
import { setAsOf } from "../../state.js";

const GLYPH_TEXT = { P1: "!", P2: "▲", P3: "●", info: "i", gap: "–" };

export function heatGrid(brief, history) {
  const units = brief.map?.units ?? [];
  return h(
    "div",
    { class: "heatgrid" },
    h("h3", { class: "eyebrow" }, t("brief.map.history", { n: history.length })),
    h(
      "table",
      { class: "heat" },
      h(
        "thead",
        null,
        h(
          "tr",
          null,
          h("th", { scope: "col", class: "sr" }, t("brief.map.units")),
          history.map((week) => h("th", { scope: "col" }, dateShort(week.asOf))),
        ),
      ),
      h(
        "tbody",
        null,
        units.map((unit) =>
          h(
            "tr",
            null,
            h("th", { scope: "row" }, unit.ward),
            history.map((week) => heatCell(unit, week, week.asOf === history.at(-1).asOf)),
          ),
        ),
      ),
    ),
  );
}

function heatCell(unit, week, current) {
  const weekUnit = (week.brief.map?.units ?? []).find((u) => u.ward === unit.ward) ?? { state: "no_data" };
  const status = unitStatus(week.brief, weekUnit);
  const lit = weekUnit.state === "signal" || weekUnit.state === "changed";
  const heat = lit && status.glyph ? `heat-${status.glyph.toLowerCase()}` : weekUnit.state === "no_data" ? "gap" : "";
  const label = t("brief.map.cell", { unit: unit.label ?? unit.ward, date: dateShort(week.asOf), state: status.word });
  return h(
    "td",
    null,
    h(
      "button",
      {
        type: "button",
        class: ["hcell", heat, current && "now"],
        title: label,
        "aria-label": label,
        "aria-current": current ? "date" : null,
        onclick: () => setAsOf(week.asOf),
      },
      lit || weekUnit.state === "no_data" ? (GLYPH_TEXT[status.glyph] ?? "") : "",
    ),
  );
}
