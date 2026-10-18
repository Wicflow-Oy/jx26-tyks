// Replay marker: numbers that changed since the previous week get a yellow underline that fades over 1.2 s.
// A view wraps a number in mk("sec-changed", "3"); main.js compares the keys before and after a replay step.

import { $$, h } from "../dom.js";

/** A number that is watched across replay steps. key is stable for the same number in every week. */
export const mk = (key, ...children) => h("span", { class: "mk", dataset: { k: key } }, children);

/** Text of every watched number in root, by key. */
export const snapshotMarks = (root) => new Map($$("[data-k]", root).map((el) => [el.dataset.k, el.textContent]));

/** Underlines the watched numbers whose text differs from the snapshot taken before the step. */
export function markChanges(root, before) {
  for (const el of $$("[data-k]", root)) {
    const was = before.get(el.dataset.k);
    if (was != null && was !== el.textContent) el.classList.add("marked");
  }
}
