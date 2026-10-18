// Infection control's approved alerts, read the strict as-of way: an alert counts once
// approved_on <= as_of + 1, and it is active while as_of + 1 <= expires_on and it is not revoked by then.
// Shared by the brief's hero, the case file, the sidebar and the My ward banner, so they all agree.

import { get } from "./api.js";
import { mondayOf } from "./dates.js";

// Demo seeds carry no signal id; the API links them to a cluster on their unit and organism (api._linked).
const SEEDED_KINDS = ["phenotype_cluster", "thl_rule"];

/**
 * Every alert approved by the as-of Monday, expired and revoked ones included (GET /api/alerts?include_expired=1),
 * each with `expired` and `revoked_on` as known that Monday. A failure returns [] so the brief and the case file
 * still render; their actions say what is known.
 */
export const loadAlerts = ({ signal } = {}) =>
  get("/api/alerts", { include_expired: 1 }, { signal }).then(
    (rows) => (Array.isArray(rows) ? rows : []),
    (error) => {
      if (signal?.aborted) throw error;
      return [];
    },
  );

/**
 * { state: "active" | "expired" | "none", alert } for one brief item. known: any rows from loadAlerts() or the
 * case file's `alerts`; the item's own `alert` (the API's active link) is always included.
 */
export function alertState(item, asOf, known = []) {
  const monday = mondayOf(asOf);
  const linked = [item?.alert, ...known]
    .filter(Boolean)
    .filter((alert) => isLinked(alert, item) && alert.approved_on <= monday && !alert.revoked_on);
  const latest = linked.sort((a, b) => (a.approved_on < b.approved_on ? 1 : -1))[0];
  if (!latest) return { state: "none", alert: null };
  return { state: latest.expired ? "expired" : "active", alert: latest };
}

function isLinked(alert, item) {
  if (alert === item?.alert) return true;
  if (alert.signal_id != null) return alert.signal_id === item?.id;
  return (
    SEEDED_KINDS.includes(item?.kind) && (alert.wards ?? []).includes(item.ward) && alert.organism === item.organism
  );
}
