// The trend chart: one drug's weekly rolling-window estimate with its interval band, drawn at the container's
// real width so its text stays at 11px or more. Weeks with not enough data break the line and get hatched stubs
// below the baseline (a gap never reads as zero); changed weeks get amber dots; the dotted local setting is
// labelled in bold; the last value is labelled.

import { linear, onWidth, px } from "../../components/svg.js";
import { h, s } from "../../dom.js";
import { dateFull, dateShort, pct } from "../../format.js";
import { changeOf } from "./cells.js";

const HEIGHT = 190;
const PAD = { left: 38, right: 46, top: 14, bottom: 34 };
const stops = new Map(); // slot → stop(): one live chart per slot (the pane, the phone card)
let hatchCount = 0;

/** trendChart(series, { line, label, slot }): label is the chart's text equivalent (aria-label). */
export function trendChart(series, { line, label, slot }) {
  stops.get(slot)?.();
  const svg = s("svg", { role: "img", "aria-label": label, height: HEIGHT });
  const figure = h("figure", { class: "tchart card" }, svg);
  stops.set(
    slot,
    onWidth(figure, (width) => draw(svg, width, series, line)),
  );
  return figure;
}

function draw(svg, width, series, line) {
  const innerW = Math.max(40, width - PAD.left - PAD.right);
  const base = HEIGHT - PAD.bottom;
  const valued = series.filter((p) => p.estimate?.pct != null);
  const lowest = Math.min(...valued.map((p) => p.estimate.ci?.[0] ?? p.estimate.pct), line ?? 1);
  // the axis starts at a round tenth below the data, never above 50%, so a fall is visible without exaggeration
  const lo = Math.max(0, Math.min(0.5, Math.floor((lowest - 0.05) * 10) / 10));
  const x = linear([0, Math.max(1, series.length - 1)], [PAD.left, PAD.left + innerW]);
  const y = linear([lo, 1], [base, PAD.top]);
  const right = PAD.left + innerW + 6;
  const hatch = `trend-hatch-${++hatchCount}`;

  const grid = gridValues(lo).map((v) => [
    s("line", { class: "grid", x1: PAD.left, x2: right, y1: px(y(v)), y2: px(y(v)) }),
    (line == null || Math.abs(y(v) - y(line)) > 18) &&
      s("text", { x: PAD.left - 7, y: px(y(v) + 4), "text-anchor": "end" }, pct(v)),
  ]);
  const local = line != null && [
    s("line", { class: "local", x1: PAD.left, x2: right, y1: px(y(line)), y2: px(y(line)) }),
    s("text", { class: "strong", x: PAD.left - 7, y: px(y(line) + 4), "text-anchor": "end" }, pct(line)),
  ];

  const stubs = series.map(
    (p, i) =>
      p.state === "not_enough_data" &&
      s("rect", { class: "stub", x: px(x(i) - 2.6), y: base + 4, width: 5.2, height: 9, fill: `url(#${hatch})` }),
  );
  const changed = series.map(
    (p, i) =>
      changeOf(p) &&
      p.estimate?.pct != null &&
      s("circle", { class: "chg", cx: px(x(i)), cy: px(y(p.estimate.pct)), r: 3.4 }),
  );
  const last = series.at(-1);
  const end = last?.estimate?.pct != null && [
    s("circle", { class: "last", cx: px(x(series.length - 1)), cy: px(y(last.estimate.pct)), r: 4.5 }),
    s(
      "text",
      { class: "strong value", x: px(x(series.length - 1) + 9), y: px(y(last.estimate.pct) + 15) },
      pct(last.estimate.pct),
    ),
  ];
  const dates = series.length > 0 && [
    s("text", { x: PAD.left, y: HEIGHT - 4 }, dateFull(series[0].as_of)),
    s("text", { x: px(x(series.length - 1)), y: HEIGHT - 4, "text-anchor": "end" }, dateShort(last.as_of)),
  ];

  svg.setAttribute("viewBox", `0 0 ${width} ${HEIGHT}`);
  svg.setAttribute("width", width);
  svg.replaceChildren(
    ...[
      s(
        "defs",
        null,
        s(
          "pattern",
          { id: hatch, width: 4, height: 4, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
          s("rect", { class: "hatch", width: 1.2, height: 4 }),
        ),
      ),
      grid,
      local,
      segments(series).map((run) => segment(run, x, y)),
      stubs,
      changed,
      end,
      dates,
    ]
      .flat(Infinity)
      .filter(Boolean),
  );
}

/** Runs of consecutive weeks with an estimate, as indexed points. */
function segments(series) {
  const runs = [];
  let run = [];
  series.forEach((p, i) => {
    if (p.estimate?.pct == null) {
      if (run.length) runs.push(run);
      run = [];
    } else run.push({ p, i });
  });
  if (run.length) runs.push(run);
  return runs;
}

/** Gridlines at even steps from 100% down to the baseline: the first step that lands on it exactly. */
function gridValues(lo) {
  const span = 1 - lo;
  const step = [0.2, 0.25, 0.3, 0.35, 0.1].find((x) => Math.abs(span / x - Math.round(span / x)) < 1e-6) ?? span;
  const values = [];
  for (let i = 0; i <= Math.round(span / step); i++) values.push(Math.round((1 - i * step) * 100) / 100);
  return values;
}

/** One run: its interval band and estimate line, or a dot for a single week. */
function segment(run, x, y) {
  if (run.length === 1)
    return s("circle", { class: "pt", cx: px(x(run[0].i)), cy: px(y(run[0].p.estimate.pct)), r: 2 });
  const point = (i, v) => `${px(x(i))},${px(y(v))}`;
  const ci = ({ p }, k) => p.estimate.ci?.[k] ?? p.estimate.pct;
  const upper = run.map((q) => point(q.i, ci(q, 1)));
  const lower = [...run].reverse().map((q) => point(q.i, ci(q, 0)));
  return [
    s("polygon", { class: "band", points: [...upper, ...lower].join(" ") }),
    s("polyline", { class: "est", points: run.map((q) => point(q.i, q.p.estimate.pct)).join(" ") }),
  ];
}
