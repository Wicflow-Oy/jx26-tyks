// "Method details": a closed disclosure with the re-runnable filter, the method's parameters and its statistics
// (p-values, log10 Bayes factor, expected counts), then the method in plain words. The API's own method string is
// developer text and is never shown.

import { icon } from "../../components/icons.js";
import { h } from "../../dom.js";
import { dateFull, int, pct } from "../../format.js";
import { t } from "../../i18n.js";
import { methodText } from "./parts.js";

// evidence.params shown, in this order; each formatted by its unit
const PARAMS = {
  window_days: "days",
  prior_days: "days",
  history_days: "days",
  learning_days: "weeks",
  active_days: "days",
  min_patients: "count",
  min_resistant: "count",
  min_tested: "count",
  rarity_max_share: "share",
  threshold: "share",
  alpha: "p",
  midp_alpha: "p",
};

/** ctx: { item, names } with names from names.labels() (the counting rules among them). */
export function methodDetails({ item, names }) {
  const ev = item.evidence ?? {};
  const rows = [...filterRows(ev.filter ?? {}, names), ...paramRows(ev.params ?? {}), ...statRows(ev)];
  return h(
    "details",
    { class: "case-disc csec" },
    h(
      "summary",
      null,
      h("span", { class: "disc", "aria-hidden": "true" }, icon("chevron", 7)),
      t("case.methodDetails"),
      h("span", { class: "r" }, t("case.methodHint")),
    ),
    rows.length > 0 &&
      h(
        "dl",
        { class: "kv" },
        rows.map(([label, value]) => [h("dt", null, label), h("dd", null, value)]),
      ),
    h("p", { class: "cap" }, methodText(item.kind), " ", t("case.methodPast")),
  );
}

function filterRows(f, names) {
  const list = (value, name = (x) => x) => (Array.isArray(value) ? value.map(name).join(", ") : value && name(value));
  const dates =
    f.date_from && f.date_to
      ? t("case.kv.range", { from: dateFull(f.date_from), to: dateFull(f.date_to) })
      : f.date_to && t("case.kv.to", { date: dateFull(f.date_to) });
  return [
    [t("case.kv.unit"), list(f.ward)],
    [t("case.kv.specimen"), list(f.specimen)],
    [t("case.kv.organism"), list(f.organism, (code) => names.organism(code) ?? code)],
    [t("case.kv.drug"), list(f.drug, (code) => names.drug(code) ?? code)],
    [t("case.kv.antibiogram"), f.profile],
    [t("case.kv.dates"), dates],
    [t("case.kv.rule"), f.rule && (names.rule(f.rule) ?? ruleLabel(f.rule))],
  ].filter(([, value]) => value);
}

// counting rules the filters catalogue does not list (the brief's culture and lab-check counts)
const OTHER_RULES = ["all_cultures", "all_isolates"];
const ruleLabel = (rule) => (OTHER_RULES.includes(rule) ? t(`case.rule.${rule}`) : rule);

function paramRows(params) {
  return Object.entries(PARAMS)
    .filter(([key]) => typeof params[key] === "number")
    .map(([key, unit]) => [t(`case.param.${key}`), formatParam(params[key], unit)]);
}

function formatParam(value, unit) {
  if (unit === "days") return t("case.kv.days", { n: int(value) });
  if (unit === "weeks") return t("case.kv.weeks", { n: int(value / 7) });
  if (unit === "share") return pct(value);
  if (unit === "p") return `p < ${value.toExponential(0)}`;
  return int(value);
}

/** Statistics behind the signal, from its counts and its competing-explanations values. */
function statRows(ev) {
  const c = ev.counts ?? {};
  const v = ev.competing_explanations?.values ?? {};
  const p = v.p_count ?? c.min_p ?? c.p ?? c.p_low;
  return [
    [t("case.kv.countTest"), p != null && `p = ${Number(p).toExponential(1)}`],
    [t("case.kv.identityTest"), v.p_identity != null && `p = ${v.p_identity.toExponential(1)}`],
    [t("case.kv.stepup"), ev.stepup?.log10_bf != null && t("case.kv.bf", { bf: ev.stepup.log10_bf.toFixed(1) })],
    [
      t("case.kv.expected"),
      c.expected_per_year != null
        ? t("case.kv.perYear", { n: Number(c.expected_per_year).toPrecision(2) })
        : c.expected_resistant != null
          ? t("case.kv.resistant", { n: c.expected_resistant })
          : c.expected_per_week != null && t("case.kv.perWeek", { n: c.expected_per_week }),
    ],
  ].filter(([, value]) => value);
}
