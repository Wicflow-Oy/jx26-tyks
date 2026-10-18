// The host's form controls: a labelled field with its "Required" line, a select and a text input, in the plain
// style of the simulated hospital system. Values stay in the order draft through the callbacks.

import { h } from "../../dom.js";
import { t } from "../../i18n.js";

/** A labelled host field; required ones carry an asterisk (spoken as "required") and a "Required" error line. */
export function field(id, key, control, { required = false, hint = "" } = {}) {
  return h(
    "div",
    { class: "fld" },
    h(
      "label",
      { for: id },
      t(`order.form.${key}`),
      required &&
        h(
          "span",
          { class: "req" },
          h("span", { "aria-hidden": "true" }, "*"),
          h("span", { class: "sr" }, ` ${t("order.form.requiredMark")}`),
        ),
      hint && h("span", { class: "hint" }, ` ${hint}`),
    ),
    control,
    required && h("span", { class: "err-msg", id: `${id}-err` }, t("order.form.required")),
  );
}

export function select(id, options, value, onChange, required = false) {
  const el = h(
    "select",
    {
      class: "ehr-select",
      id,
      "aria-describedby": required ? `${id}-err` : null,
      onchange: (e) => onChange(e.target.value),
    },
    options.map((o) => h("option", { value: o.value }, o.label)),
  );
  el.value = value ?? "";
  return el;
}

export function input(id, value, onInput, { inputmode, required = false }) {
  const el = h("input", {
    class: "ehr-input num",
    id,
    type: "text",
    inputmode,
    "aria-describedby": required ? `${id}-err` : null,
    oninput: (e) => onInput(e.target.value),
  });
  el.value = value ?? "";
  return el;
}

/** A host select's options: "Select" first, then the listed values. */
export const choices = (key) => [
  { value: "", label: t("order.form.choose") },
  ...t(key).map((v) => ({ value: v, label: v })),
];
