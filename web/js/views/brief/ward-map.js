// The ward map: a schematic 3×3 plan of the hospital units and the cross of primary-care home areas, coloured like a
// heat map by each unit's most serious open item (P1 red, P2 orange, P3 yellow, info pale). Each tile also shows its
// code, the API's map state as a word and the priority glyph, so colour is never the only signal. Then the quiet sentence,
// what quiet means, and the legend. A tile opens its top signal's case file.

import { priorityLabel, tile } from "../../components/badges.js";
import { mk } from "../../components/marker.js";
import { toast } from "../../components/toast.js";
import { h } from "../../dom.js";
import { capitalize, int, word } from "../../format.js";
import { t } from "../../i18n.js";
import { briefItems, byPriority, isOpen, PRIORITIES, unitStatus } from "../../signals.js";
import { areaName } from "../../names.js";
import { openPane } from "../../state.js";
import { completeness, quietUnits } from "./model.js";

// grid cells of the home-area cross: [row, column], in reading order (the Tab order follows it)
const CROSS = { North: [1, 2], West: [2, 1], Centre: [2, 2], East: [2, 3], South: [3, 2] };
const AREA_ORDER = Object.keys(CROSS);
const inReadingOrder = (a, b) => rank(a.area) - rank(b.area);
const rank = (area) => (AREA_ORDER.includes(area) ? AREA_ORDER.indexOf(area) : AREA_ORDER.length);

export function wardMap(brief, filters) {
  const quiet = quietUnits(brief);
  const units = brief.map?.units ?? [];
  const areas = [...(brief.map?.home_areas ?? [])].sort(inReadingOrder);
  return h(
    "section",
    { class: "group", id: "sec-map", "aria-labelledby": "h-map" },
    h(
      "h2",
      { class: "sec-h", id: "h-map" },
      t("brief.map.title"),
      quiet &&
        h(
          "span",
          { class: "count" },
          mk("map-quiet", t("brief.map.count", { quiet: int(quiet.quiet), units: int(quiet.units) })),
        ),
      h("span", { class: "right" }, t("brief.map.schematic")),
    ),
    h(
      "div",
      { class: "mapcard" },
      h(
        "div",
        { class: "maprow" },
        mapBlock(
          t("brief.map.units"),
          "plan",
          units.map((unit) => unitTile(brief, unit, unit.label ?? unit.ward, unit.ward)),
        ),
        areas.length > 0 &&
          mapBlock(
            t("brief.map.areas"),
            "cross",
            areas.map((area) => {
              const [row, column] = CROSS[area.area] ?? [];
              const name = areaName(area.area, filters);
              const label = t("brief.map.area", { area: name });
              return h(
                "div",
                { style: row ? { "grid-row": row, "grid-column": column } : null },
                unitTile(brief, area, label, area.area, name),
              );
            }),
          ),
      ),
      h(
        "div",
        { class: "map-side" },
        h(
          "p",
          { class: "quietline" },
          quiet && capitalize(t("brief.dek.quiet", { quiet: word(quiet.quiet), units: word(quiet.units) })),
          completeness(brief)
            .filter(isOpen)
            .map((item) => h("span", { class: "q" }, " ", item.text)),
        ),
        h("p", null, t("brief.map.meaning")),
        legend(),
      ),
    ),
  );
}

const mapBlock = (title, kind, tiles) =>
  h("div", { class: "mapblk" }, h("h3", { class: "eyebrow" }, title), h("div", { class: kind }, tiles));

/** One tile: lit for a signal or a change, hatched for a data gap, flat when quiet. It shows `shown` (the code). */
function unitTile(brief, unit, label, code, shown = code) {
  const status = unitStatus(brief, unit);
  const ids = unit.signal_ids ?? [];
  const lit = unit.state === "signal" || unit.state === "changed";
  return h(
    "button",
    {
      type: "button",
      class: [
        "unit",
        lit && "lit",
        lit && status.glyph && `heat-${status.glyph.toLowerCase()}`,
        unit.state === "no_data" && "gap",
      ],
      dataset: { unit: code },
      title: label,
      "aria-label": [label, status.word, ids.length > 0 && t("shell.unit.count", { n: ids.length })]
        .filter(Boolean)
        .join(", "),
      onclick: () => {
        const top = topItem(brief, ids);
        if (top) openPane("case", top.id);
        else toast(t("shell.toast.unitQuiet", { unit: label }));
      },
    },
    h(
      "span",
      { class: "u-top" },
      h("span", { class: "u-code" }, shown),
      status.glyph && status.glyph !== "gap" && tile(status.glyph, "xs"),
    ),
    h("span", { class: "u-state" }, status.word),
  );
}

const topItem = (brief, ids) =>
  byPriority(briefItems(brief).filter((item) => ids.includes(item.id) && isOpen(item)))[0];

function legend() {
  return h(
    "ul",
    { class: "legend", "aria-label": t("brief.map.legend") },
    PRIORITIES.map((priority) =>
      h(
        "li",
        null,
        h("span", { class: ["lg-heat", `heat-${priority.toLowerCase()}`], "aria-hidden": "true" }),
        tile(priority, "xs"),
        priorityLabel(priority),
      ),
    ),
    h("li", null, h("span", { class: "lg-quiet", "aria-hidden": "true" }), t("shell.unit.quiet")),
    h("li", null, h("span", { class: "lg-gap", "aria-hidden": "true" }), t("brief.map.gap")),
  );
}
