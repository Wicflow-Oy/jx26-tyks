// Date arithmetic on ISO day strings ("2026-03-29"), in UTC so no time zone shifts a day.

const DAY_MS = 864e5;

export function parseISO(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export const toISO = (date) => date.toISOString().slice(0, 10);

export function isISODate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(parseISO(value).getTime());
}

export function addDays(iso, n) {
  const d = parseISO(iso);
  d.setUTCDate(d.getUTCDate() + n);
  return toISO(d);
}

export const daysBetween = (from, to) => Math.round((parseISO(to) - parseISO(from)) / DAY_MS);

/** The brief is dated the Monday after its as-of Sunday (CONTRACTS §2). */
export const mondayOf = (asOf) => addDays(asOf, 1);

/** Every as-of Sunday from first to last, one week apart. */
export function weekGrid(first, last) {
  const weeks = [];
  for (let d = first; d <= last; d = addDays(d, 7)) weeks.push(d);
  return weeks;
}
