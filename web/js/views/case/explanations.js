// "Competing explanations": H1–H6 as the API rates them from counts (strong, contributes, unlikely). Strong is
// filled ink, contributes outlined, unlikely quiet. The counts behind each rating are the API's own short notes
// (p-values, ratios), so they sit in a closed disclosure under the list, like the method details.

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
          h("span", { class: ["rate", strength(x.rating)] }, ratingWord(x.rating)),
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
          withEvidence.map((x) => [h("dt", null, x.id), h("dd", null, `${x.rating}: ${x.evidence}`)]),
        ),
      ),
  ];
}

/** The rating's first word, capitalised: "contributes (index imported?)" → "Contributes". */
const ratingWord = (rating) => capitalize(String(rating ?? "").split(/[\s(]/)[0]);

/** The rating's visual weight from the API's word: strong · contributes, plausible, possible · anything else quiet. */
function strength(rating = "") {
  const word = String(rating).toLowerCase();
  if (word.startsWith("strong")) return "strong";
  if (/^(contributes|plausible|possible)/.test(word)) return "mid";
  return "low";
}
