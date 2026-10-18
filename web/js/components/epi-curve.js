// The unit epi curve: one square per line-list row (a patient, first isolate each) by sample date, stacked by day.
// Filled squares share the cluster's antibiogram, outlined ones have another. "Patients to date" labels sit at the
// first alert and every 7 days after it. It draws at its container's real width and never past as_of.
// Used by the brief's P1 hero and the case file; its words are in the case strings (case.epi.*).

import { addDays, daysBetween, parseISO } from "../dates.js";
import { h, s } from "../dom.js";
import { capitalize, dateShort, int } from "../format.js";
import { t } from "../i18n.js";
import { onWidth, px } from "./svg.js";

const LEAD_DAYS = 2; // empty days drawn before the first sample
const GAP = 2;
const TOP = 24; // room for the cumulative labels
const AXIS = 22; // room for the date labels under the baseline
const LABEL_ROOM = 92; // the "as of 29 Mar" label at the right end

/**
 * epiCurve({ rows, pattern, firstAlert, asOf, unit, lagDays }) → a figure with the chart, its legend and the dates
 * note. rows: line-list rows ({ isolate_id, date, specimen, profile }); pattern: the shared antibiogram (null fills
 * every square); firstAlert: the first alert's date or null; unit: "patients" | "isolates" (the counted thing);
 * lagDays: /api/meta result_lag_days.
 */
export function epiCurve({ rows, pattern, firstAlert, asOf, unit = "patients", lagDays }) {
  const shown = rows.filter((row) => row.date <= asOf).sort((a, b) => (a.date < b.date ? -1 : 1));
  const chart = h("div", { class: "epi-chart" });
  const others = pattern ? shown.filter((row) => row.profile !== pattern).length : 0;
  const alertShown = firstAlert && firstAlert <= asOf;
  onWidth(chart, (width) => chart.replaceChildren(draw({ rows: shown, pattern, firstAlert, asOf, unit, width })));
  return h(
    "figure",
    { class: "epi" },
    chart,
    h(
      "figcaption",
      { class: "legend-epi" },
      pattern && h("span", null, swatch(true), t("case.epi.shares", { pattern })),
      others > 0 && h("span", null, swatch(false), t("case.epi.other")),
      alertShown && h("span", null, t(`case.epi.numbers.${unit}`)),
      h("span", null, capitalize(t("shell.sampleDates", { days: lagDays }))),
    ),
  );
}

function draw({ rows, pattern, firstAlert, asOf, unit, width }) {
  const start = addDays(rows[0]?.date ?? asOf, -LEAD_DAYS);
  const days = daysBetween(start, asOf) + 1;
  const dayWidth = (width - 8) / days;
  const size = Math.max(5, Math.min(11, Math.floor(dayWidth - GAP)));
  const byDay = groupByDay(rows, pattern);
  const tallest = Math.max(2, ...[...byDay.values()].map((day) => day.length));
  const base = TOP + tallest * (size + GAP) + 4;
  const x = (iso) => 4 + (daysBetween(start, iso) + 0.5) * dayWidth;

  const marks = [s("line", { x1: 0, x2: width, y1: base + 0.5, y2: base + 0.5, class: "axis" })];
  let lastLabel = -Infinity;
  for (let i = 0; i < days; i++) {
    const day = addDays(start, i);
    const monday = parseISO(day).getUTCDay() === 1;
    const cx = px(x(day));
    marks.push(
      s("line", { x1: cx, x2: cx, y1: base, y2: base + (monday ? 5 : 2.5), class: monday ? "tick" : "tick minor" }),
    );
    if (monday && cx > 14 && cx < width - LABEL_ROOM && cx - lastLabel > 44) {
      marks.push(s("text", { x: cx, y: base + 18, "text-anchor": "middle", class: "lab" }, dateShort(day)));
      lastLabel = cx;
    }
  }
  if (firstAlert && firstAlert <= asOf) marks.push(...cumulative({ rows, firstAlert, asOf, x, base, width }));
  for (const [day, list] of byDay) {
    list.forEach((row, j) => marks.push(square(row, j, { x: x(day) - size / 2, base, size, pattern })));
  }
  const end = px(x(asOf));
  marks.push(
    s("line", { x1: end, x2: end, y1: base - 4, y2: base + 6, class: "now" }),
    s(
      "text",
      { x: width, y: base + 18, "text-anchor": "end", class: "lab now" },
      t("case.epi.asOf", { date: dateShort(asOf) }),
    ),
  );

  return s(
    "svg",
    {
      width,
      height: base + AXIS,
      viewBox: `0 0 ${width} ${base + AXIS}`,
      role: "img",
      "aria-label": summary({ rows, pattern, firstAlert, asOf, unit }),
    },
    marks,
  );
}

