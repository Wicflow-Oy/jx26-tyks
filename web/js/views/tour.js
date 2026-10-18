// The guided tour: five usage-only steps from the tour start week (/api/meta tour_start_as_of). Each step sets the
// app state (route, pane, week), then a dark popover and an accent ring follow the step's target as views render.
// Texts are built from the brief's own data (dates, the signal's title, its ward); nothing is invented.
// Each step lists its targets in order of preference; the first one on screen gets the ring.

import { get } from "../api.js";
import { openLayer, returnFocus } from "../components/layers.js";
import { focusPane } from "../components/pane.js";
import { mondayOf } from "../dates.js";
import { $, $$, h, mount, reducedMotion } from "../dom.js";
import { dateLong } from "../format.js";
import { t } from "../i18n.js";
import { getTourStart, playWeeks, stopPlay, weekAfter } from "../replay/timeline.js";
import { briefItems, byPriority, findItem, isSignal, loadBrief, signalTitle } from "../signals.js";
import { getState, setState, subscribe } from "../state.js";

const compact = () => matchMedia("(max-width: 1023px)").matches;
const wide = () => matchMedia("(min-width: 1280px)").matches;
const GAP = 12; // between the target and the popover, and from the viewport edges
const RING_OUTSET = 4;

const paneRow = (data) => data.item && `#view [data-pane-id="${CSS.escape(data.item.id)}"]`;

/** Each step: the app state it shows, its target candidates (first visible wins) and its text. */
const STEPS = [
  {
    state: (d) => ({ route: "brief", pane: null, asOf: d.start, params: {} }),
    targets: () => [compact() ? "#asof-pill" : "#rail", "#view .pagehead"],
    text: (d) => t("tour.brief", { date: dateLong(d.start) }),
  },
  {
    state: (d) => ({ route: "brief", pane: null, asOf: d.next, params: {} }),
    targets: (d) => [paneRow(d), compact() ? "#asof-pill" : "#rail"],
    text: (d) => {
      const how = t(compact() ? "tour.howStepCompact" : "tour.howStep");
      const date = dateLong(mondayOf(d.next));
      if (d.item?.status !== "new") return t("tour.patternNone", { how, date });
      return t("tour.pattern", { how, date, priority: d.item.priority, title: signalTitle(d.item) });
    },
  },
  {
    state: (d) => ({
      route: "brief",
      pane: d.item ? { kind: "case", id: d.item.id } : null,
      asOf: d.later,
      params: {},
    }),
    targets: (d) => ["#pane-actions", "#pane .pane-body", paneRow(d)],
    text: (d) =>
      d.item ? t("tour.case", { title: signalTitle(d.item), date: dateLong(d.later) }) : t("tour.caseNone"),
  },
  {
    state: (d) => ({ route: "ward", pane: null, asOf: d.later, params: d.item?.ward ? { ward: d.item.ward } : {} }),
    targets: () => ["#view .banner", "#view .lead", "#view .pagehead"],
    text: (d) => {
      const ward = d.item?.slots?.ward_label ?? d.item?.ward;
      return ward ? t("tour.ward", { ward }) : t("tour.wardNone");
    },
  },
  {
    // the demo patient on the signal's unit (GET /api/demo/scenarios); the order view opens the visit's own week
    state: (d) => ({ route: "order", pane: null, params: d.scenario ? { patient: d.scenario } : {} }),
    targets: () => ["#view .sw-layer", "#view .composer", "#view .pagehead"],
    text: () => t("tour.order"),
  },
];

let tour = null; // while open: { index, data, ticket, opener, removeLayer, frame, target, rect, stable, settled }
let ui = null; // the popover parts, built once

/** Starts (or restarts) the tour at step 1. Called by the toolbar's and the phone bar's Start tour buttons. */
export async function startTour() {
  stopPlay();
  ui ??= buildUi();
  if (!tour) {
    tour = {
      opener: document.activeElement,
      removeLayer: openLayer({ kind: "tour", el: ui.el, close: endTour, modal: true }),
    };
    ui.el.hidden = false;
    void ui.el.offsetWidth; // start the fade-in from the hidden state
    ui.el.classList.add("on");
    tour.frame = requestAnimationFrame(track);
  }
  await show(0);
}

