// Case file strings. Read as t("case.<key>").

export const en = {
  title: "Case file",
  loading: "Loading the case file",
  error: "The case file did not load.",
  none: "Choose a signal to see its case file.",
  notThisWeek: "This signal is not in the brief of {date}. Step the replay to a week where it is open.",

  // the one-line caveat under the title
  "caveat.phenotype_cluster":
    "Possible cluster. A shared antibiogram is a proxy for one clone until typing confirms it.",
  "caveat.seen_before": "Profile match, not typing.",
  "caveat.gap": "Data gap, cause unknown.",

  "meta.unit": "Unit",
  "meta.organism": "Organism",
  "meta.drug": "Drug",
  "meta.firstSample": "First sample",
  "meta.firstAlert": "First alert",
  "meta.patients": "Patients",
  "meta.same": "Same antibiogram",
  "meta.ofN": "of {n}",
  "meta.plusDays": "+{n} days",
  "meta.from": "From",
  "meta.to": "To",
  "meta.all": "All",
  "meta.allUnits": "All units",
  "meta.nUnits": "{n} units",

  "sec.see": "What we see",
  "sec.explanations": "Competing explanations",
  "sec.explanationsHint": "rated from counts only",
  "explanations.counts": "Counts behind the ratings",
  "sec.seen": "Seen before",
  "sec.seenHint": "profile match, not typing",
  "sec.list": "Line list",
  "sec.listHint.one": "{n} row · synthetic id",
  "sec.listHint.other": "{n} rows · synthetic ids",
  "sec.status": "Status",
  "sec.statusHint": "brief of {date}",

  // footnotes
  "note.counts": "Counts",
  "note.method": "Method",
  "note.profile": "Profile match, not typing",
  "note.profileText": "An identical antibiogram is a cheap first proxy. Typing confirms or rules out a link.",
  "note.lab": "For the lab",

  // the method in plain words; numbers and parameters are in Method details
  "method.phenotype_cluster":
    "Patients on one unit who share one exact antibiogram within a few weeks, tested against the unit's earlier year. The antibiogram must be rare on that unit.",
  "method.thl_rule":
    "THL guidance rules: every CPE and VRE case, and same-unit ESBL or MRSA counts above the usual level.",
  "method.count_stepup":
    "A test for a step change in the weekly count of new patients on a unit, against its earlier weeks.",
  "method.resistance_change":
    "Recent results on this unit against its own earlier weeks, pooled toward the hospital rate; a change test on counts.",
  "method.ward_outlier":
    "Organism and drug results above this unit's usual range in recent weeks, compared with the other units.",
  "method.seen_before":
    "Earlier patients with the same organism and exact antibiogram, by unit, and how common that antibiogram is overall.",
  "method.policy_line":
    "The rolling resistant share under the line's counting rule, against the line set by infection control.",
  "method.expert_rule": "Phenotype consistency checks (EUCAST expert rules and local rules) on reported S/R results.",
  "method.completeness":
    "Cultures this week against the unit's previous weeks. A missing week is a data gap, cause unknown.",
  "method.quiet": "Units with no open signal this week.",

  // what we see
  "cluster.readout": "{n} patients since {date}; {shared} share one antibiogram.",
  "cluster.firstAlert": "First alert {date}, {days} days after the first sample.",
  "cluster.shared": "Shared antibiogram",
  "cluster.expected":
    "{n} patients since {date}. In a whole year {unit} expects about {expected} (usually {low}–\u2060{high} a year).",
  "cluster.onset": "{share} hospital-onset.",
  "stepup.positive": "Count step-up: supports a change",
  "stepup.negative": "Count step-up: no change shown",
  "stepup.counts":
    "{n} new patients to {date}; usually {low}–\u2060{high} in the same time, from the {weeks} weeks before.",
  "stepup.only": "Supporting evidence only; it describes past counts.",
  "window.last": "Last {weeks} weeks",
  "window.before": "{weeks} weeks before",
  "window.flagged": "When last flagged, week ending {date}",
  "change.expected":
    "About {expected} resistant expected at the usual rate. Hospital, {weeks} weeks before: {hospital}.",
  "outlier.caption": "Organism and drug pairs above the usual range",
  "outlier.pair": "Organism · drug",
  "outlier.before": "Before",
  "policy.crossed": "Crossed in the week ending {date}.",
  "lab.readout": "{counts} checked results inconsistent with the expected phenotype this week.",
  "lab.byUnit": "By unit: {units}.",
  "lab.forLab": "Check the reported results. This is not a clinical signal.",
  resistant: "resistant",

  "seen.bars": "Earlier patients with the same antibiogram before {date}, by unit",
  "seen.back": "Back on {unit} on {dates}.",
  "seen.cluster": "The cluster began {date} with {n} patients.",

  // epi curve
  "epi.shares": "Shares {pattern}",
  "epi.other": "Other antibiogram",
  "epi.numbers.patients": "Numbers: patients to date",
  "epi.numbers.isolates": "Numbers: isolates to date",
  "epi.asOf": "as of {date}",
  "epi.firstAlert": "first alert",
  "epi.summary.patients": "Patients by sample date: {n} since {date}",
  "epi.summary.isolates": "Isolates by sample date: {n} since {date}",
  "epi.summary.shared": "{n} with the shared antibiogram",
  "epi.summary.alert": "first alert {date}",
  "epi.summary.asOf": "as of {date}.",

  // line list
  "list.show.one": "Show {n} row",
  "list.show.other": "Show {n} rows",
  "list.showSome": "Show the latest {n} of {total} rows",
  "list.hint": "sample date · care day",
  "list.caption": "Line list",
  "list.region": "Line list table",
  "list.isolate": "Isolate",
  "list.sample": "Sample",
  "list.unit": "Unit",
  "list.organism": "Organism",
  "list.specimen": "Specimen",
  "list.day": "Care day",
  "list.shaded": "Shaded rows have another antibiogram.",

  // status timeline
  "status.detected": "Detected {date}",
  "status.detectedSub": "first alert, {n} days after the first sample",
  "status.inBrief": "In the brief of {date}",
  "status.firstSample": "first sample {date}",
  "status.approved": "Approved {date} by infection control",
  "status.seed": "Demo seed",
  "status.until": "until {date}",
  "status.expired": "Approved {approved} · expired {until}",
  "status.again": "Approve again?",
  "status.notApproved": "No active alert",
  "status.waiting": "An approved alert shows on My ward and in the order form",
  "status.headsUp": "Heads-up to the ED",
  "status.notDrafted": "Not drafted",
  "status.huDrafted": "Heads-up drafted · brief of {date}",
  "status.huApproved": "Heads-up approved · brief of {date}",
  "status.toEd": "To the emergency department",
  "status.delivery": "Delivery",
  "status.notSent": "Not sent (demo). Nothing leaves {app}.",

  // method details
  methodDetails: "Method details",
  methodHint: "re-runnable filter",
  methodPast: "Statistics describe past counts.",
  "kv.unit": "Unit",
  "kv.specimen": "Specimen",
  "kv.organism": "Organism",
  "kv.drug": "Drug",
  "kv.antibiogram": "Antibiogram",
  "kv.dates": "Sample dates",
  "kv.range": "{from} to {to}",
  "kv.to": "to {date}",
  "kv.rule": "Counting rule",
  "rule.all_cultures": "All cultures",
  "rule.all_isolates": "All isolates",
  "kv.days": "{n} days",
  "kv.weeks": "{n} weeks",
  "kv.countTest": "Count test",
  "kv.identityTest": "Identity test",
  "kv.stepup": "Step-up",
  "kv.bf": "log10 Bayes factor {bf}",
  "kv.expected": "Expected",
  "kv.perYear": "{n} a year",
  "kv.perWeek": "{n} a week",
  "kv.resistant": "{n} resistant",
  "param.window_days": "Window",
  "param.prior_days": "Compared with",
  "param.history_days": "History",
  "param.learning_days": "Learning period",
  "param.active_days": "Shown for",
  "param.min_patients": "Minimum patients",
  "param.min_resistant": "Minimum resistant",
  "param.min_tested": "Minimum tested",
  "param.rarity_max_share": "Rarity limit",
  "param.threshold": "Line",
  "param.alpha": "Significance",
  "param.midp_alpha": "Significance",

  // actions
  "actions.approve": "Approve alert",
  "actions.again": "Approve again",
  "actions.active": "Alert active · until {date}",
  "actions.huDraft": "Draft heads-up to ED",
  "actions.huOpen": "Open heads-up draft",
  "actions.huApproved": "Approved · not sent",
  "actions.note": "Nothing is sent. Approvals and drafts stay in this demo session.",
  "actions.noteOnly": "For the lab and infection control. Nothing is sent from {app}.",
  "toast.approved": "Alert approved until {date}. Nothing sent.",
  "toast.huApproved": "Heads-up approved. Not sent (demo).",

  // sidebar lists of this session's alerts and drafts (session-lists.js)

  // heads-up sheet
  "hu.eyebrowDraft": "Heads-up · draft",
  "hu.eyebrowApproved": "Heads-up · approved",
  "hu.title": "To the emergency department",
  "hu.to": "To",
  "hu.message": "Message",
  "hu.rendered": "Rendered from computed numbers only. Sample dates; results arrive a couple of days later.",
  "hu.noteDraft": "Approving marks the draft ready. Nothing is ever sent from the prototype.",
  "hu.noteApproved": "Approved by infection control. Not sent (demo): nothing leaves {app}.",
  "hu.keep": "Keep as draft",
  "hu.approve": "Approve draft",
  "hu.done": "Done",
  "hu.notSent": "Not sent (demo)",
};

/** @type {Partial<typeof en>} */
export const fi = {};
