// Glyphs and badges. Colour never carries meaning alone: every tile has a shape and a word next to it.

import { h } from "../dom.js";
import { t } from "../i18n.js";
import { icon } from "./icons.js";

const TILE_ICON = { P1: "P1", P2: "P2", P3: "P3", info: "info", ok: "ok", gap: "gap", line: "line" };
const ICON_SIZE = { md: 16, sm: 12, xs: 10 };

/** Priority word: "P1", "P2", "P3", "Info", "OK", "Data gap". kind: P1 | P2 | P3 | info | ok | gap */
export const priorityLabel = (kind) => t(`shell.priority.${kind}`);

/** The glyph tile. size: md (28) | sm (20) | xs (16). The data-gap tile is hatched with no icon at xs. */
export function tile(kind, size = "md") {
  const glyph = kind === "gap" && size === "xs" ? null : icon(TILE_ICON[kind] ?? "info", ICON_SIZE[size]);
  return h("span", { class: ["tile", size !== "md" && size, `g-${kind}`], "aria-hidden": "true" }, glyph);
}

/** The row's priority column: tile above its label. */
export const priorityColumn = (kind) =>
  h("span", { class: ["prio", kind] }, tile(kind), h("span", { class: "plabel" }, priorityLabel(kind)));

/** Tile and label in one capsule, for case and pane heads. */
export const priorityBadge = (kind) => h("span", { class: ["pbadge", kind] }, tile(kind, "xs"), priorityLabel(kind));

/** State word: New (ink dot), Ongoing, ✓ Resolved. */
export function stateWord(status) {
  if (status === "new")
    return h(
      "span",
      { class: "state new" },
      h("span", { class: "newdot", "aria-hidden": "true" }),
      t("shell.status.new"),
    );
  if (status === "resolved") return h("span", { class: "state resolved" }, icon("ok", 12), t("shell.status.resolved"));
  return h("span", { class: "state" }, t("shell.status.ongoing"));
}

/** Neutral outlined chip for API advice ("Typing advised", "Lab check"); nothing when there is no advice. */
export const adviceChip = (advice) => (advice ? h("span", { class: "chip chip-advice" }, advice) : null);

/** One S/R letter badge; drugName is read out ("Cefoxitin resistant"). */
export function srBadge(result, drugName) {
  const word = t(`shell.sr.${result}`);
  return h("span", { class: ["srb", result], role: "img", "aria-label": `${drugName} ${word}` }, result);
}

/**
 * An antibiogram as code + letter pairs: "FOX:R VAN:S CLI:R" → FOX [R] VAN [S] CLI [R].
 * drugLabel(code) gives the spoken name (from /api/filters drugs); unknown codes are read as the code.
 */
export function srSet(profile, drugLabel = (code) => code) {
  const pairs = String(profile ?? "")
    .split(" ")
    .map((pair) => pair.split(":"))
    .filter(([code, result]) => code && (result === "S" || result === "R"));
  return h(
    "span",
    { class: "sr-set" },
    pairs.map(([code, result]) =>
      h("span", { class: "sr-pair", title: drugLabel(code) }, code, srBadge(result, drugLabel(code))),
    ),
  );
}

/** The "Prototype · synthetic data" capsule shown on every screen. */
export const prototypeCapsule = () =>
  h("span", { class: "capsule" }, h("span", { class: "dot", "aria-hidden": "true" }), t("shell.prototype"));
