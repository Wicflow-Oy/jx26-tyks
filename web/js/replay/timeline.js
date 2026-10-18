// The replay weeks: tick data from GET /api/replay/weeks, stepping one week, and "Play March" (the tour month,
// one week every 1.1 s). Moving the week always goes through the global as-of in state.js.

import { get } from "../api.js";
import { parseISO, weekGrid } from "../dates.js";
import { dateLong } from "../format.js";
import { t } from "../i18n.js";
import { loadBrief } from "../signals.js";
import { asOfRange, getState, setAsOf, subscribe } from "../state.js";

const PLAY_STEP_MS = 1100;
const REFRESH_MS = 20_000;
const REFRESH_LIMIT = 6;
// used only when /api/meta has no tour_start_as_of (an older backend); ignored unless it is a replay week
const TOUR_START_FALLBACK = "2026-03-01";

let weeks = []; // [{ as_of, monday, n_p1, n_signals }], oldest first
let tourStart = "";
let playTimer = 0;
let playAsOf = ""; // the week Play set last; any other move stops Play
const listeners = new Set();

/** Starts from the meta week grid (so the rail works at once) and loads the tick counts. */
export function initTimeline(meta) {
  const grid = weekGrid(meta.replay.first, meta.replay.last);
  const start = meta.tour_start_as_of ?? TOUR_START_FALLBACK;
  tourStart = grid.includes(start) ? start : "";
  weeks = grid.map((asOf) => ({ as_of: asOf }));
  subscribe((state, prev) => {
    if (isPlaying() && state.asOf !== prev.asOf && state.asOf !== playAsOf) stopPlay();
  });
  loadWeeks(0);
}

async function loadWeeks(attempt) {
  try {
    const rows = await get("/api/replay/weeks", {}, { asOf: false, lang: false, fresh: attempt > 0 });
    if (!Array.isArray(rows) || rows.length === 0) return;
    weeks = rows;
    notify();
    // after a server restart the counts are filled in the background; fetch again until every week has them
    if (rows.some((row) => row.n_signals == null) && attempt < REFRESH_LIMIT) {
      setTimeout(() => loadWeeks(attempt + 1), REFRESH_MS);
    }
  } catch {
    // the rail keeps working on the week grid; ticks stay flat until a reload
  }
}

/** fn() runs when the tick data or the play state changes. */
export function onTimeline(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

const notify = () => listeners.forEach((fn) => fn());

export const getWeeks = () => weeks;
export const getTourStart = () => tourStart;
export const weekIndex = (asOf) => weeks.findIndex((week) => week.as_of === asOf);
export const weekOf = (asOf) => weeks[weekIndex(asOf)];

/** The week delta steps away from asOf (default: the current week), or undefined past either end. */
export function weekAfter(delta, asOf = getState().asOf) {
  const i = weekIndex(asOf);
  return i < 0 ? undefined : weeks[i + delta]?.as_of;
}

export const canStep = (delta) => Boolean(weekAfter(delta));

export function step(delta) {
  const asOf = weekAfter(delta);
  if (asOf) setAsOf(asOf);
}

export const goLatest = () => setAsOf(asOfRange().last);
export const goTourStart = () => setAsOf(tourStart);

/**
 * The range input's spoken value. With the brief's per-priority counts: "Sun 8 Mar 2026: 2 P1, 1 P2, 3 P3, 2 info";
 * without them, the replay totals: "Sun 8 Mar 2026: 2 P1, 6 signals".
 */
export function weekValueText(asOf, counts) {
  const date = dateLong(asOf);
  if (counts) {
    const { P1 = 0, P2 = 0, P3 = 0, info = 0 } = counts;
    return t("replay.valueText.counts", { date, P1, P2, P3, info });
  }
  const week = weekOf(asOf);
  if (week?.n_signals != null) return t("replay.valueText.totals", { date, p1: week.n_p1 ?? 0, n: week.n_signals });
  return date;
}

// ---------------------------------------------------------------- Play: the tour month, week by week

/** The weeks Play steps through: from the tour start to the last Sunday of that month. */
export function playWeeks() {
  if (!tourStart) return [];
  const month = parseISO(tourStart).getUTCMonth();
  return weeks.map((w) => w.as_of).filter((asOf) => asOf >= tourStart && parseISO(asOf).getUTCMonth() === month);
}

export const isPlaying = () => playTimer !== 0;

export function togglePlay() {
  if (isPlaying()) {
    stopPlay();
    return;
  }
  const run = playWeeks();
  if (run.length < 2) return;
  // warm the shared brief cache so each week shows as soon as Play reaches it
  for (const asOf of run) loadBrief(asOf).catch(() => {});
  // from the current week when it is inside the run, else from the start
  const startAt = run.slice(0, -1).includes(getState().asOf) ? getState().asOf : run[0];
  moveTo(startAt);
  playTimer = setInterval(() => {
    const next = run[run.indexOf(getState().asOf) + 1];
    if (next) moveTo(next);
    if (!next || next === run.at(-1)) stopPlay();
  }, PLAY_STEP_MS);
  notify();
}

export function stopPlay() {
  if (!isPlaying()) return;
  clearInterval(playTimer);
  playTimer = 0;
  notify();
}

function moveTo(asOf) {
  playAsOf = asOf;
  setAsOf(asOf);
}
