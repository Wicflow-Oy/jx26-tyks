// Pill menus (the My ward scope bar): a pill button opens one shared menu (#menu) of menuitemradio options.
// ✓ marks the current value; arrows, Home and End move; Esc or Tab closes and focus returns to the pill.

import { $, h, mount } from "../dom.js";
import { icon } from "./icons.js";
import { openLayer } from "./layers.js";

let current = null;

/**
 * pillMenu({ key: "Ward", value: "ICU", isDefault, label, items: () => [...], onSelect(value) })
 * key is the quiet prefix, value the shown value (ink-2 while it is the default). label: accessible name.
 * items: [{ value, label, checked, disabled, hint }] built when the menu opens; disabled options are
 * aria-disabled (the API cannot serve them) and stay in the list.
 */
export function pillMenu({ key, value, isDefault = false, label, items, onSelect }) {
  const pill = h(
    "button",
    {
      type: "button",
      class: ["pill", isDefault && "def"],
      "aria-haspopup": "menu",
      "aria-expanded": "false",
      "aria-label": label,
      onclick: () => (current?.pill === pill ? closeMenu() : openMenu(pill, items(), onSelect)),
    },
    key && h("span", { class: "k" }, key),
    h("span", { class: "v" }, value),
    icon("down", 10),
  );
  return pill;
}

function openMenu(pill, items, onSelect) {
  closeMenu(false);
  const menu = $("#menu");
  const buttons = items.map((item) =>
    h(
      "button",
      {
        type: "button",
        role: "menuitemradio",
        "aria-checked": String(Boolean(item.checked)),
        "aria-disabled": item.disabled ? "true" : null,
        tabindex: "-1",
        onclick: () => {
          if (item.disabled) return;
          closeMenu();
          onSelect(item.value);
        },
      },
      h("span", { class: "ck", "aria-hidden": "true" }, item.checked && icon("ok", 13)),
      item.label,
      item.hint && h("small", null, item.hint),
    ),
  );
  mount(menu, buttons);
  menu.setAttribute("aria-label", pill.getAttribute("aria-label") ?? "");

  const r = pill.getBoundingClientRect();
  menu.style.left = `${Math.max(16, Math.min(r.left, innerWidth - menu.offsetWidth - 16))}px`;
  menu.style.top = `${r.bottom + 6}px`;
  menu.classList.add("open");
  pill.setAttribute("aria-expanded", "true");

  const removeLayer = openLayer({ kind: "menu", el: menu, close: () => closeMenu() });
  current = { pill, menu, buttons, removeLayer };
  (buttons.find((b) => b.getAttribute("aria-checked") === "true") ?? buttons[0])?.focus();
}

/** Closes the open menu; refocus returns focus to its pill. */
export function closeMenu(refocus = true) {
  if (!current) return;
  const { pill, menu, removeLayer } = current;
  current = null;
  removeLayer();
  menu.classList.remove("open");
  pill.setAttribute("aria-expanded", "false");
  if (refocus) pill.focus();
}

document.addEventListener("keydown", (event) => {
  if (!current) return;
  const { buttons } = current;
  const i = buttons.indexOf(document.activeElement);
  const move = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: buttons.length - 1 }[event.key];
  if (move !== undefined) {
    event.preventDefault();
    buttons[(move + buttons.length) % buttons.length].focus();
  } else if (event.key === "Tab") {
    closeMenu(false);
  }
});

// the menu is placed under its pill once; when the page scrolls it would float away, so it closes
addEventListener("scroll", () => current && closeMenu(false), { passive: true });

// a click anywhere outside the menu and its pill closes it, without stealing focus from what was clicked
document.addEventListener(
  "pointerdown",
  (event) => {
    if (current && !current.menu.contains(event.target) && !current.pill.contains(event.target)) closeMenu(false);
  },
  true,
);
