// The host's patient list: the demo patients from GET /api/demo/scenarios. Each visit has its own week, so
// opening a patient also moves the global as-of date there (and the rail with it).

import { mondayOf } from "../../dates.js";
import { h } from "../../dom.js";
import { dateLong } from "../../format.js";
import { t } from "../../i18n.js";
import { labels } from "../../names.js";
import { getState, setState } from "../../state.js";
import { draftFor } from "./draft.js";

/** worklist({ scenarios, current, filters }) → the panel; current is the open scenario or null. */
export function worklist({ scenarios, current, filters }) {
  const names = labels(null, filters);
  return h(
    "section",
    { class: "ehr-panel wl", "aria-labelledby": "wl-title" },
    h(
      "div",
      { class: "ehr-ph" },
      h("h2", { id: "wl-title" }, t("order.ehr.list")),
      h("span", { class: "ehr-cnt" }, t("order.ehr.listCount", { n: scenarios.length })),
    ),
    h(
      "ul",
      { class: "wl-list" },
      scenarios.map((scenario) => {
        const draft = draftFor(scenario);
        const lines = [
          patientLine(scenario.patient),
          unitName(scenario.unit, filters),
          t("order.ehr.visit", { date: dateLong(mondayOf(scenario.as_of)) }),
          draft.drug && t("order.ehr.draft", { drug: names.drug(draft.drug) ?? draft.drug }),
        ];
        return h(
          "li",
          null,
          h(
            "button",
            {
              type: "button",
              class: "wl-row",
              id: `wl-${scenario.key}`, // keeps focus on the row across the re-render that opens it
              // the visual lines run together when read as one name, so the name lists them with commas
              "aria-label": [scenario.patient_id, ...lines].filter(Boolean).join(", "),
              "aria-current": scenario.key === current?.key ? "true" : null,
              onclick: () => open(scenario),
            },
            h("span", { class: "wl-top" }, h("b", { class: "num" }, scenario.patient_id), h("span", null, lines[0])),
            h("span", { class: "wl-unit" }, lines[1]),
            h("span", { class: "wl-meta num" }, lines[2]),
            lines[3] && h("span", { class: "wl-meta" }, lines[3]),
          ),
        );
      }),
    ),
  );
}

function open(scenario) {
  const { params } = getState();
  setState({ asOf: scenario.as_of, params: { ...params, patient: scenario.key } }, { push: true });
}

/** "Female, 35 y" (or "" when the API gives neither) */
export function patientLine(patient) {
  const sex = patient?.sex ? t(`order.ehr.sex.${patient.sex}`) : "";
  const age = patient?.age != null ? t("order.ehr.age", { age: patient.age }) : "";
  return [sex, age].filter(Boolean).join(", ");
}

/** "Urology (URO)" */
export function unitName(code, filters) {
  const label = filters?.wards?.find((w) => w.code === code)?.label;
  return label ? `${label} (${code})` : code;
}
