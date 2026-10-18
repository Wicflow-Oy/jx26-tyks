// The order view's API calls (CONTRACTS §7b): the order context at select and at sign, the drug picker, the
// patient's history, and the doctor's answers (POST /api/order-feedback). Optional fields are read defensively,
// because the backend is still adding some of them.

import { get, isAbort, post } from "../../api.js";
import { t } from "../../i18n.js";

/**
 * POST /api/order-context for the draft: { scenario, asOf, indication, drug, stage: "select" | "sign", signal }.
 * The backend decides the state, the wording and the numbers; the view only renders them.
 */
export function orderContext({ scenario, asOf, indication, drug, stage, signal }) {
  const body = { as_of: asOf, patient_id: scenario.patient_id, unit: scenario.unit, indication, drug, stage };
  return post("/api/order-context", body, { signal, keepCache: true });
}

/** The drug picker for an indication: [{ drug, name, atc }], the order drugs with a result on its specimen. */
export async function orderDrugs(indication, { signal } = {}) {
  const list = await get("/api/order-drugs", { indication }, { asOf: false, signal });
  return Array.isArray(list) ? list.filter((d) => d?.drug && d?.name) : [];
}

/** [{ key, label }]: GET /api/meta indications, or the labelled fallback until the backend lists them. */
export function indications(meta) {
  const listed = Array.isArray(meta?.indications) ? meta.indications.filter((i) => i?.key && i?.label) : [];
  return listed.length ? listed : t("order.form.indicationFallback");
}

/** GET /api/patients/{id}/history for the banner's risk info; null when it does not load (the banner says so). */
export async function patientHistory(patientId, { signal }) {
  try {
    return await get(`/api/patients/${encodeURIComponent(patientId)}/history`, {}, { signal });
  } catch (error) {
    if (isAbort(error)) throw error;
    return null;
  }
}

/**
 * Logs the doctor's answer to a card: outcome shown | keep | edit | change | details. "shown" goes once per
 * card per draft. A failed log never gets in the doctor's way, so errors are dropped.
 */
export function logFeedback(draft, ctx, outcome, extra = {}) {
  if (!ctx?.card_key) return;
  if (outcome === "shown") {
    if (draft.shown.has(ctx.card_key)) return;
    draft.shown.add(ctx.card_key);
  }
  const body = {
    as_of: ctx.as_of,
    card_key: ctx.card_key,
    source_id: ctx.source?.id ?? null,
    state: ctx.state,
    outcome,
    ...extra,
  };
  post("/api/order-feedback", body, { keepCache: true }).catch(() => {});
}
