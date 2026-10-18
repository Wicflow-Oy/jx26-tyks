// "Competing explanations": H1–H6 as the API rates them from counts. The pill shows the API's rating_label; its
// weight comes from the rating code: strong is filled ink, the middle ratings are outlined, weak and unlikely are
// quiet. The counts behind each rating are the API's own short notes (p-values, ratios), so they sit in a closed
// disclosure under the list, like the method details.

import { icon } from "../../components/icons.js";
import { h } from "../../dom.js";
import { capitalize } from "../../format.js";
import { t } from "../../i18n.js";

export function explanations(ce) {
  const withEvidence = ce.hypotheses.filter((x) => x.evidence);
  return [
    h(
      "ul",
      { class: "hyp" },
      ce.hypotheses.map((x) =>
        h(
          "li",
          null,
          h("span", { class: "hid" }, x.id),
          h("span", { class: "hl" }, x.label),
          h("span", { class: ["rate", STRENGTH[x.rating] ?? "low"] }, capitalize(x.rating_label)),
        ),
      ),
    ),
    withEvidence.length > 0 &&
      h(
        "details",
        { class: "case-disc" },
        h(
          "summary",
          null,
          h("span", { class: "disc", "aria-hidden": "true" }, icon("chevron", 7)),
          t("case.explanations.counts"),
        ),
        h(
          "dl",
          { class: "kv" },
          withEvidence.map((x) => [h("dt", null, x.id), h("dd", null, `${x.rating_label}: ${x.evidence}`)]),
        ),
      ),
  ];
}

/** The pill's weight per rating code (CONTRACTS §5.1); weak, unlikely and anything else are quiet. */
const STRENGTH = {
  strong: "strong",
  moderate: "mid",
  plausible: "mid",
  possible: "mid",
  check: "mid",
  "contributes (index imported?)": "mid",
};