function buildUi() {
  const el = $("#tour");
  el.setAttribute("aria-modal", "true");
  el.setAttribute("aria-labelledby", "tour-count");
  el.setAttribute("aria-describedby", "tour-text");
  const parts = {
    el,
    count: h("p", { class: "tour-count", id: "tour-count" }),
    text: h("p", { class: "tour-text", id: "tour-text" }),
    skip: h("button", { type: "button", class: "tour-btn", onclick: endTour }),
    back: h("button", { type: "button", class: "tour-btn", onclick: () => show(tour.index - 1) }),
    next: h("button", { type: "button", class: "tour-btn primary", onclick: () => next() }),
    ring: h("div", { class: "tour-ring", "aria-hidden": "true" }),
  };
  // the step text is announced when it changes; focus stays on Next
  mount(
    el,
    h("div", { "aria-live": "polite", "aria-atomic": "true" }, parts.count, parts.text),
    h("div", { class: "tour-btns" }, parts.skip, h("span", { class: "grow" }), parts.back, parts.next),
  );
  document.body.append(parts.ring);
  subscribe((state, prev) => tour && state.lang !== prev.lang && show(tour.index, { move: false }));
  return parts;
}

const next = () => (tour.index >= STEPS.length - 1 ? endTour() : show(tour.index + 1));

/** Shows step i: loads its data (cached briefs), moves the app there and rewrites the popover. */
async function show(i, { move = true } = {}) {
  const ticket = (tour.ticket = {});
  const data = await tourData();
  if (!tour || tour.ticket !== ticket) return; // closed, or a newer step was asked for meanwhile
  const step = STEPS[i];
  tour.index = i;
  tour.data = data;
  if (move) {
    const patch = step.state(data);
    setState(patch, { push: patch.route !== getState().route });
    Object.assign(tour, { target: null, rect: null, stable: 0, settled: false });
  }
  ui.count.textContent = t("tour.count", { n: i + 1, total: STEPS.length });
  ui.text.textContent = step.text(data);
  ui.skip.textContent = t("tour.skip");
  ui.skip.hidden = i === STEPS.length - 1;
  ui.back.textContent = t("tour.back");
  ui.back.hidden = i === 0;
  ui.next.textContent = t(i === STEPS.length - 1 ? "tour.done" : "tour.next");
  if (!ui.el.contains(document.activeElement) || document.activeElement.hidden) ui.next.focus({ preventScroll: true });
}

/**
 * The weeks and the signal the tour shows: the tour start, the week after it (where the new signal appears) and
 * the end of the tour month (where the case file and My ward are shown), plus the demo order on that signal's unit.
 * Everything comes from the shared GET cache.
 */
async function tourData() {
  const start = getTourStart() || getState().asOf;
  const nextWeek = weekAfter(1, start) ?? start;
  const monthEnd = playWeeks().at(-1) ?? nextWeek;
  const [nextBrief, endBrief, scenarios] = await Promise.all([
    loadBrief(nextWeek).catch(() => null),
    loadBrief(monthEnd).catch(() => null),
    get("/api/demo/scenarios", {}, { asOf: false }).catch(() => []),
  ]);
  const open = briefItems(nextBrief).filter(isSignal);
  const item = byPriority(open.filter((x) => x.status === "new"))[0] ?? byPriority(open)[0] ?? null;
  const later = item && findItem(endBrief, item.id) ? monthEnd : nextWeek;
  const scenario = Array.isArray(scenarios) && item ? scenarios.find((x) => x.unit === item.ward)?.key : undefined;
  return { start, next: nextWeek, later, item, scenario };
}

function endTour() {
  if (!tour) return;
  cancelAnimationFrame(tour.frame);
  const { opener, removeLayer } = tour;
  tour = null;
  removeLayer();
  // hidden at once (no fade-out), so nothing can return focus to its buttons once it is closed
  ui.el.classList.remove("on");
  ui.el.hidden = true;
  ui.ring.classList.remove("on");
  // a pushed case page or drawer covers the opener; focus goes into it instead
  if (getState().pane && !wide()) focusPane();
  else returnFocus(opener, compact() ? "#mtop .icon-btn" : ".tb-tour");
}

