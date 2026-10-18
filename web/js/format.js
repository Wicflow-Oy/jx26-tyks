// Formatting for dates, shares and counts, in the language of the UI's words (i18n.textLang).
// English: "Sun 29 Mar 2026", "29 Mar", "20.4%". Finnish: "su 29.3.2026", "29.3.", "20,4 %".

import { parseISO } from "./dates.js";
import { t, textLang } from "./i18n.js";

const NBSP = " ";
const NAMES = {
  en: {
    days: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    months: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    monthsLong: [
      "January",
      "February",
      "March",
      "April",
      "May",
      "June",
      "July",
      "August",
      "September",
      "October",
      "November",
      "December",
    ],
  },
  fi: {
    days: ["su", "ma", "ti", "ke", "to", "pe", "la"],
    months: ["tammi", "helmi", "maalis", "huhti", "touko", "kesä", "heinä", "elo", "syys", "loka", "marras", "joulu"],
    monthsLong: [
      "tammikuu",
      "helmikuu",
      "maaliskuu",
      "huhtikuu",
      "toukokuu",
      "kesäkuu",
      "heinäkuu",
      "elokuu",
      "syyskuu",
      "lokakuu",
      "marraskuu",
      "joulukuu",
    ],
  },
};

const fi = () => textLang() === "fi";
const names = () => NAMES[textLang()] ?? NAMES.en;

function parts(iso) {
  const d = parseISO(iso);
  return { day: d.getUTCDay(), date: d.getUTCDate(), month: d.getUTCMonth(), year: d.getUTCFullYear() };
}

/** "Sun 29 Mar 2026" · "su 29.3.2026" */
export function dateLong(iso) {
  const p = parts(iso);
  return `${names().days[p.day]} ${dateFull(iso)}`;
}

/** "29 Mar 2026" · "29.3.2026" */
export function dateFull(iso) {
  const p = parts(iso);
  return fi() ? `${p.date}.${p.month + 1}.${p.year}` : `${p.date} ${names().months[p.month]} ${p.year}`;
}

/** "Sun 29 Mar" · "su 29.3." */
export function dateDay(iso) {
  return `${names().days[parts(iso).day]} ${dateShort(iso)}`;
}

/** "29 Mar" · "29.3." */
export function dateShort(iso) {
  const p = parts(iso);
  return fi() ? `${p.date}.${p.month + 1}.` : `${p.date} ${names().months[p.month]}`;
}

/** "Mar" · "maalis" (axis labels) */
export const monthShort = (iso) => names().months[parts(iso).month];

/** "March" · "maaliskuu" */
export const monthLong = (iso) => names().monthsLong[parts(iso).month];

/** 1350 → "1,350" · "1 350" */
export function int(n) {
  const digits = String(Math.round(Math.abs(n))).replace(/\B(?=(\d{3})+(?!\d))/g, fi() ? NBSP : ",");
  return n < 0 ? `−${digits}` : digits;
}

/**
 * A share (0..1) as a percent, rounded half up the way a reader rounds by hand (10 of 16 → "63%"), matching the
 * backend's render.fmt. A share above 0 never prints "0%" and one below 1 never "100%": "<1%" and ">99%".
 */
export function pct(share, places = 0) {
  if (share == null || Number.isNaN(share)) return "";
  const value = halfUp(share, places);
  const step = 10 ** -places;
  let text = number(value, places);
  if (share > 0 && value === 0) text = `<${number(step, places)}`;
  else if (share < 1 && value === 100) text = `>${number(100 - step, places)}`;
  return fi() ? `${text}${NBSP}%` : `${text}%`;
}

/** An interval of shares: [0.61, 0.85] → "[61–85]", never broken at the dash (U+2060 word joiner). */
export function interval(ci, places = 0) {
  if (!Array.isArray(ci) || ci.length !== 2) return "";
  return `[${number(halfUp(ci[0], places), places)}–\u2060${number(halfUp(ci[1], places), places)}]`;
}

/** A rate to a few significant digits, for expected counts: 0.2634 → "0.26" · "0,26"; 3.71 → "3.7". */
export function significant(value, digits = 2) {
  if (value == null || !Number.isFinite(Number(value))) return "";
  const text = String(Number(Number(value).toPrecision(digits)));
  return fi() ? text.replace(".", ",") : text;
}

/** "11 of 24" (the template lives in the shell strings, so Finnish can read "11/24") */
export const xOfN = (x, n) => t("shell.format.xOfN", { x: int(x), n: int(n) });

/** Small counts as words for running text ("one", "two" …); larger ones stay digits. */
export function word(n) {
  const words = t("shell.format.numberWords");
  return Array.isArray(words) && n >= 0 && n < words.length ? words[n] : int(n);
}

export const capitalize = (text) => text.charAt(0).toLocaleUpperCase(textLang()) + text.slice(1);

/** Percent value of a share, rounded half up. The exponent shift keeps 0.145 as 14.5 (0.145 * 100 is 14.499…). */
function halfUp(share, places) {
  const shifted = Number(`${share}e${2 + places}`);
  const scaled = Number.isFinite(shifted) ? shifted : share * 10 ** (2 + places);
  return Math.round(scaled) / 10 ** places;
}

const number = (value, places) => {
  const text = value.toFixed(places);
  return fi() ? text.replace(".", ",") : text;
};
