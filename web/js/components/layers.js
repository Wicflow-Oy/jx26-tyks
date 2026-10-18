// The overlay stack. Esc (or a click on the scrim) closes the highest open layer in the order
// menu → sheet → replay sheet → tour → pushed page (DESIGN §6). Modal layers keep Tab inside themselves.
// Browser Back closes every layer above the page, so a sheet never stays open over a page it no longer belongs to.

import { $ } from "../dom.js";

const RANK = { page: 1, tour: 2, replay: 3, sheet: 4, menu: 5 };
const open = new Set();

/**
 * openLayer({ kind, el, close, scrim, modal, escapable }) → remove()
 * kind: a RANK key · close(): closes it (and returns focus) · scrim: shows the shared scrim ·
 * modal / escapable: booleans or functions, read at the moment of the key press.
 */
export function openLayer(layer) {
  const entry = { scrim: false, modal: false, escapable: true, ...layer };
  open.add(entry);
  syncScrim();
  return () => {
    open.delete(entry);
    syncScrim();
  };
}

const read = (value) => (typeof value === "function" ? value() : value);

function top(filter = () => true) {
  return [...open].filter(filter).sort((a, b) => RANK[b.kind] - RANK[a.kind])[0];
}

function syncScrim() {
  $("#scrim")?.classList.toggle(
    "open",
    [...open].some((layer) => layer.scrim),
  );
}

/** The keyboard-focusable elements inside el, in order, visible ones only. */
export function focusables(el) {
  return [
    ...el.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]"),
  ].filter((node) => node.tabIndex >= 0 && node.getClientRects().length > 0);
}

/** Focus the opener again if it is still on the page, else the first match of fallback, else main. */
export function returnFocus(opener, fallback) {
  const target =
    opener?.isConnected && opener.getClientRects().length ? opener : (fallback && $(fallback)) || $("#main");
  target?.focus({ preventScroll: true });
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const layer = top((l) => read(l.escapable));
    if (layer) {
      event.preventDefault();
      layer.close();
    }
  } else if (event.key === "Tab") {
    const layer = top((l) => read(l.modal));
    if (layer) trapTab(layer.el, event);
  }
});

addEventListener("popstate", () => {
  for (const layer of [...open].filter((l) => l.kind !== "page")) layer.close();
});

document.addEventListener("click", (event) => {
  if (event.target.id === "scrim") top((l) => read(l.escapable))?.close();
});

function trapTab(el, event) {
  const items = focusables(el);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const outside = !el.contains(document.activeElement);
  if (event.shiftKey && (document.activeElement === first || outside)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || outside)) {
    event.preventDefault();
    first.focus();
  }
}
