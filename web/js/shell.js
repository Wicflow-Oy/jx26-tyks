// The frame around every view: the desktop toolbar (title, role switch, as-of date and stepper, Start tour), the
// phone top bar and role switch, the floating tab bar, the language switch, each view's page head, the title that
// slides into the bar on scroll, and the live announcement of each replay step.

import { prototypeCapsule } from "./components/badges.js";
import { button, iconButton, weekStepper } from "./components/buttons.js";
import { icon } from "./components/icons.js";
import { mountPane } from "./components/pane.js";
import { segmented } from "./components/segmented.js";
import { mondayOf } from "./dates.js";
import { $, h, mount, reducedMotion } from "./dom.js";
import { dateLong } from "./format.js";
import { t } from "./i18n.js";
import { mountRail } from "./replay/rail.js";
import { mountReplaySheet, openReplaySheet } from "./replay/sheet.js";
import { canStep, step } from "./replay/timeline.js";
import { mountSidebar } from "./sidebar.js";
import { loadBrief } from "./signals.js";
import { HOME, getState, navigate, openPane, roleOf, setState, subscribe } from "./state.js";

const ROLE_OPTIONS = () => [
  { value: "ic", label: t("shell.role.ic") },
  { value: "doc", label: t("shell.role.doc") },
];
const LANG_OPTIONS = [
  { value: "en", label: "EN", ariaLabel: "English", lang: "en" },
  { value: "fi", label: "FI", ariaLabel: "Suomi", lang: "fi" },
];

let startTour = () => {};
let titleObserver = null;
let briefTab = "brief"; // the infection-control tab bar's current tab: "brief" or "wards" (both scroll the brief)
let appName = "";
const roleSwitches = [];

/** Builds the shell once, after /api/meta has loaded. onTour starts the guided tour. */
export function mountShell({ meta, onTour }) {
  startTour = onTour;
  appName = meta.app_name;
  document.title = appName;
  $(".skip").textContent = t("shell.skip");

  const sideLang = langSwitch("lang-side");
  mountToolbar();
  mountPhoneBar();
  mountSidebar({ meta, langSwitch: sideLang.el });
  mountRail($("#rail"));
  mountReplaySheet($("#replay-sheet"));
  mountPane();
  renderTabbar(getState());

  subscribe((state, prev) => {
    if (state.lang !== prev.lang) {
      $(".skip").textContent = t("shell.skip");
      sideLang.set(state.lang);
      for (const control of roleSwitches) control.relabel(t("shell.role.label"), ROLE_OPTIONS());
    }
    for (const control of roleSwitches) control.set(roleOf(state.route));
    if (state.route !== prev.route) briefTab = "brief";
    if (state.route !== prev.route || state.pane !== prev.pane || state.lang !== prev.lang) renderTabbar(state);
    if (state.asOf !== prev.asOf) announceWeek(state);
  });
}

// ---------------------------------------------------------------- toolbar (>=1024)

function mountToolbar() {
  const title = h("span", { class: "tb-title", id: "tb-title", "aria-hidden": "true" });
  const roles = roleSwitch();
  const asOf = h("span", { class: "asof-label" });
  const steps = weekStepper({ onStep: step });
  const tour = button({ label: "", attrs: { class: "tb-tour" }, onClick: () => startTour() });
  mount($("#toolbar"), title, roles.el, h("div", { class: "tb-right" }, asOf, steps.el, tour));

  // in a narrow toolbar (a pane open beside it) CSS hides "As of" and the tour label, so both keep a full name
  const render = (state) => {
    mount(asOf, icon("calendar", 15), asOfText(state.asOf));
    steps.update(canStep(-1), canStep(1));
    tour.setAttribute("aria-label", t("shell.tour"));
    mount(tour, icon("tour", 15), h("span", { class: "lbl" }, t("shell.tour")));
  };
  subscribe((state, prev) => {
    if (state.asOf !== prev.asOf || state.lang !== prev.lang) render(state);
  });
  render(getState());
}

/** The role switch; the toolbar and the phone each have one, kept in step. */
function roleSwitch() {
  const control = segmented({
    label: t("shell.role.label"),
    options: ROLE_OPTIONS(),
    value: roleOf(getState().route),
    onChange: (role) => navigate(HOME[role]),
  });
  roleSwitches.push(control);
  return control;
}

// ---------------------------------------------------------------- phone and tablet (<1024)

function mountPhoneBar() {
  const tour = iconButton({ icon: "tour", size: 20, label: t("shell.tour"), onClick: () => startTour() });
  const capsule = h("span", { class: "capsule-slot" }, prototypeCapsule());
  mount(
    $("#mtop"),
    h("span", { class: "mark sm" }, icon("mark", 16)),
    h(
      "span",
      { class: "swapname" },
      h("span", { class: "mt-brand" }, appName),
      h("span", { class: "mt-title", id: "mt-title", "aria-hidden": "true" }),
    ),
    capsule,
    tour,
  );
  mount($("#m-role"), roleSwitch().el);
  subscribe((state, prev) => {
    if (state.lang === prev.lang) return;
    tour.setAttribute("aria-label", t("shell.tour"));
    mount(capsule, prototypeCapsule());
  });
}

