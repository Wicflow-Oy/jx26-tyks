// The one app state, mirrored in the URL hash so every screen can be linked:
//   #<route>[/<pane kind>[/<pane id>]]?<view params>&as_of=YYYY-MM-DD&lang=fi
// e.g. #brief/case/phe-7972cb3f12?as_of=2026-03-29 or #ward/trend/MEM?ward=ICU.
// No as_of means the latest week; no lang means English.

import { addDays, daysBetween, isISODate } from "./dates.js";

/** Each route belongs to one role and lists the pane kinds it can open beside it. */
export const ROUTES = {
  brief: { role: "ic", panes: ["case"] },
  ward: { role: "doc", panes: ["trend"] },
  order: { role: "doc", panes: [] },
};
export const HOME = { ic: "brief", doc: "ward" };

let state = Object.freeze({ route: "brief", pane: null, asOf: "", lang: "en", params: {} });
let range = { first: "", last: "" };
const listeners = new Set();
const lastParams = {}; // per route, so a doctor's filters survive a trip to the brief and back
let paneReturnHash = ""; // where Back lands after openPane() pushed a history entry
let defaultPane = null; // the pane selectDefaultPane() opened, until someone opens another

export const getState = () => state;
export const roleOf = (route) => ROUTES[route]?.role ?? "ic";
export const asOfRange = () => range;

/** The params a route had when it was last shown (My ward's filters while the order form is open). */
export const paramsFor = (route) => (state.route === route ? state.params : (lastParams[route] ?? {}));

/** Reads the hash once meta has given the replay range. lang: the stored preference, used when the URL has none. */
export function initState(replay, lang) {
  range = { first: replay.first, last: replay.last };
  const fromUrl = parseHash(location.hash);
  state = normalize({ ...state, ...fromUrl, lang: fromUrl.lang ?? lang });
  writeHash("replace");
  addEventListener("popstate", syncFromHash);
  addEventListener("hashchange", syncFromHash);
}

/** Before /api/meta has loaded: the language from the URL (else `lang`), so the boot screens and request use it. */
export function presetLang(lang) {
  const wanted = parseHash(location.hash).lang ?? lang;
  state = Object.freeze({ ...state, lang: wanted === "fi" ? "fi" : "en" });
}

/** fn(state, prev) runs after every change. Returns an unsubscribe function. */
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setState(patch, { push = false } = {}) {
  commit(normalize({ ...state, ...patch }), push ? "push" : "replace");
}

/** The global as-of Sunday; clamped and snapped to the replay weeks. */
export const setAsOf = (asOf) => setState({ asOf });

/** Merges view params (filters); null or "" removes one. */
export const setParams = (patch) => setState({ params: { ...state.params, ...patch } });

/** Goes to another route (and so maybe another role), with a history entry. */
export function navigate(route, { params = lastParams[route] ?? {}, pane = null } = {}) {
  paneReturnHash = "";
  setState({ route, params, pane }, { push: true });
}

/**
 * Opens the pane beside the current page: openPane("case", signalId) or openPane("trend", "MEM"). Asking again for
 * the item that is already open fires "pane-reopen", so the pane can take focus (components/pane.js).
 */
export function openPane(kind, id = "") {
  defaultPane = null;
  if (state.pane?.kind === kind && state.pane.id === id) {
    document.dispatchEvent(new Event("pane-reopen"));
    return;
  }
  if (state.pane) {
    setState({ pane: { kind, id } });
    return;
  }
  paneReturnHash = toHash(state);
  setState({ pane: { kind, id } }, { push: true });
}

/**
 * The default selection beside a page (the highest-priority open item), when no pane is open or the open one is
 * still the default. It replaces the history entry, so Back still leaves the page.
 */
export function selectDefaultPane(kind, id) {
  if (!id || (state.pane && !isDefaultPane())) return;
  defaultPane = { kind, id };
  setState({ pane: defaultPane });
}

/** True while the open pane is the page's default selection: nobody asked for it, so it does not take focus. */
export const isDefaultPane = () =>
  Boolean(defaultPane && state.pane?.kind === defaultPane.kind && state.pane.id === defaultPane.id);

/** Closes the pane. Uses history.back() only when Back lands exactly where closing would. */
export function closePane() {
  if (!state.pane) return;
  const target = toHash({ ...state, pane: null });
  if (paneReturnHash === target) {
    paneReturnHash = "";
    history.back();
  } else {
    setState({ pane: null });
  }
}

function syncFromHash() {
  const parsed = parseHash(location.hash);
  if (!parsed.pane) paneReturnHash = "";
  // lang is a preference: a hash without lang (an older history entry) keeps the current one
  commit(normalize({ ...state, ...parsed, lang: parsed.lang ?? state.lang }), "none");
  writeHash("replace"); // a hand-typed or clamped value is shown as what is really displayed
}

function commit(next, historyMode) {
  if (toHash(next) === toHash(state)) return;
  const prev = state;
  state = next;
  lastParams[next.route] = next.params;
  if (historyMode !== "none") writeHash(historyMode);
  for (const fn of listeners) fn(state, prev);
}

function normalize(st) {
  const route = ROUTES[st.route] ? st.route : "brief";
  const pane =
    st.pane && ROUTES[route].panes.includes(st.pane.kind) ? { kind: st.pane.kind, id: st.pane.id ?? "" } : null;
  const params = Object.fromEntries(
    Object.entries(st.params ?? {})
      .filter(([, v]) => v != null && v !== "")
      .map(([k, v]) => [k, String(v)]),
  );
  return Object.freeze({ route, pane, asOf: clampAsOf(st.asOf), lang: st.lang === "fi" ? "fi" : "en", params });
}

/** Strict as-of: any date becomes the nearest replay Sunday inside the range from /api/meta. */
function clampAsOf(value) {
  if (!isISODate(value) || value >= range.last) return range.last;
  if (value <= range.first) return range.first;
  return addDays(range.first, 7 * Math.round(daysBetween(range.first, value) / 7));
}

function parseHash(hash) {
  const [path = "", query = ""] = hash.replace(/^#\/?/, "").split("?");
  const [route = "", kind = "", id = ""] = path.split("/").map(decodeURIComponent);
  const search = new URLSearchParams(query);
  const params = Object.fromEntries([...search].filter(([key]) => key !== "as_of" && key !== "lang"));
  const shared = { asOf: search.get("as_of"), lang: search.get("lang"), params };
  // CDS Hooks cards link to #/signal/<id> (CONTRACTS §7): that is the brief's case file
  if (route === "signal") return { ...shared, route: "brief", pane: { kind: "case", id: kind } };
  return { ...shared, route, pane: kind ? { kind, id } : null };
}

function toHash(st) {
  const path = [st.route, st.pane?.kind, st.pane?.id].filter(Boolean).map(encodeURIComponent).join("/");
  const query = new URLSearchParams(st.params);
  if (st.asOf !== range.last) query.set("as_of", st.asOf);
  if (st.lang !== "en") query.set("lang", st.lang);
  const search = query.toString();
  return `#${path}${search ? `?${search}` : ""}`;
}

function writeHash(mode) {
  const hash = toHash(state);
  if (location.hash === hash) return;
  if (mode === "push") history.pushState(null, "", hash);
  else history.replaceState(null, "", hash);
}
