// A cluster's evidence (phenotype cluster or THL card with two or more patients): the readout, the unit epi curve,
// the shared antibiogram, footnotes, the THL rule card and the count step-up, which is supporting evidence only.

import { srSet } from "../../components/badges.js";
import { epiCurve } from "../../components/epi-curve.js";
import { daysBetween } from "../../dates.js";
import { h } from "../../dom.js";
import { dateShort, int, pct, significant } from "../../format.js";
import { t } from "../../i18n.js";
import { rich } from "../../text.js";
import { MIN_N_FOR_SHARE, methodText, notes } from "./parts.js";

/** ctx: { item, file, asOf, names, lagDays } */
export function clusterEvidence({ item, file, asOf, names, lagDays }) {
  const slots = item.slots ?? {};
  const counts = item.evidence?.counts ?? {};
  const rows = file.line_list.rows.filter((row) => row.date <= asOf);
  // a heterogeneous card's filter still names its most common antibiogram; it is "shared" only when two patients have it
  const top = slots.pattern ?? item.evidence?.filter?.profile ?? null;
  const shared = top ? rows.filter((row) => row.profile === top).length : rows.length;
  const pattern = shared >= 2 ? top : null;
  const onset = item.evidence?.competing_explanations?.values?.hospital_onset_share;
  const isPhenotype = item.kind === "phenotype_cluster" && counts.first_alert_date;

  return [
    isPhenotype
      ? h(
          "p",
          { class: "readout" },
          rich("case.cluster.readout", {
            n: h("b", null, int(rows.length)),
            date: dateShort(item.first_sample_date),
            shared: h("b", null, int(shared)),
          }),
          " ",
          t("case.cluster.firstAlert", {
            date: dateShort(counts.first_alert_date),
            days: int(daysBetween(item.first_sample_date, counts.first_alert_date)),
          }),
        )
      : h("p", { class: "readout" }, item.text),
    h(
      "div",
      { class: "card epi-card" },
      epiCurve({
        rows,
        pattern,
        firstAlert: counts.first_alert_date ?? null,
        asOf,
        unit: counts.n_patients === file.line_list.n ? "patients" : "isolates",
        lagDays,
      }),
    ),
    pattern &&
      h(
        "div",
        { class: "soft soft-row" },
        h("span", { class: "t-footnote ink2" }, t("case.cluster.shared")),
        srSet(pattern, (code) => names.drug(code) ?? code),
      ),
    notes([
      isPhenotype && [
        t("case.note.counts"),
        [
          t("case.cluster.expected", {
            n: int(slots.n_patients),
            date: dateShort(item.first_sample_date),
            expected: significant(counts.expected_per_year, 2),
            unit: item.ward,
            low: int(slots.expected_low),
            high: int(slots.expected_high),
          }),
          onset != null && rows.length >= MIN_N_FOR_SHARE ? ` ${t("case.cluster.onset", { share: pct(onset) })}` : "",
        ].join(""),
      ],
      [t("case.note.method"), methodText(item.kind)],
      pattern && [t("case.note.profile"), t("case.note.profileText")],
    ]),
    thlCard(item.evidence?.thl_rule),
    stepUp(file.stepup ?? item.evidence?.stepup, asOf),
  ];
}

/** The THL guidance card that came with a cluster: its rule and the action it names. */
const thlCard = (rule) =>
  rule?.text &&
  h(
    "div",
    { class: "soft step" },
    h("p", { class: "t-subhead" }, h("b", null, rule.text)),
    rule.action && h("p", { class: "cap" }, rule.action),
  );

/** The count step-up test: supporting evidence only; it describes past counts, nothing ahead. */
function stepUp(stepup, asOf) {
  if (!stepup) return null;
  return h(
    "div",
    { class: "soft step" },
    h("p", { class: "t-subhead" }, h("b", null, t(stepup.positive ? "case.stepup.positive" : "case.stepup.negative"))),
    h(
      "p",
      { class: "cap" },
      t("case.stepup.counts", {
        n: int(stepup.y4),
        recent: int(stepup.recent_weeks),
        low: int(stepup.usual_low),
        high: int(stepup.usual_high),
        weeks: int(stepup.baseline_weeks),
        date: dateShort(asOf),
      }),
      " ",
      t("case.stepup.only"),
    ),
  );
}
