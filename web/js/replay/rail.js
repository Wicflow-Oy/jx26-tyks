// The replay rail under the desktop toolbar: [▶ Play March] [week ticks] ["26 weeks back · Latest ›"].
// Always visible at >=1024; phones get the same drawing in the replay sheet (replay/sheet.js).

import { linkButton } from "../components/buttons.js";
import { icon } from "../components/icons.js";
import { daysBetween } from "../dates.js";
import { $, h, mount } from "../dom.js";
import { dateLong, monthLong } from "../format.js";
import { t } from "../i18n.js";
import { asOfRange, getState, subscribe } from "../state.js";
import { weekScrubber } from "./ticks.js";
import { getTourStart, goLatest, isPlaying, onTimeline, togglePlay } from "./timeline.js";

export const RAIL_GEOMETRY = { height: 46, top: 4, base: 28, maxTick: 15, label: 42 };

/** Fills #rail once; it keeps itself in sync with the as-of date and the play state. */
export function mountRail(rail) {
  const status = h("div", { class: "rail-status" });
  mount(rail, playButton(), weekScrubber(RAIL_GEOMETRY), status);
  const render = () => {
    rail.setAttribute("aria-label", t("replay.label"));
    renderStatus(status);
  };
  subscribe((state, prev) => {
    if (state.asOf !== prev.asOf || state.lang !== prev.lang) render();
  });
  render();
}

/** The "Play March" / "Pause" pill, shared by the rail and the sheet. */
export function playButton() {
  const el = h("button", { type: "button", class: "play", onclick: togglePlay });
  const update = () => {
    const month = getTourStart() ? monthLong(getTourStart()) : "";
    const playing = isPlaying();
    el.hidden = !month;
    el.setAttribute("aria-label", playing ? t("replay.pause") : t("replay.playAria", { month }));
    mount(
      el,
      icon(playing ? "pause" : "play", 10),
      h("span", null, playing ? t("replay.pause") : t("replay.play", { month })),
    );
  };
  onTimeline(update);
  subscribe((state, prev) => state.lang !== prev.lang && update());
  update();
  return el;
}

function renderStatus(status) {
  const { last } = asOfRange();
  const back = Math.round(daysBetween(getState().asOf, last) / 7);
  if (back <= 0) {
    mount(status, h("span", null, t("replay.atLatest")));
    return;
  }
  mount(
    status,
    h("span", null, back === 1 ? t("replay.weekBack") : t("replay.weeksBack", { n: back })),
    linkButton({
      label: t("replay.latest"),
      // the link goes away at the latest week; focus stays on the rail's week control
      onClick: () => {
        goLatest();
        $("input[type=range]", status.parentElement)?.focus();
      },
      attrs: { "aria-label": t("replay.latestAria", { date: dateLong(last) }) },
    }),
  );
}
