// Two small helpers on top of t() for running text: sentences whose placeholders are nodes (a bold or marked
// number), and a key's singular or plural form.

import { t } from "./i18n.js";

/**
 * t() with nodes for placeholders: rich("case.readout", { n: h("b", null, "13") }) → ["", <b>13</b>, " patients"].
 * Strings stay text and nodes stay nodes; a placeholder without a value is kept as written, the way t() keeps it.
 */
export function rich(key, vars = {}) {
  return String(t(key))
    .split(/\{(\w+)\}/)
    .map((part, i) => (i % 2 ? (vars[part] ?? `{${part}}`) : part));
}

/** The ".one" or ".other" form of a key: plural("brief.dek.lab", 2, { n: "two" }). */
export const plural = (key, n, vars) => t(`${key}.${n === 1 ? "one" : "other"}`, vars);
