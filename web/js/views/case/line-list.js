// "Line list": a closed disclosure with the evidence rows as a real table. Synthetic isolate ids, sample dates,
// care day and S/R columns for the cluster's antibiogram (or the signal's drug). Never patient names or ids.

import { srBadge } from "../../components/badges.js";
import { icon } from "../../components/icons.js";
import { h } from "../../dom.js";
import { dateShort, int } from "../../format.js";
import { t } from "../../i18n.js";
import { plural } from "../../text.js";

/** ctx: { item, file, asOf, names } */
export function lineList({ item, file, asOf, names }) {
  const rows = (file.line_list.rows ?? []).filter((row) => row.date <= asOf);
  const pattern = item.slots?.pattern ?? item.evidence?.filter?.profile ?? null;
  const drugs = pattern ? pattern.split(" ").map((pair) => pair.split(":")[0]) : [item.drug].filter(Boolean);
  const many = (key) => new Set(rows.map((row) => row[key])).size > 1;
  const columns = [
    { label: t("case.list.isolate"), cell: (row) => row.isolate_id },
    { label: t("case.list.sample"), cell: (row) => dateShort(row.date) },
    many("ward") && { label: t("case.list.unit"), cell: (row) => row.ward },
    many("organism") && { label: t("case.list.organism"), cell: (row) => names.organism(row.organism) ?? row.organism },
    { label: t("case.list.specimen"), cell: (row) => row.specimen, class: "hide-s" },
    { label: t("case.list.day"), cell: (row) => (row.care_day == null ? "–" : int(row.care_day)), class: "r" },
    ...drugs.map((code) => ({
      label: code,
      title: names.drug(code) ?? code,
      class: "c",
      cell: (row) => result(row, code, names),
    })),
  ].filter(Boolean);
  const shownOfAll = rows.length < file.line_list.n;

  return h(
    "details",
    { class: "case-disc" },
    h(
      "summary",
      null,
      h("span", { class: "disc", "aria-hidden": "true" }, icon("chevron", 7)),
      shownOfAll
        ? t("case.list.showSome", { n: int(rows.length), total: int(file.line_list.n) })
        : plural("case.list.show", rows.length, { n: int(rows.length) }),
      h("span", { class: "r" }, t("case.list.hint")),
    ),
    // a wide antibiogram scrolls inside its own box on phones; the box takes focus so keys can scroll it
    h(
      "div",
      { class: "lltab-wrap", tabindex: "0", role: "region", "aria-label": t("case.list.region") },
      h(
        "table",
        { class: "lltab" },
        h("caption", { class: "sr" }, t("case.list.caption")),
        h(
          "thead",
          null,
          h(
            "tr",
            null,
            columns.map((col) => h("th", { scope: "col", class: col.class, title: col.title }, col.label)),
          ),
        ),
        h(
          "tbody",
          null,
          rows.map((row) =>
            h(
              "tr",
              { class: pattern && row.profile !== pattern ? "other" : null },
              columns.map((col) => h("td", { class: col.class }, col.cell(row))),
            ),
          ),
        ),
      ),
    ),
    h("p", { class: "cap" }, pattern ? `${t("case.list.shaded")} ` : "", file.note),
  );
}

/** The row's S/R for one drug from its antibiogram string ("FOX:R VAN:S"), as a letter badge; "–" if untested. */
function result(row, code, names) {
  const pair = String(row.profile ?? "")
    .split(" ")
    .find((p) => p.startsWith(`${code}:`));
  const value = pair?.split(":")[1];
  return value === "S" || value === "R" ? srBadge(value, names.drug(code) ?? code) : "–";
}
