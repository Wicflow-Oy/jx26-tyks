// The infection-control sidebar: Brief and Replay; this session's approved alerts and heads-up drafts in the as-of
// week, each opening its case file; and the nine units with their state this week.

import { alertState } from "../alerts.js";
import { tile } from "../components/badges.js";
import { toast } from "../components/toast.js";
import { $, reducedMotion } from "../dom.js";
import { dateShort } from "../format.js";
import { t } from "../i18n.js";
import { briefItems, isSignal, signalTitle, unitItems, unitStatus } from "../signals.js";
import { navigate, openPane } from "../state.js";
import { group, sideItem, sideNote } from "./parts.js";

/** data: { brief, alerts } (null while loading or when a request failed). */
export function icGroups(state, { brief, alerts }, meta) {
  const items = briefItems(brief);
  const units =
    brief?.map?.units ?? (meta.wards ?? []).map((w) => ({ ward: w.code, label: w.label, state: null, signal_ids: [] }));
  return [
    group(t("shell.side.brief"), [
      sideItem({
        icon: "brief",
        label: t("shell.nav.brief"),
        count: brief ? items.filter(isSignal).length : "",
        current: state.route === "brief",
        onClick: () => (state.route === "brief" ? scrollTo({ top: 0, behavior: motion() }) : navigate("brief")),
      }),
      sideItem({ icon: "replay", label: t("shell.nav.replay"), onClick: () => $("#rail input")?.focus() }),
    ]),
    brief && sessionGroups(items, state.asOf, alerts ?? []),
    group(
      t("shell.side.units"),
      units.map((unit) => unitItem(brief, unit, meta)),
    ),
  ];
}

/** Approved alerts (active or expired) and heads-up drafts, from the brief's items and GET /api/alerts. */
function sessionGroups(items, asOf, alerts) {
  const approved = items
    .map((item) => ({ item, alert: alertState(item, asOf, alerts) }))
    .filter(({ alert }) => alert.state !== "none");
  const drafts = items.filter((item) => item.heads_up);
  const entry = (item, state) =>
    sideItem({
      slot: tile(item.priority, "xs"),
      label: signalTitle(item),
      count: state,
      onClick: () => openPane("case", item.id),
    });
  return [
    group(
      t("shell.side.alerts"),
      approved.length
        ? approved.map(({ item, alert }) =>
            entry(
              item,
              t(alert.state === "active" ? "shell.side.until" : "shell.side.expired", {
                date: dateShort(alert.alert.expires_on),
              }),
            ),
          )
        : sideNote(t("shell.side.noAlerts")),
    ),
    group(
      t("shell.side.drafts"),
      drafts.length
        ? drafts.map((item) =>
            entry(item, t(item.heads_up.status === "approved" ? "shell.side.notSent" : "shell.side.draft")),
          )
        : sideNote(t("shell.side.noDrafts")),
    ),
  ];
}

function unitItem(brief, unit, meta) {
  const label = unit.label ?? meta.wards?.find((w) => w.code === unit.ward)?.label ?? unit.ward;
  const status = unit.state ? unitStatus(brief, unit) : { glyph: null, word: "" };
  const count = unit.signal_ids?.length || "";
  return sideItem({
    slot: status.glyph && tile(status.glyph, "xs"),
    code: unit.ward,
    label: status.word,
    count,
    name: [label, status.word, count && t("shell.unit.count", { n: count })].filter(Boolean).join(", "),
    onClick: () => showUnit(brief, unit, label),
  });
}

/** The unit's tile on the brief's ward map if it is there, else its top signal's case file, else a quiet note. */
function showUnit(brief, unit, label) {
  const tileEl = $(`#main [data-unit="${CSS.escape(unit.ward)}"]`);
  if (tileEl) {
    tileEl.scrollIntoView({ block: "center", behavior: motion() });
    tileEl.focus({ preventScroll: true });
    return;
  }
  const top = unitItems(brief, unit.ward)[0];
  if (top) openPane("case", top.id);
  else toast(t("shell.toast.unitQuiet", { unit: label }));
}

const motion = () => (reducedMotion() ? "auto" : "smooth");
