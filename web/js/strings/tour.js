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
    "When a doctor orders an antibiotic, the order card checks the drug entered. If something is going on, such as an active alert or a possible cluster on the unit, it flags that drug and asks whether it still fits. The doctor decides.",
};

/** @type {Partial<typeof en>} */
export const fi = {
  count: "Esittely · {n}/{total}",
  skip: "Ohita",
  back: "Takaisin",
  next: "Seuraava",
  done: "Valmis",

  brief:
    "Maanantaikatsaus on infektioiden torjunnan aloitusnäkymä. Tämä katsaus kattaa {date} päättyvän viikon. Yksi päivämäärä ohjaa kaikkia näkymiä, eikä myöhemmin otettuja näytteitä käytetä.",
  howStep: "Nuolet ja aikajana siirtävät viikon kerrallaan.",
  howStepCompact: "Päivämääräpainike avaa aikajanan, viikko kerrallaan.",
  pattern: "Viikkoa myöhemmin, katsauksessa {date}, näkyy uusi signaali ({priority}): ”{title}”. {how}",
  patternNone: "Viikkoa myöhemmin: katsaus {date}. {how}",
  case: "Tapauksen tiedot kokoavat näytön, johon signaali ”{title}” perustuu (tilanne {date}). Toimintopalkista infektioiden torjunta voi hyväksyä yksikölle hälytyksen. Mitään ei lähetetä; hyväksynnät jäävät tähän demoistuntoon.",
  caseNone:
    "Tapauksen tiedot kokoavat näytön, johon signaali perustuu. Toimintopalkista infektioiden torjunta voi hyväksyä yksikölle hälytyksen. Mitään ei lähetetä; hyväksynnät jäävät tähän demoistuntoon.",
  ward: "Yläreunan roolivalinnalla vaihdetaan osastolääkärin näkymään. Oma osasto näyttää yhden yksikön, tässä {ward}: kuinka usein kukin lääke kattoi yksikön tuoreet isolaatit ja onko infektioiden torjunta hyväksynyt yksikölle hälytyksen.",
  wardNone:
    "Yläreunan roolivalinnalla vaihdetaan osastolääkärin näkymään. Oma osasto näyttää yhden yksikön: kuinka usein kukin lääke kattoi yksikön tuoreet isolaatit ja onko infektioiden torjunta hyväksynyt yksikölle hälytyksen.",
  order:
    "Kun lääkäri kirjaa antibioottimääräyksen, määräyskortti tarkistaa syötetyn lääkkeen. Jos yksikössä on jotain meneillään, kuten voimassa oleva hälytys tai mahdollinen rypäs, kortti merkitsee lääkkeen ja kysyy, sopiiko se edelleen. Lääkäri päättää.",
};
