// The sticky action bar: one primary (Approve alert / Approve again / done "Alert active · until 23 Mar") and one
// bordered (Draft heads-up to ED / Open heads-up draft / done "Approved · not sent"), then the note that nothing
// is sent. Lab checks, data completeness and the quiet line get the note only (DESIGN §9).

import { button } from "../../components/buttons.js";
import { paneActions } from "../../components/pane.js";
import { toast } from "../../components/toast.js";
import { dateShort } from "../../format.js";
import { t } from "../../i18n.js";
import { isOpen } from "../../signals.js";
import { openHeadsUp } from "./heads-up.js";
import { approveAlert } from "./writes.js";

const NOTE_ONLY = ["expert_rule", "completeness", "quiet"];

/** ctx: { item, asOf, lang, alert: alertState(...), headsUp, wardLabel, appName }. A write re-renders the case (main.js). */
export function caseActions(ctx) {
  const { item, alert, headsUp, appName } = ctx;
  if (NOTE_ONLY.includes(item.kind) || !isOpen(item))
    return paneActions({ note: t("case.actions.noteOnly", { app: appName }) });

  const approve =
    alert.state === "active"
      ? button({
          label: t("case.actions.active", { date: dateShort(alert.alert.expires_on) }),
          variant: "done",
          large: true,
          attrs: { id: "case-approve" },
        })
      : button({
          label: t(alert.state === "expired" ? "case.actions.again" : "case.actions.approve"),
          variant: "primary",
          large: true,
          attrs: { id: "case-approve" },
          onClick: () => runWrite(approve, () => approveAgain(ctx)),
        });
  const draft = button({
    label: headsUp
      ? t(headsUp.status === "approved" ? "case.actions.huApproved" : "case.actions.huOpen")
      : t("case.actions.huDraft"),
    icon: headsUp?.status === "approved" ? "ok" : null,
    large: true,
    attrs: { id: "case-draft", "aria-haspopup": "dialog", dataset: { draft: item.id } },
    onClick: () => runWrite(draft, () => openHeadsUp(ctx)),
  });
  return paneActions({ buttons: [approve, draft], note: t("case.actions.note") });
}

/** Approve, or approve again with the expired alert's units and drugs (so it covers what it covered before). */
async function approveAgain({ item, asOf, alert }) {
  const previous = alert.state === "expired" ? alert.alert : null;
  const result = await approveAlert({ item, asOf, wards: previous?.wards ?? [], drugs: previous?.drugs ?? [] });
  toast(t("case.toast.approved", { date: dateShort(result.expires_on) }));
}

/** One write at a time per button; a failure says why in a toast and changes nothing on screen. */
async function runWrite(el, fn) {
  if (el.getAttribute("aria-busy") === "true") return;
  el.setAttribute("aria-busy", "true");
  try {
    await fn();
  } catch (error) {
    toast(error.message);
  } finally {
    el.removeAttribute("aria-busy");
  }
}
