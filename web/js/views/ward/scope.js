// The My ward scope, shared by the page and the trend pane: the filters in the URL and the API queries they make.
// URL params: ward, specimen, organism, sex, age_band, setting (as the API names them) and window (the recent
// window's key, absent for the first one).

import { t } from "../../i18n.js";

/** The demo doctor works on the intensive care unit, where the tour's story happens. */
const DEMO_WARD = "ICU";

/** The API's specimen group when the URL names none (CONTRACTS §4.2). */
export const DEFAULT_SPECIMEN = "blood_wound";

/** The comparison window of every row: the last 52 weeks (CONTRACTS §2). */
export const YEAR = "12m";

export const FILTER_KEYS = ["ward", "specimen", "organism", "sex", "age_band", "setting"];

/** The ward My ward opens on when the URL names none: the demo ward if the API lists it, else its first ward. */
export function defaultWard(filters) {
  const codes = (filters?.wards ?? []).map((w) => w.code);
  return codes.includes(DEMO_WARD) ? DEMO_WARD : (codes[0] ?? "");
}

/** The recent windows the doctor can compare with the year, from /api/filters ("4w", "4m"). */
export const recentWindows = (filters) => (filters?.windows ?? []).filter((w) => w.key !== YEAR);

export const recentKey = (state, filters) => state.params.window ?? recentWindows(filters)[0]?.key ?? "4w";

const filterQuery = (state, filters) => ({
  ...Object.fromEntries(FILTER_KEYS.map((key) => [key, state.params[key]])),
  ward: state.params.ward ?? defaultWard(filters),
});

/** GET /api/my-ward params for the current scope. */
export const wardQuery = (state, filters) => ({
  ...filterQuery(state, filters),
  windows: `${recentKey(state, filters)},${YEAR}`,
});

/** GET /api/trend params for one drug in the current scope. */
export const trendQuery = (state, filters, drug) => ({
  ...filterQuery(state, filters),
  drug,
  window: recentKey(state, filters),
});

/** Whole weeks in an API window ({ days: 28 } → 4). */
export const weeksOf = (window) => Math.round((window?.days ?? 0) / 7);

/** A label from a /api/filters list, falling back to the raw value. */
export const labelIn = (list, value, key = "key") => list?.find((item) => item[key] === value)?.label ?? value;

/** Labels of the narrowing filters in params or an API filter echo: ["E. coli", "Women", "age 18-64"]. */
export function scopeExtras(scope, filters) {
  return [
    scope.organism && labelIn(filters.organisms, scope.organism, "organism"),
    scope.sex && labelIn(filters.sexes, scope.sex, "code"),
    scope.age_band && t("ward.age", { band: labelIn(filters.age_bands, scope.age_band) }),
    scope.setting && labelIn(filters.settings, scope.setting),
  ].filter(Boolean);
}
