// The trend pane: one drug's weekly coverage on the doctor's unit (a pane on desktop, a pushed page on phones).
// Opened without a drug (the Trend tab) it shows the drug of My ward's lead sentence; with no lead drug, or a drug
// this scope does not show, it lets the doctor choose one.

import { get, isAbort } from "../api.js";
import { linkButton } from "../components/buttons.js";
import { paneScroll } from "../components/pane.js";
import { emptyState, errorState, loadingState } from "../components/states.js";
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { noBreak } from "../names.js";
import { openPane } from "../state.js";
import { leadRow } from "./ward/lead.js";
import { trendQuery, wardQuery } from "./ward/scope.js";
import { trendContent } from "./ward/trend-card.js";

const heading = (text) => h("h2", { class: "trend-title", tabindex: "-1" }, text);

/**
 * The pane's scroll area, focusable so a keyboard can scroll it: the trend has no control of its own to land on.
 * (A candidate for components/pane.js paneScroll.)
 */
function scroller(label, ...children) {
  const el = paneScroll(...children);
  el.tabIndex = 0;
  el.setAttribute("role", "region");
  el.setAttribute("aria-label", label);
  return el;
}

/** render(root, { state, meta, filters, signal, first, retry }): root is the pane body; state.pane.id the drug. */
export async function render(root, { state, meta, filters, signal, first, retry }) {
  const drug = state.pane.id;
  if (first) mount(root, paneScroll(heading(t("ward.trend.title")), loadingState(t("ward.trend.loading"))));
  try {
    // the page's own my-ward response (cached): it says which drugs this scope shows, so a drug the scope
    // leaves out (nitrofurantoin on blood) gets the API's reason instead of a failed request
    const ward = await get("/api/my-ward", wardQuery(state, filters), { signal });
    const rows = ward.rows ?? [];
    const lead = leadRow(ward);
    if (!drug && lead) {
      openPane("trend", lead.drug);
      return;
    }
    if (!rows.some((row) => row.drug === drug)) {
      const reason = (ward.not_shown ?? []).find((item) => item.drug === drug)?.reason;
      mount(root, paneScroll(heading(t("ward.trend.title")), choose(rows, reason ?? t("ward.trend.none"))));
      return;
    }
    const trend = await get("/api/trend", trendQuery(state, filters, drug), { signal });
    mount(root, scroller(trend.label ?? drug, trendContent(trend, { meta, filters, inPane: true })));
  } catch (error) {
    if (isAbort(error)) throw error;
    mount(
      root,
      paneScroll(heading(t("ward.trend.title")), errorState({ title: t("ward.trend.error"), error, onRetry: retry })),
    );
  }
}

/** A sentence (why there is no trend to show) and the unit's drugs to choose from. */
function choose(rows, sentence) {
  return [
    h("div", { class: "card" }, emptyState(sentence, null)),
    rows.length > 0 &&
      h(
        "section",
        { class: "group", "aria-labelledby": "h-trend-choose" },
        h("h3", { class: "sec-h", id: "h-trend-choose" }, t("ward.trend.choose")),
        h(
          "ul",
          { class: "inset trend-choose" },
          rows.map((row) =>
            h("li", null, linkButton({ label: noBreak(row.label), onClick: () => openPane("trend", row.drug) })),
          ),
        ),
      ),
  ];
}
