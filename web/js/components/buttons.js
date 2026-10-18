// Buttons. One primary per surface; the rest bordered or plain. Hit areas are at least 24×24.

import { h } from "../dom.js";
import { t } from "../i18n.js";
import { icon } from "./icons.js";

/**
 * button({ label, variant: "primary" | "bordered" | "plain" | "done", large, icon: "tour", onClick, attrs })
 * "done" is a finished state ("✓ Alert active"): it shows a check and is aria-disabled.
 */
export function button({ label, variant = "bordered", large = false, icon: iconName, onClick, attrs = {} }) {
  const done = variant === "done";
  const { class: extraClass, ...rest } = attrs;
  return h(
    "button",
    {
      type: "button",
      class: ["btn", `btn-${variant}`, large && "btn-lg", extraClass],
      onclick: done ? null : onClick,
      "aria-disabled": done ? "true" : null,
      ...rest,
    },
    done ? icon("ok", 14) : iconName && icon(iconName, 15),
    label,
  );
}

/** A 30×30 icon button; label is its accessible name. */
export const iconButton = ({ icon: iconName, label, onClick, size = 14, attrs = {} }) =>
  h(
    "button",
    { type: "button", class: "icon-btn", "aria-label": label, onclick: onClick, ...attrs },
    icon(iconName, size),
  );

/** A text link that acts in the page ("Case file ›", "Latest ›"). */
export const linkButton = ({ label, onClick, chevron = true, attrs = {} }) =>
  h("button", { type: "button", class: "linkbtn", onclick: onClick, ...attrs }, label, chevron && icon("chevron", 6));

/**
 * ◀ ▶ week stepper. Returns { el, update(canPrev, canNext) }; update also refreshes the labels after a language
 * switch. Disabled ends cannot be pressed.
 */
export function weekStepper({ onStep }) {
  const prev = iconButton({ icon: "prev", label: "", onClick: () => onStep(-1) });
  const next = iconButton({ icon: "next", label: "", onClick: () => onStep(1) });
  const el = h("span", { class: "stepper", role: "group" }, prev, next);
  const update = (canPrev, canNext) => {
    el.setAttribute("aria-label", t("shell.step.group"));
    prev.setAttribute("aria-label", t("shell.step.prev"));
    next.setAttribute("aria-label", t("shell.step.next"));
    const focused = document.activeElement;
    prev.disabled = !canPrev;
    next.disabled = !canNext;
    // a button that has just become disabled at the end of the range hands focus to the other one
    if (focused === prev && !canPrev) next.focus();
    if (focused === next && !canNext) prev.focus();
  };
  return { el, update };
}
