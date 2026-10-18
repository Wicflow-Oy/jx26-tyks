// "Status": detected → alert (approved, expired or waiting) → heads-up to the ED → delivery, which always stays
// open: nothing leaves the prototype.

import { icon } from "../../components/icons.js";
import { daysBetween, mondayOf } from "../../dates.js";
import { h } from "../../dom.js";
import { dateShort, int } from "../../format.js";
import { t } from "../../i18n.js";

/** ctx: { item, asOf, alert: alertState(...), headsUp (latest or null), appName } */
export function statusTimeline({ item, asOf, alert, headsUp, appName }) {
  const firstAlert = item.evidence?.counts?.first_alert_date;
  const detected = firstAlert
    ? [
        t("case.status.detected", { date: dateShort(firstAlert) }),
        item.first_sample_date &&
          t("case.status.detectedSub", { n: int(daysBetween(item.first_sample_date, firstAlert)) }),
      ]
    : [
        t("case.status.inBrief", { date: dateShort(mondayOf(asOf)) }),
        item.first_sample_date && t("case.status.firstSample", { date: dateShort(item.first_sample_date) }),
      ];
  return h(
    "div",
    { class: "soft" },
    h(
      "ol",
      { class: "tl" },
      step(true, ...detected),
      step(...alertStep(alert)),
      step(...headsUpStep(headsUp)),
      step(false, t("case.status.delivery"), t("case.status.notSent", { app: appName })),
    ),
  );
}

function alertStep({ state, alert }) {
  if (state === "active")
    return [
      true,
      t("case.status.approved", { date: dateShort(alert.approved_on) }),
      [alert.seed && t("case.status.seed"), t("case.status.until", { date: dateShort(alert.expires_on) })]
        .filter(Boolean)
        .join(" · "),
    ];
  if (state === "expired")
    return [
      false,
      t("case.status.expired", { approved: dateShort(alert.approved_on), until: dateShort(alert.expires_on) }),
      t("case.status.again"),
    ];
  return [false, t("case.status.notApproved"), t("case.status.waiting")];
}

function headsUpStep(headsUp) {
  if (!headsUp) return [false, t("case.status.headsUp"), t("case.status.notDrafted")];
  const approved = headsUp.status === "approved";
  return [
    true,
    t(approved ? "case.status.huApproved" : "case.status.huDrafted", { date: dateShort(mondayOf(headsUp.as_of)) }),
    t("case.status.toEd"),
  ];
}

function step(done, title, sub) {
  return h(
    "li",
    { class: done ? "done" : null },
    h("span", { class: "dotx", "aria-hidden": "true" }, done && icon("ok", 9)),
    h("span", { class: "tx" }, h("b", null, title), sub && h("span", { class: "s" }, sub)),
  );
}
