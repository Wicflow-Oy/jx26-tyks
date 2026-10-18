// Loading, empty and error states. A view never shows a blank area or a raw error.

import { ApiError } from "../api.js";
import { h } from "../dom.js";
import { t } from "../i18n.js";
import { tile } from "./badges.js";
import { button } from "./buttons.js";

/** Skeleton card with a shimmer (static under reduced motion). label is read out: "Loading the brief". */
export const loadingState = (label) =>
  h(
    "div",
    { class: "statecard", role: "status", "aria-busy": "true", "aria-label": label },
    h(
      "div",
      { class: "skel" },
      [62, 88, 74, 40].map((width) => h("i", { style: { width: `${width}%` } })),
    ),
  );

/**
 * A calm empty line: a tile and a sentence, emptyState("No unusual pattern this week."). Put it in a .card or an
 * .inset li. glyph: "ok" (nothing to report) or null for a prompt that is not a result ("Choose a drug …").
 */
export const emptyState = (text, glyph = "ok") =>
  h("div", { class: "empty" }, glyph && tile(glyph), h("span", null, text));

/**
 * Error card with role=alert: title ("The brief for Sun 29 Mar 2026 did not load."), the friendly message of an
 * api.js error (any other error reads as a generic one, never as developer text), and Try again.
 */
export function errorState({ title, error, onRetry }) {
  return h(
    "div",
    { class: "statecard", role: "alert" },
    h("p", { class: "t-headline" }, title),
    h(
      "p",
      { class: "t-subhead ink2" },
      error instanceof ApiError ? error.message : t("shell.error.server"),
      " ",
      t("shell.error.unchanged"),
    ),
    onRetry && h("div", { class: "btns" }, button({ label: t("shell.error.retry"), onClick: onRetry })),
  );
}