function renderTabbar(state) {
  const role = roleOf(state.route);
  const trendOpen = state.pane?.kind === "trend";
  const tabs =
    role === "ic"
      ? [
          {
            icon: "brief",
            label: t("shell.tab.brief"),
            current: briefTab === "brief",
            onClick: () => scrollToSection(null, "brief"),
          },
          {
            icon: "grid",
            label: t("shell.tab.wards"),
            current: briefTab === "wards",
            onClick: () => scrollToSection("#sec-map", "wards"),
          },
          { icon: "replay", label: t("shell.tab.replay"), onClick: openReplaySheet },
        ]
      : [
          {
            icon: "ward",
            label: t("shell.tab.ward"),
            current: state.route === "ward" && !trendOpen,
            onClick: () => navigate("ward"),
          },
          { icon: "trend", label: t("shell.tab.trend"), current: trendOpen, onClick: () => openTrend(state) },
          {
            icon: "order",
            label: t("shell.tab.order"),
            current: state.route === "order",
            onClick: () => navigate("order"),
          },
          { icon: "replay", label: t("shell.tab.replay"), onClick: openReplaySheet },
        ];
  const bar = $("#tabbar");
  bar.setAttribute("aria-label", t("shell.tabs"));
  mount(
    bar,
    tabs.map((tab) =>
      h(
        "button",
        { type: "button", "aria-current": tab.current ? "page" : null, onclick: tab.onClick },
        icon(tab.icon, 18),
        h("span", null, tab.label),
      ),
    ),
  );
}

function openTrend(state) {
  const drug = state.params.drug ?? "";
  if (state.route === "ward") openPane("trend", drug);
  else navigate("ward", { pane: { kind: "trend", id: drug } });
}

function scrollToSection(selector, tab) {
  briefTab = tab;
  renderTabbar(getState());
  const target = selector && $(selector);
  const behavior = reducedMotion() ? "auto" : "smooth";
  if (target) target.scrollIntoView({ block: "start", behavior });
  else scrollTo({ top: 0, behavior });
}

// ---------------------------------------------------------------- language

/** The EN | FI switch. Returns { el, set }. The id keeps focus on it across a re-render. */
export function langSwitch(id) {
  return segmented({
    label: t("shell.lang.label"),
    options: LANG_OPTIONS,
    value: getState().lang,
    small: true,
    id,
    onChange: (lang) => setState({ lang }),
  });
}

// ---------------------------------------------------------------- page head, scrolled title, announcements

/**
 * The head every page view starts with: the Large title (h1#view-title, the view's label), on phones the as-of
 * pill (opens the replay sheet) and the language switch, then the dateline nodes.
 */
export function pageHead({ title, dateline }) {
  const { asOf } = getState();
  return h(
    "header",
    { class: "pagehead" },
    h("h1", { class: "t-large", id: "view-title", tabindex: "-1" }, title),
    h(
      "div",
      { class: "m-asof m-only" },
      h(
        "button",
        {
          type: "button",
          class: "btn btn-bordered asof-pill",
          id: "asof-pill",
          "aria-haspopup": "dialog",
          onclick: openReplaySheet,
        },
        icon("replay", 15),
        asOfText(asOf),
        icon("down", 10),
      ),
      langSwitch("lang-page").el,
    ),
    dateline && h("p", { class: "dateline t-subhead" }, dateline),
  );
}

/** "As of <b>Sun 29 Mar 2026</b>" for the toolbar and the phone's as-of pill. */
const asOfText = (asOf) =>
  h("span", null, h("span", { class: "pre" }, t("shell.asOf"), " "), h("b", null, dateLong(asOf)));

/**
 * Mirrors the view's h1 into the toolbar, the phone bar and the document title, and shows it in the bars once
 * the h1 scrolls away.
 */
export function observeTitle(root) {
  titleObserver?.disconnect();
  const heading = $("h1", root);
  const text = heading?.textContent ?? "";
  $("#tb-title").textContent = text;
  $("#mt-title").textContent = text;
  document.title = text ? `${text} · ${appName}` : appName;
  if (!heading) return;
  const compact = matchMedia("(max-width: 1023px)").matches;
  titleObserver = new IntersectionObserver(
    ([entry]) => {
      const away = !entry.isIntersecting && entry.boundingClientRect.top < 80;
      document.body.classList.toggle("scrolled", away);
      $("#mtop").classList.toggle("scrolled", away);
    },
    { rootMargin: `-${compact ? 52 : 98}px 0px 0px 0px` },
  );
  titleObserver.observe(heading);
}

/** Reads each replay step out: "Monday brief, Mon 9 Mar 2026: 2 P1, 1 P2, 3 P3, 2 info." */
async function announceWeek(state) {
  const live = $("#live");
  if (roleOf(state.route) === "doc") {
    live.textContent = t("shell.announce.ward", { date: dateLong(state.asOf) });
    return;
  }
  const brief = await loadBrief(state.asOf).catch(() => null);
  if (getState().asOf !== state.asOf) return;
  const c = brief?.counts ?? {};
  live.textContent = brief
    ? t("shell.announce.brief", {
        date: dateLong(mondayOf(state.asOf)),
        P1: c.P1 ?? 0,
        P2: c.P2 ?? 0,
        P3: c.P3 ?? 0,
        info: c.info ?? 0,
      })
    : t("shell.announce.week", { date: dateLong(state.asOf) });
}
