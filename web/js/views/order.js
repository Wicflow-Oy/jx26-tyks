// The doctor's order view (CONTRACTS §7b): a stand-in for the hospital's own order entry with our layer running on
// top of it, the way an EHR would call it through CDS Hooks (order-select while the order is drafted, order-sign at
// signing). The patient list is GET /api/demo/scenarios; ?patient=<scenario key> opens one. The parts live in
// views/order/; this file fetches and lays them out.

import { get, isAbort } from "../api.js";
import { prototypeCapsule } from "../components/badges.js";
import { emptyState, errorState, loadingState } from "../components/states.js";
import { mondayOf } from "../dates.js";
import { h, mount } from "../dom.js";
import { dateDay, dateLong } from "../format.js";
import { t } from "../i18n.js";
import { pageHead } from "../shell.js";
import { setAsOf, setParams } from "../state.js";
import { patientBanner } from "./order/banner.js";
import { composer } from "./order/composer.js";
import { draftFor } from "./order/draft.js";
import { chartTabs, ehrFrame } from "./order/ehr-frame.js";
import { orderDrugs, patientHistory } from "./order/requests.js";
import { signedList } from "./order/signed-list.js";
import { unitName, worklist } from "./order/worklist.js";

let shownPatient = ""; // the patient the page shows, so a week change can tell "opened" from "moved away"

/** render(root, { state, meta, filters, signal, first, retry }): see main.js for the view contract. */
export async function render(root, { state, meta, filters, signal, first, retry }) {
  const head = pageHead({ title: t("order.title"), dateline: dateline(state, meta) });
  if (first) mount(root, head, loadingState(t("order.loading")));

  let scenarios;
  let scenario = null;
  let history = null;
  let drugs = [];
  try {
    // each demo visit carries its own week, so the list does not follow the global as-of
    const list = await get("/api/demo/scenarios", {}, { asOf: false, signal });
    scenarios = Array.isArray(list) ? list.filter((s) => s?.key && s?.patient_id && s?.unit) : [];
    scenario = scenarios.find((s) => s.key === state.params.patient) ?? null;
    // a visit belongs to its week: opening a patient (by link or list) moves there, and a replay step that moves
    // the open patient's page to another week closes the patient
    if (scenario && scenario.as_of !== state.asOf) {
      if (first || scenario.key !== shownPatient) setAsOf(scenario.as_of);
      else setParams({ patient: null });
      return;
    }
    shownPatient = scenario?.key ?? "";
    if (scenario) {
      const draft = draftFor(scenario);
      [history, drugs] = await Promise.all([
        patientHistory(scenario.patient_id, { signal }),
        draft.indication ? orderDrugs(draft.indication, { signal }) : [],
      ]);
    }
  } catch (error) {
    if (isAbort(error)) throw error;
    mount(root, head, errorState({ title: t("order.error"), error, onRetry: retry }));
    return;
  }

  const appName = meta.app_name;
  const visit = mondayOf(state.asOf);
  let list = worklist({ scenarios, current: scenario, filters });
  // a signed order leaves the patient's "Draft: …" line in the list
  const onSigned = () => {
    const fresh = worklist({ scenarios, current: scenario, filters });
    list.replaceWith(fresh);
    list = fresh;
  };
  const body = h(
    "div",
    { class: "ehr-body" },
    list,
    scenario
      ? chart({ scenario, history, drugs, state, meta, filters, appName, onSigned })
      : h("div", { class: "chart chart-empty" }, emptyState(t("order.ehr.pick"), null)),
  );
  mount(
    root,
    head,
    ehrFrame({
      user: meta.roles?.find((r) => r.key === "ward_doctor")?.label,
      date: dateLong(visit),
      body,
      status: scenario ? [unitName(scenario.unit, filters), " · ", dateLong(visit)] : [],
      note: meta.cds_hooks?.note,
    }),
    h("footer", { class: "foot" }, h("span", null, t("order.footer")), prototypeCapsule()),
  );
  showCurrentPatient(list);
}

/** On a narrow window the patient list scrolls sideways; the open patient is scrolled into it. */
function showCurrentPatient(list) {
  const row = list.querySelector('[aria-current="true"]');
  const scroller = row?.closest(".wl-list");
  if (!row || scroller.scrollWidth <= scroller.clientWidth) return;
  scroller.scrollLeft += row.getBoundingClientRect().left - scroller.getBoundingClientRect().left - 16;
}

/** The open patient's chart on the Orders tab: banner, the order form with our layer, and this visit's orders. */
function chart({ scenario, history, drugs, state, meta, filters, appName, onSigned }) {
  const draft = draftFor(scenario);
  const signed = h("div", { class: "side" }, signedList(draft));
  return h(
    "div",
    { class: "chart" },
    patientBanner({ scenario, history, filters, asOf: state.asOf }),
    chartTabs(),
    h(
      "div",
      { class: "orders" },
      composer({
        scenario,
        asOf: state.asOf,
        meta,
        filters,
        appName,
        draft,
        drugs,
        onSigned: () => {
          mount(signed, signedList(draft));
          onSigned();
        },
      }),
      signed,
    ),
  );
}

/** "data to Sun 15 Mar · sample dates; results ~2 days later" */
const dateline = (state, meta) => [
  t("order.dataTo", { date: dateDay(state.asOf) }),
  " · ",
  t("shell.sampleDates", { days: meta.result_lag_days ?? 2 }),
];
