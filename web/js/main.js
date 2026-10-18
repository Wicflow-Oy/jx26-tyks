// Boot and route dispatch. Loads /api/meta, reads the URL into the app state, builds the shell, then renders the
// page view for the route and the pane view beside it whenever the state changes.
//
// The view contract (js/views/*.js):
//   export async function render(root, ctx)
//   ctx = { state, meta, filters, signal, first, retry }
//   - root: the page's <section id="view"> or the pane body; the view replaces its children (dom.mount).
//   - meta, filters: GET /api/meta and GET /api/filters (in the current language).
//   - signal: an AbortSignal; pass it to api.get(). When the state moves on, the request aborts: rethrow it.
//   - first: true when this route or pane item is new (show the loading state); false on a replay step, when
//     the old content should stay until the new week has loaded.
//   - retry(): renders the view again (for the error state's Try again).
// Page views start with shell.pageHead(). Elements with data-pane-id="<id>" get aria-current while that pane
// item is open; numbers wrapped in marker.mk(key, …) are underlined when a replay step changes them.
// After any write (an approval, a heads-up) the page and the pane render again from fresh data.
// ?state=loading or ?state=error shows those states for the page (DESIGN §3).

import { ApiError, get, isAbort, onWrite } from "./api.js";
import { markChanges, snapshotMarks } from "./components/marker.js";
import { focusPane, hidePane, showPane } from "./components/pane.js";
import { errorState, loadingState } from "./components/states.js";
import { isISODate } from "./dates.js";
import { $, $$, mount, reducedMotion } from "./dom.js";
import { initLang, storedLang, t } from "./i18n.js";
import { initTimeline } from "./replay/timeline.js";
import { mountShell, observeTitle, pageHead } from "./shell.js";
import { closePane, getState, initState, isDefaultPane, subscribe } from "./state.js";
import * as brief from "./views/brief.js";
import * as caseFile from "./views/case.js";
import * as order from "./views/order.js";
import { startTour } from "./views/tour.js";
import * as trend from "./views/trend.js";
import * as ward from "./views/ward.js";

const PAGES = { brief, ward, order };
const PANES = { case: caseFile, trend };

let meta = null; // GET /api/meta
let pageRun = null;
let paneRun = null;
let lastFocused = null; // see restoreFocus()
document.addEventListener("focusin", (event) => (lastFocused = event.target));

boot();

async function boot() {
  const root = $("#view");
  mount(root, loadingState(t("shell.loading")));
  try {
    meta = await get("/api/meta", {}, { asOf: false, lang: false });
    if (!isISODate(meta?.replay?.first) || !isISODate(meta?.replay?.last)) throw new ApiError("server");
  } catch (error) {
    mount(root, errorState({ title: t("shell.error.boot"), error, onRetry: boot }));
    return;
  }
  initState(meta.replay, storedLang());
  initLang();
  initTimeline(meta);
  mountShell({ meta, onTour: startTour });
  subscribe(onChange);
  onWrite(() => {
    const state = getState();
    renderPage(state, state);
    renderPane(state, state);
  });
  onChange(getState(), null);
}

function onChange(state, prev) {
  const scopeChanged =
    !prev || state.asOf !== prev.asOf || state.lang !== prev.lang || paramsKey(state) !== paramsKey(prev);
  if (scopeChanged || state.route !== prev.route) renderPage(state, prev);
  if (scopeChanged || !samePane(state.pane, prev?.pane)) renderPane(state, prev);
  markSelection(state);
}

