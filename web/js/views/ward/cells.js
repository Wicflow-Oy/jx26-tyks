// One coverage cell (CONTRACTS §4.1) on screen: the share it shows, the cell text and its spoken summary.
// The API decides every state; these helpers only read it.

import { mk } from "../../components/marker.js";
import { h } from "../../dom.js";
import { int, interval, pct, xOfN } from "../../format.js";
import { t } from "../../i18n.js";
import { weeksOf } from "./scope.js";

/**
 * The share a cell shows, or null when there is not enough data. The API's estimate is already the observed share
 * when there are enough results and the stabilised one when there are few.
 */
export function shown(cell) {
  if (!cell || cell.state === "not_enough_data" || cell.estimate?.pct == null) return null;
  return { share: cell.estimate.pct, ci: cell.estimate.ci ?? null, stabilised: cell.estimate.method === "stabilised" };
}

/** "down" | "up" when the change test flagged the cell, else null. */
export const changeOf = (cell) => (cell?.changed?.changed ? cell.changed.direction : null);

/** Combination keys join drug codes with "+" ("MEM+VAN"). */
export const isCombo = (row) => String(row.drug).includes("+");

/** "11 of 24" from a cell's observed counts. */
export const observedXOfN = (cell) => xOfN(cell?.observed?.covered ?? 0, cell?.observed?.tested ?? 0);

/** The Changed ↓ / Changed ↑ chip; since (a date) makes it "Changed ↓ since 15 Mar". */
export function changeChip(direction, since) {
  if (!direction) return null;
  const word = t(`ward.chip.${direction}`);
  return h(
    "span",
    { class: ["chip", direction === "down" ? "chip-down" : "chip-up"] },
    since ? t("ward.trend.changedSince", { chip: word, date: since }) : word,
  );
}

/**
 * The numbers of one window in a row: "74% [61–85] / 11 of 24 · stabilised", or the dashed "Not enough data"
 * capsule with "n = 2 · 1 of 2" and no percentage. label is shown only in the narrow layout ("4 weeks").
 */
export function windowCell(cell, { label, cls, markKey }) {
  const value = shown(cell);
  const tested = cell?.observed?.tested ?? 0;
  const x = observedXOfN(cell);
  const wl = h("span", { class: "wl" }, label);
  if (!value) {
    const count = tested ? t("ward.cell.nOf", { n: int(tested), x }) : t("ward.cell.n", { n: int(tested) });
    return h(
      "span",
      { class: ["wcell", cls] },
      wl,
      h("span", { class: "ned" }, t("ward.cell.ned")),
      h("span", { class: "x" }, count),
    );
  }
  return h(
    "span",
    { class: ["wcell", cls] },
    wl,
    h("span", { class: "v" }, mk(markKey, h("b", null, pct(value.share))), h("span", null, interval(value.ci))),
    h("span", { class: "x" }, value.stabilised ? t("ward.cell.stabilised", { x }) : x),
  );
}

/** A row's full spoken summary: "Meropenem: last 4 weeks: 11 of 24 covered, stabilised 72%, …; changed down." */
export function rowSummary(row, [recent, year], line) {
  const cell = row.cells?.[recent.key];
  const parts = [cellSummary(cell, recent), cellSummary(row.cells?.[year.key], year)];
  const change = changeOf(cell);
  if (change) parts.push(t(`ward.aria.${change}`));
  if (line != null && cell?.below_local_setting && shown(cell)) parts.push(t("ward.aria.below", { line: pct(line) }));
  return `${row.label}: ${parts.join("; ")}. ${t("ward.aria.open")}`;
}

function cellSummary(cell, window) {
  const name = t("ward.window.last", { n: weeksOf(window) });
  const value = shown(cell);
  if (!value) return t("ward.aria.ned", { window: name, n: int(cell?.observed?.tested ?? 0) });
  const [lo, hi] = value.ci ?? [];
  return t(value.stabilised ? "ward.aria.stabilised" : "ward.aria.observed", {
    window: name,
    x: observedXOfN(cell),
    pct: pct(value.share),
    lo: pct(lo),
    hi: pct(hi),
  });
}
