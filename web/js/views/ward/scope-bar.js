// The scope bar: pill menus Ward · Specimen · Organism | Sex · Age · Setting, built from /api/filters.
// A filter left at its default reads "All" in --ink-2; a set one reads in ink. Choosing writes the URL params.

import { pillMenu } from "../../components/menu.js";
import { h } from "../../dom.js";
import { t } from "../../i18n.js";
import { setParams } from "../../state.js";
import { DEFAULT_SPECIMEN, defaultWard } from "./scope.js";

export function scopeBar({ state, filters }) {
  const params = state.params;
  const ward = params.ward ?? defaultWard(filters);
  const specimen = params.specimen ?? DEFAULT_SPECIMEN;
  const wardSetting = filters.wards?.find((w) => w.code === ward)?.setting;

  const pill = (param, key, value, items, { optional = true } = {}) => {
    const current = value ?? null;
    const shown = current == null ? t("ward.scope.all") : items.find((item) => item.value === current)?.short;
    const el = pillMenu({
      key,
      value: shown ?? current,
      isDefault: optional && current == null,
      label: t("ward.scope.pill", { key: key || t("ward.scope.specimen"), value: shown ?? current }),
      items: () => [
        ...(optional ? [{ value: null, label: t("ward.scope.all"), checked: current == null }] : []),
        ...items.map((item) => ({ ...item, checked: item.value === current })),
      ],
      onSelect: (next) => setParams({ [param]: next }),
    });
    el.id = `scope-${param}`; // keeps focus on the pill when the page re-renders after a choice
    return el;
  };

  return h(
    "div",
    { class: "scopebar", role: "group", "aria-label": t("ward.scope.label") },
    pill(
      "ward",
      t("ward.scope.ward"),
      ward,
      (filters.wards ?? []).map((w) => ({ value: w.code, short: w.code, label: `${w.code} · ${w.label}` })),
      { optional: false },
    ),
    pill(
      "specimen",
      "",
      specimen,
      (filters.specimen_groups ?? []).map((g) => ({ value: g.key, short: g.label, label: g.label })),
      { optional: false },
    ),
    pill(
      "organism",
      t("ward.scope.organism"),
      params.organism,
      (filters.organisms ?? []).map((o) => ({ value: o.organism, short: o.label, label: o.label })),
    ),
    h("span", { class: "sep", "aria-hidden": "true" }),
    pill(
      "sex",
      t("ward.scope.sex"),
      params.sex,
      (filters.sexes ?? []).map((x) => ({ value: x.code, short: x.label, label: x.label })),
    ),
    pill(
      "age_band",
      t("ward.scope.age"),
      params.age_band,
      (filters.age_bands ?? []).map((a) => ({ value: a.key, short: a.label, label: a.label })),
    ),
    pill(
      "setting",
      t("ward.scope.setting"),
      params.setting,
      (filters.settings ?? []).map((s) => ({
        value: s.key,
        short: s.label,
        label: s.label,
        // a unit is either inpatient or outpatient (/api/filters wards[].setting): the other one has no isolates
        disabled: wardSetting != null && s.key !== wardSetting,
        hint: wardSetting != null && s.key !== wardSetting ? t("ward.scope.notThisUnit") : null,
      })),
    ),
  );
}
