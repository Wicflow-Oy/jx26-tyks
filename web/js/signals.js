// The Monday brief as data: loading it and reading its signals. Shared by the sidebar, the brief, the case file
// and My ward, so they all agree (one cached GET /api/brief per as-of week).

import { get } from "./api.js";
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

/**
 * A signal's title as parts, joined with " · " on screen: ["ICU", "S. aureus", "Cefoxitin"]. The API's plain
 * title (slots.title) wins; until every signal has one, the title is built from the kind and the signal's slots
 * (ward, marker, organism, drug, population), never from its text. The one title rule for every screen.
 */
export function titleParts(item) {
  const slots = item?.slots ?? {};
  if (slots.title) return [slots.title];
  const organism = slots.organism_label ?? item?.organism;
  const drug = slots.drug_label ?? item?.drug;
  const kind = kindLabel(item?.kind);
  const parts = {
    phenotype_cluster: () => [item.ward, t("shell.title.cluster", { organism })],
    seen_before: () => [item.ward, t("shell.title.pattern", { organism })],
    thl_rule: () => (slots.marker_label ? [item.ward, slots.marker_label, organism] : [item.ward, organism, kind]),
    policy_line: () => [drug, slots.population_label],
    expert_rule: () => [kind, slots.units_text],
    completeness: () => (item.ward ? [item.ward, t("shell.priority.gap")] : [kind]),
    ward_outlier: () => [item.ward, kind],
    resistance_change: () => [item.ward, organism, drug],
  }[item?.kind];
  return (parts ? parts() : [item?.ward, organism, drug, kind]).filter(Boolean);
}

/** The title as one line: "ICU · S. aureus · Cefoxitin". */
export const signalTitle = (item) => titleParts(item).join(" · ");

/** The title without the unit, where the context already names it ("On ICU this week"). */
export const titleOffUnit = (item) => {
  const parts = titleParts(item);
  return (parts[0] === item?.ward && parts.length > 1 ? parts.slice(1) : parts).join(" · ");
};

/** The P1 hero's headline: "ICU: possible cluster of MRSA" for a cluster, else the title. */
export function heroTitle(item) {
  const slots = item?.slots ?? {};
  if (slots.title || item?.kind !== "phenotype_cluster" || !item.ward) return signalTitle(item);
  return t("shell.title.clusterHero", { ward: item.ward, organism: slots.organism_label ?? item.organism });
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