async function renderPage(state, prev) {
  pageRun?.abort();
  const run = (pageRun = new AbortController());
  const root = $("#view");
  const first = !prev || state.route !== prev.route;
  const before = first ? null : snapshotMarks(root);
  const focusId = focusedId(root);

  if (DEMO_STATES.includes(state.params.state)) {
    mount(root, pageHead({ title: t(`${state.route}.title`) }), demoState(state.params.state));
    observeTitle(root);
    return;
  }
  await runView(PAGES[state.route], root, {
    state,
    first,
    signal: run.signal,
    retry: () => renderPage(getState(), null),
  });
  if (run.signal.aborted) return;

  if (first) scrollTo({ top: 0 });
  else if (state.asOf !== prev.asOf) {
    markChanges(root, before);
    crossfade(root);
  }
  restoreFocus(root, focusId);
  observeTitle(root);
  markSelection(getState());
}

async function renderPane(state, prev) {
  paneRun?.abort();
  if (!state.pane) {
    hidePane();
    return;
  }
  const run = (paneRun = new AbortController());
  const { kind, id } = state.pane;
  const first = !samePane(state.pane, prev?.pane);
  const root = showPane({
    label: t(`shell.pane.${kind}`),
    backLabel: t(`shell.back.${state.route}`),
    returnTo: `#view [data-pane-id="${CSS.escape(id)}"]`,
    onClose: closePane,
  });
  const focusId = focusedId(root);

  await runView(PANES[kind], root, { state, first, signal: run.signal, retry: () => renderPane(getState(), null) });
  if (run.signal.aborted) return;
  if (first && !isDefaultPane()) focusPane();
  else restoreFocus(root, focusId);
  markSelection(getState());
}

/** Runs a view; a failure the view did not handle becomes a generic error card. Aborts are silent. */
async function runView(view, root, ctx) {
  try {
    const filters = await get("/api/filters", {}, { asOf: false, signal: ctx.signal });
    await view.render(root, { meta, filters, ...ctx });
  } catch (error) {
    if (isAbort(error) || ctx.signal.aborted) return;
    console.error(error);
    mount(root, errorState({ title: t("shell.error.view"), error, onRetry: ctx.retry }));
  }
}

/** ?state=loading | error: the page's loading or error state, to look at them (DESIGN §3). */
const DEMO_STATES = ["loading", "error"];
const demoState = (kind) =>
  kind === "loading"
    ? loadingState(t("shell.loading"))
    : errorState({ title: t("shell.error.view"), error: new ApiError("server") });

/** aria-current on the page's element for the open pane item (a brief row, an antibiogram row). */
function markSelection(state) {
  for (const el of $$("#view [data-pane-id]")) {
    if (state.pane && el.dataset.paneId === state.pane.id) el.setAttribute("aria-current", "true");
    else el.removeAttribute("aria-current");
  }
}

/** Replay steps crossfade the content in 150 ms (none under reduced motion). */
function crossfade(root) {
  if (!reducedMotion()) root.animate([{ opacity: 0.3 }, { opacity: 1 }], { duration: 150, easing: "ease-out" });
}

/** The id of the focused control inside root (or of its nearest ancestor with one), to refocus after a render. */
function focusedId(root) {
  const active = document.activeElement;
  if (!root.contains(active) || active === root) return "";
  const withId = active.id ? active : active.parentElement?.closest("[id]");
  return withId && withId !== root && root.contains(withId) ? withId.id : "";
}

/**
 * After a render replaced the focused control, focus its new equivalent: the one with the id that had focus when
 * the render began, or (when focus arrived meanwhile, e.g. returned from a sheet) the last focused control's id.
 */
function restoreFocus(root, id) {
  if (document.activeElement && document.activeElement !== document.body) return;
  const wanted = id || (lastFocused && !lastFocused.isConnected ? lastFocused.id : "");
  if (!wanted) return;
  const target = root.querySelector(`#${CSS.escape(wanted)}`);
  const control =
    target?.getAttribute("role") === "radiogroup" ? target.querySelector('[aria-checked="true"]') : target;
  control?.focus({ preventScroll: true });
}

const paramsKey = (state) => JSON.stringify(state.params);
const samePane = (a, b) => (a ?? null) === (b ?? null) || (a && b && a.kind === b.kind && a.id === b.id);
