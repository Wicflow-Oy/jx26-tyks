// Guided tour strings: usage only, no claims. Read as t("tour.<key>").

export const en = {
  count: "Tour · {n} of {total}",
  skip: "Skip",
  back: "Back",
  next: "Next",
  done: "Done",

  brief:
    "The Monday brief is the home for infection control. This one covers the week up to {date}. One date drives every view, and nothing sampled later is used.",
  howStep: "The arrows and the replay rail step one week at a time.",
  howStepCompact: "The date button opens the replay, one week at a time.",
  pattern: "One week later, in the brief of {date}, a new {priority} signal appears: {title}. {how}",
  patternNone: "One week later: the brief of {date}. {how}",
  case: "The case file holds the evidence behind {title}, as of {date}. From its action bar, infection control can approve an alert for the unit. Nothing is sent; approvals stay in this demo session.",
  caseNone:
    "The case file holds the evidence behind a signal. From its action bar, infection control can approve an alert for the unit. Nothing is sent; approvals stay in this demo session.",
  ward: "The role switch at the top changes to Ward doctor. My ward shows one unit, here {ward}: how often each drug covered its recent isolates, and any alert infection control has approved for it.",
  wardNone:
    "The role switch at the top changes to Ward doctor. My ward shows one unit: how often each drug covered its recent isolates, and any alert infection control has approved for it.",
  order:
    "When a doctor orders an antibiotic, the order card checks the drug entered. If something is going on, such as an active alert or a possible cluster on the unit, it flags that drug and notes that other drugs could be considered. The doctor decides.",
};

/** @type {Partial<typeof en>} */
export const fi = {};
