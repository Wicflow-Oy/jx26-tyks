// Segmented control as a radio group: one tab stop (roving tabindex); arrow keys move and select.

import { h } from "../dom.js";

/**
 * segmented({ label, options: [{ value, label, ariaLabel?, lang? }], value, onChange, small, id })
 * Returns { el, set(value), relabel(label, options) }. set() changes the selection without calling onChange;
 * relabel() updates the words after a language switch.
 */
export function segmented({ label, options, value, onChange, small = false, id }) {
  const buttons = options.map((option) =>
    h(
      "button",
      {
        type: "button",
        role: "radio",
        lang: option.lang,
        "aria-label": option.ariaLabel,
        dataset: { value: option.value },
        onclick: () => choose(option.value),
      },
      option.label,
    ),
  );
  const el = h(
    "div",
    { class: ["seg", small && "small"], id, role: "radiogroup", "aria-label": label, onkeydown: onKey },
    buttons,
  );

  function relabel(groupLabel, labels) {
    el.setAttribute("aria-label", groupLabel);
    labels.forEach((option, i) => (buttons[i].textContent = option.label));
  }

  function set(next) {
    for (const b of buttons) {
      const on = b.dataset.value === next;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    }
  }

  function choose(next) {
    const changed = buttons.find((b) => b.getAttribute("aria-checked") === "true")?.dataset.value !== next;
    set(next);
    if (changed) onChange(next);
  }

  function onKey(event) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    const i = buttons.indexOf(document.activeElement);
    if (!step || i < 0) return;
    event.preventDefault();
    const target = buttons[(i + step + buttons.length) % buttons.length];
    target.focus();
    choose(target.dataset.value);
  }

  set(value);
  return { el, set, relabel };
}
