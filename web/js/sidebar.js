// The glass sidebar (>=1024): the brand and language switch, the role's groups (sidebar/infection-control.js,
// sidebar/ward-doctor.js) and the footer with the Prototype capsule and the data date. It re-renders when the
// route, the pane, the week, the language or the view's filters change, and after every write (an approval).

import { loadAlerts } from "./alerts.js";
import { get, onWrite } from "./api.js";
import { prototypeCapsule } from "./components/badges.js";
import { icon } from "./components/icons.js";
import { $, h, mount } from "./dom.js";
import { dateDay } from "./format.js";
import { t } from "./i18n.js";
import { icGroups } from "./sidebar/infection-control.js";
import { doctorGroups } from "./sidebar/ward-doctor.js";
import { loadBrief } from "./signals.js";
import { asOfRange, getState, roleOf, subscribe } from "./state.js";

let renderToken = 0;

/** Builds the sidebar once. langSwitch: the EN | FI control's element. */
export function mountSidebar({ meta, langSwitch }) {
  const roleLabel = h("span", { class: "brand-sub" });
  const nav = h("div", { class: "side-scroll" });
  const status = h("span", { class: "status-line" });
  const foot = h("div", { class: "side-foot" });
  mount(
    $("#sidebar"),
    h(
      "div",
      { class: "brand" },
      h("span", { class: "mark" }, icon("mark", 18)),
      h("span", { class: "brand-text" }, h("span", { class: "brand-name" }, meta.app_name), roleLabel),
      langSwitch,
    ),
    nav,
    foot,
  );

  const render = async () => {
    const state = getState();
    const role = roleOf(state.route);
    const token = ++renderToken;
    $("#sidebar").setAttribute("aria-label", t("shell.sections"));
    roleLabel.textContent = t(`shell.role.${role}`);
    status.textContent = t(state.asOf === asOfRange().last ? "shell.status.latest" : "shell.status.replay", {
      date: dateDay(state.asOf),
    });
    mount(foot, prototypeCapsule(), status);

    const draw = (data) => mount(nav, role === "ic" ? icGroups(state, data, meta) : doctorGroups(state, data));
    if (nav.dataset.role !== role) draw({}); // a role switch clears the old role's groups at once
    nav.dataset.role = role;
    const data = await sidebarData(state, role);
    if (token === renderToken) draw(data);
  };
  subscribe((state, prev) => {
    const params = JSON.stringify(state.params) !== JSON.stringify(prev.params);
    if (params || state.route !== prev.route || state.asOf !== prev.asOf || state.lang !== prev.lang) render();
    else if (state.pane !== prev.pane) render();
  });
  onWrite(render);
  render();
}

/** The brief (shared with the views through the API cache); infection control: the alerts; doctor: drug names. */
async function sidebarData(state, role) {
  const [brief, alerts, filters] = await Promise.all([
    loadBrief(state.asOf).catch(() => null),
    role === "ic" ? loadAlerts() : null,
    role === "doc" ? get("/api/filters", {}, { asOf: false }).catch(() => null) : null,
  ]);
  return { brief, alerts, drugs: filters?.drugs ?? [] };
}
