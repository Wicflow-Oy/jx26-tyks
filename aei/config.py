"""Single source of configuration. Change the product name, windows, thresholds and local-guide content here only."""
import os
from pathlib import Path

APP_NAME = "Strainwatch"  # placeholder; the team decides the final name

ROOT = Path(__file__).resolve().parents[1]


def _load_env_local(path: Path) -> None:
    """Local development only: the team lead puts this app's keys in builds/tyks/.env.local (gitignored). Real environment
    variables win. Values are never printed or logged."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_local(ROOT / ".env.local")


def env(name: str, default: str | None = None) -> str | None:
    """Read an env var; an empty value counts as unset (the server's .env names every variable, most left empty)."""
    v = os.environ.get(name)
    return default if v is None or v.strip() == "" else v.strip()


_DATASET = Path("data") / "synthetic_microbiology_dataset"
_DEV_DATA_CANDIDATES = [
    ROOT.parent / "jx26-tyks-context" / _DATASET,  # context repo cloned next to this one
    ROOT.parent.parent / "context" / _DATASET,  # the original hackathon folder layout
]
_DEV_DATA = next((p for p in _DEV_DATA_CANDIDATES if p.is_dir()), None)
DATA_DIR = Path(env("AEI_DATA_DIR") or _DEV_DATA or ROOT / "data")
CACHE_DIR = Path(env("AEI_CACHE_DIR") or ROOT / ".cache")

DATA_START = "2023-10-02"  # Monday of ISO 2023-W40
DATA_END = "2026-09-27"
REPLAY_FIRST_WEEK = 55  # the replay slider starts at data.week_end(55): detectors need 52 weeks of history before it
RESULT_LAG_DAYS = 2  # susceptibility results usually arrive 2-3 days after sampling; the data has no result time

DRUGS = ["AMP", "MEC", "TZP", "FOX", "CXM", "CRO", "CAZ", "MEM", "CIP", "TMP", "NIT", "VAN", "CLI"]
DRUG_NAMES = {"AMP": "Ampicillin", "MEC": "Mecillinam", "TZP": "Piperacillin-tazobactam", "FOX": "Cefoxitin",
              "CXM": "Cefuroxime", "CRO": "Ceftriaxone", "CAZ": "Ceftazidime", "MEM": "Meropenem", "CIP": "Ciprofloxacin",
              "TMP": "Trimethoprim", "NIT": "Nitrofurantoin", "VAN": "Vancomycin", "CLI": "Clindamycin"}
# WHO AWaRe group of each lab drug (checked against WHO EML 2023, and AWaRe 2021 for agents outside the EML) and a
# fixed display order owned by stewardship
AWARE = {"NIT": "Access", "MEC": "Access", "TMP": "Access", "AMP": "Access", "CLI": "Access",
         "CXM": "Watch", "FOX": "Watch", "CIP": "Watch", "CRO": "Watch", "CAZ": "Watch", "VAN": "Watch", "TZP": "Watch", "MEM": "Watch"}
DISPLAY_ORDER = ["NIT", "MEC", "TMP", "AMP", "CLI", "CXM", "CIP", "CRO", "CAZ", "VAN", "TZP", "MEM", "CRO+VAN", "TZP+VAN", "MEM+VAN"]
HIDDEN_AS_OPTION = {"FOX"}  # cefoxitin is an MRSA screening marker, not a therapy option
URINE_ONLY = {"MEC", "TMP", "NIT"}
COMBOS = {"CRO+VAN": ("CRO", "VAN"), "TZP+VAN": ("TZP", "VAN"), "MEM+VAN": ("MEM", "VAN")}

WINDOWS = {"4w": 28, "4m": 112, "12m": 364}  # days, ending on the as-of date inclusive
WINDOW_LABELS = {"4w": "Last 4 weeks", "4m": "Last 16 weeks", "12m": "Last 52 weeks"}  # 364 days is not 12 months
SMALL_N_NONE = 10  # fewer isolates than this in the window -> "not_enough_data", no percentage
SMALL_N_LOW = 30   # 10..29 -> estimate shown with a "low_n" tag (CLSI M39 style threshold)
ELIGIBLE_MIN_TESTED_SHARE = 0.90  # a drug is shown for a ward x specimen only if tested on >=90% of the organism mix
COVERAGE_DRAWS = 4000
POOLING_K = 20  # pseudo-count pulling small cells toward the hospital-wide rate (same specimen group)
CHANGE_ALPHA = 0.01  # "changed" when P(window < prior 52 weeks) >= 1 - alpha
HOSPITAL_ONSET_MIN_CARE_DAY = 3  # dataset README: sample on care day >= 3, admission day = day 1

AGE_BANDS = [(0, 17, "0-17"), (18, 64, "18-64"), (65, 79, "65-79"), (80, 200, "80+")]
WARD_LABELS = {"ED": "Emergency department", "MED-A": "Internal medicine A", "MED-B": "Internal medicine B", "SURG": "Surgery",
               "URO": "Urology", "ICU": "Intensive care unit", "GER": "Geriatrics", "PHC-N": "Health centre North", "PHC-S": "Health centre South"}
SPECIMEN_GROUPS = {"urine": ["urine"], "blood_wound": ["blood", "wound"], "blood": ["blood"], "wound": ["wound"]}

# Species-level EUCAST facts; both count as R and not covered (aei/phenotype_rules.py).
# INTRINSIC: EUCAST Expected Resistant Phenotypes v1.2 pairs only (S. aureus/S. saprophyticus ceftazidime: rows 4.5/4.1).
INTRINSIC = {"Pseudomonas aeruginosa": {"AMP", "CXM", "CRO", "TMP", "VAN", "CLI"}, "Enterococcus faecalis": {"CXM", "CRO", "CAZ", "CLI"},
             "Klebsiella pneumoniae": {"AMP", "VAN", "CLI"}, "Klebsiella oxytoca": {"AMP", "VAN", "CLI"},
             "Citrobacter freundii": {"AMP", "FOX", "VAN", "CLI"}, "Proteus mirabilis": {"NIT", "VAN", "CLI"},
             "Escherichia coli": {"VAN", "CLI"}, "Staphylococcus aureus": {"CAZ"}, "Staphylococcus saprophyticus": {"CAZ"}}
# NO_BREAKPOINT: EUCAST Breakpoint Tables v16.1 give no breakpoint (a dash: "unsuitable ... report resistant", note 8).
# Enterococci have no meropenem breakpoint. Cefuroxime breakpoints cover only E. coli, Klebsiella, Raoultella and
# P. mirabilis, and Expert Rules v3.3 rule 5 says to report C. freundii cefuroxime R, so its reported S is not counted.
NO_BREAKPOINT = {"Enterococcus faecalis": {"MEC", "MEM"}, "Pseudomonas aeruginosa": {"MEC", "NIT"},
                 "Staphylococcus aureus": {"MEC"}, "Staphylococcus saprophyticus": {"MEC"}, "Citrobacter freundii": {"CXM"}}

# Policy lines (local guide content; the alternative is quoted from the local guide, never chosen by a model)
POLICY_LINES = [
    {"id": "tmp_uti_women_20", "label": "Trimethoprim for uncomplicated UTI in women",
     "organism": "Escherichia coli", "specimen": "urine", "drug": "TMP", "threshold": 0.20,
     "population": {"wards": ["PHC-N", "PHC-S"], "sex": "F"}, "window_days": 364, "counting_rule": "readme_period",
     "message": "Review the empirical UTI guidance", "local_guide_alternative": {"drug": "MEC", "text": "pivmecillinam (local guide)"},
     "order_units": ["ED", "PHC-N", "PHC-S"], "order_indication": "urinary"},
]

# Phenotype consistency checks on reported results (aei/detectors/expert_rules.py implements each id). `text` is shown
# in the brief and holds no digits; `basis` names the rule behind it.
EXPERT_RULES_LABEL = "Phenotype consistency checks (EUCAST expert rules + local rules)"
EXPERT_RULES = [
    {"id": "esbl_ceph_s", "text": "ESBL producer reported S to cefuroxime or ceftriaxone", "organisms": None,
     "basis": "local reporting rule: ESBL producers are reported R to cefuroxime and ceftriaxone"},
    {"id": "mrsa_fox_s", "text": "MRSA-flagged S. aureus reported cefoxitin S", "organisms": ["Staphylococcus aureus"],
     "basis": "EUCAST Staphylococcus expert rule 1: MRSA is a positive cefoxitin screen"},
    # Ceftriaxone resistance in these species comes from beta-lactamases that also hydrolyse ampicillin and cefuroxime.
    # Scope: the species with EUCAST cefuroxime breakpoints (ampicillin S occurs only in E. coli and P. mirabilis).
    {"id": "cro_r_amp_or_cxm_s",
     "text": "Ceftriaxone R with ampicillin S or cefuroxime S (E. coli, Klebsiella spp., P. mirabilis)",
     "organisms": ["Escherichia coli", "Klebsiella pneumoniae", "Klebsiella oxytoca", "Proteus mirabilis"],
     "basis": "local consistency check"},
    {"id": "tzp_r_amp_s", "text": "Piperacillin-tazobactam R with ampicillin S (E. coli, P. mirabilis)",
     "organisms": ["Escherichia coli", "Proteus mirabilis"],
     "basis": "EUCAST Expert Rules v3.3 Enterobacterales rule 1: ampicillin S means piperacillin S"},
]

ALERT_DEFAULT_EXPIRY_DAYS = 14

# Demo story: each beat is a real Monday brief (data to the Sunday before). See CONTRACTS.md section 7.
DEMO_MONDAYS = ["2025-06-09", "2025-12-15", "2026-03-09", "2026-06-22", "2026-09-14"]
ROLES = {"infection_control": "Infection control", "ward_doctor": "Ward doctor"}

# ATC codes for reading orders (CDS Hooks MedicationRequest coding). Pivmecillinam is the oral prodrug of mecillinam.
ATC = {"J01CA01": "AMP", "J01CA08": "MEC", "J01CA11": "MEC", "J01CR05": "TZP", "J01DC01": "FOX", "J01DC02": "CXM",
       "J01DD04": "CRO", "J01DD02": "CAZ", "J01DH02": "MEM", "J01MA02": "CIP", "J01EA01": "TMP", "J01XE01": "NIT",
       "J01XA01": "VAN", "J01FF01": "CLI", "J01CA04": "AMP"}
ATC_NOTES = {"J01CA04": "Amoxicillin is read from the ampicillin result (EUCAST infers amoxicillin from ampicillin)."}
ORDER_DRUG_NAMES = {"MEC": "Pivmecillinam"}  # what a prescriber orders when the lab reports mecillinam

# ---------------------------------------------------------------------------------------------------------------
# Doctor's view (order screen). Everything below marked "example, to be set by Tyks" is illustrative local content.
ATC["J01CF05"] = "FOX"  # flucloxacillin: S. aureus susceptibility is read from the cefoxitin screen (MRSA = FOX R)
ORDER_DRUGS = [  # what the drug picker offers: (code used in the data, name a prescriber orders, ATC)
    ("MEC", "Pivmecillinam", "J01CA08"), ("NIT", "Nitrofurantoin", "J01XE01"), ("TMP", "Trimethoprim", "J01EA01"),
    ("AMP", "Ampicillin", "J01CA01"), ("FOX", "Flucloxacillin", "J01CF05"), ("CLI", "Clindamycin", "J01FF01"),
    ("CXM", "Cefuroxime", "J01DC02"), ("CIP", "Ciprofloxacin", "J01MA02"), ("CRO", "Ceftriaxone", "J01DD04"),
    ("CAZ", "Ceftazidime", "J01DD02"), ("VAN", "Vancomycin", "J01XA01"), ("TZP", "Piperacillin-tazobactam", "J01CR05"),
    ("MEM", "Meropenem", "J01DH02")]
# WHO AWaRe of what is ordered: flucloxacillin is Access, although the cefoxitin screen it is read from is Watch
ORDER_AWARE = {name: AWARE[code] for code, name, _ in ORDER_DRUGS} | {"Flucloxacillin": "Access"}
BETA_LACTAMS = {"AMP", "MEC", "TZP", "FOX", "CXM", "CRO", "CAZ", "MEM"}
# This laboratory reports ESBL producers R to cefuroxime and ceftriaxone (0 of 517 ESBL isolates reported S). A local
# rule: EUCAST reports cephalosporins as tested (Breakpoint Tables v16.1, Enterobacterales cephalosporin note 1).
LOCAL_ESBL_R = {"CXM", "CRO"}
INDICATIONS = {
    "uti": {"label": "Urinary tract infection", "specimen": "urine", "reference_organism": "Escherichia coli", "sex_matched": True},
    "bloodstream": {"label": "Bloodstream infection", "specimen": "blood", "reference_organism": None, "sex_matched": False},
    "wound": {"label": "Wound infection", "specimen": "wound", "reference_organism": None, "sex_matched": False},
}
COMMUNITY_UNITS = {"ED", "PHC-N", "PHC-S"}  # for these, unit numbers use the patient's home area (ED + primary care)
# Empirical-use lines per indication (example, to be set by Tyks). Info banner when the unit's observed resistance is
# within INFO_MARGIN below the line or above it. Never interruptive on its own.
EMPIRICAL_LINES = {"uti": {"TMP": 0.20, "_default": 0.10}, "bloodstream": {"_default": 0.10}, "wound": {"_default": 0.10}}
INFO_MARGIN = 0.03
# Local guide examples, shown as "example, to be set by Tyks". `sex` None fits either; `source` is shown when given.
LOCAL_GUIDE_EXAMPLE = [
    {"indication": "uti", "sex": "F", "drugs": ["MEC", "NIT", "TMP"],
     "source": "Käypä hoito 2024: uncomplicated cystitis in women"},
    {"indication": "uti", "sex": "M", "drugs": ["TMP", "NIT"],
     "source": "Käypä hoito 2024: afebrile lower UTI in men; nitrofurantoin only if confined to the bladder, "
               "not for prostatitis"},
    {"indication": "bloodstream", "sex": None, "drugs": ["CRO", "TZP", "MEM"], "source": None},
    {"indication": "wound", "sex": None, "drugs": ["FOX", "CLI", "CXM"], "source": None},
]
NO_GUIDE_ALTERNATIVE = "No alternative in the local guide example covers this pattern; discuss with infectious diseases."


def local_guide_example(indication: str, sex: str | None) -> dict | None:
    """The guide example for an indication and the patient's sex; None when there is none (a uti without a patient)."""
    return next((g for g in LOCAL_GUIDE_EXAMPLE if g["indication"] == indication and g["sex"] in (None, sex)), None)


KEEP_REASONS = ["Discussed with infectious diseases", "Patient-specific reason", "Previous result supports it", "Other"]

# Demo seeds: infection-control-approved alerts. `resistant_to` is what the flagged antibiogram is R to: its reported R
# plus what its marker implies (MRSA: every beta-lactam). The alert covers exactly those drugs. Messages and
# antibiograms are checked against the raw data in tests/test_against_source.py.
_URO_ESBL_R = ["AMP", "CXM", "CRO", "CIP", "TMP"]
_ICU_MRSA_R = sorted(BETA_LACTAMS | {"CLI"})
DEMO_ALERT_SEEDS = [
    {"id": "seed-uro-esbl-2025", "wards": ["URO"], "drugs": _URO_ESBL_R, "resistant_to": _URO_ESBL_R,
     "organism": "Escherichia coli", "specimen": "urine", "approved_on": "2025-06-09", "expires_on": "2025-06-23",
     "approved_by_role": "Infection control",
     "message": "Possible ESBL E. coli cluster, URO: 6 patients since 30 May with one antibiogram (ampicillin, "
                "cefuroxime, ceftriaxone, ciprofloxacin and trimethoprim R). Usually about 1 ESBL E. coli patient a "
                "month. Under investigation."},
    {"id": "seed-icu-mrsa-2026", "wards": ["ICU"], "drugs": _ICU_MRSA_R, "resistant_to": _ICU_MRSA_R,
     "organism": "Staphylococcus aureus", "specimen": None, "approved_on": "2026-03-09", "expires_on": "2026-03-23",
     "approved_by_role": "Infection control",
     "message": "Unusual MRSA pattern, ICU: 3 patients with one antibiogram (cefoxitin R, clindamycin R, vancomycin S) "
                "since 3 Mar. None of the beta-lactams on this panel cover MRSA (ceftaroline and ceftobiprole "
                "excepted). Under investigation; typing advised."},
]
# Doctor's-view demo scenarios (synthetic patients from the dataset; checked by tests/test_demo_scenarios.py)
DEMO_SCENARIOS = [
    {"key": "uro-esbl", "as_of": "2025-06-15", "patient_id": "P001948", "unit": "URO", "indication": "uti", "drug": "CRO",
     "expect": "warning", "why": "approved URO ESBL alert covers ceftriaxone"},  # a woman: the clone is 10 women, 1 man
    {"key": "phc-tmp", "as_of": "2026-06-21", "patient_id": "P001889", "unit": "PHC-N", "indication": "uti", "drug": "TMP",
     "expect": "info", "why": "primary-care women's trimethoprim above the local 20% line"},
    {"key": "icu-mrsa", "as_of": "2026-03-15", "patient_id": "P003851", "unit": "ICU", "indication": "wound", "drug": "CXM",
     "expect": "warning", "why": "approved ICU MRSA alert covers beta-lactams"},
    {"key": "medb-quiet", "as_of": "2026-03-15", "patient_id": "P005490", "unit": "MED-B", "indication": "uti", "drug": "NIT",
     "expect": "quiet", "why": "no alert, no line near, previous isolate susceptible"},
    {"key": "ed-own-history", "as_of": "2026-03-15", "patient_id": "P008135", "unit": "ED", "indication": "uti", "drug": "TMP",
     "expect": "warning", "why": "this patient's E. coli of 16 Jan 2026 was trimethoprim R"},
]

# Guided tour for judges: the replay starts just before the ICU cluster
TOUR_START_AS_OF = "2026-03-01"

# ---------------------------------------------------------------------------------------------------------------
# Public deployment guards (env-overridable)
PUBLIC = env("AEI_PUBLIC", "0") == "1"
STATE_DB = Path(env("AEI_STATE_DB") or CACHE_DIR / "state.sqlite")  # writable; may be ephemeral (/tmp)
DAILY_SPEND_USD = float(env("AEI_DAILY_SPEND_USD", "20"))
RATE_LIMIT_PER_MIN = int(env("AEI_RATE_LIMIT_PER_MIN", "120"))      # all API requests per IP
LLM_RATE_LIMIT_PER_MIN = int(env("AEI_LLM_RATE_LIMIT_PER_MIN", "6"))  # live model calls per IP
LLM_RATE_LIMIT_PER_DAY = int(env("AEI_LLM_RATE_LIMIT_PER_DAY", "60"))
SESSION_HEADER = "X-Demo-Session"  # random id from the browser; scopes judges' approvals and order feedback
MAX_WRITES_PER_SESSION = int(env("AEI_MAX_WRITES_PER_SESSION", "200"))
