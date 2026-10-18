// Data quality: a closed disclosure (open when a unit has a data gap) with the lab checks, the completeness line
// (OK, or the P2 gap) and "Cultures this week by unit".

import { icon } from "../../components/icons.js";
import { mk } from "../../components/marker.js";
import { unitBars } from "../../components/unit-bars.js";
import { h } from "../../dom.js";
import { int } from "../../format.js";
import { t } from "../../i18n.js";
import { isOpen } from "../../signals.js";
import { plural } from "../../text.js";
import { completeness, openCount, section, sectionItems } from "./model.js";
import { rowList, signalRow } from "./row.js";

export function dataQuality(brief, wards) {
  const items = sectionItems(brief, "data_quality");
  const lab = items.filter((item) => item.kind === "expert_rule" && isOpen(item)).length;
  const gaps = completeness(brief).filter((item) => item.ward && isOpen(item)).length;
  const cultures = completeness(brief).find((item) => isPlainObject(item.evidence?.counts?.cultures_this_week));
  const summary = [
    lab > 0 && plural("brief.dek.lab", lab, { n: int(lab) }),
    gaps > 0 && plural("brief.dek.gap", gaps, { n: int(gaps) }),
  ]
    .filter(Boolean)
    .join(" · ");

  return h(
    "details",
    { class: "group dq", id: "sec-data_quality", open: gaps > 0 },
    h(
      "summary",
      null,
      h(
        "h2",
        { class: "sec-h" },
        h("span", { class: "disc", "aria-hidden": "true" }, icon("chevron", 7)),
        section(brief, "data_quality")?.title ?? t("brief.section.data_quality"),
        h("span", { class: "count" }, mk("sec-data_quality", int(openCount(brief, "data_quality")))),
        summary && h("span", { class: "right" }, summary),
      ),
    ),
    rowList(
      items.map((item) => signalRow(item)),
      t("brief.empty.data_quality"),
    ),
    cultures && culturesCard(cultures.evidence.counts.cultures_this_week, wards),
    h("p", { class: "group-foot" }, t("brief.foot.data_quality")),
  );
}

/** One bar per unit, in the hospital's unit order. */
function culturesCard(byUnit, wards) {
  const order = wards.length ? wards.map((w) => w.code) : Object.keys(byUnit);
  const title = t("brief.cultures");
  return h(
    "div",
    { class: "card cultures" },
    h("div", { class: "eyebrow" }, title),
    unitBars(
      order.map((code) => [code, byUnit[code] ?? 0]),
      { label: title },
    ),
  );
}

const isPlainObject = (value) => value != null && typeof value === "object" && !Array.isArray(value);
