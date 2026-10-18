// The sidebar's building blocks: a titled group, an item button (icon or glyph slot, optional unit code, label,
// count) and a quiet note in place of an empty list.

import { icon } from "../components/icons.js";
import { h } from "../dom.js";

export const group = (heading, items) =>
  h("div", { class: "side-group" }, h("div", { class: "side-h" }, heading), items);

/**
 * sideItem({ icon | slot, code, label, count, name, current, onClick }). count: a number or a short word on the
 * right ("until 23 Mar"). name: the full accessible name and tooltip; by default label and count read as one
 * ("Monday brief, 7", not "Monday brief7").
 */
export function sideItem({ icon: iconName, slot, code, label, count = "", name, current = false, onClick }) {
  const spoken = name ?? (count !== "" ? `${label}, ${count}` : null);
  return h(
    "button",
    {
      type: "button",
      class: "side-item",
      title: name ?? label,
      "aria-current": current ? "page" : null,
      "aria-label": spoken,
      onclick: onClick,
    },
    iconName ? h("span", { class: "ico" }, icon(iconName, 16)) : h("span", { class: "slot" }, slot),
    code && h("span", { class: "code" }, code),
    h("span", { class: "lbl" }, label),
    count !== "" && h("span", { class: "cnt" }, count),
  );
}

export const sideNote = (text) => h("p", { class: "side-note" }, text);
