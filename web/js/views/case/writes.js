// The writes the case file makes: approve an alert, draft and approve a heads-up. api.post() clears the GET cache
// and tells its onWrite() listeners, so the brief, the sidebar and this case file read fresh data afterwards.

import { post } from "../../api.js";

/**
 * POST /api/alerts for a signal, strictly as of the brief's week. wards and drugs come from an earlier alert when
 * approving again; empty lets the backend use the signal's units and its own defaults.
 */
export const approveAlert = ({ item, asOf, wards = [], drugs = [] }) =>
  post("/api/alerts", { signal_id: item.id, as_of: asOf, wards, drugs, message: alertMessage(item.text) });

/** POST /api/heads-up: the backend narrates the draft for the emergency department from the signal's numbers. */
export const draftHeadsUp = ({ item, asOf, lang }) =>
  post("/api/heads-up", { signal_id: item.id, as_of: asOf, language: lang });

/** POST /api/heads-up/{id}/approve. Nothing is ever sent; the response says "not sent (demo)". */
export const approveHeadsUp = (id) => post(`/api/heads-up/${encodeURIComponent(id)}/approve`, {});

// The alert message is the signal's own text (the API caps it at 500 characters).
const MESSAGE_MAX = 500;
const alertMessage = (text = "") => (text.length <= MESSAGE_MAX ? text : `${text.slice(0, MESSAGE_MAX - 1)}…`);
