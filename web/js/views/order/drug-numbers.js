// This drug in this population: R of n over the last 4 and the last 52 weeks with their intervals, each on one
// 0–100% bar. Counts come from the order context's "your_drug" line; nothing is computed here but a label.

import { intervalBar } from "../../components/interval-bar.js";
import { h } from "../../dom.js";
import { int, interval, pct } from "../../format.js";
import { t } from "../../i18n.js";
import { areaName } from "../../names.js";
import { drugName, line } from "./parts.js";
import { organismName, specimenWord } from "./previous-results.js";

/** The numbers block, or the line's own text when the backend shows no number for this drug. */
export function drugNumbers(ctx, filters, heading = "h4") {
  const yours = line(ctx, "your_drug");
  if (!yours) return null;
  const nums = yours.numbers;
  const population = ctx.evidence?.population;
  const head = h(
    heading,
    { class: "nums-head" },
    h("span", { class: "nums-drug" }, t("order.nums.title", { drug: drugName(ctx) })),
    h("span", { class: "nums-pop" }, populationLabel(population, filters)),
  );
  if (!nums) return h("section", { class: "sw-sec" }, head, h("p", { class: "sw-text" }, yours.text));

  // with a reference organism the count is R of that organism; over a mix of organisms it is "not covered"
  const word = population?.organism ? "order.nums.resistant" : "order.nums.notCovered";
  return h(
    "section",
    { class: "sw-sec nums-sec" },
    head,
    h(
      "div",
      { class: "nums" },
      h(
        "span",
        { class: "nums-axis", "aria-hidden": "true" },
        [0, 0.5, 1].map((share) => h("span", null, pct(share))),
      ),
      windowRow(windowLabel(filters, nums.window ?? "4w"), nums.r, nums.n, nums.pct, nums.ci, nums.state, word),
      windowRow(windowLabel(filters, "12m"), nums.r12, nums.n12, nums.pct12, nums.ci12, nums.state12, word),
    ),
  );
}

function windowRow(label, r, n, share, ci, state, word) {
  if (state === "not_enough_data") {
    return h(
      "div",
      { class: "nums-row" },
      h("span", { class: "nums-win" }, label),
      h("span", { class: "nums-count" }, h("span", { class: "ned" }, t("order.nums.notEnough"))),
      h("span", { class: "nums-share" }, t("order.nums.n", { n: int(n) })),
      h("span", { class: "nums-bar" }),
    );
  }
  return h(
    "div",
    { class: "nums-row" },
    h("span", { class: "nums-win" }, label),
    h("b", { class: "nums-count num" }, t(word, { x: int(r), n: int(n) })),
    h(
      "span",
      { class: "nums-share num" },
      `${pct(share, 1)} ${interval(ci)}`,
      state === "low_n" && h("span", { class: "nums-few" }, t("order.nums.few")),
    ),
    h("span", { class: "nums-bar" }, intervalBar({ value: share, interval: ci, max: 1 })),
  );
}

const windowLabel = (filters, key) => filters?.windows?.find((w) => w.key === key)?.label ?? key;

/** "URO · urine · E. coli · women" or "ED + PHC-N + PHC-S · patients from North · urine · E. coli · women". */
function populationLabel(population, filters) {
  if (!population) return "";
  const sex = filters?.sexes?.find((s) => s.code === population.sex)?.label;
  return [
    (population.units ?? []).join(" + "),
    population.home_area && t("order.nums.homeArea", { area: areaName(population.home_area, filters) }),
    population.specimen && specimenWord(population.specimen, filters),
    population.organism ? organismName(population.organism, filters) : t("order.nums.allOrganisms"),
    sex && sex.toLocaleLowerCase(),
  ]
    .filter(Boolean)
    .join(" · ");
}