// ---------------------------------------------------------------- following the target

/** Runs every frame while the tour is open: finds the target, scrolls it into view once, and places the parts. */
function track() {
  if (!tour) return;
  tour.frame = requestAnimationFrame(track);
  if (tour.data == null) return;
  const target = findTarget(STEPS[tour.index].targets(tour.data));
  const rect = target?.getBoundingClientRect() ?? null;
  tour.stable = target === tour.target && sameRect(rect, tour.rect) ? tour.stable + 1 : 0;
  if (target !== tour.target) matchRadius(target);
  tour.target = target;
  tour.rect = rect;
  // a view renders its loading state first: act once the target has held still for a few frames
  if (target && tour.stable === 3 && !tour.settled) {
    tour.settled = true;
    if (!inView(rect))
      target.scrollIntoView({
        block: rect.height > innerHeight / 2 ? "start" : "center",
        behavior: reducedMotion() ? "auto" : "smooth",
      });
    // opening a pane moves focus into it; the tour keeps it while it is open
    if (!ui.el.contains(document.activeElement)) ui.next.focus({ preventScroll: true });
  }
  place(rect);
}

function findTarget(selectors) {
  for (const selector of selectors.filter(Boolean)) {
    const el = $$(selector).find((node) => node.getClientRects().length > 0);
    if (el) return el;
  }
  return null;
}

const sameRect = (a, b) =>
  a && b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height;

/** The space the fixed bars leave: toolbar and rail on desktop, the top bar and tab bar on phones. */
function viewport() {
  const bar = compact() ? $("#mtop") : $("#rail");
  const tabbar = $("#tabbar");
  const top = Math.max(GAP, (bar?.getBoundingClientRect().bottom ?? 0) + GAP);
  const tabTop = tabbar?.getClientRects().length ? tabbar.getBoundingClientRect().top : innerHeight;
  return { top, bottom: Math.min(innerHeight, tabTop) - GAP };
}

const inView = (rect) => {
  const { top, bottom } = viewport();
  return rect.top >= top && rect.bottom <= bottom;
};

/** Ring around the target; popover below it, else above it, else at the bottom of the screen. */
function place(rect) {
  const { top: minTop, bottom: maxBottom } = viewport();
  const width = ui.el.offsetWidth;
  const height = ui.el.offsetHeight;
  let left = (innerWidth - width) / 2;
  let top = maxBottom - height;
  if (rect) {
    left = rect.left;
    if (rect.bottom + GAP + height <= maxBottom) top = rect.bottom + GAP;
    else if (rect.top - GAP - height >= minTop) top = rect.top - GAP - height;
  }
  setBox(ui.el, {
    left: clamp(left, GAP, innerWidth - width - GAP),
    top: clamp(top, minTop, maxBottom - height),
  });
  ui.ring.classList.toggle("on", Boolean(rect));
  if (rect) {
    // RING_OUTSET outside the target, but never past the window's edges (a pane's action bar touches them)
    const left = Math.max(2, rect.left - RING_OUTSET);
    const top = Math.max(2, rect.top - RING_OUTSET);
    const right = Math.min(innerWidth - 2, rect.right + RING_OUTSET);
    const bottom = Math.min(innerHeight - 2, rect.bottom + RING_OUTSET);
    setBox(ui.ring, { left, top, width: right - left, height: bottom - top });
  }
}

/** The ring follows the target's corner radius, RING_OUTSET further out. */
function matchRadius(target) {
  const radius = target ? parseFloat(window.getComputedStyle(target).borderTopLeftRadius) || 8 : 8;
  ui.ring.style.borderRadius = `${radius + RING_OUTSET}px`;
}

const clamp = (value, min, max) => Math.max(min, Math.min(value, Math.max(min, max)));

function setBox(el, box) {
  for (const [prop, value] of Object.entries(box)) {
    const css = `${Math.round(value)}px`;
    if (el.style[prop] !== css) el.style[prop] = css;
  }
}
