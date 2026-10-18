// The brief's signal sections in order: Unusual patterns (with the P1 hero), What changed, Policy lines and Seen
// before. Each has its heading with the open count, its rows (resolved ones stay listed, marked resolved) and a
// one-line foot saying what the section looks at.

import { mk } from "../../components/marker.js";
import { h } from "../../dom.js";
import { int } from "../../format.js";
import { t } from "../../i18n.js";
import { hero } from "./hero.js";
import { openCount, section, sectionItems } from "./model.js";
import { policyList } from "./policy.js";
import { rowList, signalRow } from "./row.js";

const KEYS = ["unusual_patterns", "changed", "policy", "seen_before"];

/** page: { brief, alerts, hero, heroFile, asOf, drugLabel, lagDays } from the brief view. */
export function signalSections(page) {
  return KEYS.map((key) => sectionGroup(key, page));
}

function sectionGroup(key, page) {
  const { brief } = page;
  const headingId = `h-${key}`;
  return h(
    "section",
    { class: "group", id: `sec-${key}`, "aria-labelledby": headingId },
    h(
      "h2",
      { class: "sec-h", id: headingId },
      section(brief, key)?.title ?? t(`brief.section.${key}`),
      h("span", { class: "count" }, mk(`sec-${key}`, int(openCount(brief, key)))),
    ),
    body(key, page),
    h("p", { class: "group-foot" }, t(`brief.foot.${key}`)),
  );
}

function body(key, page) {
  const { brief } = page;
  if (key === "policy") return policyList(brief);
  const items = sectionItems(brief, key);
  if (key !== "unusual_patterns" || !page.hero)
    return rowList(
      items.map((item) => signalRow(item)),
      t(`brief.empty.${key}`),
    );

  const rest = items.filter((item) => item.id !== page.hero.id);
  return [
    hero({ ...page, item: page.hero, file: page.heroFile }),
    rest.length > 0 &&
      h(
        "ul",
        { class: "inset rows" },
        rest.map((item) => signalRow(item)),
      ),
  ];
}
