// "How to read a row": the three cell states, each shown with a real row from this week's table, then the key.

import { h } from "../../dom.js";
import { int, interval, pct } from "../../format.js";
import { t } from "../../i18n.js";
import { noBreak } from "../../names.js";
import { rich } from "../../text.js";
import { changeChip, observedXOfN, shown } from "./cells.js";
import { dumbbell } from "./dumbbell.js";
import { weeksOf } from "./scope.js";

/** ward: the my-ward response · line: the local setting as a share. */
export function readKey(ward, line) {
  const [recent, year] = ward.windows ?? [];
  if (!recent || !year || !year.n_isolates) return null;
  const rows = ward.rows ?? [];
  const small = ward.small_n ?? {};
  const cellsIn = (window) => rows.map((row) => ({ row, window, cell: row.cells?.[window.key] }));
  const all = [...cellsIn(recent), ...cellsIn(year)];

  const enough = cellsIn(year).find((x) => x.cell?.state === "ok" && shown(x.cell));
  const few = cellsIn(recent).find((x) => x.cell?.state === "low_n" && shown(x.cell)?.stabilised);
  const thin = all.find((x) => x.cell?.state === "not_enough_data" && x.cell.observed?.tested > 0);

  return h(
    "section",
    { class: "group", "aria-labelledby": "h-key" },
    h("h2", { class: "sec-h", id: "h-key" }, t("ward.key.title")),
    h(
      "div",
      { class: "keycard card" },
      enough && enoughPanel(enough, line),
      few && fewPanel(few, small.low_n_below, line),
      thinPanel(thin, small.not_enough_data_below),
    ),
    keyLine(year, line),
  );
}

const panel = (title, ...body) => h("div", null, h("h3", null, title), body);
const bold = (text) => h("b", { class: "num" }, text);
const windowName = (window) => t("ward.window.last", { n: weeksOf(window) });

function enoughPanel({ row, window, cell }, line) {
  const value = shown(cell);
  return panel(
    t("ward.key.enough"),
    dumbbell({ recent: null, year: cell, line }),
    h(
      "p",
      null,
      rich("ward.key.enoughText", {
        pct: bold(pct(value.share)),
        ci: interval(value.ci),
        x: observedXOfN(cell),
        drug: noBreak(row.label),
        window: windowName(window),
      }),
    ),
  );
}

function fewPanel({ cell }, below, line) {
  const value = shown(cell);
  return panel(
    below != null ? t("ward.key.few", { n: int(below) }) : t("ward.key.fewPlain"),
    dumbbell({ recent: cell, year: null, line }),
    h(
      "p",
      null,
      rich("ward.key.fewText", {
        pct: bold(pct(value.share)),
        ci: interval(value.ci),
        x: observedXOfN(cell),
        observed: pct(cell.observed?.pct),
      }),
    ),
  );
}

/** Not enough data: a real thin cell when the table has one, else the rule alone. */
function thinPanel(example, below) {
  const title = below != null ? t("ward.key.ned", { n: int(below) }) : t("ward.key.nedPlain");
  const text = example
    ? t("ward.key.nedText", {
        drug: noBreak(example.row.label),
        window: windowName(example.window),
        tested: int(example.cell.observed.tested),
      })
    : t("ward.key.nedNone", { n: int(below ?? 0) });
  return panel(title, h("span", { class: "ned" }, t("ward.cell.ned")), h("p", null, text));
}

function keyLine(year, line) {
  const item = (glyphClass, text) => h("span", null, h("span", { class: glyphClass, "aria-hidden": "true" }), text);
  return h(
    "p",
    { class: "keyline" },
    item("kd4", t("ward.key.recent")),
    item("kd12", t("ward.key.year", { n: weeksOf(year) })),
    item("kband", t("ward.key.interval")),
    item("kobs", t("ward.key.observed")),
    line != null && item("krule", t("ward.key.line", { line: pct(line) })),
    h("span", null, changeChip("down"), t("ward.key.changed", { n: weeksOf(year) })),
  );
}
