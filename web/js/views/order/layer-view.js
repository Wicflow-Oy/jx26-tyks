// What our layer shows under the medication field for one order context, by the backend's state:
//   quiet    a calm chip with a grey dot (never a check: a check would read "this drug is approved"), "Numbers"
//   no_data  a hatched, dashed chip: no number for this drug here, which is not the same as quiet
//   notice   a one-line chip: an alert on the unit that does not apply to this order, no numbers
//   info     a passive card: what is happening in full, this drug's numbers behind "Show details" (a warning at
//            select is shown the same way; it asks only at signing)
// Nothing here takes focus or blocks the order, and nothing names another drug.

import { tile } from "../../components/badges.js";
import { icon } from "../../components/icons.js";
import { h } from "../../dom.js";
import { t } from "../../i18n.js";
import { drugNumbers } from "./drug-numbers.js";
import { detailsLink, line, notesSection, smallPrint, sourceLabel } from "./parts.js";
import { previousLine, previousTable } from "./previous-results.js";

const CHIP_TILE = { quiet: "P3", no_data: "gap", notice: "info" };
const MINI_ROWS = 3; // previousLine shows this many; more rows go in the table behind the disclosure

/** layerView(ctx, { appName, filters, draft, onDetails }) → nodes. draft.detailsOpen keeps a disclosure open. */
export function layerView(ctx, env) {
  if (ctx.state === "info" || ctx.state === "warning") return infoCard(ctx, env);
  return chips(ctx, env);
}

function chips(ctx, { appName, filters, draft, onDetails }) {
  const quiet = ctx.state === "quiet";
  const panel = quiet
    ? h(
        "div",
        { class: "sw-panel", id: "sw-more" },
        (ctx.previous_results ?? []).length > MINI_ROWS && previousTable(ctx, filters),
        drugNumbers(ctx, filters),
        notesSection(ctx),
        foot(ctx, onDetails),
      )
    : null;
  return [
    h(
      "div",
      { class: "sw-chips" },
      h(
        "p",
        { class: ["sw-chip", ctx.state === "no_data" && "nodata"] },
        tile(CHIP_TILE[ctx.state], "sm"),
        h("span", { class: "sw-chip-text" }, ctx.chip),
        quiet && h("span", { class: "sw-chip-note" }, t("order.layer.quietNote")),
      ),
      panel && disclosure(panel, draft, t("order.layer.numbers")),
      sourceLabel(appName),
    ),
    previousLine(ctx, filters),
    panel,
  ];
}

function infoCard(ctx, { appName, filters, draft, onDetails }) {
  const more = h(
    "div",
    { class: "sw-more", id: "sw-more" },
    (ctx.previous_results ?? []).length > MINI_ROWS && previousTable(ctx, filters),
    drugNumbers(ctx, filters),
    notesSection(ctx),
    h("div", { class: "sw-foot" }, smallPrint(ctx)),
  );
  return h(
    "section",
    { class: "sw-card", "aria-labelledby": "sw-headline" },
    h(
      "div",
      { class: "sw-head" },
      tile("info", "sm"),
      h("h3", { class: "sw-title", id: "sw-headline" }, ctx.headline),
      h("p", { class: "sw-meta" }, sourceLabel(appName, ctx)),
      h("p", { class: "sw-text" }, line(ctx, "happening")?.text),
      h("p", { class: "sw-ask" }, ctx.ask),
      previousLine(ctx, filters),
    ),
    h(
      "div",
      { class: "sw-acts" },
      disclosure(more, draft, t("order.layer.showDetails"), t("order.layer.hideDetails")),
      detailsLink(ctx, { onFollow: onDetails }),
    ),
    more,
  );
}

/** The button that opens and closes a panel; its state survives a drug change (draft.detailsOpen). */
function disclosure(panel, draft, closedLabel, openLabel = closedLabel) {
  const label = h("span");
  const button = h("button", { type: "button", class: "sw-disc", "aria-controls": panel.id }, label, icon("down", 10));
  const sync = () => {
    panel.hidden = !draft.detailsOpen;
    button.setAttribute("aria-expanded", String(draft.detailsOpen));
    label.textContent = draft.detailsOpen ? openLabel : closedLabel;
  };
  button.addEventListener("click", () => {
    draft.detailsOpen = !draft.detailsOpen;
    sync();
  });
  sync();
  return button;
}

const foot = (ctx, onDetails) =>
  h("div", { class: "sw-foot" }, detailsLink(ctx, { onFollow: onDetails }), smallPrint(ctx));
