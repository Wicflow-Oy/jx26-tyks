// Names for the codes the API uses (units, organisms, drugs, counting rules), read from /api/meta and /api/filters,
// and the one typographic rule for drug names.

/**
 * labels(meta, filters) → { ward(code), organism(code), drug(code), rule(key), specimen(key) }, each the API's label or null
 * when the code is unknown, so callers choose their own fallback (usually the code itself).
 */
export function labels(meta, filters) {
  const lookup = (rows, key) => {
    const map = new Map((rows ?? []).map((row) => [row[key], row.label]));
    return (code) => map.get(code) ?? null;
  };
  return {
    ward: lookup(meta?.wards ?? filters?.wards, "code"),
    organism: lookup(filters?.organisms, "organism"),
    drug: lookup(filters?.drugs, "drug"),
    rule: lookup(filters?.rules, "key"),
    specimen: lookup(filters?.specimen_groups, "key"),
  };
}

/** A home area's label in the current language ("Pohjoinen" for North), else its key. */
export const areaName = (key, filters) => filters?.home_areas?.find((area) => area.key === key)?.label ?? key;

/** Drug names keep their hyphen on one line ("Piperacillin‑tazobactam", with U+2011). */
export const noBreak = (label) => String(label ?? "").replaceAll("-", "‑");