/** Rows by sample day; on each day the squares sharing the pattern stack first. */
function groupByDay(rows, pattern) {
  const byDay = new Map();
  for (const row of rows) byDay.set(row.date, [...(byDay.get(row.date) ?? []), row]);
  for (const list of byDay.values()) list.sort((a, b) => (b.profile === pattern) - (a.profile === pattern));
  return byDay;
}

/** "3 · 5 · 8 · 13": count to date at the first alert and every 7 days after, with "first alert" by the first. */
function cumulative({ rows, firstAlert, asOf, x, base, width }) {
  const marks = [];
  for (let day = firstAlert, k = 0; day <= asOf; day = addDays(day, 7), k++) {
    const n = rows.filter((row) => row.date <= day).length;
    const cx = px(x(day));
    marks.push(
      s("line", { x1: cx, x2: cx, y1: 17, y2: base - 1, class: "guide" }),
      s("text", { x: cx, y: 12, "text-anchor": "middle", class: "cum" }, int(n)),
    );
    if (k === 0) {
      const right = cx + 74 < width;
      marks.push(
        s(
          "text",
          { x: right ? cx + 9 : cx - 9, y: 12, "text-anchor": right ? "start" : "end", class: "lab" },
          t("case.epi.firstAlert"),
        ),
      );
    }
  }
  return marks;
}

function square(row, j, { x, base, size, pattern }) {
  const shared = !pattern || row.profile === pattern;
  const y = base - 3 - (j + 1) * size - j * GAP;
  const tip = s(
    "title",
    null,
    [row.isolate_id, dateShort(row.date), row.specimen, shared ? null : t("case.epi.other")]
      .filter(Boolean)
      .join(" · "),
  );
  const inset = shared ? 0 : 0.75;
  return s(
    "rect",
    {
      x: px(x + inset),
      y: px(y + inset),
      width: size - inset * 2,
      height: size - inset * 2,
      rx: 1.5,
      class: shared ? "sq" : "sq other",
    },
    tip,
  );
}

/** The chart's text equivalent: "Patients by sample date: 13 since 3 Mar, 12 with the shared antibiogram; …" */
function summary({ rows, pattern, firstAlert, asOf, unit }) {
  const shared = pattern ? rows.filter((row) => row.profile === pattern).length : rows.length;
  return [
    t(`case.epi.summary.${unit}`, { n: int(rows.length), date: rows[0] ? dateShort(rows[0].date) : dateShort(asOf) }),
    pattern ? t("case.epi.summary.shared", { n: int(shared) }) : null,
    firstAlert && firstAlert <= asOf ? t("case.epi.summary.alert", { date: dateShort(firstAlert) }) : null,
    t("case.epi.summary.asOf", { date: dateShort(asOf) }),
  ]
    .filter(Boolean)
    .join("; ");
}

const swatch = (filled) =>
  s(
    "svg",
    { width: 10, height: 10, viewBox: "0 0 10 10", "aria-hidden": "true" },
    s(
      "rect",
      filled
        ? { width: 10, height: 10, rx: 1.5, class: "sq" }
        : { x: 0.75, y: 0.75, width: 8.5, height: 8.5, rx: 1.5, class: "sq other" },
    ),
  );
