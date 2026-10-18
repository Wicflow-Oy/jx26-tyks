// The Monday brief as data: loading it and reading its signals. Shared by the sidebar, the brief, the case file
// and My ward, so they all agree (one cached GET /api/brief per as-of week).

import { get } from "./api.js";
import { capitalize } from "./format.js";
import { t } from "./i18n.js";

export const PRIORITIES = ["P1", "P2", "P3", "info"];
const rank = (priority) => (PRIORITIES.includes(priority) ? PRIORITIES.indexOf(priority) : PRIORITIES.length);

/** GET /api/brief?as_of= (shared and cached with every other caller for that week). */
export const loadBrief = (asOf, { signal } = {}) => get("/api/brief", { as_of: asOf }, { signal });

/** Every item in the brief, in section order, each with its section key. */
export const briefItems = (brief) =>
  (brief?.sections ?? []).flatMap((section) =>
    (section.items ?? []).map((item) => ({ ...item, section: item.section ?? section.key })),
  );

export const findItem = (brief, id) => briefItems(brief).find((item) => item.id === id);

/** Open = still firing this week: not resolved and not the "quiet" summary item. */
export const isOpen = (item) => item.status !== "resolved" && item.kind !== "quiet";

/** Items counted as signals: open, without the informational "all units sent data" line. */
export const isSignal = (item) => isOpen(item) && !(item.kind === "completeness" && item.priority === "info");

/** Sorts items highest priority first (stable within a priority). */
export const byPriority = (items) => [...items].sort((a, b) => rank(a.priority) - rank(b.priority));

/** The open items touching a unit, highest priority first, from the brief's map. */
export function unitItems(brief, ward) {
  const unit = brief?.map?.units?.find((u) => u.ward === ward);
  const ids = new Set(unit?.signal_ids ?? []);
  return byPriority(briefItems(brief).filter((item) => ids.has(item.id) && isOpen(item)));
}

/** The highest priority among signal ids, or null. */
export function topPriority(brief, ids = []) {
  const items = briefItems(brief).filter((item) => ids.includes(item.id));
  return byPriority(items)[0]?.priority ?? null;
}

/** A signal's title as the API writes it, in the UI language: "ICU: possible cluster of MRSA". Every screen. */
export const signalTitle = (item) => item?.title ?? "";

/** The title without its unit, where the context already names it ("On ICU this week"): "Possible cluster of MRSA". */
export function titleOffUnit(item) {
  const title = signalTitle(item);
  const prefix = `${item?.ward}: `;
  return title.startsWith(prefix) ? capitalize(title.slice(prefix.length)) : title;
}

const KINDS = [
  "phenotype_cluster",
  "thl_rule",
  "count_stepup",
  "ward_outlier",
  "resistance_change",
  "policy_line",
  "seen_before",
  "expert_rule",
  "completeness",
  "quiet",
];

/** The plain name of a signal kind: "Unusual pattern", "Resistance change" … ("Signal" for an unknown kind). */
export const kindLabel = (kind) => t(`shell.kind.${KINDS.includes(kind) ? kind : "other"}`);

/**
 * How a unit reads this week, for the sidebar and the ward map: glyph (the highest priority among its signal_ids,
 * "gap" for a data gap, null when quiet) and word. The API decides map state: signal | changed | quiet | no_data.
 */
export function unitStatus(brief, unit) {
  const top = topPriority(brief, unit.signal_ids);
  if (unit.state === "no_data") return { glyph: "gap", word: t("shell.unit.gap") };
  if (unit.state === "changed") return { glyph: top, word: t("shell.unit.changed") };
  if (unit.state === "signal") return { glyph: top, word: t(top === "info" ? "shell.unit.info" : "shell.unit.signal") };
  return { glyph: null, word: t("shell.unit.quiet") };
}
