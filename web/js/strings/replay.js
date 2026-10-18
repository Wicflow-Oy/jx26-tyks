// Replay strings: the rail, the phone replay sheet and Play. Read as t("replay.<key>").

export const en = {
  label: "Replay",
  rangeLabel: "As of week. Arrow keys step one week; Home and End go to the first and the latest week.",
  "valueText.counts": "{date}: {P1} P1, {P2} P2, {P3} P3, {info} info",
  "valueText.totals": "{date}: {p1} P1, {n} signals",
  play: "Play {month}",
  playAria: "Play {month}, one week at a time",
  pause: "Pause",
  latest: "Latest",
  latestAria: "Back to the latest week, {date}",
  atLatest: "Latest data · refreshed nightly",
  weekBack: "1 week back",
  weeksBack: "{n} weeks back",
  sheetEyebrow: "Replay · one week at a time",
  read: "{p1} P1 · {n} signals",
  sheetSub: "Monday brief {date}. Nothing sampled later is used.",
  tourStart: "Tour start",
  tourStartAria: "Tour start, {date}",
};

/** @type {Partial<typeof en>} */
export const fi = {
  label: "Aikajana",
  rangeLabel:
    "Tilanneviikko. Nuolinäppäimet siirtävät viikon kerrallaan; Home ja End siirtävät ensimmäiseen ja uusimpaan viikkoon.",
  "valueText.counts": "{date}: P1 {P1}, P2 {P2}, P3 {P3}, tiedoksi {info}",
  "valueText.totals": "{date}: P1 {p1}, signaaleja {n}",
  play: "Toista {month}",
  playAria: "Toista {month} viikko kerrallaan",
  pause: "Pysäytä",
  latest: "Uusin",
  latestAria: "Takaisin uusimpaan viikkoon, {date}",
  atLatest: "Uusin data · päivitetään öisin",
  weekBack: "1 viikko taaksepäin",
  weeksBack: "{n} viikkoa taaksepäin",
  sheetEyebrow: "Aikajana · viikko kerrallaan",
  read: "P1 {p1} · signaaleja {n}",
  sheetSub: "Maanantaikatsaus {date}. Myöhemmin otettuja näytteitä ei käytetä.",
  tourStart: "Esittely",
  tourStartAria: "Esittelyn alku, {date}",
};
