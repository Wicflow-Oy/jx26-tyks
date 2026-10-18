// The organism mix of the recent window and the year: a stacked bar in greys and the counts with their flags
// (MRSA, ESBL). The list under each bar carries the numbers in text, so the bar itself is decorative.

import { mk } from "../../components/marker.js";
import { h } from "../../dom.js";
import { int } from "../../format.js";
import { t } from "../../i18n.js";

const TONES = 8; // .tone-0 … .tone-7 in ward.css, darkest first

export function organismMix(ward) {
  const windows = ward.windows ?? [];
  if (!windows.some((w) => (ward.organisms?.[w.key] ?? []).length)) return null;
  return h(
    "section",
    { class: "group", "aria-labelledby": "h-mix" },
    h("h2", { class: "sec-h", id: "h-mix" }, t("ward.mix.title")),
    h(
      "div",
      { class: "card mix" },
      windows.map((w) => mixRow(w, ward.organisms?.[w.key] ?? [])),
    ),
    h("p", { class: "group-foot" }, t("ward.mix.foot")),
  );
}

function mixRow(window, list) {
  const total = list.reduce((sum, o) => sum + (o.n ?? 0), 0);
  const tone = (i) => `tone-${Math.min(i, TONES - 1)}`;
  return h(
    "div",
    { class: "mixrow" },
    h(
      "div",
      { class: "h" },
      h("b", null, window.label),
      h("span", null, mk(`mix-${window.key}`, t("ward.mix.isolates", { n: int(total) }))),
    ),
    h(
      "div",
      { class: "stack", "aria-hidden": "true" },
      list.map((o, i) => h("i", { class: tone(i), style: { flex: String(o.n ?? 0) } })),
    ),
    h(
      "div",
      { class: "mixlist" },
      list.map((o, i) =>
        h(
          "span",
          null,
          h("span", { class: ["sw", tone(i)] }),
          o.label,
          " ",
          h("b", null, int(o.n ?? 0)),
          Object.entries(o.flags ?? {}).map(([flag, n]) => [" · ", flagName(flag), " ", h("b", null, int(n))]),
        ),
      ),
    ),
  );
}

const flagName = (flag) => {
  const name = t(`ward.flag.${flag}`);
  return name === `ward.flag.${flag}` ? flag.toUpperCase() : name;
};
