// Reading the brief for the page: its sections, their open items and counts, the P1 hero, and everything the page
// loads besides the brief (alerts for the hero's alert line, and the hero's case file for its epi curve).

import { loadAlerts } from "../../alerts.js";
import { get, isAbort } from "../../api.js";
import { isOpen, loadBrief } from "../../signals.js";

/**
 * Loads the brief, then the alerts and the hero's case file side by side. Only the brief is required: the
 * others fall back to [] and null, so a slow or failed extra never blanks the page.
 */
export async function loadBriefPage(asOf, { signal }) {
  const [brief, alerts] = await Promise.all([loadBrief(asOf, { signal }), loadAlerts({ signal })]);
  const hero = heroItem(brief);
  const heroFile = hero
    ? await get(`/api/signals/${encodeURIComponent(hero.id)}`, {}, { signal }).catch((error) => {
        if (isAbort(error)) throw error;
        return null;
      })
    : null;
  return { brief, alerts, hero, heroFile };
}

export const section = (brief, key) => (brief?.sections ?? []).find((s) => s.key === key) ?? null;

/** A section's items without the "quiet" summary line (that one feeds the dek and the map). */
export const sectionItems = (brief, key) => (section(brief, key)?.items ?? []).filter((item) => item.kind !== "quiet");

/** Open items in a section; data quality leaves out the informational "all units sent data" line. */
export function openCount(brief, key) {
  const counted = (item) => isOpen(item) && !(key === "data_quality" && item.priority === "info");
  return sectionItems(brief, key).filter(counted).length;
}

/** Only the top open P1 gets the hero: the first one in Unusual patterns (the API ranks the section). */
export const heroItem = (brief) =>
  sectionItems(brief, "unusual_patterns").find((item) => item.priority === "P1" && isOpen(item)) ?? null;

/** The quiet summary: { quiet, units } from the "quiet" item's slots, or null. */
export function quietUnits(brief) {
  const [quiet, units] = section(brief, "quiet")?.items?.[0]?.slots?.quiet ?? [];
  return Number.isInteger(quiet) && Number.isInteger(units) ? { quiet, units } : null;
}

/** Completeness items: the hospital-wide line (no ward) and per-unit data gaps (with a ward). */
export const completeness = (brief) =>
  sectionItems(brief, "data_quality").filter((item) => item.kind === "completeness");
