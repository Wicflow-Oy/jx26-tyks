// Case file (pane, drawer or pushed page): one renderer for every signal kind. Head and meta strip, numbered
// sections (what we see, competing explanations, seen before, line list, status), method details, and the sticky
// actions. Data: GET /api/signals/{id} plus the session's alerts (expired ones included).

import { alertState, loadAlerts } from "../alerts.js";
import { get, isAbort } from "../api.js";
import { paneScroll } from "../components/pane.js";
import { emptyState, errorState, loadingState } from "../components/states.js";
import { mondayOf } from "../dates.js";
import { h, mount } from "../dom.js";
import { dateLong, dateShort, int } from "../format.js";
import { t } from "../i18n.js";
import { labels } from "../names.js";
import { findItem, isOpen, loadBrief } from "../signals.js";
import { plural } from "../text.js";
import { caseActions } from "./case/actions.js";
import { explanations } from "./case/explanations.js";
import { caseHead, metaStrip } from "./case/head.js";
import { lineList } from "./case/line-list.js";
import { methodDetails } from "./case/method.js";
import { caseSection } from "./case/parts.js";
import { seenBefore } from "./case/seen-before.js";
import { statusTimeline } from "./case/status.js";
import { whatWeSee } from "./case/what-we-see.js";

const NO_STATUS = ["expert_rule", "completeness", "quiet"];

/** render(root, { state, meta, filters, signal, first, retry }): root is the pane body; state.pane.id the signal id. */
export async function render(root, ctx) {
  const { state, signal, first, retry } = ctx;
  const heading = () => h("h2", { class: "t-title2", tabindex: "-1" }, t("case.title"));
  if (!state.pane.id) {
    mount(root, paneScroll(heading(), h("div", { class: "card" }, emptyState(t("case.none"), null))));
    return;
  }
  if (first) mount(root, paneScroll(heading(), loadingState(t("case.loading"))));

  let file, alerts;
  try {
    let brief;
    [brief, alerts] = await Promise.all([loadBrief(state.asOf, { signal }), loadAlerts({ signal })]);
    // a replay step can land on a week without this signal: say so instead of asking for it (a 404)
    if (!findItem(brief, state.pane.id)) {
      const text = t("case.notThisWeek", { date: dateLong(mondayOf(state.asOf)) });
      mount(root, paneScroll(heading(), h("div", { class: "card" }, emptyState(text, null))));
      return;
    }
    file = await get(`/api/signals/${encodeURIComponent(state.pane.id)}`, {}, { signal });
  } catch (error) {
    if (isAbort(error)) throw error;
    mount(root, paneScroll(heading(), errorState({ title: t("case.error"), error, onRetry: retry })));
    return;
  }
  mount(root, ...caseFile(file, alerts, ctx));
}

function caseFile(file, alerts, ctx) {
  const { state, meta, filters } = ctx;
  const item = file.signal ?? {};
  const asOf = state.asOf;
  const names = labels(meta, filters);
  const alert = alertState(item, asOf, [...(file.alerts ?? []), ...alerts]);
  const headsUp = (file.heads_ups ?? [])[0] ?? null;
  const parts = { item, file, asOf, names, wards: meta.wards ?? [], lagDays: meta.result_lag_days };

  const sections = [
    [t("case.sec.see"), null, whatWeSee(parts)],
    item.evidence?.competing_explanations?.hypotheses?.length && [
      t("case.sec.explanations"),
      t("case.sec.explanationsHint"),
      explanations(item.evidence.competing_explanations),
    ],
    file.seen_before?.length > 0 && [t("case.sec.seen"), t("case.sec.seenHint"), seenBefore(file.seen_before[0])],
    file.line_list?.n > 0 && [
      t("case.sec.list"),
      plural("case.sec.listHint", file.line_list.n, { n: int(file.line_list.n) }),
      lineList(parts),
    ],
    !NO_STATUS.includes(item.kind) &&
      isOpen(item) && [
        t("case.sec.status"),
        t("case.sec.statusHint", { date: dateShort(mondayOf(asOf)) }),
        statusTimeline({ item, asOf, alert, headsUp, appName: meta.app_name }),
      ],
  ].filter(Boolean);

  return [
    paneScroll(
      caseHead(item),
      metaStrip(item, file, names),
      sections.map(([title, hint, body], i) => caseSection(i + 1, title, hint, body)),
      methodDetails({ item, names }),
    ),
    caseActions({
      item,
      asOf,
      lang: state.lang,
      alert,
      headsUp,
      wardLabel: names.ward,
      appName: meta.app_name,
    }),
  ];
}
