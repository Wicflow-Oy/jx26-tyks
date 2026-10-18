// The trend of one drug on this unit (GET /api/trend), shared by the trend pane and the phone card under the lead
// sentence: badges and title, the lede in counts, the chart, its legend and, in the pane, the last five weeks.

import { mk } from "../../components/marker.js";
import { h, s } from "../../dom.js";
import { dateDay, dateShort, int, interval, pct, xOfN } from "../../format.js";
import { t } from "../../i18n.js";
import { noBreak } from "../../names.js";
import { rich } from "../../text.js";
import { changeChip, changeOf } from "./cells.js";
import { labelIn, scopeExtras, weeksOf } from "./scope.js";
import { trendChart } from "./trend-chart.js";

const TABLE_WEEKS = 5;

/**
 * trendContent(trend, { meta, filters, inPane }): the nodes of the trend. inPane: the pane's version (focusable
 * h2, the weekly table); otherwise the compact phone card.
 */
export function trendContent(trend, { meta, filters, inPane }) {
  const series = trend.series ?? [];
  const last = series.at(-1);
  const weeks = weeksOf(filters.windows?.find((w) => w.key === trend.window)) || 4;
  const line = trend.local_setting?.value ?? null;
  const echo = trend.filters ?? {};
  const ward = [echo.ward].flat().filter(Boolean).join(", ");
  const title = [noBreak(trend.label), ward].filter(Boolean).join(" · ");
  const earlier = series.length > weeks ? series[series.length - 1 - weeks] : null;
  if (!last) return [h("h2", { class: "trend-title", tabindex: inPane ? "-1" : null }, title)];

  return [
    h(
      "div",
      { class: "trend-head" },
      h("div", { class: "trend-badges" }, h("span", { class: "chip chip-outline" }, trend.aware), sinceChip(series)),
      h("h2", { class: "trend-title", tabindex: inPane ? "-1" : null }, title),
      h(
        "p",
        { class: "trend-sub" },
        [
          t("ward.trend.sub", {
            specimen: labelIn(filters.specimen_groups, echo.specimen_group),
            weeks,
            n: int(series.length),
            date: dateShort(last.as_of),
          }),
          ...scopeExtras(echo, filters),
        ].join(" · "),
      ),
    ),
    h("p", { class: "readout" }, lede(earlier, last, weeks), " ", now(last, line)),
    h("p", { class: "cap" }, latest(last, weeks)),
    trendChart(series, {
      line,
      label: chartLabel(trend, { ward, earlier, last, weeks }),
      slot: inPane ? "pane" : "card",
    }),
    legend(series, line),
    inPane && weekTable(series.slice(-TABLE_WEEKS)),
    h(
      "p",
      { class: "cap" },
      series.some((p) => p.estimate?.method === "stabilised") ? [t("ward.trend.cap.few"), " "] : null,
      t("ward.trend.cap.dates", { days: meta.result_lag_days ?? 2 }),
    ),
  ];
}

/** "Changed ↓ since 15 Mar": the start of the run of changed weeks that ends this week. */
function sinceChip(series) {
  const direction = changeOf(series.at(-1));
  if (!direction) return null;
  let i = series.length - 1;
  while (i > 0 && changeOf(series[i - 1]) === direction) i -= 1;
  return changeChip(direction, dateShort(series[i].as_of));
}

const covered = (p) => xOfN(p.observed?.covered ?? 0, p.observed?.tested ?? 0);

function lede(earlier, last, weeks) {
  const z = mk("trend-z", h("b", null, covered(last)));
  if (!earlier) return rich("ward.trend.ledeOne", { z, weeks, zDate: dateShort(last.as_of) });
  return rich("ward.trend.lede", {
    a: h("b", null, covered(earlier)),
    weeks,
    aDate: dateShort(earlier.as_of),
    z,
    zDate: dateShort(last.as_of),
  });
}

/** The latest week's estimate in one sentence. */
function now(last, line) {
  const e = last.estimate ?? {};
  if (e.pct == null) return t("ward.trend.nowNed", { n: int(last.observed?.tested ?? 0) });
  const kind = e.method === "stabilised" ? "Stabilised" : "Observed";
  const below = last.below_local_setting && line != null ? "Below" : "";
  return t(`ward.trend.now${kind}${below}`, { pct: pct(e.pct), ci: interval(e.ci), line: pct(line) });
}

