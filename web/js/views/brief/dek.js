// The dek: one sentence built from the section counts ("One unusual pattern, two changes and one lab check."),
// the quiet clause ("Seven of nine units quiet."), then the count capsules by priority.

import { priorityLabel, tile } from "../../components/badges.js";
import { mk } from "../../components/marker.js";
import { h } from "../../dom.js";
import { capitalize, int, word } from "../../format.js";
import { t } from "../../i18n.js";
import { isOpen, PRIORITIES } from "../../signals.js";
import { plural, rich } from "../../text.js";
import { completeness, openCount, quietUnits, sectionItems } from "./model.js";

export function dek(brief) {
  const lab = sectionItems(brief, "data_quality").filter((item) => item.kind === "expert_rule" && isOpen(item)).length;
  const gaps = completeness(brief).filter((item) => item.ward && isOpen(item)).length;
  const parts = [
    ["unusual", openCount(brief, "unusual_patterns")],
    ["changed", openCount(brief, "changed")],
    ["policy", openCount(brief, "policy")],
    ["seenBefore", openCount(brief, "seen_before")],
    ["gap", gaps],
    ["lab", lab],
  ]
    .filter(([, n]) => n > 0)
    .map(([key, n]) => plural(`brief.dek.${key}`, n, { n: word(n) }));
  const lead = parts.length ? `${capitalize(joinWords(parts))}.` : t("brief.dek.none");
  const quiet = quietUnits(brief);
  return h(
    "p",
    { class: "dek" },
    lead,
    quiet &&
      h(
        "span",
        { class: "q" },
        " ",
        capitalize(t("brief.dek.quiet", { quiet: word(quiet.quiet), units: word(quiet.units) })),
      ),
  );
}

/** "a, b and c" */
function joinWords(parts) {
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts.slice(0, -1).join(", ")} ${t("brief.dek.and")} ${parts.at(-1)}`;
}

/** Count capsules P1 · P2 · P3 · Info from brief.counts, and "2 of 9 units with a signal" from the map. */
export function countCapsules(brief) {
  const counts = brief.counts ?? {};
  const units = brief.map?.units ?? [];
  const withSignal = units.filter((unit) => unit.state === "signal" || unit.state === "changed").length;
  return h(
    "ul",
    { class: "counts", "aria-label": t("brief.counts.label") },
    PRIORITIES.map((priority) =>
      h(
        "li",
        { class: "cc" },
        tile(priority, "sm"),
        h("span", { class: "n" }, mk(`cap-${priority}`, int(counts[priority] ?? 0))),
        h("span", { class: "l" }, priorityLabel(priority)),
      ),
    ),
    units.length > 0 &&
      h(
        "li",
        { class: "aside" },
        rich("brief.counts.units", { n: mk("units-signal", int(withSignal)), units: int(units.length) }),
      ),
  );
}
