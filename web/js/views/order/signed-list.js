// The host's "Orders this visit": what the doctor signed for this patient, with how the check was answered.

import { h } from "../../dom.js";
import { t } from "../../i18n.js";

export function signedList(draft) {
  const orders = draft.signed;
  return h(
    "section",
    { class: "ehr-panel signed", "aria-labelledby": "signed-title" },
    h(
      "div",
      { class: "ehr-ph" },
      h("h3", { id: "signed-title" }, t("order.orders.title")),
      orders.length > 0 && h("span", { class: "ehr-cnt" }, t("order.ehr.listCount", { n: orders.length })),
    ),
    orders.length
      ? h(
          "ul",
          { class: "olist" },
          orders.map((order) =>
            h(
              "li",
              null,
              h(
                "span",
                { class: "o-top" },
                h("b", null, order.name),
                h("span", { class: "o-atc" }, order.atc),
                h("span", { class: "o-status" }, t("order.orders.status")),
              ),
              h("span", { class: "o-line" }, order.dosing),
              order.note && h("span", { class: "o-line" }, order.note),
            ),
          ),
        )
      : h("p", { class: "ehr-empty" }, t("order.orders.none")),
  );
}
