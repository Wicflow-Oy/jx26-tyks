// The replay sheet for tablets and phones: the rail's drawing in a bottom sheet, with the week stepper,
// Play March, Tour start and Latest. Opened by the as-of pill and the Replay tab.

import { button, iconButton, weekStepper } from "../components/buttons.js";
import { openLayer, returnFocus } from "../components/layers.js";
import { mondayOf } from "../dates.js";
import { $, h, mount } from "../dom.js";
import { dateLong } from "../format.js";
import { t } from "../i18n.js";
import { asOfRange, getState, subscribe } from "../state.js";
import { playButton } from "./rail.js";
import { weekScrubber } from "./ticks.js";
import { canStep, getTourStart, goLatest, goTourStart, onTimeline, step, weekOf } from "./timeline.js";

const SHEET_GEOMETRY = { height: 64, top: 6, base: 40, maxTick: 20, label: 60 };
let close = null;

/** Fills #replay-sheet once; it stays in sync while hidden, so opening it is instant. */
export function mountReplaySheet(sheet) {
  const read = h("div", { class: "scrub-read", id: "scrub-read" });
  const sub = h("p", { class: "scrub-sub" });
  const eyebrow = h("div", { class: "eyebrow" });
  const closeButton = iconButton({ icon: "close", label: t("shell.close"), onClick: () => close?.() });
  const steps = weekStepper({ onStep: step });
  const tourButton = button({ label: "", variant: "plain", onClick: goTourStart });
  const latestButton = button({ label: "", variant: "plain", onClick: goLatest });
  const scrubber = weekScrubber(SHEET_GEOMETRY);

  mount(
    sheet,
    h("div", { class: "grabber", "aria-hidden": "true" }),
    h("div", { class: "scrub-head" }, h("div", null, eyebrow, read, sub), closeButton),
    scrubber,
    h("div", { class: "scrub-ctrls" }, steps.el, playButton(), tourButton, latestButton),
  );
  sheet.setAttribute("aria-labelledby", "scrub-read");

  const render = () => {
    const { asOf } = getState();
    const week = weekOf(asOf) ?? {};
    eyebrow.textContent = t("replay.sheetEyebrow");
    mount(
      read,
      dateLong(asOf),
      week.n_signals != null && h("span", null, " · ", t("replay.read", { p1: week.n_p1 ?? 0, n: week.n_signals })),
    );
    sub.textContent = t("replay.sheetSub", { date: dateLong(mondayOf(asOf)) });
    closeButton.setAttribute("aria-label", t("shell.close"));
    steps.update(canStep(-1), canStep(1));
    tourButton.textContent = t("replay.tourStart");
    tourButton.setAttribute(
      "aria-label",
      t("replay.tourStartAria", { date: getTourStart() ? dateLong(getTourStart()) : "" }),
    );
    tourButton.hidden = !getTourStart();
    latestButton.textContent = t("replay.latest");
    latestButton.disabled = asOf === asOfRange().last;
  };
  subscribe((state, prev) => {
    if (state.asOf !== prev.asOf || state.lang !== prev.lang) render();
  });
  onTimeline(render);
  render();
}

export function openReplaySheet() {
  if (close) return;
  const sheet = $("#replay-sheet");
  const opener = document.activeElement;
  sheet.classList.add("open");
  const removeLayer = openLayer({ kind: "replay", el: sheet, close: () => close(), scrim: true, modal: true });
  close = () => {
    close = null;
    removeLayer();
    sheet.classList.remove("open");
    returnFocus(opener, "#asof-pill"); // the pill is re-rendered with the view on each step
  };
  requestAnimationFrame(() => close && $("input[type=range]", sheet)?.focus());
}
