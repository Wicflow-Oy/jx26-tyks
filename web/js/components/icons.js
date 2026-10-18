// Icons as small inline SVGs, built node by node. Always decorative (aria-hidden): a word sits next to each one.

import { s } from "../dom.js";

const LINE = { fill: "none", stroke: "currentColor", "stroke-linecap": "round", "stroke-linejoin": "round" };
const FILL = { fill: "currentColor" };

// name: [width, height, root attributes, [tag, attributes] ...] in the icon's own 16-unit (or stated) box
const ICONS = {
  P1: [
    16,
    16,
    {},
    ["path", { d: "M8 3.4v5.6", ...LINE, "stroke-width": 2.2 }],
    ["circle", { cx: 8, cy: 12.3, r: 1.3, ...FILL }],
  ],
  P2: [
    16,
    16,
    {},
    [
      "path",
      { d: "M8 3.3l5 8.8H3z", ...FILL, stroke: "currentColor", "stroke-width": 1.2, "stroke-linejoin": "round" },
    ],
  ],
  P3: [16, 16, {}, ["circle", { cx: 8, cy: 8, r: 3.4, ...FILL }]],
  info: [
    16,
    16,
    {},
    ["circle", { cx: 8, cy: 4.5, r: 1.25, ...FILL }],
    ["path", { d: "M8 7.2v5", ...LINE, "stroke-width": 2 }],
  ],
  ok: [16, 16, { ...LINE, "stroke-width": 2 }, ["path", { d: "M3.8 8.4l2.7 2.7 5.7-6.2" }]],
  gap: [
    16,
    16,
    {},
    [
      "circle",
      { cx: 8, cy: 8, r: 4.6, fill: "none", stroke: "currentColor", "stroke-width": 1.5, "stroke-dasharray": "2.4 2" },
    ],
  ],
  line: [
    16,
    16,
    { ...LINE, "stroke-width": 1.6 },
    ["path", { d: "M2.5 12.5l3.5-3.6 2.6 1.8 4.9-5.2" }],
    ["path", { d: "M2.5 6.5h11", "stroke-dasharray": "1.6 2" }],
  ],
  chevron: [8, 13, { ...LINE, "stroke-width": 1.8 }, ["path", { d: "M1.5 1.5l5 5-5 5" }]],
  down: [10, 10, { ...LINE, "stroke-width": 1.5 }, ["path", { d: "M2.5 4l2.5 2.5L7.5 4" }]],
  prev: [14, 14, { ...LINE, "stroke-width": 1.7 }, ["path", { d: "M8.5 3L4.5 7l4 4" }]],
  next: [14, 14, { ...LINE, "stroke-width": 1.7 }, ["path", { d: "M5.5 3l4 4-4 4" }]],
  close: [14, 14, { ...LINE, "stroke-width": 1.7 }, ["path", { d: "M3.5 3.5l7 7M10.5 3.5l-7 7" }]],
  back: [11, 18, { ...LINE, "stroke-width": 2.2 }, ["path", { d: "M9 2L2 9l7 7" }]],
  play: [12, 12, {}, ["path", { d: "M3 1.8v8.4L10 6z", ...FILL }]],
  pause: [
    12,
    12,
    {},
    ["rect", { x: 2.5, y: 2, width: 2.6, height: 8, rx: 0.8, ...FILL }],
    ["rect", { x: 6.9, y: 2, width: 2.6, height: 8, rx: 0.8, ...FILL }],
  ],
  tour: [
    16,
    16,
    {},
    ["circle", { cx: 8, cy: 8, r: 6.2, fill: "none", stroke: "currentColor", "stroke-width": 1.4 }],
    ["path", { d: "M6.7 5.5v5l4-2.5z", ...FILL }],
  ],
  calendar: [
    16,
    16,
    { ...LINE, "stroke-width": 1.4 },
    ["rect", { x: 2.5, y: 3.5, width: 11, height: 10, rx: 2.2 }],
    ["path", { d: "M2.5 6.6h11M5.6 2v2.6M10.4 2v2.6" }],
  ],
  brief: [
    16,
    16,
    { ...LINE, "stroke-width": 1.4 },
    ["rect", { x: 2.4, y: 2.6, width: 11.2, height: 10.8, rx: 2.4 }],
    ["path", { d: "M5.2 6h5.6M5.2 8.4h5.6M5.2 10.8h3.4" }],
  ],
  replay: [
    16,
    16,
    { ...LINE, "stroke-width": 1.4 },
    ["path", { d: "M2.9 8.3A5.2 5.2 0 1 0 4.5 4.3" }],
    ["path", { d: "M2.6 2.6v2.6h2.6" }],
    ["path", { d: "M8 5.4V8l1.9 1.3" }],
  ],
  shield: [
    16,
    16,
    { ...LINE, "stroke-width": 1.4 },
    ["path", { d: "M8 1.9l5 1.9v3.9c0 3.1-2.1 5.2-5 6.4-2.9-1.2-5-3.3-5-6.4V3.8z" }],
    ["path", { d: "M5.8 8.1l1.5 1.5 2.9-3.1" }],
  ],
  draft: [
    16,
    16,
    { ...LINE, "stroke-width": 1.4 },
    ["path", { d: "M13 9.2v3.3A1.5 1.5 0 0 1 11.5 14h-7A1.5 1.5 0 0 1 3 12.5v-7A1.5 1.5 0 0 1 4.5 4h3.3" }],
    ["path", { d: "M11.6 2.4l2 2-5.4 5.4H6.2V7.8z" }],
  ],
  grid: [
    16,
    16,
    { fill: "none", stroke: "currentColor", "stroke-width": 1.4 },
    ["rect", { x: 2.4, y: 2.4, width: 4.6, height: 4.6, rx: 1.3 }],
    ["rect", { x: 9, y: 2.4, width: 4.6, height: 4.6, rx: 1.3 }],
    ["rect", { x: 2.4, y: 9, width: 4.6, height: 4.6, rx: 1.3 }],
    ["rect", { x: 9, y: 9, width: 4.6, height: 4.6, rx: 1.3 }],
  ],
  ward: [
    16,
    16,
    { ...LINE, "stroke-width": 1.4 },
    ["path", { d: "M2.6 13.4V5.2L8 2.4l5.4 2.8v8.2z" }],
    ["path", { d: "M8 6v4M6 8h4" }],
  ],
  trend: [
    16,
    16,
    { ...LINE, "stroke-width": 1.4 },
    ["path", { d: "M2.4 11.8l3.4-3.9 2.8 2.3 4.9-6" }],
    ["path", { d: "M2.4 13.6h11.2" }],
  ],
  order: [
    16,
    16,
    { ...LINE, "stroke-width": 1.4 },
    ["rect", { x: 3.2, y: 3, width: 9.6, height: 11, rx: 2 }],
    ["path", { d: "M6 1.9h4v2.3H6z" }],
    ["path", { d: "M5.8 7.6h4.4M5.8 10.2h2.8" }],
  ],
  // the app mark: a ring with a centre dot and one satellite (coloured by .mark-dot in shell.css)
  mark: [
    18,
    18,
    {},
    ["circle", { cx: 9, cy: 9, r: 6.2, fill: "none", stroke: "currentColor", "stroke-width": 1.6 }],
    ["circle", { cx: 9, cy: 9, r: 2, ...FILL }],
    ["circle", { class: "mark-dot", cx: 13.4, cy: 4.6, r: 1.9, "stroke-width": 1 }],
  ],
};

/** icon("P1", 16): width in px; the height follows the icon's own proportions. */
export function icon(name, width = 16) {
  const [w, h, root, ...nodes] = ICONS[name];
  return s(
    "svg",
    {
      width,
      height: Math.round((width * h) / w),
      viewBox: `0 0 ${w} ${h}`,
      "aria-hidden": "true",
      focusable: "false",
      ...root,
    },
    nodes.map(([tag, attrs]) => s(tag, attrs)),
  );
}