/** The observed share of the latest window next to the stabilised one, so neither stands unexplained. */
function latest(last, weeks) {
  const o = last.observed ?? {};
  if (last.state === "not_enough_data" || o.pct == null) return t("ward.trend.latestNed", { weeks, x: covered(last) });
  const vars = { weeks, pct: pct(o.pct), ci: interval(o.ci) };
  if (last.estimate?.method !== "stabilised") return t("ward.trend.latest", vars);
  return t("ward.trend.latestFew", { ...vars, spct: pct(last.estimate.pct), sci: interval(last.estimate.ci) });
}

function chartLabel(trend, { ward, earlier, last, weeks }) {
  const series = trend.series ?? [];
  return t("ward.trend.aria", {
    drug: trend.label,
    ward,
    n: series.length,
    date: dateShort(last.as_of),
    a: covered(earlier ?? last),
    weeks,
    aDate: dateShort((earlier ?? last).as_of),
    z: covered(last),
    zDate: dateShort(last.as_of),
    ned: series.filter((p) => p.state === "not_enough_data").length,
    changed: series.filter((p) => changeOf(p)).length,
  });
}

function legend(series, line) {
  const ned = series.filter((p) => p.state === "not_enough_data").length;
  const glyph = (width, height, ...children) =>
    s("svg", { width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" }, children);
  return h(
    "p",
    { class: "trend-legend" },
    h("span", null, glyph(18, 8, s("path", { class: "est", d: "M1 6 L8 3 L17 4" })), t("ward.trend.legend.estimate")),
    ned > 0 &&
      h("span", null, h("span", { class: "kstub", "aria-hidden": "true" }), t("ward.trend.legend.ned", { n: ned })),
    h("span", null, glyph(10, 10, s("circle", { class: "chg", cx: 5, cy: 5, r: 3.4 })), t("ward.trend.legend.changed")),
    line != null &&
      h(
        "span",
        null,
        glyph(16, 6, s("line", { class: "local", x1: 0, x2: 16, y1: 3, y2: 3 })),
        t("ward.trend.legend.line", { line: pct(line) }),
      ),
  );
}

function weekTable(weeks) {
  const state = (p) => {
    if (p.state === "not_enough_data") return h("span", { class: "ink2" }, t("ward.cell.ned"));
    return changeChip(changeOf(p)) ?? h("span", { class: "ink2" }, t("ward.trend.table.usual"));
  };
  return h(
    "section",
    { class: "trend-weeks", "aria-labelledby": "h-trend-weeks" },
    h(
      "div",
      { class: "trend-weeks-h" },
      h("h3", { id: "h-trend-weeks" }, t("ward.trend.table.title", { n: weeks.length })),
      h("span", null, t("ward.trend.table.ending")),
    ),
    h(
      "table",
      { class: "wk-tab" },
      h(
        "thead",
        null,
        h(
          "tr",
          null,
          h("th", { scope: "col" }, t("ward.trend.table.week")),
          h("th", { scope: "col", class: "r" }, t("ward.trend.table.covered")),
          h("th", { scope: "col", class: "r" }, t("ward.trend.table.estimate")),
          h("th", { scope: "col", class: "r" }, t("ward.trend.table.state")),
        ),
      ),
      h(
        "tbody",
        null,
        weeks.map((p) =>
          h(
            "tr",
            null,
            h("th", { scope: "row" }, dateDay(p.as_of)),
            h("td", { class: "r" }, h("b", null, covered(p))),
            h(
              "td",
              { class: "r" },
              p.estimate?.pct != null
                ? [pct(p.estimate.pct), " ", h("span", { class: "ink2" }, interval(p.estimate.ci))]
                : h("span", { class: "ink2" }, t("ward.cell.n", { n: int(p.observed?.tested ?? 0) })),
            ),
            h("td", { class: "r" }, state(p)),
          ),
        ),
      ),
    ),
  );
}
