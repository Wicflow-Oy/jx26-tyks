// The pane beside the page (case file, trend). One element, three presentations by width (shell.css):
// >=1280 a floating third surface · 1024–1279 a drawer over a scrim · <1024 a pushed full-screen page
// with "‹ Brief" and the Prototype capsule. main.js shows and hides it from the route; views fill its body.

import { $, h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { prototypeCapsule } from "./badges.js";
import { iconButton } from "./buttons.js";
import { icon } from "./icons.js";
import { focusables, openLayer, returnFocus } from "./layers.js";

/** True when the pane sits beside the page (>=1280) rather than over it. */
export const paneBeside = () => matchMedia("(min-width: 1280px)").matches;
let open = null; // { opener, returnTo, removeLayer }

/**
 * Shows the pane and returns its body for the pane view to fill.
 * label: accessible name and eyebrow ("Case file") · backLabel: phone back button ("Brief") ·
 * returnTo: selector focused on close when the opener is gone · onClose: called by ×, ‹, Esc and the scrim.
 */
export function showPane({ label, backLabel, returnTo, onClose }) {
  const pane = $("#pane");
  pane.setAttribute("aria-label", label);
  mount(
    $(".pane-top", pane),
    h("button", { type: "button", class: "back", onclick: onClose }, icon("back", 11), backLabel),
    h("span", { class: "eyebrow" }, label),
    h("span", { class: "grow" }),
    prototypeCapsule(),
    iconButton({ icon: "close", label: t("shell.close"), onClick: onClose, attrs: { class: "icon-btn close" } }),
  );
  if (!open) {
    open = {
      opener: document.activeElement,
      removeLayer: openLayer({
        kind: "page",
        el: pane,
        close: onClose,
        modal: () => !paneBeside(),
      }),
    };
    document.body.classList.add("pane-open");
  }
  open.returnTo = returnTo;
  return $(".pane-body", pane);
}

/**
 * Moves focus into the pane (its heading, else its first control). Beside the page this happens only when someone
 * opened it (focus was on a control); a pane opened on page load leaves focus where it is.
 */
export function focusPane() {
  const active = document.activeElement;
  if (paneBeside() && (!active || active === document.body)) return;
  const pane = $("#pane");
  const target = $("h2[tabindex='-1'], h1[tabindex='-1']", pane) ?? focusables(pane)[0];
  target?.focus({ preventScroll: true });
}

document.addEventListener("pane-reopen", () => open && focusPane());

export function hidePane() {
  if (!open) return;
  const { opener, returnTo, removeLayer } = open;
  open = null;
  removeLayer();
  document.body.classList.remove("pane-open");
  if (!paneBeside() || $("#pane").contains(document.activeElement)) returnFocus(opener, returnTo);
}

/** The pane's scrolling content. A pane view mounts paneScroll(...) and, optionally, paneActions(...). */
export const paneScroll = (...children) => h("div", { class: "pane-scroll" }, children);

/** The sticky action bar under the scroll area: buttons side by side, the note centred below. */
export const paneActions = ({ buttons = [], note }) =>
  h(
    "div",
    { class: "pane-actions", id: "pane-actions" },
    buttons.length > 0 && h("div", { class: "btns" }, buttons),
    note && h("p", { class: "note" }, note),
  );

/** Builds the pane frame once: top bar and body. The top bar gains a hairline once the body scrolls. */
export function mountPane() {
  const top = h("div", { class: "pane-top" });
  const body = h("div", { class: "pane-body" });
  body.addEventListener("scroll", (event) => top.classList.toggle("scrolled", event.target.scrollTop > 4), {
    capture: true,
    passive: true,
  });
  mount($("#pane"), top, body);
}
