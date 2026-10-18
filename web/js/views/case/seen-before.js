// "Seen before": earlier patients with the exact antibiogram, by unit (or the dates it came back to the unit).
// Profile match, not typing: an identical antibiogram is a cheap first proxy, never proof of one clone.

import { unitBars } from "../../components/unit-bars.js";
import { h } from "../../dom.js";
import { dateFull, dateShort, int } from "../../format.js";
import { t } from "../../i18n.js";
import { notes } from "./parts.js";

/** A cluster's seen-before match: its sentence, the visual and the typing note. */
export const seenBefore = (match) => [
  h("p", { class: "readout" }, match.text),
  seenBeforeVisual(match),
  notes([[t("case.note.profile"), t("case.note.profileText")]]),
];

/** Bars of earlier patients by unit, or the dates the antibiogram came back (return mode). */
export function seenBeforeVisual(match) {
  const c = match.evidence?.counts ?? {};
  return byUnit(match, c) ?? comeBack(match, c);
}

/** Bars of earlier patients elsewhere, by unit, then the cluster's own unit. */
function byUnit(match, c) {
  const elsewhere = Object.entries(c.elsewhere_by_ward ?? {});
  if (elsewhere.length === 0 && c.n_same_ward_before == null) return null;
  const label = t("case.seen.bars", { date: dateShort(match.first_sample_date) });
  return h(
    "div",
    { class: "soft" },
    unitBars([...elsewhere, [match.ward, c.n_same_ward_before ?? 0]], { label }),
    h("p", { class: "cap" }, label),
  );
}

/** Return mode: the dates the antibiogram came back to the unit after its cluster. */
function comeBack(match, c) {
  if (!Array.isArray(c.return_dates) || c.return_dates.length === 0) return null;
  return h(
    "div",
    { class: "soft" },
    h(
      "p",
      { class: "t-subhead" },
      t("case.seen.back", { unit: match.ward, dates: c.return_dates.map(dateShort).join(", ") }),
      c.cluster_first_sample &&
        ` ${t("case.seen.cluster", { date: dateFull(c.cluster_first_sample), n: int(c.cluster_patients) })}`,
    ),
  );
}
