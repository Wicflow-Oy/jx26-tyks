// This patient's previous results (the order context's previous_results, last 52 weeks): shown first whenever
// there are any. A full table for the card and the signing sheet; one line under a chip.

import { srBadge } from "../../components/badges.js";
import { h } from "../../dom.js";
import { dateFull } from "../../format.js";
import { t } from "../../i18n.js";
import { drugName, line } from "./parts.js";

const MINI = 3;

/** The table, with the result that raised a flag marked (own history: its sample date and an R). */
export function previousTable(ctx, filters, heading = "h4") {
  const rows = ctx.previous_results ?? [];
  if (!rows.length) return null;
  const source = line(ctx, "happening")?.source;
  const flagged = (row) => source?.kind === "own_history" && row.date === source.flagged_on && row.drug_result === "R";
  return h(
    "section",
    { class: "sw-sec" },
    h(
      heading,
      { class: "eyebrow" },
      t("order.prev.title"),
      h("span", { class: "sw-count" }, t("order.prev.count", { n: rows.length })),
    ),
    h(
      "table",
      { class: "prev" },
      h(
        "thead",
        null,
        h(
          "tr",
          null,
          h("th", { scope: "col" }, t("order.prev.date")),
          h("th", { scope: "col", class: "hide-s" }, t("order.prev.unit")),
          h("th", { scope: "col", class: "hide-s" }, t("order.prev.specimen")),
          h("th", { scope: "col" }, t("order.prev.organism")),
          h("th", { scope: "col" }, drugName(ctx)),
        ),
      ),
      h(
        "tbody",
        null,
        rows.map((row) =>
          h(
            "tr",
            { class: flagged(row) && "hit" },
            h("td", { class: "num nobr" }, dateFull(row.date)),
            h("td", { class: "hide-s" }, row.unit),
            h("td", { class: "hide-s" }, specimenWord(row.specimen, filters)),
            h("td", null, organismName(row.organism, filters), flags(row)),
            h("td", null, result(row, ctx)),
          ),
        ),
      ),
    ),
  );
}

/** "Previous results (5)  16 Jan 2026 · E. coli · urine · trimethoprim [R]  …  +2 more": this drug's results first. */
export function previousLine(ctx, filters) {
  const rows = ctx.previous_results ?? [];
  if (!rows.length) return null;
  const shown = [...rows.filter((r) => r.drug_result), ...rows.filter((r) => !r.drug_result)].slice(0, MINI);
  return h(
    "p",
    { class: "prev-line" },
    h("span", { class: "prev-lbl" }, `${t("order.prev.title")} (${rows.length})`),
    shown.map((row) =>
      h(
        "span",
        { class: "prev-it" },
        `${dateFull(row.date)} · ${organismName(row.organism, filters)}`,
        flags(row),
        ` · ${specimenWord(row.specimen, filters)} · ${drugName(ctx).toLocaleLowerCase()} `,
        result(row, ctx),
      ),
    ),
    rows.length > shown.length && h("span", null, t("order.prev.more", { n: rows.length - shown.length })),
  );
}

/**
 * The S/R letter, or a dash with the reason there is none ("not tested"), then the API's reason_text when the result
 * is not simply as reported: a species rule ("intrinsic resistance (EUCAST); the laboratory reported S" when it
 * overrules the laboratory's reported_result), an inference, or flucloxacillin read from the cefoxitin screen.
 */
function result(row, ctx) {
  const name = drugName(ctx);
  const badge =
    row.drug_result === "S" || row.drug_result === "R"
      ? srBadge(row.drug_result, name)
      : h("span", { class: "srb none", role: "img", "aria-label": t("order.prev.none") }, "–");
  const plain = row.reason === "reported" && ctx.drug !== "FOX";
  const why = plain ? "" : row.reason_text;
  return h("span", { class: "prev-res" }, badge, why && h("span", { class: "prev-why" }, why));
}

const flags = (row) => (row.flags ?? []).map((flag) => h("span", { class: "flag" }, flag));

export function organismName(organism, filters) {
  return filters?.organisms?.find((o) => o.organism === organism)?.label ?? organism ?? "";
}

export function specimenWord(specimen, filters) {
  const label = filters?.specimen_groups?.find((g) => g.key === specimen)?.label;
  return label ? label.toLocaleLowerCase() : (specimen ?? "");
}
