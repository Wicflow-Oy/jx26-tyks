// My ward, the ward doctor's home: scope bar, banners, the lead sentence, the coverage table on one shared axis,
// how to read a row, the organism mix and the footer, for one unit and the global as-of week (GET /api/my-ward).
// The parts live in views/ward/; this file fetches and lays them out.

import { get, isAbort } from "../api.js";
import { prototypeCapsule } from "../components/badges.js";
import { paneBeside } from "../components/pane.js";
import { errorState, loadingState } from "../components/states.js";
import { h, mount } from "../dom.js";
import { dateDay, dateLong } from "../format.js";
import { t } from "../i18n.js";
import { pageHead } from "../shell.js";
import { loadBrief } from "../signals.js";
import { selectDefaultPane, setParams } from "../state.js";
import { unitBanners } from "./ward/banner.js";
import { coverageSection } from "./ward/coverage.js";
import { leadParagraph, leadRow } from "./ward/lead.js";
import { organismMix } from "./ward/organism-mix.js";
import { readKey } from "./ward/read-key.js";
import { scopeBar } from "./ward/scope-bar.js";
import { DEFAULT_SPECIMEN, defaultWard, labelIn, scopeExtras, trendQuery, wardQuery } from "./ward/scope.js";
import { trendContent } from "./ward/trend-card.js";

const compact = () => matchMedia("(max-width: 1023px)").matches;
let openedWithoutWard = false; // the next render is still the page's first one (see below)

/** render(root, { state, meta, filters, signal, first, retry }): see main.js for the view contract. */
export async function render(root, { state, meta, filters, signal, first, retry }) {
  if (!state.params.ward) {
    // the URL names the doctor's ward, so the sidebar, the Trend tab and a shared link all see the same unit
    if (first) mount(root, loadingState(t("ward.loading")));
    openedWithoutWard = first;
    setParams({ ward: defaultWard(filters) });
    return;
  }
  const opening = first || openedWithoutWard;
  openedWithoutWard = false;
  const head = pageHead({ title: t("ward.title"), dateline: dateline(state, meta, filters) });
  const bar = scopeBar({ state, filters });
  if (first) mount(root, head, bar, loadingState(t("ward.loading")));

  let ward;
  let brief;
  try {
    [ward, brief] = await Promise.all([
      get("/api/my-ward", wardQuery(state, filters), { signal }),
      // the brief links a signal to infection control's alert; without it the banner simply has no alert clause
      loadBrief(state.asOf, { signal }).catch((error) => {
        if (isAbort(error)) throw error;
        return null;
      }),
    ]);
  } catch (error) {
    if (isAbort(error)) throw error;
    mount(
      root,
      head,
      bar,
      errorState({ title: t("ward.error", { date: dateLong(state.asOf) }), error, onRetry: retry }),
    );
    return;
  }

  const line = ward.local_setting?.value ?? null;
  const lead = leadRow(ward);
  const card = compact() && lead ? h("section", { class: "trendcard", "aria-label": t("ward.trend.card") }) : null;
  mount(
    root,
    head,
    bar,
    unitBanners({ ward, brief, asOf: state.asOf }),
    leadParagraph(ward, line),
    card,
    coverageSection({ ward, filters, line }),
    readKey(ward, line),
    organismMix(ward),
    h("footer", { class: "foot" }, ward.footer && h("span", null, ward.footer), prototypeCapsule()),
  );
  if (card) fillTrendCard(card, { state, meta, filters, signal, drug: lead.drug });
  else if (opening && lead && paneBeside()) selectDefaultPane("trend", lead.drug);
}

/** "Intensive care unit · blood and wound · data to Sun 29 Mar · sample dates; results ~2 days later" */
function dateline(state, meta, filters) {
  const { ward, specimen = DEFAULT_SPECIMEN } = state.params;
  const scope = [
    labelIn(filters.specimen_groups, specimen).toLocaleLowerCase(state.lang),
    ...scopeExtras(state.params, filters),
  ];
  return [
    h("b", null, labelIn(filters.wards, ward, "code")),
    ` · ${scope.join(" · ")} · `,
    t("ward.dataTo", { date: dateDay(state.asOf) }),
    " · ",
    t("shell.sampleDates", { days: meta.result_lag_days ?? 2 }),
  ];
}

/** Phones: the lead drug's trend as a card under the lead sentence (the pane holds the weekly table). */
async function fillTrendCard(card, { state, meta, filters, signal, drug }) {
  mount(card, loadingState(t("ward.trend.loading")));
  try {
    const trend = await get("/api/trend", trendQuery(state, filters, drug), { signal });
    mount(card, trendContent(trend, { meta, filters, inPane: false }));
  } catch (error) {
    if (isAbort(error)) return;
    mount(card, errorState({ title: t("ward.trend.error"), error }));
  }
}
