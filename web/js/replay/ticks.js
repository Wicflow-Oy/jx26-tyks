// The week scrubber: one tick per replay week (height by signal count), a red dot above past P1 weeks, a ◆ under
// the tour start, quarter labels, and an ink playhead with its date pill. A transparent range input on top is the
// real control: arrows step a week, Home and End jump to the ends, a drag scrubs. Used by the desktop rail and the
// phone sheet.

import { linear, onWidth, px } from "../components/svg.js";
import { parseISO } from "../dates.js";
import { h, s } from "../dom.js";
import { dateShort, monthShort } from "../format.js";
import { t } from "../i18n.js";
import { loadBrief } from "../signals.js";
import { getState, setAsOf, subscribe } from "../state.js";
import { getTourStart, getWeeks, onTimeline, weekIndex, weekValueText } from "./timeline.js";

// the range thumb is 2 × PAD wide (replay.css), so the browser maps a pointer to the same week the drawing shows
const PAD = 4;
const PILL_W = 50;
// while dragging, the playhead follows the pointer at once and the views follow at most this often
const DRAG_COMMIT_MS = 180;

/**
 * weekScrubber({ height, top, base, maxTick, label }) → element. Geometry in px: the playhead runs from top to
 * base, ticks grow up from base by up to maxTick, and label is the baseline of the date row.
 */
export function weekScrubber(geometry) {
  const svg = s("svg", { "aria-hidden": "true" });
  const input = h("input", { type: "range", min: 0, step: 1, value: 0 });
  const el = h("div", { class: "ticks" }, svg, input);
  let width = 0;
  let dragging = false;
  let hover = -1;
  let commitTimer = 0;

  const pickedAsOf = () => getWeeks()[Number(input.value)]?.as_of;
  const shownAsOf = () => (dragging ? pickedAsOf() : getState().asOf) ?? getState().asOf;

  const redraw = () => {
    const asOf = shownAsOf();
    input.max = String(Math.max(0, getWeeks().length - 1));
    if (!dragging) input.value = String(Math.max(0, weekIndex(asOf)));
    input.setAttribute("aria-label", t("replay.rangeLabel"));
    input.setAttribute("aria-valuetext", weekValueText(asOf));
    if (width) draw(svg, width, { asOf, hover }, geometry);
  };

  const commit = () => {
    clearTimeout(commitTimer);
    commitTimer = 0;
    const asOf = pickedAsOf();
    if (asOf && asOf !== getState().asOf) setAsOf(asOf);
  };

  input.addEventListener("input", () => {
    if (dragging) {
      redraw();
      commitTimer ||= setTimeout(commit, DRAG_COMMIT_MS);
    } else {
      commit(); // keyboard: one week per key press
    }
  });
  input.addEventListener("pointerdown", () => {
    dragging = true;
    hover = -1;
    onRelease(() => {
      dragging = false;
      commit();
      redraw();
    });
  });
  // a hover line and date show which week a click would pick (mouse only; touch has no hover)
  input.addEventListener("pointermove", (event) => {
    const at = indexAt(event.offsetX, width);
    if (event.pointerType !== "mouse" || dragging || at === hover) return;
    hover = at;
    redraw();
  });
  input.addEventListener("pointerleave", () => {
    hover = -1;
    redraw();
  });

  onWidth(el, (w) => {
    width = w;
    redraw();
  });
  subscribe((state, prev) => {
    if (state.asOf === prev.asOf && state.lang === prev.lang) return;
    redraw();
    speakCounts(input, state.asOf);
  });
  onTimeline(redraw);
  return el;
}

/** Upgrades the spoken value to the brief's per-priority counts once that (shared, cached) brief has loaded. */
async function speakCounts(input, asOf) {
  const brief = await loadBrief(asOf).catch(() => null);
  if (brief?.counts && getState().asOf === asOf)
    input.setAttribute("aria-valuetext", weekValueText(asOf, brief.counts));
}

function indexAt(offsetX, width) {
  const last = getWeeks().length - 1;
  if (last < 1 || width <= 2 * PAD) return -1;
  return Math.min(last, Math.max(0, Math.round(((offsetX - PAD) / (width - 2 * PAD)) * last)));
}

