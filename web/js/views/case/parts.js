// Small building blocks of the case file: the plain method text of a kind, numbered sections, footnotes and a
// resistant-of-tested meter.

import { h } from "../../dom.js";
import { pct, xOfN } from "../../format.js";
import { t } from "../../i18n.js";

const METHOD_KINDS = [
  "phenotype_cluster",
  "thl_rule",
  "count_stepup",
  "resistance_change",
  "ward_outlier",
  "seen_before",
  "policy_line",
  "expert_rule",
  "completeness",
  "quiet",
];

/** The method of a signal kind in plain words ("" for a kind the UI does not know yet). */
export const methodText = (kind) => (METHOD_KINDS.includes(kind) ? t(`case.method.${kind}`) : "");

/** A numbered case-file section: "01 What we see" with an optional quiet note on the right. */
export function caseSection(number, title, right, ...body) {
  const id = `csec-${number}`;
  return h(
    "section",
    { class: "csec", "aria-labelledby": id },
    h(
      "div",
      { class: "csec-h" },
      h("span", { class: "no", "aria-hidden": "true" }, String(number).padStart(2, "0")),
      h("h3", { id }, title),
      right && h("span", { class: "r" }, right),
    ),
    body,
  );
}

/** Footnotes under a visual: [["Counts", "13 patients …"], ["Method", "…"]]; empty entries are skipped. */
export const notes = (entries) =>
  h(
    "div",
    { class: "notes" },
    entries.filter((entry) => entry?.[1]).map(([label, text]) => h("p", null, h("b", null, `${label}.`), " ", text)),
  );

/** Below this many results a share is not shown as a percent, only as "x of n" (DESIGN §16, not enough data). */
export const MIN_N_FOR_SHARE = 10;

/**
 * "Last 4 weeks · 13 of 20 resistant · 65%" with a bar for the share; label is the window, already in words.
 * Fewer than MIN_N_FOR_SHARE results show the counts only, and no bar.
 */
export function resistantMeter(label, resistant, tested) {
  const enough = tested >= MIN_N_FOR_SHARE;
  const share = enough ? resistant / tested : 0;
  return h(
    "div",
    { class: "rmeter" },
    h(
      "div",
      { class: "h" },
      h("span", null, label),
      h(
        "span",
        { class: "num" },
        h("b", null, xOfN(resistant, tested)),
        ` ${t("case.resistant")}`,
        enough && ` · ${pct(share)}`,
      ),
    ),
    enough &&
      h("div", { class: "bar", "aria-hidden": "true" }, h("i", { style: { width: `${Math.max(1.5, share * 100)}%` } })),
  );
}
