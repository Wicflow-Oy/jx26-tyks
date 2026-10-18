// The ward doctor's sidebar: My ward, Trend and the order form, then the open signals on the doctor's unit
// ("On ICU this week"), which open infection control's case file.

import { tile } from "../components/badges.js";
import { t } from "../i18n.js";
import { titleOffUnit, unitItems } from "../signals.js";
import { navigate, openPane, paramsFor } from "../state.js";
import { group, sideItem, sideNote } from "./parts.js";

/** data: { brief, drugs } (brief null while loading). The unit is My ward's, also while the order form is open. */
export function doctorGroups(state, { brief, drugs = [] }) {
  const ward = state.route === "ward" ? state.params.ward : paramsFor("ward").ward;
  const drug = state.pane?.kind === "trend" ? state.pane.id : state.params.drug;
  const drugLabel = drug && drugs.find((d) => d.drug === drug)?.label;
  const onWard = brief && ward ? unitItems(brief, ward) : [];
  const openTrend = () =>
    state.route === "ward"
      ? openPane("trend", drug ?? "")
      : navigate("ward", { pane: { kind: "trend", id: drug ?? "" } });

  return [
    group(t("shell.side.doctor"), [
      sideItem({
        icon: "ward",
        label: t("shell.nav.ward"),
        count: ward ?? "",
        current: state.route === "ward" && state.pane?.kind !== "trend",
        onClick: () => navigate("ward"),
      }),
      sideItem({
        icon: "trend",
        label: drugLabel ? t("shell.nav.trendOf", { drug: drugLabel }) : t("shell.nav.trend"),
        current: state.pane?.kind === "trend",
        onClick: openTrend,
      }),
      sideItem({
        icon: "order",
        label: t("shell.nav.order"),
        current: state.route === "order",
        onClick: () => navigate("order"),
      }),
    ]),
    ward &&
      group(
        t("shell.side.onWard", { ward }),
        brief && onWard.length === 0
          ? sideNote(t("shell.side.noSignals"))
          : onWard.map((item) =>
              sideItem({
                slot: tile(item.priority, "xs"),
                label: titleOffUnit(item),
                onClick: () => navigate("brief", { params: {}, pane: { kind: "case", id: item.id } }),
              }),
            ),
      ),
  ];
}
