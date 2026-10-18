// Banners on My ward. First the highest-priority open P1 or P2 signal touching this unit, with infection
// control's alert while its approval is active; then any active alert or policy line on the unit (from the
// my-ward response) that the signal banner does not already carry, in the API's own words.

import { alertState } from "../../alerts.js";
import { tile } from "../../components/badges.js";
import { linkButton } from "../../components/buttons.js";
import { mk } from "../../components/marker.js";
import { h } from "../../dom.js";
import { dateShort, int } from "../../format.js";
import { t } from "../../i18n.js";
import { byPriority, findItem, isOpen, signalTitle } from "../../signals.js";
import { navigate } from "../../state.js";

const BANNER_PRIORITIES = ["P1", "P2"];

/** ward: the my-ward response · brief: the week's brief (or null), which links each signal to its alert. */
export function unitBanners({ ward, brief, asOf }) {
  const open = (ward.signals ?? []).filter((item) => isOpen(item) && BANNER_PRIORITIES.includes(item.priority));
  const top = byPriority(open)[0];
  const linked = top && alertState(findItem(brief, top.id) ?? top, asOf);
  const alert = linked?.state === "active" ? linked.alert : null;
  const rest = (ward.banners ?? []).filter((b) => b.id !== alert?.id && !(top && b.signal_id === top.id));
  if (!top && !rest.length) return null;
  return h(
    "section",
    { class: "banners", "aria-label": t("ward.banner.label") },
    top && signalBanner(top, alert),
    rest.map(apiBanner),
  );
}

function signalBanner(item, alert) {
  const title = signalTitle(item);
  const slots = item.slots ?? {};
  const hasRange = slots.n_patients != null && slots.expected_low != null && slots.expected_high != null;
  const facts = [
    hasRange &&
      mk(
        "banner-patients",
        t("ward.banner.patients", {
          n: int(slots.n_patients),
          low: int(slots.expected_low),
          high: int(slots.expected_high),
        }),
      ),
    item.advice,
    alert && t("ward.banner.alertActive", { on: dateShort(alert.approved_on), until: dateShort(alert.expires_on) }),
  ].filter(Boolean);
  return h(
    "div",
    { class: ["banner", item.priority] },
    tile(item.priority),
    h(
      "p",
      { class: "t" },
      h("b", null, title),
      facts.length > 0 &&
        h(
          "span",
          null,
          facts.flatMap((fact, i) => (i ? [" · ", fact] : [fact])),
        ),
    ),
    caseLink(item.id, title),
  );
}

/** An active alert or policy line the API sent as a banner; its text is the API's sentence, unchanged. */
function apiBanner(banner) {
  const name = t(banner.kind === "policy" ? "ward.banner.policy" : "ward.banner.alert");
  return h(
    "div",
    { class: "banner" },
    tile(banner.kind === "policy" ? "line" : "info"),
    h("p", { class: "t" }, h("b", null, name), h("span", null, banner.text)),
    banner.signal_id && caseLink(banner.signal_id, name),
  );
}

/** "Case file ›": the infection-control case file of the signal, in the brief. */
function caseLink(id, title) {
  return linkButton({
    label: t("ward.banner.caseFile"),
    onClick: () => navigate("brief", { pane: { kind: "case", id } }),
    attrs: { class: "linkbtn case-link", "aria-label": t("ward.banner.caseFileOf", { title }) },
  });
}
