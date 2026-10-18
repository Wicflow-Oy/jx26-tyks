// The Coverage section: the window control, the shared-axis column head, a row per drug, the combinations
// disclosure and the drugs the API left out with its reasons.

import { linkButton } from "../../components/buttons.js";
import { icon } from "../../components/icons.js";
import { mk } from "../../components/marker.js";
import { segmented } from "../../components/segmented.js";
import { emptyState } from "../../components/states.js";
import { h } from "../../dom.js";
import { dateShort, int, pct } from "../../format.js";
import { t } from "../../i18n.js";
import { setParams } from "../../state.js";
import { isCombo } from "./cells.js";
import { drugRow } from "./drug-row.js";
import { FILTER_KEYS, recentWindows, weeksOf } from "./scope.js";

/** Back to the unit's whole default scope: every narrowing filter off, the ward kept. */
const clearFilters = () => setParams(Object.fromEntries(FILTER_KEYS.filter((k) => k !== "ward").map((k) => [k, null])));

// a disclosure the doctor opened or closed stays that way while replay re-renders the page
const disclosure = { combos: null, notShown: false };

/** ward: the my-ward response · filters: /api/filters · line: the local setting as a share. */
export function coverageSection({ ward, filters, line }) {
  const windows = ward.windows ?? [];
  const [recent, year] = windows;
  const yearWeeks = weeksOf(year);
  const rows = ward.rows ?? [];
  const singles = rows.filter((row) => !isCombo(row));
  const combos = rows.filter(isCombo);

  const body = year?.n_isolates
    ? [
        columnHead(windows, line),
        narrowAxis(line),
        h(
          "ul",
          { class: "inset" },
          singles.map((row) => drugRow(row, windows, line)),
        ),
        combos.length > 0 && combosDisclosure(combos, windows, line),
      ]
    : h(
        "div",
        { class: "card empty-card" },
        emptyState(t("ward.cov.empty", { n: yearWeeks }), null),
        linkButton({ label: t("ward.cov.clear"), onClick: clearFilters }),
      );

  return h(
    "section",
    { class: "group abg", "aria-labelledby": "h-coverage" },
    h(
      "div",
      { class: "sec-h abg-h" },
      h("h2", { id: "h-coverage" }, t("ward.cov.title"), " ", h("span", { class: "count" }, t("ward.cov.unit"))),
      h(
        "span",
        { class: "right win" },
        h("span", { class: "wl2", "aria-hidden": "true" }, t("ward.cov.compare", { n: yearWeeks })),
        windowControl(filters, recent, yearWeeks),
      ),
    ),
    body,
    notShown(ward.not_shown ?? []),
  );
}

/** The recent window as a radio group: "4 weeks | 16 weeks", compared with the year. */
function windowControl(filters, recent, yearWeeks) {
  const options = recentWindows(filters).map((w) => ({
    value: w.key,
    label: t("ward.window.short", { n: weeksOf(w) }),
  }));
  if (options.length < 2) return null;
  return segmented({
    label: t("ward.cov.window", { n: yearWeeks }),
    options,
    value: recent?.key ?? options[0].value,
    small: true,
    id: "ward-window",
    onChange: (key) => setParams({ window: key === options[0].value ? null : key }),
  }).el;
}

function columnHead([recent, year], line) {
  return h(
    "div",
    { class: "abg-cols abg-head", "aria-hidden": "true" },
    h("span", { class: "wh" }, h("b", null, t("ward.cov.drug")), h("span", null, t("ward.cov.aware"))),
    axis("axis", line),
    h(
      "span",
      { class: "wh" },
      h("b", null, recent.label),
      h("span", null, t("ward.cov.range", { from: dateShort(recent.from), to: dateShort(recent.to) })),
      h("span", null, mk(`n-${recent.key}`, t("ward.cov.isolates", { n: int(recent.n_isolates ?? 0) }))),
    ),
    h(
      "span",
      { class: "wh" },
      h("b", null, year.label),
      h("span", null, mk(`n-${year.key}`, t("ward.cov.isolates", { n: int(year.n_isolates ?? 0) }))),
    ),
    h("span"),
  );
}

/** 0 · 50 · 100 with the local setting labelled in bold where its dashed rule runs. */
function axis(cls, line) {
  return h(
    "span",
    { class: cls },
    h("span", { class: "end start" }, "0"),
    h("span", { style: { left: "50%" } }, "50"),
    line != null && h("span", { class: "loc", style: { left: `${line * 100}%` } }, pct(line)),
    h("span", { class: "end stop" }, pct(1)),
  );
}

/** The same axis above the rows in the narrow layout, where the column head is hidden. */
const narrowAxis = (line) => h("div", { class: "axis-m", "aria-hidden": "true" }, axis("axis", line));

function combosDisclosure(combos, windows, line) {
  const open = disclosure.combos ?? !matchMedia("(max-width: 640px)").matches;
  return h(
    "details",
    { class: "combos", open, ontoggle: (event) => (disclosure.combos = event.target.open) },
    h(
      "summary",
      { class: "sub-sum" },
      h("span", { class: "disc", "aria-hidden": "true" }, icon("chevron", 6)),
      t("ward.cov.combos"),
      h("span", { class: "count" }, int(combos.length)),
    ),
    h(
      "ul",
      { class: "inset" },
      combos.map((row) => drugRow(row, windows, line)),
    ),
  );
}

/** "7 drugs not shown ›" with the API's reason for each. */
function notShown(list) {
  if (!list.length) return null;
  return h(
    "details",
    { class: "notshown", open: disclosure.notShown, ontoggle: (event) => (disclosure.notShown = event.target.open) },
    h(
      "summary",
      null,
      t("ward.cov.notShown", { n: int(list.length) }),
      h("span", { class: "disc", "aria-hidden": "true" }, icon("chevron", 6)),
    ),
    h(
      "ul",
      null,
      list.map((item) => h("li", null, item.reason ?? item.label ?? item.drug)),
    ),
  );
}
