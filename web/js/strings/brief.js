// Monday brief strings. Read as t("brief.<key>").

export const en = {
  title: "Monday brief",
  dataTo: "data to {date}",
  loading: "Loading the brief",
  error: "The brief for {date} did not load.",

  // the dek: counted phrases joined into one sentence, then the quiet clause
  "dek.unusual.one": "{n} unusual pattern",
  "dek.unusual.other": "{n} unusual patterns",
  "dek.changed.one": "{n} change",
  "dek.changed.other": "{n} changes",
  "dek.policy.one": "{n} policy line crossed",
  "dek.policy.other": "{n} policy lines crossed",
  "dek.seenBefore.one": "{n} seen-before match",
  "dek.seenBefore.other": "{n} seen-before matches",
  "dek.gap.one": "{n} data gap",
  "dek.gap.other": "{n} data gaps",
  "dek.lab.one": "{n} lab check",
  "dek.lab.other": "{n} lab checks",
  "dek.and": "and",
  "dek.none": "No open signals this week.",
  "dek.quiet": "{quiet} of {units} units quiet.",

  "counts.label": "Signals by priority",
  "counts.units": "{n} of {units} units with a signal",

  // section titles, used only if the API sends none
  "section.unusual_patterns": "Unusual patterns",
  "section.changed": "What changed",
  "section.policy": "Policy lines",
  "section.seen_before": "Seen before",
  "section.data_quality": "Data quality",

  "foot.unusual_patterns":
    "Possible clusters by shared antibiogram, and THL rules (CPE, VRE; ESBL and MRSA on one unit).",
  "foot.changed": "Recent resistance on each unit against its own earlier results.",
  "foot.policy": "Lines set by infection control and antibiotic stewardship.",
  "foot.seen_before": "Earlier patients with the exact antibiogram. Profile match, not typing.",
  "foot.data_quality":
    "Phenotype consistency checks on reported S/R results, and units that sent less data than usual.",

  "empty.unusual_patterns": "No unusual pattern this week.",
  "empty.changed": "Nothing outside the usual range this week.",
  "empty.policy": "No policy line is crossed this week.",
  "empty.seen_before": "No earlier matches this week.",
  "empty.data_quality": "No lab checks this week.",

  "hero.open": "Case file",
  "hero.patients": "{n} patients",
  "hero.usual": "usually {range} a year",
  "hero.share": "{counts} same antibiogram",
  "hero.noAlert": "No active alert",
  "hero.alertActive": "Alert approved {approved} by infection control, until {until}",
  "hero.alertExpired": "Alert approved {approved}, expired {until}",

  "policy.rate": "{rate} resistant ({counts}, last {weeks} weeks).",
  "policy.threshold": "The line is at {threshold}.",
  "policy.prior": "Same window a year earlier: {rate} ({counts}).",
  "policy.spoken": "{rate} resistant, {counts}, last {weeks} weeks; the line is at {threshold}",
  "policy.lineLabel": "{threshold} line",
  "policy.above": "Above the line",
  "policy.below": "Below the line",

  cultures: "Cultures this week by unit",

  "map.title": "Quiet this week",
  "map.count": "{quiet} of {units}",
  "map.schematic": "Schematic, not a floor plan",
  "map.units": "Hospital units",
  "map.areas": "Home areas · primary care",
  "map.area": "Home area {area}",
  "map.meaning": "Quiet means no open signal this week. Resistance can still be present.",
  "map.legend": "Legend",
  "map.gap": "Data gap, cause unknown",
};

/** @type {Partial<typeof en>} */
export const fi = {};
