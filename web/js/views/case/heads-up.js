// The heads-up sheet: a draft for the emergency department, narrated by the backend from the signal's computed
// numbers. The text is shown as stored (the API has no edit endpoint, so an edit could not be what is approved);
// "Approve draft" marks it approved. Nothing is ever sent.

import { button } from "../../components/buttons.js";
import { openSheet } from "../../components/sheet.js";
import { toast } from "../../components/toast.js";
import { h } from "../../dom.js";
import { t } from "../../i18n.js";
import { approveHeadsUp, draftHeadsUp } from "./writes.js";

const ED = "ED";

/**
 * Opens the sheet for an item, drafting first when there is no draft yet.
 * ctx: { item, asOf, lang, headsUp (latest or null), wardLabel(code), appName }
 */
export async function openHeadsUp(ctx) {
  let draft = ctx.headsUp;
  if (!draft) {
    draft = await draftHeadsUp({ item: ctx.item, asOf: ctx.asOf, lang: ctx.lang });
  }
  show(draft, ctx);
}

function show(draft, ctx) {
  const approved = draft.status === "approved";
  const text = h("blockquote", { class: "draft", id: "heads-up-text" }, draft.text ?? "");

  const approve = button({
    label: t("case.hu.approve"),
    variant: "primary",
    large: true,
    onClick: async () => {
      approve.setAttribute("aria-busy", "true");
      try {
        const result = await approveHeadsUp(draft.id);
        toast(t("case.toast.huApproved"));
        show({ ...draft, ...result }, ctx);
      } catch (error) {
        toast(error.message);
      } finally {
        approve.removeAttribute("aria-busy");
      }
    },
  });
  const close = () => sheet.close();

  const sheet = openSheet({
    eyebrow: t(approved ? "case.hu.eyebrowApproved" : "case.hu.eyebrowDraft"),
    title: t("case.hu.title"),
    body: [
      recipients(ctx.item.ward, ctx.wardLabel),
      h("h3", { class: "sr" }, t("case.hu.message")),
      text,
      h("p", { class: "cap" }, t("case.hu.rendered")),
    ],
    note: approved ? t("case.hu.noteApproved", { app: ctx.appName }) : t("case.hu.noteDraft"),
    actions: approved
      ? [
          button({ label: t("case.hu.done"), large: true, onClick: close }),
          button({ label: t("case.hu.notSent"), variant: "done", large: true }),
        ]
      : [button({ label: t("case.hu.keep"), large: true, onClick: close }), approve],
    returnTo: `#pane [data-draft="${CSS.escape(ctx.item.id)}"]`,
  });
}

/** To: the emergency department, and the signal's own unit when that is another one. */
function recipients(ward, wardLabel) {
  const person = (code) =>
    h("span", { class: "person" }, h("span", { class: "av", "aria-hidden": "true" }, code), wardLabel(code) ?? code);
  return h(
    "div",
    { class: "to" },
    h("span", { class: "k" }, t("case.hu.to")),
    person(ED),
    ward && ward !== ED && person(ward),
  );
}
