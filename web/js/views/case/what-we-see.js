// "01 What we see": the evidence for one signal, by kind. A cluster gets its own evidence (cluster-evidence.js);
// other kinds get the API's sentence and the visual their counts allow. Footnotes name the counts and the method
// in plain words.

import { intervalBar } from "../../components/interval-bar.js";
import { unitBars } from "../../components/unit-bars.js";
import { h } from "../../dom.js";
import { dateFull, dateShort, int, pct, significant, xOfN } from "../../format.js";
import { t } from "../../i18n.js";
import { rich } from "../../text.js";
import { clusterEvidence } from "./cluster-evidence.js";
import { methodText, notes, resistantMeter } from "./parts.js";
import { seenBeforeVisual } from "./seen-before.js";

/** ctx: { item, file, asOf, names, wards, lagDays } */
export function whatWeSee(ctx) {
  const { item, file } = ctx;
  // a single case gets the sentence only: one square is not a curve
  if ((file?.line_list?.rows ?? []).length > 1 && (item.kind === "phenotype_cluster" || item.kind === "thl_rule"))
    return clusterEvidence(ctx);
  const visual = {
    resistance_change: resistanceChange,
    ward_outlier: wardOutlier,
    policy_line: policyLine,
    expert_rule: expertRule,
    completeness: cultures,
    seen_before: () => seenBeforeVisual(item),
  }[item.kind];
  return [
    h("p", { class: "readout" }, item.text),
    visual?.(ctx),
    item.kind !== "quiet" &&
      notes([
        item.kind === "resistance_change" && changeCounts(item),
        [t("case.note.method"), methodText(item.kind)],
        item.kind === "seen_before" && [t("case.note.profile"), t("case.note.profileText")],
        item.kind === "expert_rule" && [t("case.note.lab"), t("case.lab.forLab")],
      ]),
  ];
}

function resistanceChange({ item }) {
  const c = item.evidence?.counts ?? {};
  const slots = item.slots ?? {};
  return h(
    "div",
    { class: "soft" },
    c.tested != null &&
      resistantMeter(t("case.window.last", { weeks: int(slots.window_weeks) }), c.resistant, c.tested),
    c.prior_tested != null &&
      resistantMeter(t("case.window.before", { weeks: int(slots.prior_weeks) }), c.prior_resistant, c.prior_tested),
    c.last_flagged_tested != null &&
      resistantMeter(
        t("case.window.flagged", { date: dateShort(slots.last_flagged) }),
        c.last_flagged_resistant,
        c.last_flagged_tested,
      ),
  );
}

/** "About 0.34 resistant expected at the usual rate. Hospital, 52 weeks before: 34 of 958." */
function changeCounts(item) {
  const c = item.evidence?.counts ?? {};
  if (c.expected_resistant == null) return null;
  return [
    t("case.note.counts"),
    t("case.change.expected", {
      expected: significant(c.expected_resistant, 2),
      weeks: int(item.slots?.prior_weeks),
      hospital: xOfN(c.hospital_prior_resistant, c.hospital_prior_tested),
    }),
  ];
}

function wardOutlier({ item, names }) {
  const cells = item.evidence?.counts?.cells ?? [];
  if (cells.length === 0) return null;
  const weeks = int(item.slots?.window_weeks);
  return h(
    "div",
    { class: "soft lltab-wrap", tabindex: "0", role: "region", "aria-label": t("case.outlier.caption") },
    h(
      "table",
      { class: "lltab" },
      h("caption", { class: "sr" }, t("case.outlier.caption")),
      h(
        "thead",
        null,
        h(
          "tr",
          null,
          h("th", { scope: "col" }, t("case.outlier.pair")),
          h("th", { scope: "col", class: "r" }, t("case.window.last", { weeks })),
          h("th", { scope: "col", class: "r" }, t("case.outlier.before")),
        ),
      ),
      h(
        "tbody",
        null,
        cells.map((cell) =>
          h(
            "tr",
            null,
            h("td", null, `${names.organism(cell.organism) ?? cell.organism} · ${names.drug(cell.drug) ?? cell.drug}`),
            h("td", { class: "r" }, xOfN(cell.resistant, cell.tested)),
            h("td", { class: "r" }, xOfN(cell.prior_resistant, cell.prior_tested)),
          ),
        ),
      ),
    ),
  );
}

function policyLine({ item }) {
  const slots = item.slots ?? {};
  if (slots.rate == null) return null;
  return h(
    "div",
    { class: "soft" },
    intervalBar({
      value: slots.rate,
      interval: slots.interval,
      line: slots.threshold,
      lineLabel: t("brief.policy.lineLabel", { threshold: pct(slots.threshold) }),
    }),
    slots.crossed_on && h("p", { class: "cap" }, t("case.policy.crossed", { date: dateFull(slots.crossed_on) })),
  );
}

function expertRule({ item }) {
  const c = item.evidence?.counts ?? {};
  if (c.checked == null) return null;
  const byUnit = Object.entries(c.by_unit ?? {});
  return h(
    "div",
    { class: "soft" },
    h(
      "p",
      { class: "t-subhead" },
      rich("case.lab.readout", { counts: h("b", null, xOfN(c.hits, c.checked)) }),
      byUnit.length > 0 &&
        ` ${t("case.lab.byUnit", { units: byUnit.map(([unit, n]) => `${unit} ${int(n)}`).join(", ") })}`,
    ),
  );
}

function cultures({ item, wards }) {
  const byUnit = item.evidence?.counts?.cultures_this_week;
  if (byUnit == null || typeof byUnit !== "object") return null;
  const order = wards.length ? wards.map((w) => w.code) : Object.keys(byUnit);
  return h(
    "div",
    { class: "soft" },
    unitBars(
      order.map((code) => [code, byUnit[code] ?? 0]),
      { label: t("brief.cultures") },
    ),
  );
}
