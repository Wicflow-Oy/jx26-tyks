// One brief item as a row: priority tile and label, the title, the API's text (clamped to three lines), a fixed
// right column with the state word and the advice chip, and a chevron. The whole row opens the case file.

import { adviceChip, priorityColumn, priorityLabel, stateWord } from "../../components/badges.js";
import { icon } from "../../components/icons.js";
import { emptyState } from "../../components/states.js";
import { h } from "../../dom.js";
import { t } from "../../i18n.js";
import { signalTitle } from "../../signals.js";
import { openPane } from "../../state.js";

/**
 * signalRow(item, { extra }) → <li>. extra: nodes under the text (the policy meter); a row with extra shows its
 * text in full. The completeness line that says every unit sent data gets the OK tile.
 */
export function signalRow(item, { extra = null } = {}) {
  const title = signalTitle(item);
  const glyph = item.kind === "completeness" && item.priority === "info" ? "ok" : item.priority;
  const textId = `row-text-${item.id}`;
  const label = [priorityLabel(glyph), title, t(`shell.status.${item.status}`), item.advice].filter(Boolean).join(", ");
  return h(
    "li",
    null,
    h(
      "button",
      {
        type: "button",
        class: ["row", item.status === "resolved" && "is-resolved"],
        "aria-label": label,
        "aria-describedby": textId,
        dataset: { paneId: item.id },
        onclick: () => openPane("case", item.id),
      },
      priorityColumn(glyph),
      h(
        "span",
        { class: "row-main" },
        h("span", { class: "row-title t-headline" }, title),
        h("span", { class: ["row-text t-subhead", extra && "full"], id: textId }, item.text),
        extra,
      ),
      h("span", { class: "row-meta" }, stateWord(item.status), adviceChip(item.advice)),
      h("span", { class: "chev", "aria-hidden": "true" }, icon("chevron", 8)),
    ),
  );
}

/** Title parts joined with quiet "·" separators. */
export const titleNodes = (parts) =>
  parts.map((part, i) => [i > 0 && h("span", { class: "k", "aria-hidden": "true" }, "·"), h("span", null, part)]);

/** An inset list of rows, or the section's calm empty line when it has none. glyph: the empty line's tile. */
export const rowList = (rows, emptyText, glyph = "ok") =>
  h("ul", { class: "inset rows" }, rows.length ? rows : h("li", null, emptyState(emptyText, glyph)));
