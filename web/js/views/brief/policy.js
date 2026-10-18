// Policy lines: every line from brief.policy_states, never an empty section. A line with a signal this week (crossed,
// or resolved) is its signal row with the meter under the text; any other line is a quiet "Line" row with the same
// meter.

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
  const signals = new Map(sectionItems(brief, "policy").map((item) => [item.id, item]));
  const rows = brief.policy_states.map((line) =>
    signals.has(line.signal_id) ? signalRow(signals.get(line.signal_id), { extra: meter(line) }) : lineRow(line),
  );
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

/** The 0–40% meter of a policy state: interval band, value dot (amber at or over the line), labelled line. */
const meter = (line) =>
  intervalBar({
    value: line.rate,
    interval: line.interval,
    line: line.threshold,
    lineLabel: t("brief.policy.lineLabel", { threshold: pct(line.threshold) }),
  });
