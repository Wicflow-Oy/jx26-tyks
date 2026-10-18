// The P1 hero: only the top open P1 gets headline scale. Kicker, state and advice; the title; the API's full text;
// count chips; the unit epi curve from the case file; the alert line and "Case file ›".

import { alertState } from "../../alerts.js";
import { adviceChip, priorityLabel, srSet, stateWord, tile } from "../../components/badges.js";
import { linkButton } from "../../components/buttons.js";
import { epiCurve } from "../../components/epi-curve.js";
import { mk } from "../../components/marker.js";
import { h } from "../../dom.js";
import { dateShort, int, xOfN } from "../../format.js";
import { t } from "../../i18n.js";
import { kindLabel, signalTitle } from "../../signals.js";
import { openPane } from "../../state.js";
import { rich } from "../../text.js";

/** hero({ item, file, alerts, asOf, drugLabel, lagDays }): file is the item's case file (null if it did not load). */
export function hero({ item, file, alerts, asOf, drugLabel, lagDays }) {
  const open = () => openPane("case", item.id);
  const titleId = `hero-title-${item.id}`;
  return h(
    "article",
    {
      class: "hero",
      id: "brief-hero",
      "aria-labelledby": titleId,
      dataset: { paneId: item.id },
      // the whole card opens the case file for a pointer; keyboard users have the "Case file" button
      onclick: (event) => !event.target.closest("button, summary, a") && open(),
    },
    h(
      "div",
      { class: "hero-top" },
      tile(item.priority, "sm"),
      h("span", { class: "hero-kicker" }, h("b", null, priorityLabel(item.priority)), ` · ${kindLabel(item.kind)}`),
      h("span", { class: "hero-meta" }, stateWord(item.status), adviceChip(item.advice)),
    ),
    h("h3", { id: titleId }, signalTitle(item)),
    h("p", { class: "lede" }, item.text),
    chips(item.slots ?? {}, drugLabel),
    epi(item, file, asOf, lagDays),
    h(
      "div",
      { class: "hero-foot" },
      h("span", { class: "t-footnote ink2" }, alertLine(alertState(item, asOf, alerts))),
      linkButton({ label: t("brief.hero.open"), onClick: open, attrs: { "aria-describedby": titleId } }),
    ),
  );
}

/** "13 patients | usually 0–2 a year", "12 of 13 same antibiogram", the S/R badges: each only when its slots exist. */
function chips(slots, drugLabel) {
  const n = slots.n_patients;
  const usual = slots.expected_low != null && slots.expected_high != null;
  const list = [
    n != null &&
      h(
        "span",
        { class: "vs" },
        h("span", null, rich("brief.hero.patients", { n: h("b", null, mk("hero-n", int(n))) })),
        usual && h("i", { "aria-hidden": "true" }),
        usual &&
          h(
            "span",
            null,
            rich("brief.hero.usual", {
              range: h("b", null, `${int(slots.expected_low)}–\u2060${int(slots.expected_high)}`),
            }),
          ),
      ),
    slots.n_share != null &&
      n != null &&
      h(
        "span",
        { class: "vs" },
        rich("brief.hero.share", { counts: h("b", null, mk("hero-share", xOfN(slots.n_share, n))) }),
      ),
    slots.pattern && h("span", { class: "vs" }, srSet(slots.pattern, drugLabel)),
  ].filter(Boolean);
  return list.length > 0 && h("div", { class: "row-extra" }, list);
}

/** The epi curve from the case file's line list; the cluster's antibiogram fills the squares that share it. */
function epi(item, file, asOf, lagDays) {
  const rows = file?.line_list?.rows ?? [];
  if (rows.length < 2) return null; // one case is a single square: the text says it better
  const counts = item.evidence?.counts ?? {};
  return h(
    "div",
    { class: "epi-wrap" },
    epiCurve({
      rows,
      pattern: item.slots?.pattern ?? item.evidence?.filter?.profile ?? null,
      firstAlert: counts.first_alert_date ?? null,
      asOf,
      unit: counts.n_patients === file.line_list.n ? "patients" : "isolates",
      lagDays,
    }),
  );
}

/** "Alert approved 9 Mar by infection control, until 23 Mar" · "Alert approved 9 Mar, expired 23 Mar" · none. */
export function alertLine({ state, alert }) {
  if (state === "none") return t("brief.hero.noAlert");
  const dates = { approved: dateShort(alert.approved_on), until: dateShort(alert.expires_on) };
  return t(state === "active" ? "brief.hero.alertActive" : "brief.hero.alertExpired", dates);
}
