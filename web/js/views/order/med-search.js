// The host's medication search: an ARIA 1.2 combobox over the drug picker list. Typing filters by name or ATC
// prefix; arrows move, Enter picks, Esc closes. Leaving the field shows the picked drug again.

import { h } from "../../dom.js";
import { t } from "../../i18n.js";

let uid = 0;

/**
 * medSearch({ id, drugs: [{ drug, name, atc }], value: code, describedBy, onPick(code) })
 * → { el, input, setDrugs(drugs, value), setValue(code) }
 */
export function medSearch({ id, drugs, value, describedBy, onPick }) {
  const listId = `${id}-list-${++uid}`;
  let list = drugs;
  let current = value;
  let options = [];
  let active = -1;

  const input = h("input", {
    class: "ehr-input",
    id,
    type: "text",
    role: "combobox",
    autocomplete: "off",
    spellcheck: "false",
    "aria-autocomplete": "list",
    "aria-expanded": "false",
    "aria-controls": listId,
    "aria-describedby": describedBy,
    placeholder: t("order.form.search"),
  });
  const atc = h("span", { class: "combo-atc", "aria-hidden": "true" });
  const listbox = h("ul", { class: "combo-list", id: listId, role: "listbox", "aria-label": t("order.form.options") });
  listbox.hidden = true;

  const byCode = (code) => list.find((d) => d.drug === code);
  const show = () => {
    const drug = byCode(current);
    input.value = drug?.name ?? "";
    atc.textContent = drug?.atc ?? "";
  };

  function open(query) {
    const q = query.trim().toLocaleLowerCase();
    options = list.filter(
      (d) => !q || d.name.toLocaleLowerCase().includes(q) || (d.atc ?? "").toLocaleLowerCase().startsWith(q),
    );
    listbox.replaceChildren(
      ...options.map((d, i) =>
        h(
          "li",
          {
            id: `${listId}-${i}`,
            role: "option",
            "aria-selected": String(i === active),
            onmousedown: (event) => {
              event.preventDefault(); // keep focus in the field
              pick(d.drug);
            },
          },
          h("span", { class: "combo-check", "aria-hidden": "true" }, d.drug === current ? "✓" : ""),
          h("span", { class: "combo-name" }, d.name),
          h("span", { class: "combo-code" }, d.atc ?? ""),
        ),
      ),
    );
    if (!options.length)
      listbox.append(h("li", { class: "combo-empty", "aria-disabled": "true" }, t("order.form.noMatch")));
    listbox.hidden = false;
    input.setAttribute("aria-expanded", "true");
    highlight(Math.min(active, options.length - 1));
  }

  function close() {
    listbox.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }

  function highlight(index) {
    const items = listbox.querySelectorAll("[role=option]");
    active = items.length ? index : -1;
    items.forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
    const li = items[active] ?? null;
    if (li) {
      input.setAttribute("aria-activedescendant", li.id);
      li.scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
  }

  function pick(code) {
    close();
    const changed = code !== current;
    current = code;
    show();
    input.select(); // the next keystrokes search again instead of extending the name
    if (changed) onPick(code);
  }

  input.addEventListener("focus", () => input.select());
  // a click on the closed field selects the name, so the next keystrokes search again instead of extending it
  // (selecting on mouseup, because the browser places the caret after mousedown)
  input.addEventListener("mouseup", (event) => {
    if (!listbox.hidden) return;
    event.preventDefault();
    input.select();
    open("");
  });
  input.addEventListener("input", () => {
    active = 0;
    open(input.value);
  });
  input.addEventListener("blur", () => {
    close();
    show();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (listbox.hidden) open("");
      const step = event.key === "ArrowDown" ? 1 : -1;
      highlight(Math.max(0, Math.min(options.length - 1, active + step)));
    } else if (event.key === "Enter") {
      const choice = options[active] ?? (options.length === 1 ? options[0] : null);
      if (!listbox.hidden && choice) {
        event.preventDefault();
        pick(choice.drug);
      }
    } else if (event.key === "Escape" && !listbox.hidden) {
      event.preventDefault();
      event.stopPropagation(); // the list closes; no layer behind it does
      close();
      show();
    }
  });

  show();
  return {
    el: h("div", { class: "combo" }, input, atc, listbox),
    input,
    setDrugs(next, code) {
      list = next;
      current = code;
      show();
    },
    setValue(code) {
      current = code;
      show();
    },
  };
}
