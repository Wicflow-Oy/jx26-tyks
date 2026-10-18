// The host's patient banner: who, where, which visit, and the risk info a hygiene nurse would have marked. Risk
// info is only what the patient's own results in the last 12 months flag (ESBL, MRSA); nothing else is invented.

import { mondayOf } from "../../dates.js";
import { h } from "../../dom.js";
import { dateFull, dateLong } from "../../format.js";
import { t } from "../../i18n.js";
import { areaName } from "../../names.js";
import { organismName } from "./previous-results.js";
import { patientLine, unitName } from "./worklist.js";

/** patientBanner({ scenario, history (or null when it did not load), filters, asOf }) */
export function patientBanner({ scenario, history, filters, asOf }) {
  const patient = history?.patient ?? scenario.patient ?? { id: scenario.patient_id };
  const setting = filters?.wards?.find((w) => w.code === scenario.unit)?.setting;
  return h(
    "section",
    { class: "ehr-banner", "aria-labelledby": "pt-id" },
    h(
      "div",
      { class: "pt-who" },
      h("span", { class: "pt-avatar", "aria-hidden": "true" }),
      h(
        "div",
        null,
        h("h2", { class: "pt-id num", id: "pt-id" }, patient.id ?? scenario.patient_id),
        h(
          "p",
          { class: "pt-sub" },
          patientLine(patient),
          patient.home_area && ` · ${t("order.ehr.homeArea", { area: areaName(patient.home_area, filters) })}`,
        ),
      ),
    ),
    h(
      "dl",
      { class: "pt-facts" },
      fact(t("order.ehr.unit"), unitName(scenario.unit, filters)),
      fact(
        t("order.ehr.encounter"),
        [setting && t(`order.ehr.setting.${setting}`), dateLong(mondayOf(asOf))].filter(Boolean).join(" · "),
      ),
      fact(t("order.ehr.risk"), riskInfo(history, filters), "risk"),
    ),
  );
}

const fact = (label, value, cls) => h("div", { class: ["pt-fact", cls] }, h("dt", null, label), h("dd", null, value));

/** "ESBL E. coli · 6 Dec 2025"; "None recorded"; or a quiet note when the history did not load. */
function riskInfo(history, filters) {
  if (!history) return h("span", { class: "muted" }, t("order.ehr.historyError"));
  const flagged = (history.previous_results ?? []).filter((r) => (r.flags ?? []).length);
  if (!flagged.length) return h("span", { class: "muted" }, t("order.ehr.riskNone"));
  return flagged
    .map((r) =>
      t("order.ehr.riskItem", {
        flag: r.flags.join(", "),
        organism: organismName(r.organism, filters),
        date: dateFull(r.date),
      }),
    )
    .join("; ");
}
