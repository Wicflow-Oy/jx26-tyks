// The host's "New medication order" form with our layer under Medication. Signing runs the host's own checks
// first (required fields), then asks the backend for the order-sign context: a warning opens the check sheet,
// anything else signs straight away. If the check cannot load, the order still signs: the layer never blocks.

import { mondayOf } from "../../dates.js";
import { h } from "../../dom.js";
import { dateFull } from "../../format.js";
import { t } from "../../i18n.js";
import { resetOrder } from "./draft.js";
import { choices, field, input, select } from "./form-fields.js";
import { orderLayer } from "./layer.js";
import { medSearch } from "./med-search.js";
import { drugName } from "./parts.js";
import { logFeedback, orderContext, orderDrugs } from "./requests.js";
import { openSignSheet } from "./sign-sheet.js";

/**
 * composer({ scenario, asOf, meta, filters, appName, draft, drugs, onSigned }) → element
 * drugs: the picker list for the draft's indication. onSigned() redraws the host's list of signed orders.
 */
export function composer({ scenario, asOf, meta, filters, appName, draft, drugs, onSigned }) {
  let list = drugs;
  const layer = orderLayer({ appName, filters });
  const refresh = () => layer.update({ scenario, asOf, draft });

  const indicationOptions = meta.indications.map((i) => ({ value: i.key, label: i.label }));
  const indication = select(
    "ord-ind",
    [{ value: "", label: t("order.form.indicationPick") }, ...indicationOptions],
    draft.indication,
    async (value) => {
      draft.indication = value;
      list = value ? await orderDrugs(value).catch(() => []) : [];
      // a drug the picker does not offer for this indication leaves the order
      if (!list.some((d) => d.drug === draft.drug)) draft.drug = "";
      med.setDrugs(list, draft.drug);
      refresh();
    },
    true,
  );
  const med = medSearch({
    id: "ord-med",
    drugs: list,
    value: draft.drug,
    describedBy: "ord-med-err",
    onPick: (code) => {
      draft.drug = code;
      // a new medication starts its dosing again; nothing is carried over or suggested
      Object.assign(draft, { dose: "", route: "", frequency: "" });
      for (const control of [dose, route, frequency]) control.value = "";
      clearErrors();
      refresh();
    },
  });
  const dose = input("ord-dose", draft.dose, (v) => (draft.dose = v), { inputmode: "decimal", required: true });
  const units = t("order.form.doseUnits");
  const unitOptions = units.map((u) => ({ value: u, label: u }));
  const doseUnit = select("ord-unit", unitOptions, draft.doseUnit || units[0], (v) => (draft.doseUnit = v));
  doseUnit.setAttribute("aria-label", t("order.form.doseUnit"));
  const route = select("ord-route", choices("order.form.routes"), draft.route, (v) => (draft.route = v), true);
  const frequency = select(
    "ord-freq",
    choices("order.form.frequencies"),
    draft.frequency,
    (v) => (draft.frequency = v),
    true,
  );
  const duration = input("ord-dur", draft.duration, (v) => (draft.duration = v), { inputmode: "numeric" });
  const comment = h("textarea", {
    class: "ehr-input",
    id: "ord-cmt",
    rows: "2",
    oninput: (e) => (draft.comment = e.target.value),
  });
  comment.value = draft.comment;

  const required = [
    { field: indication, key: "indication", filled: () => draft.indication },
    { field: med.input, key: "medication", filled: () => draft.drug },
    { field: dose, key: "dose", filled: () => draft.dose.trim() },
    { field: route, key: "route", filled: () => draft.route },
    { field: frequency, key: "frequency", filled: () => draft.frequency },
  ];
  const message = h("p", { class: "ehr-msg", role: "status" });
  const signButton = h("button", { type: "button", class: "ehr-btn sign", onclick: sign }, t("order.form.sign"));
  const clearButton = h("button", { type: "button", class: "ehr-btn", onclick: clear }, t("order.form.clear"));

  function clearErrors() {
    for (const r of required) {
      r.field.closest(".fld").classList.remove("err");
      r.field.removeAttribute("aria-invalid");
    }
    message.classList.remove("err");
  }

  function say(text, error = false) {
    message.textContent = text;
    message.classList.toggle("err", error);
  }

  async function sign() {
    if (signButton.getAttribute("aria-busy") === "true") return; // a double click signs once
    clearErrors();
    const missing = required.filter((r) => !r.filled());
    if (missing.length) {
      for (const r of missing) {
        r.field.closest(".fld").classList.add("err");
        r.field.setAttribute("aria-invalid", "true");
      }
      say(t("order.form.missing", { fields: missing.map((r) => t(`order.form.${r.key}`)).join(", ") }), true);
      missing[0].field.focus();
      return;
    }
    signButton.setAttribute("aria-busy", "true");
    say(t("order.form.signing"));
    const ctx = await orderContext({
      scenario,
      asOf,
      indication: draft.indication,
      drug: draft.drug,
      stage: "sign",
    }).catch(() => null);
    signButton.removeAttribute("aria-busy");
    if (ctx?.state !== "warning") {
      commit(ctx ? changedNote() : t("order.orders.unchecked", { app: appName }));
      return;
    }
    say("");
    openSignSheet(ctx, {
      appName,
      filters,
      draft,
      onKeep: (reason) => commit(t("order.orders.kept", { app: appName, reason })),
      onEdit: () => {
        draft.edited = ctx;
        say(t("order.form.editing"));
        med.input.focus();
      },
      onCancel: () => say(t("order.form.notSigned")),
    });
  }

  /** "Changed from ceftriaxone after the Strainwatch check" when the doctor edited the drug after a warning. */
  function changedNote() {
    const from = draft.edited && draft.edited.drug !== draft.drug ? drugName(draft.edited) : "";
    return from ? t("order.orders.changed", { drug: from.toLocaleLowerCase(), app: appName }) : "";
  }

  function commit(note) {
    const drug = list.find((d) => d.drug === draft.drug);
    if (draft.edited && draft.edited.drug !== draft.drug) {
      logFeedback(draft, draft.edited, "change", { changed_to: draft.drug });
    }
    draft.signed.unshift({ name: drug?.name ?? draft.drug, atc: drug?.atc ?? "", dosing: dosingText(), note });
    resetOrder(draft);
    syncFields();
    refresh();
    onSigned();
    say(t("order.form.signed", { drug: drug?.name ?? "" }));
  }

  function clear() {
    resetOrder(draft);
    syncFields();
    clearErrors();
    say("");
    refresh();
  }

  function syncFields() {
    med.setValue(draft.drug);
    dose.value = draft.dose;
    doseUnit.value = units[0];
    route.value = draft.route;
    frequency.value = draft.frequency;
    duration.value = draft.duration;
    comment.value = draft.comment;
  }

  function dosingText() {
    const days = draft.duration.trim() ? `${draft.duration.trim()} ${t("order.form.days")}` : "";
    return [`${draft.dose.trim()} ${doseUnit.value}`, draft.route, draft.frequency, days].filter(Boolean).join(" · ");
  }

  const el = h(
    "section",
    { class: "ehr-panel composer", "aria-labelledby": "ord-title" },
    h(
      "div",
      { class: "ehr-ph" },
      h("h3", { id: "ord-title" }, t("order.form.title")),
      h("span", { class: "ehr-tag" }, t("order.form.draft")),
      h("span", { class: "ehr-for" }, `${scenario.patient_id} · ${scenario.unit}`),
    ),
    h(
      "form",
      { class: "ehr-form", novalidate: true, autocomplete: "off", onsubmit: (e) => e.preventDefault() },
      h(
        "div",
        { class: "frow ab" },
        field("ord-ind", "indication", indication, { required: true }),
        field("ord-med", "medication", med.el, { required: true, hint: t("order.form.medicationHint") }),
      ),
      layer.el,
      h(
        "div",
        { class: "frow dose" },
        field("ord-dose", "dose", h("div", { class: "pair" }, dose, doseUnit), { required: true }),
        field("ord-route", "route", route, { required: true }),
        field("ord-freq", "frequency", frequency, { required: true }),
        field(
          "ord-dur",
          "duration",
          h("div", { class: "pair" }, duration, h("span", { class: "u" }, t("order.form.days"))),
        ),
        field(
          "ord-start",
          "start",
          h("input", { class: "ehr-input num", id: "ord-start", readonly: true, value: dateFull(mondayOf(asOf)) }),
        ),
      ),
      field("ord-cmt", "comment", comment),
    ),
    h("div", { class: "ehr-foot" }, message, clearButton, signButton),
  );
  refresh();
  return el;
}
