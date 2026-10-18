// UI strings, deliberately simple: one hook, t(key). Each area module in js/strings/ exports { en, fi } and its
// keys are read as "area.key", e.g. t("shell.role.ic"). A key missing in Finnish falls back to English. The language
// itself is state.lang (in the URL hash), remembered in localStorage; the API gets it as ?lang=, and dates, numbers
// (format.js) and <html lang> follow it.

import { getState, subscribe } from "./state.js";
import * as brief from "./strings/brief.js";
import * as caseFile from "./strings/case.js";
import * as order from "./strings/order.js";
import * as replay from "./strings/replay.js";
import * as shell from "./strings/shell.js";
import * as tour from "./strings/tour.js";
import * as ward from "./strings/ward.js";

const AREAS = { shell, brief, case: caseFile, ward, replay, tour, order };
const STORAGE_KEY = "lang";

const tables = { en: {}, fi: {} };
for (const [area, table] of Object.entries(AREAS)) {
  for (const lang of Object.keys(tables)) {
    for (const [key, value] of Object.entries(table[lang] ?? {})) tables[lang][`${area}.${key}`] = value;
  }
}

/** t("shell.asOf") → the string; t("replay.read", { p1: 2, n: 7 }) fills {p1} and {n}. Unknown keys return the key. */
export function t(key, vars) {
  const value = tables[getLang()]?.[key] ?? tables.en[key];
  if (value == null) return key;
  return typeof value === "string" && vars ? value.replace(/\{(\w+)\}/g, (m, name) => String(vars[name] ?? m)) : value;
}

/** The chosen language (state.lang): "en" or "fi". */
export const getLang = () => getState().lang;

/** Keeps <html lang> and the stored preference in step with state.lang. Call once, after initState(). */
export function initLang() {
  applyLang(getLang());
  subscribe((state, prev) => state.lang !== prev.lang && applyLang(state.lang));
}

function applyLang(lang) {
  document.documentElement.lang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // storage blocked (private mode): the choice still holds for this page
  }
}

/** The remembered language, or null (storage may be blocked or empty). */
export function storedLang() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}
