// Our layer inside the host's order form, directly under Medication. Every indication or drug change asks the
// backend for the order context at "select" (the CDS Hooks order-select moment) and redraws in place; an older
// answer that arrives late is dropped. Screen readers hear one short line per change, never the whole card.

import { isAbort } from "../../api.js";
import { tile } from "../../components/badges.js";
import { h, mount } from "../../dom.js";
import { t } from "../../i18n.js";
import { layerView } from "./layer-view.js";
import { headline } from "./parts.js";
import { logFeedback, orderContext } from "./requests.js";

const FLAGS = new Set(["info", "warning"]);

/** orderLayer({ appName, filters }) → { el, update({ scenario, asOf, draft }) } */
export function orderLayer({ appName, filters }) {
  const slot = h("div", { class: "sw-slot" });
  const live = h("p", { class: "sr", "aria-live": "polite" });
  let run = null;
  let drawn = false;

  async function update({ scenario, asOf, draft }) {
    run?.abort();
    if (!draft.indication || !draft.drug) {
      slot.replaceChildren();
      live.textContent = "";
      drawn = false;
      return;
    }
    const controller = (run = new AbortController());
    slot.setAttribute("aria-busy", "true");
    // a redraw keeps the old card until the new one is ready; only the first check shows a waiting chip
    if (!drawn) mount(slot, statusChip("P3", t("order.layer.checking")));
    let ctx;
    try {
      const { indication, drug } = draft;
      ctx = await orderContext({ scenario, asOf, indication, drug, stage: "select", signal: controller.signal });
    } catch (error) {
      if (isAbort(error) || controller.signal.aborted) return;
      slot.removeAttribute("aria-busy");
      mount(slot, statusChip("info", t("order.layer.error", { app: appName })));
      drawn = false;
      return;
    }
    if (controller.signal.aborted) return;
    slot.removeAttribute("aria-busy");
    const onDetails = () => FLAGS.has(ctx.state) && logFeedback(draft, ctx, "details");
    mount(slot, layerView(ctx, { appName, filters, draft, onDetails }));
    drawn = true;
    live.textContent = `${appName}: ${FLAGS.has(ctx.state) ? headline(ctx) : ctx.chip}`;
    if (FLAGS.has(ctx.state)) logFeedback(draft, ctx, "shown");
  }

  const el = h("section", { class: "sw-layer", "aria-label": t("order.layer.label", { app: appName }) }, slot, live);
  return { el, update };
}

const statusChip = (kind, text) =>
  h("div", { class: "sw-chips" }, h("p", { class: "sw-chip" }, tile(kind, "sm"), h("span", null, text)));
