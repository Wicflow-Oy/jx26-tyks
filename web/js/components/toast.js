// Toast: a dark capsule at the bottom centre for 2.6 s, announced politely. Only to confirm a write
// ("Alert approved until 13 Apr. Nothing sent.") or to say why a click did nothing.

import { $ } from "../dom.js";

const SHOW_MS = 2600;
let timer = 0;

export function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("on");
  clearTimeout(timer);
  timer = setTimeout(() => el.classList.remove("on"), SHOW_MS);
}
