// The lead sentence: the drug whose recent coverage fell most among the rows the change test flagged down, told
// with that row's own numbers, and a quiet line counting the changed rows. Built only from the my-ward response.

import { mk } from "../../components/marker.js";
import { h } from "../../dom.js";
import { int, interval, pct } from "../../format.js";
import { t } from "../../i18n.js";
import { noBreak } from "../../names.js";
import { rich } from "../../text.js";
import { changeOf, isCombo, observedXOfN, shown } from "./cells.js";
import { weeksOf } from "./scope.js";

/** The single-drug row changed down with the largest drop from the year to the recent window, or null. */
export function leadRow(ward) {
  const [recent, year] = ward.windows ?? [];
  if (!recent || !year) return null;
  const drop = (row) => shown(row.cells[year.key]).share - shown(row.cells[recent.key]).share;
  const candidates = (ward.rows ?? []).filter(
    (row) =>
      !isCombo(row) &&
      changeOf(row.cells?.[recent.key]) === "down" &&
      shown(row.cells[recent.key]) &&
      shown(row.cells?.[year.key]),
  );
  return candidates.sort((a, b) => drop(b) - drop(a))[0] ?? null;
}

/** The lead paragraph, or null when the scope has no isolates at all (the coverage card says so). */
export function leadParagraph(ward, line) {
  const [recent, year] = ward.windows ?? [];
  if (!recent || !year?.n_isolates) return null;
  const rows = ward.rows ?? [];
  const weeks = weeksOf(year);
  const changed = rows.filter((row) => changeOf(row.cells?.[recent.key])).length;
  const paragraph = (...children) => h("p", { class: "lead", id: "ward-lead" }, children);
  if (!recent.n_isolates || rows.every((row) => !shown(row.cells?.[recent.key]))) {
    const vars = { n: int(recent.n_isolates ?? 0), window: windowName(recent), yearWindow: windowName(year) };
    return paragraph(t("ward.lead.thin", vars));
  }
  if (!changed) return paragraph(t("ward.lead.noneChanged", { weeks }));
  return paragraph(
    mainSentence(ward, recent, year, line),
    " ",
    h(
      "span",
      { class: "q tail" },
      rich("ward.lead.changed", { n: mk("lead-changed", int(changed)), total: int(rows.length), weeks }),
    ),
  );
}

const windowName = (window) => t("ward.window.last", { n: weeksOf(window) });

function mainSentence(ward, recent, year, line) {
  const window = windowName(recent);
  const yearWindow = windowName(year);
  const row = leadRow(ward);
  if (!row) return t("ward.lead.noDrop", { weeks: weeksOf(year) });

  const now = row.cells[recent.key];
  const before = row.cells[year.key];
  const value = shown(now);
  const yearValue = shown(before);
  const bold = (key, text) => mk(`lead-${key}`, h("b", null, text));
  const share = rich(value.stabilised ? "ward.lead.shareStabilised" : "ward.lead.shareObserved", {
    pct: bold("pct", pct(value.share)),
    ci: interval(value.ci),
  });
  // the year is almost always observed; with narrow filters it can be stabilised too, and then it says so
  const yearShare = yearValue.stabilised
    ? rich("ward.lead.shareStabilised", { pct: pct(yearValue.share), ci: interval(yearValue.ci) })
    : pct(yearValue.share);
  return [
    rich("ward.lead.sentence", {
      drug: noBreak(row.label),
      recent: bold("recent", observedXOfN(now)),
      window,
      share,
      year: bold("year", observedXOfN(before)),
      yearShare,
      yearWindow,
    }),
    now.below_local_setting && line != null ? [" ", t("ward.lead.below", { line: pct(line) })] : null,
  ];
}
