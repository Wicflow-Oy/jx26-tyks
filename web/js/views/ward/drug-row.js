// One antibiogram row: drug name, AWaRe group and change chip, the dumbbell, the recent and the year cells.
// The whole row is a button that opens the drug's trend.

import { icon } from "../../components/icons.js";
import { h } from "../../dom.js";
import { t } from "../../i18n.js";
import { noBreak } from "../../names.js";
import { openPane } from "../../state.js";
import { changeChip, changeOf, rowSummary, windowCell } from "./cells.js";
import { dumbbell } from "./dumbbell.js";
import { weeksOf } from "./scope.js";

/** windows: [recent, year] from the my-ward response; line: the local setting as a share. */
export function drugRow(row, windows, line) {
  const [recent, year] = windows;
  const cells = row.cells ?? {};
  return h(
    "li",
    null,
    h(
      "button",
      {
        type: "button",
        class: "drow abg-cols",
        id: `drow-${row.drug}`,
        "aria-label": rowSummary(row, windows, line),
        dataset: { paneId: row.drug },
        onclick: () => openPane("trend", row.drug),
      },
      h(
        "span",
        { class: "dname" },
        h("b", null, noBreak(row.label)),
        h("span", { class: "sub" }, row.aware, changeChip(changeOf(cells[recent.key]))),
      ),
      dumbbell({ recent: cells[recent.key], year: cells[year.key], line }),
      windowCell(cells[recent.key], {
        label: t("ward.window.short", { n: weeksOf(recent) }),
        cls: "w4",
        markKey: `cell-${recent.key}-${row.drug}`,
      }),
      windowCell(cells[year.key], {
        label: t("ward.window.short", { n: weeksOf(year) }),
        cls: "w12",
        markKey: `cell-${year.key}-${row.drug}`,
      }),
      h("span", { class: "chev" }, icon("chevron", 7)),
    ),
  );
}
