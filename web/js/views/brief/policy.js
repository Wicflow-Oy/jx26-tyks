// Policy lines: every line from brief.policy_states, never an empty section. A crossed line is its P2 signal row with
// the meter under the text; a line below its threshold is a quiet "Line" row with the same meter. Without
// policy_states (an older backend) the section lists the policy signals the brief has.

import { tile } from "../../components/badges.js";
import { intervalBar } from "../../components/interval-bar.js";
import { mk } from "../../components/marker.js";
import { h } from "../../dom.js";
import { pct, xOfN } from "../../format.js";
import { t } from "../../i18n.js";
import { rich } from "../../text.js";
import { sectionItems } from "./model.js";
import { rowList, signalRow, titleNodes } from "./row.js";

export function policyList(brief) {
  const items = sectionItems(brief, "policy");
  const states = Array.isArray(brief.policy_states) ? brief.policy_states : [];
  const signals = new Map(items.map((item) => [item.id, item]));
  const stated = new Set(states.map((line) => line.signal_id));
  const rows = [
    ...states.map((line) =>
      signals.has(line.signal_id) ? signalRow(signals.get(line.signal_id), { extra: meter(line) }) : lineRow(line),
    ),
    // a policy signal without a state (all of them on a backend without policy_states) carries its own slots
    ...items.filter((item) => !stated.has(item.id)).map((item) => signalRow(item, { extra: meter(item.slots) })),
  ];
  return rowList(rows, t("brief.empty.policy"), "line");
}

/** A line below its threshold: "17.7% resistant (136 of 770, last 52 weeks). The line is at 20%. …" */
function lineRow(line) {
  const weeks = Math.round(line.window_days / 7);
  const rate = h("b", { class: "num" }, mk(`policy-${line.id}`, pct(line.rate, 1)));
  return h(
    "li",
    null,
    h(
      "div",
      { class: "row line-row", role: "group", "aria-label": lineSummary(line, weeks) },
      h("span", { class: "prio line" }, tile("line"), h("span", { class: "plabel" }, t("shell.priority.line"))),
      h(
        "span",
        { class: "row-main" },
        h(
          "span",
          { class: "row-title t-headline" },
          titleNodes([line.drug_label, line.population_label].filter(Boolean)),
        ),
        h(
          "span",
          { class: "row-text t-subhead full" },
          rich("brief.policy.rate", { rate, counts: xOfN(line.x, line.n), weeks }),
          " ",
          t("brief.policy.threshold", { threshold: pct(line.threshold) }),
          line.rate_prior != null &&
            ` ${t("brief.policy.prior", { weeks, rate: pct(line.rate_prior, 1), counts: xOfN(line.x_prior, line.n_prior) })}`,
        ),
        meter(line),
      ),
      h(
        "span",
        { class: "row-meta" },
        h("span", { class: "state" }, t(line.active ? "brief.policy.above" : "brief.policy.below")),
      ),
    ),
  );
}

const lineSummary = (line, weeks) =>
  [
    [line.drug_label, line.population_label].filter(Boolean).join(", "),
    t("brief.policy.spoken", {
      rate: pct(line.rate, 1),
      counts: xOfN(line.x, line.n),
      weeks,
      threshold: pct(line.threshold),
    }),
  ].join(": ");

/** The 0–40% meter: interval band, value dot (amber at or over the line), labelled line. A state or a signal's slots. */
const meter = (line) =>
  line?.rate != null &&
  intervalBar({
    value: line.rate,
    interval: line.interval,
    line: line.threshold,
    lineLabel: t("brief.policy.lineLabel", { threshold: pct(line.threshold) }),
  });
