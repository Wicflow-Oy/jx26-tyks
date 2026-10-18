// The window of the simulated hospital system that our layer runs on top of: a plain title bar, its menu, its
// chart tabs and a status bar. It is deliberately older and denser than our product and has no vendor look.
// The menu and tabs are scenery (only Orders works here), so they are hidden from assistive technology.

import { icon } from "../../components/icons.js";
import { h } from "../../dom.js";
import { t } from "../../i18n.js";

/** ehrFrame({ user, date, body, status: [nodes], note }) → the window; note is meta.cds_hooks.note when given. */
export function ehrFrame({ user, date, body, status = [], note }) {
  return h(
    "section",
    { class: "ehr", "aria-label": t("order.ehr.name") },
    h(
      "header",
      { class: "ehr-title" },
      h("span", { class: "ehr-app" }, h("span", { class: "ehr-logo", "aria-hidden": "true" }), t("order.ehr.name")),
      h("span", { class: "ehr-sp" }),
      user && h("span", { class: "ehr-user" }, icon("ward", 13), h("span", null, t("order.ehr.user", { role: user }))),
      date && h("span", { class: "ehr-date num" }, date),
    ),
    scenery("ehr-menu", t("order.ehr.menu"), 2),
    body,
    h(
      "footer",
      { class: "ehr-status" },
      h("span", { class: "ehr-status-main" }, status),
      note && h("span", { class: "ehr-status-note" }, note),
    ),
  );
}

/** The host's chart tabs above the order form, with Orders current. */
export const chartTabs = () => scenery("ehr-tabs", t("order.ehr.tabs"), 3);

const scenery = (cls, labels, current) =>
  h(
    "div",
    { class: cls, "aria-hidden": "true" },
    labels.map((label, i) => h("span", { class: i === current && "on" }, label)),
  );
