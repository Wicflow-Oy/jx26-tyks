// The sheet: one modal dialog (#sheet), centred on desktop and a bottom sheet on phones. Focus is trapped
// inside, Esc or the scrim closes it, and focus returns to the control that opened it.

import { $, h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { iconButton } from "./buttons.js";
import { focusables, openLayer, returnFocus } from "./layers.js";

let current = null;

/**
 * openSheet({ eyebrow, title, body: [nodes], note, actions: [buttons], initialFocus, returnTo, onClose })
 * → { el, close }. Calling it again while open swaps the content and keeps the original opener.
 * returnTo: a selector for the opener's re-rendered equivalent (e.g. '[data-draft="phe-…"]').
 */
export function openSheet({ eyebrow, title, body = [], note, actions = [], initialFocus, returnTo, onClose }) {
  const el = $("#sheet");
  const opener = current ? current.opener : document.activeElement;
  current?.detach();

  mount(
    el,
    h("div", { class: "grabber", "aria-hidden": "true" }),
    h(
      "div",
      { class: "sheet-head" },
      h(
        "div",
        null,
        eyebrow && h("div", { class: "eyebrow" }, eyebrow),
        h("h2", { class: "t-title2", id: "sheet-title" }, title),
      ),
      iconButton({ icon: "close", label: t("shell.close"), onClick: () => close() }),
    ),
    h("div", { class: "sheet-body" }, body),
    (note || actions.length > 0) &&
      h(
        "div",
        { class: "sheet-foot" },
        note && h("p", { class: "note" }, note),
        actions.length > 0 && h("div", { class: "btns" }, actions),
      ),
  );
  el.classList.add("open");

  const removeLayer = openLayer({ kind: "sheet", el, close: () => close(), scrim: true, modal: true });
  const handle = {
    el,
    opener,
    detach: removeLayer,
    close,
  };
  current = handle;
  // first focus: initialFocus, else the last control that does something (a "done" chip is aria-disabled)
  const target = () => initialFocus ?? focusables(el).findLast((node) => node.ariaDisabled !== "true") ?? el;
  requestAnimationFrame(() => current === handle && target().focus());

  function close() {
    if (current !== handle) return;
    current = null;
    removeLayer();
    el.classList.remove("open");
    returnFocus(opener, returnTo);
    onClose?.();
  }
  return { el, close };
}
