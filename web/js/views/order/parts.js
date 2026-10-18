// Small pieces of our layer shared by the chips, the card and the signing sheet. They read the order context from
// POST /api/order-context (CONTRACTS §7b) and render its text as it is: the backend owns every rule and word.
// The context's local-guide alternatives and "change to" codes are never read: the layer does not name another drug.

import { icon } from "../../components/icons.js";
import { h } from "../../dom.js";
import { dateFull } from "../../format.js";
import { t } from "../../i18n.js";

/** The line with this key ("happening" or "your_drug"), or null. */
export const line = (ctx, key) => (Array.isArray(ctx?.lines) ? ctx.lines.find((l) => l?.key === key) : null) ?? null;

/** The ordered drug's name as the backend writes it ("Ceftriaxone"), or its code. */
export const drugName = (ctx) => ctx?.drug_name ?? ctx?.drug ?? "";

/** The card's title: the clinical reason when the backend gives one, else its short summary. */
export const headline = (ctx) => ctx.headline ?? ctx.summary ?? ctx.chip ?? "";

/** The neutral sentence for an info or a warning; the fallback is the same sentence until `ask` arrives. */
export const ask = (ctx) => (ctx.ask === undefined ? t("order.layer.ask") : ctx.ask);

/** Who flagged it (from the "happening" source) and when; for the patient's own result, the date is a sample date. */
export function flaggedBy(ctx) {
  const source = line(ctx, "happening")?.source;
  return { who: source?.flagged_by ?? "", on: source?.flagged_on ?? "", ownResult: source?.kind === "own_history" };
}

/** "[mark] Strainwatch · Infection control · flagged 9 Jun 2025", or just the product name for a chip. */
export function sourceLabel(appName, ctx) {
  const { who, on, ownResult } = ctx ? flaggedBy(ctx) : { who: "", on: "" };
  const when = t(ownResult ? "order.layer.sampled" : "order.layer.flagged", { date: dateFull(on) });
  return h(
    "span",
    { class: "sw-src" },
    h("span", { class: "sw-mark" }, icon("mark", 10)),
    who ? t("order.layer.source", { app: appName, who }) : appName,
    on && h("span", { class: "sw-when" }, when),
  );
}

/** The link to My ward for this unit, specimen and organism, so the doctor can look at every drug. */
export function detailsLink(ctx, { onFollow } = {}) {
  const details = ctx.actions?.details;
  const link = details?.link ?? ctx.actions?.details_link;
  if (!link) return null;
  // the API gives "/#/ward?…"; keeping only the hash part stays inside this app wherever it is served
  const href = link.slice(Math.max(0, link.indexOf("#")));
  return h(
    "a",
    { class: "sw-link", href, onclick: onFollow },
    details?.label ?? t("order.layer.details"),
    icon("chevron", 6),
  );
}

/** "Observed unit-level information, not a prediction for this patient. The doctor decides." plus the lag note. */
export const smallPrint = (ctx) =>
  h("p", { class: "sw-fine" }, ctx.small_print && h("b", null, ctx.small_print), " ", ctx.note ?? "");

/** What is happening: the alert's or the result's own text. heading: "h4" in the card, "h3" in the sheet. */
export function happeningSection(ctx, heading = "h4") {
  const happening = line(ctx, "happening");
  if (!happening?.text) return null;
  return h(
    "section",
    { class: "sw-sec" },
    h(heading, { class: "eyebrow" }, t("order.layer.happening")),
    h("p", { class: "sw-text" }, happening.text),
  );
}

/** Species-level notes on this patient's isolates (intrinsic resistance, no breakpoint): passive, never a flag. */
export function notesSection(ctx, heading = "h4") {
  const notes = (ctx.notes ?? []).filter(Boolean);
  if (!notes.length) return null;
  return h(
    "section",
    { class: "sw-sec" },
    h(heading, { class: "eyebrow" }, t("order.layer.notes")),
    notes.map((note) => h("p", { class: "sw-text" }, note)),
  );
}
