// The case file's head (badge, state, advice, title, the kind's one-line caveat) and its meta strip of six cells.

import { adviceChip, priorityBadge, stateWord } from "../../components/badges.js";
import { mk } from "../../components/marker.js";
import { daysBetween, parseISO } from "../../dates.js";
import { h } from "../../dom.js";
import { dateShort, int } from "../../format.js";
import { getLang, t } from "../../i18n.js";
import { signalTitle } from "../../signals.js";

// kinds whose caveat must sit right under the title
const CAVEATS = ["phenotype_cluster", "seen_before"];

export function caseHead(item) {
  const caveat = CAVEATS.includes(item.kind)
    ? t(`case.caveat.${item.kind}`)
    : item.kind === "completeness" && item.ward
      ? t("case.caveat.gap")
      : null;
  return h(
    "div",
    { class: "case-head" },
    h(
      "div",
      { class: "case-badges" },
      item.priority && priorityBadge(item.priority),
      stateWord(item.status),
      adviceChip(item.advice),
    ),
    h("h2", { id: "case-title", tabindex: "-1" }, signalTitle(item)),
    caveat && h("p", { class: "case-sub" }, caveat),
  );
}

/**
 * Six cells. A cluster: unit, organism, first sample, first alert (+days), patients, same antibiogram. Anything
 * else: unit, organism, drug, first sample, and the dates the evidence covers. names: { organism(code), drug(code) }.
 */
export function metaStrip(item, file, names) {
  const slots = item.slots ?? {};
  const counts = item.evidence?.counts ?? {};
  const filter = item.evidence?.filter ?? {};
  const cells =
    slots.n_patients != null && slots.n_share != null
      ? [
          [t("case.meta.unit"), item.ward],
          [t("case.meta.organism"), slots.organism_label ?? names.organism(item.organism)],
          [t("case.meta.firstSample"), withYear(item.first_sample_date)],
          [t("case.meta.firstAlert"), firstAlert(item.first_sample_date, counts.first_alert_date)],
          [t("case.meta.patients"), mk("case-n", int(file?.line_list?.n ?? slots.n_patients))],
          [
            t("case.meta.same"),
            [int(slots.n_share), " ", h("small", null, t("case.meta.ofN", { n: int(slots.n_patients) }))],
          ],
        ]
      : [
          [t("case.meta.unit"), units(filter.ward ?? item.ward)],
          [t("case.meta.organism"), slots.organism_label ?? names.organism(item.organism) ?? t("case.meta.all")],
          [t("case.meta.drug"), slots.drug_label ?? names.drug(item.drug) ?? "–"],
          [t("case.meta.firstSample"), item.first_sample_date ? withYear(item.first_sample_date) : "–"],
          [t("case.meta.from"), filter.date_from ? withYear(filter.date_from) : "–"],
          [t("case.meta.to"), withYear(filter.date_to ?? item.as_of)],
        ];
  return h(
    "dl",
    { class: "meta" },
    cells.map(([label, value]) => h("div", null, h("dt", null, label), h("dd", null, value ?? "–"))),
  );
}

/** "3 Mar 2026" with the year quiet. */
// "3 Mar 2026" · "3.3.2026" (a Finnish short date ends in its own period, so the year follows it directly)
const withYear = (iso) => [
  dateShort(iso),
  getLang() === "fi" ? "" : " ",
  h("small", null, String(parseISO(iso).getUTCFullYear())),
];

/** "7 Mar +4 days" */
function firstAlert(firstSample, alertDate) {
  if (!alertDate) return "–";
  const days = firstSample ? daysBetween(firstSample, alertDate) : null;
  return [dateShort(alertDate), days != null && [" ", h("small", null, t("case.meta.plusDays", { n: int(days) }))]];
}

/** A filter's ward: one code, "3 units", or all units. */
function units(ward) {
  if (Array.isArray(ward)) return ward.length === 1 ? ward[0] : t("case.meta.nUnits", { n: int(ward.length) });
  return ward ?? t("case.meta.allUnits");
}
