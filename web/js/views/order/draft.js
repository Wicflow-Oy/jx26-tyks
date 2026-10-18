// The doctor's order draft per demo patient, kept in memory for this tab. A replay step or a trip to My ward
// re-renders the page; the draft (and the orders already signed this visit) is still there afterwards.

const drafts = new Map();

/**
 * The draft for a scenario from GET /api/demo/scenarios. A new draft starts with the order the demo patient's
 * doctor entered (its indication and drug); dosing is never prefilled.
 */
export function draftFor(scenario) {
  if (!drafts.has(scenario.key)) {
    drafts.set(scenario.key, {
      indication: scenario.indication ?? "",
      drug: scenario.drug ?? "",
      dose: "",
      doseUnit: "",
      route: "",
      frequency: "",
      duration: "",
      comment: "",
      detailsOpen: false,
      // the check's card the doctor answered with "Edit the order"; a different drug signed afterwards is a "change"
      edited: null,
      shown: new Set(), // card keys already logged as shown in this draft (CONTRACTS §7b: once per draft)
      signed: [],
    });
  }
  return drafts.get(scenario.key);
}

/** After signing or Clear: an empty order for the same patient and indication; the signed list stays. */
export function resetOrder(draft) {
  Object.assign(draft, {
    drug: "",
    dose: "",
    doseUnit: "",
    route: "",
    frequency: "",
    duration: "",
    comment: "",
    detailsOpen: false,
    edited: null,
    shown: new Set(),
  });
}
