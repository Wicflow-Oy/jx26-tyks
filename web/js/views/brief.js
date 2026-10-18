// Monday brief, the infection-control home: the dek and count capsules, the signal sections with the P1 hero, data
// quality and the ward map. Every number and label comes from GET /api/brief (and the hero's case file).

import { isAbort } from "../api.js";
import { paneBeside } from "../components/pane.js";
import { errorState, loadingState } from "../components/states.js";
import { mondayOf } from "../dates.js";
import { h, mount } from "../dom.js";
import { dateDay, dateLong } from "../format.js";
import { t } from "../i18n.js";
import { labels } from "../names.js";
import { pageHead } from "../shell.js";
import { isDefaultPane, selectDefaultPane } from "../state.js";
import { dataQuality } from "./brief/data-quality.js";
import { countCapsules, dek } from "./brief/dek.js";
import { loadBriefPage } from "./brief/model.js";
import { signalSections } from "./brief/sections.js";
import { wardMap } from "./brief/ward-map.js";

/** render(root, { state, meta, filters, signal, first, retry }): see main.js for the view contract. */
export async function render(root, ctx) {
  const { state, meta, filters, signal, first, retry } = ctx;
  const monday = mondayOf(state.asOf);
  const head = pageHead({
    title: t("brief.title"),
    dateline: [
      h("b", null, dateLong(monday)),
      ` · ${t("brief.dataTo", { date: dateDay(state.asOf) })} · ${t("shell.sampleDates", { days: meta.result_lag_days })}`,
    ],
  });
  if (first) mount(root, head, loadingState(t("brief.loading")));

  let page;
  try {
    page = await loadBriefPage(state.asOf, { signal });
  } catch (error) {
    if (isAbort(error)) throw error;
    mount(root, head, errorState({ title: t("brief.error", { date: dateLong(monday) }), error, onRetry: retry }));
    return;
  }
  const { brief } = page;
  const names = labels(meta, filters);
  mount(
    root,
    head,
    dek(brief),
    countCapsules(brief),
    wardMap(brief, filters, page.history),
    signalSections({
      ...page,
      asOf: state.asOf,
      drugLabel: (code) => names.drug(code) ?? code,
      lagDays: meta.result_lag_days,
    }),
    dataQuality(brief, meta.wards ?? []),
    h("footer", { class: "foot" }, h("span", null, brief.footer), h("span", null, t("shell.prototype"))),
  );
  // the default selection follows each replay week until someone opens or closes a pane
  if (page.hero && paneBeside() && (first || isDefaultPane())) selectDefaultPane("case", page.hero.id);
}
