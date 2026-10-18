// The check at signing, shown only when the backend's order-sign context is a warning: a compact sheet over the
// order. Previous results first, then what is happening, this drug's numbers and the neutral sentence. The doctor
// keeps the order with a reason, goes back to edit it, or opens My ward to look at every drug. It never blocks:
// closing it leaves the order an unsigned draft.

import { tile } from "../../components/badges.js";
import { button } from "../../components/buttons.js";
import { openSheet } from "../../components/sheet.js";
import { $, h } from "../../dom.js";
import { t } from "../../i18n.js";
import { drugNumbers } from "./drug-numbers.js";
import {
  ask,
  detailsLink,
  drugName,
  happeningSection,
  headline,
  notesSection,
  smallPrint,
  sourceLabel,
} from "./parts.js";
import { previousTable } from "./previous-results.js";
import { logFeedback } from "./requests.js";

/**
 * openSignSheet(ctx, { appName, filters, draft, onKeep(reason), onEdit(), onCancel() })
 * Exactly one of the three callbacks runs; following "All drugs on My ward" leaves the order as a draft.
 */
export function openSignSheet(ctx, { appName, filters, draft, onKeep, onEdit, onCancel }) {
  logFeedback(draft, ctx, "shown");
  let answered = false;
  const answer = (fn) => {
    answered = true;
    sheet.close();
    fn();
  };

  const drug = drugName(ctx).toLocaleLowerCase();
  const keepLabel = ctx.actions?.keep?.label ?? t("order.sign.keep", { drug });
  const reasons = ctx.actions?.keep?.reasons ?? ctx.actions?.keep_reasons ?? [];
  const keep = keepBox({
    label: keepLabel,
    drug,
    reasons,
    onConfirm: (reason) => {
      logFeedback(draft, ctx, "keep", { reason });
      answer(() => onKeep(reason));
    },
  });
  const keepToggle = button({
    label: t("order.sign.keepMore", { label: keepLabel }),
    large: true,
    attrs: { "aria-controls": keep.el.id },
    // the reasons and "Keep … and sign" take its place, scrolled into view above the sheet's sticky footer
    onClick: () => {
      keep.el.hidden = false;
      keepToggle.hidden = true;
      keep.focus();
      const foot = $(".sheet-foot", sheet.el);
      sheet.el.style.scrollPaddingBottom = `${foot?.offsetHeight ?? 0}px`;
      keep.el.scrollIntoView({ block: "nearest" });
    },
  });
  const edit = button({
    label: ctx.actions?.edit?.label ?? t("order.sign.edit"),
    large: true,
    onClick: () => {
      logFeedback(draft, ctx, "edit");
      answer(onEdit);
    },
  });
  const details = detailsLink(ctx, {
    onFollow: () => {
      logFeedback(draft, ctx, "details");
      answered = true;
      sheet.close();
    },
  });

  const sheet = openSheet({
    eyebrow: [tile("P2", "xs"), h("span", null, t("order.sign.kicker"))],
    title: headline(ctx),
    body: [
      h("p", { class: "sw-meta" }, sourceLabel(appName, ctx)),
      previousTable(ctx, filters, "h3"),
      happeningSection(ctx, "h3"),
      drugNumbers(ctx, filters, "h3"),
      notesSection(ctx, "h3"),
      h("p", { class: "sw-ask" }, ask(ctx)),
      keep.el,
      smallPrint(ctx),
    ],
    note: details,
    actions: [edit, keepToggle],
    onClose: () => {
      sheet.el.classList.remove("order-sheet");
      sheet.el.style.scrollPaddingBottom = "";
      if (!answered) onCancel();
    },
  });
  sheet.el.classList.add("order-sheet");
  // focus lands on the title, not a button, so a reflexive Enter cannot answer the check
  const title = $("#sheet-title", sheet.el);
  title.tabIndex = -1;
  requestAnimationFrame(() => title.isConnected && title.focus());
}

/** Keep with a reason: one radio per reason the API lists (the backend accepts only those), then "Keep X and sign". */
function keepBox({ label, drug, reasons, onConfirm }) {
  const message = h("p", { class: "keep-msg", role: "status" });
  const radios = reasons.map((reason, i) =>
    h("input", {
      type: "radio",
      name: "keep-reason",
      id: `keep-${i}`,
      value: reason,
      onchange: () => (message.textContent = ""),
    }),
  );
  const el = h(
    "fieldset",
    { class: "keep", id: "keep-box" },
    h("legend", { class: "keep-q" }, t("order.sign.why", { drug })),
    h(
      "div",
      { class: "keep-opts" },
      reasons.map((reason, i) => h("label", { class: "keep-opt", for: `keep-${i}` }, radios[i], reason)),
    ),
    h(
      "div",
      { class: "keep-row" },
      button({
        label: t("order.sign.keepSign", { label }),
        variant: "primary",
        large: true,
        onClick: () => {
          const chosen = radios.find((r) => r.checked);
          if (chosen) onConfirm(chosen.value);
          else {
            message.textContent = t("order.sign.chooseReason");
            radios[0]?.focus();
          }
        },
      }),
      message,
    ),
  );
  el.hidden = true;
  return { el, focus: () => radios[0]?.focus() };
}