function draw(svg, width, { asOf, hover }, { height, top, base, maxTick, label }) {
  const weeks = getWeeks();
  const x = linear([0, Math.max(1, weeks.length - 1)], [PAD, width - PAD]);
  const current = weekIndex(asOf);
  const maxSignals = Math.max(1, ...weeks.map((w) => w.n_signals ?? 0));
  const tickTop = (week) => base - 4 - maxTick * ((week.n_signals ?? 0) / maxSignals);
  const nodes = [s("line", { class: "tk-base", x1: PAD, x2: width - PAD, y1: base + 0.5, y2: base + 0.5 })];

  // P1 dots shrink where weeks sit close together (phones), so neighbours do not merge
  const dotR = Math.min(2, (x(1) - x(0)) * 0.45);
  weeks.forEach((week, i) => {
    const past = i <= current;
    const y = tickTop(week);
    nodes.push(s("line", { class: ["tk", !past && "future"], x1: px(x(i)), x2: px(x(i)), y1: px(y), y2: base }));
    // only weeks up to the as-of date may show a P1 (strict as-of)
    if (past && week.n_p1 > 0) nodes.push(s("circle", { class: "tk-p1", cx: px(x(i)), cy: px(y - 4.5), r: px(dotR) }));
  });

  const head = x(Math.max(0, current));
  nodes.push(s("line", { class: "tk-head", x1: px(head), x2: px(head), y1: top, y2: base + 1 }));

  const pillAt = (cx) => Math.min(Math.max(cx, PAD + PILL_W / 2), width - PAD - PILL_W / 2);
  const pills = [pillAt(head)];
  if (hover >= 0 && hover !== current) {
    nodes.push(s("line", { class: "tk-hover", x1: px(x(hover)), x2: px(x(hover)), y1: top, y2: base + 1 }));
    // the hover date gets its own pill unless it would overlap the playhead's
    if (Math.abs(pillAt(x(hover)) - pills[0]) >= PILL_W + 4) pills.push(pillAt(x(hover)));
  }
  const underPill = (cx) => pills.some((p) => Math.abs(cx - p) <= PILL_W / 2 + 4);

  const tour = weekIndex(getTourStart());
  if (tour >= 0 && !underPill(x(tour))) {
    nodes.push(s("path", { class: "tk-tour", d: `M${px(x(tour))} ${base + 3}l3.4 3.4-3.4 3.4-3.4-3.4z` }));
  }

  // quarter labels at each quarter's first Sunday (the year at January), hidden where a date pill sits
  weeks.forEach((week, i) => {
    const d = parseISO(week.as_of);
    const month = d.getUTCMonth();
    if (month % 3 !== 0 || d.getUTCDate() > 7 || pills.some((p) => Math.abs(x(i) - p) <= PILL_W / 2 + 18)) return;
    const text = month === 0 ? String(d.getUTCFullYear()) : monthShort(week.as_of);
    nodes.push(s("text", { class: "tk-label", x: px(x(i)), y: label, "text-anchor": "middle" }, text));
  });

  if (pills[1]) nodes.push(...datePill(pills[1], label, weeks[hover].as_of, true));
  nodes.push(...datePill(pills[0], label, asOf, false));

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.replaceChildren(...nodes);
}

const datePill = (cx, label, asOf, hovered) => [
  s("rect", {
    class: ["tk-pill", hovered && "hover"],
    x: px(cx - PILL_W / 2),
    y: label - 11,
    width: PILL_W,
    height: 15,
    rx: 7.5,
  }),
  s(
    "text",
    { class: ["tk-pill-text", hovered && "hover"], x: px(cx), y: label, "text-anchor": "middle" },
    dateShort(asOf),
  ),
];

/** Runs fn once when the pointer is released or the gesture is cancelled, wherever the pointer is. */
function onRelease(fn) {
  const done = () => {
    removeEventListener("pointerup", done);
    removeEventListener("pointercancel", done);
    fn();
  };
  addEventListener("pointerup", done);
  addEventListener("pointercancel", done);
}
