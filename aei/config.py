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


_DEV_DATA = ROOT.parent.parent / "context" / "data" / "synthetic_microbiology_dataset"  # the hackathon folder layout
DATA_DIR = Path(env("AEI_DATA_DIR") or (_DEV_DATA if _DEV_DATA.is_dir() else ROOT / "data"))
CACHE_DIR = Path(env("AEI_CACHE_DIR") or ROOT / ".cache")

DATA_START = "2023-10-02"  # Monday of ISO 2023-W40
DATA_END = "2026-09-27"
RESULT_LAG_DAYS = 2  # susceptibility results usually arrive 2-3 days after sampling; the data has no result time

DRUGS = ["AMP", "MEC", "TZP", "FOX", "CXM", "CRO", "CAZ", "MEM", "CIP", "TMP", "NIT", "VAN", "CLI"]
DRUG_NAMES = {"AMP": "Ampicillin", "MEC": "Mecillinam", "TZP": "Piperacillin-tazobactam", "FOX": "Cefoxitin",
              "CXM": "Cefuroxime", "CRO": "Ceftriaxone", "CAZ": "Ceftazidime", "MEM": "Meropenem", "CIP": "Ciprofloxacin",
              "TMP": "Trimethoprim", "NIT": "Nitrofurantoin", "VAN": "Vancomycin", "CLI": "Clindamycin"}
# WHO AWaRe group (team's reading; MEC/FOX/VAN groups to verify) and a fixed display order owned by stewardship
AWARE = {"NIT": "Access", "MEC": "Access", "TMP": "Access", "AMP": "Access", "CLI": "Access",
         "CXM": "Watch", "FOX": "Watch", "CIP": "Watch", "CRO": "Watch", "CAZ": "Watch", "VAN": "Watch", "TZP": "Watch", "MEM": "Watch"}
DISPLAY_ORDER = ["NIT", "MEC", "TMP", "AMP", "CLI", "CXM", "CIP", "CRO", "CAZ", "VAN", "TZP", "MEM", "CRO+VAN", "TZP+VAN", "MEM+VAN"]
HIDDEN_AS_OPTION = {"FOX"}  # cefoxitin is an MRSA screening marker, not a therapy option
URINE_ONLY = {"MEC", "TMP", "NIT"}
COMBOS = {"CRO+VAN": ("CRO", "VAN"), "TZP+VAN": ("TZP", "VAN"), "MEM+VAN": ("MEM", "VAN")}

WINDOWS = {"4w": 28, "4m": 112, "12m": 364}  # days, ending on the as-of date inclusive
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

# EUCAST intrinsic resistance and "no breakpoint" pairs count as not covered (from the analysis code, 26_trace)
INTRINSIC = {"Pseudomonas aeruginosa": {"AMP", "CXM", "CRO", "TMP", "VAN", "CLI"}, "Enterococcus faecalis": {"CXM", "CRO", "CAZ", "CLI"},
             "Klebsiella pneumoniae": {"AMP", "VAN", "CLI"}, "Klebsiella oxytoca": {"AMP", "VAN", "CLI"},
             "Citrobacter freundii": {"AMP", "CXM", "FOX", "VAN", "CLI"}, "Proteus mirabilis": {"NIT", "VAN", "CLI"},
             "Escherichia coli": {"VAN", "CLI"}, "Staphylococcus aureus": {"CAZ"}, "Staphylococcus saprophyticus": {"CAZ"}}
NO_BREAKPOINT = {"Enterococcus faecalis": {"MEC"}, "Pseudomonas aeruginosa": {"MEC", "NIT"},
                 "Staphylococcus aureus": {"MEC"}, "Staphylococcus saprophyticus": {"MEC"}}

# Policy lines (local guide content; the alternative is quoted from the local guide, never chosen by a model)
POLICY_LINES = [
    {"id": "tmp_uti_women_20", "label": "Trimethoprim for uncomplicated UTI in women",
     "organism": "Escherichia coli", "specimen": "urine", "drug": "TMP", "threshold": 0.20,
     "population": {"wards": ["PHC-N", "PHC-S"], "sex": "F"}, "window_days": 364, "counting_rule": "readme_period",
     "message": "Review the empirical UTI guidance", "local_guide_alternative": {"drug": "MEC", "text": "pivmecillinam (local guide)"},
     "order_units": ["ED", "PHC-N", "PHC-S"], "order_indication": "urinary"},
]

# Shallow EUCAST expert-rule layer: (description, test on an isolate row) -- implausible or rule-breaking combinations
EXPERT_RULES = [
    {"id": "esbl_ceph_s", "text": "ESBL-flagged but susceptible to cefuroxime or ceftriaxone", "organisms": None},
    {"id": "mrsa_fox_s", "text": "MRSA-flagged but cefoxitin susceptible", "organisms": ["Staphylococcus aureus"]},
    {"id": "cro_r_amp_s", "text": "Ceftriaxone R with ampicillin S (E. coli)", "organisms": ["Escherichia coli"]},
    {"id": "cro_r_cxm_s", "text": "Ceftriaxone R with cefuroxime S", "organisms": ["Escherichia coli", "Klebsiella pneumoniae"]},
]

ALERT_DEFAULT_EXPIRY_DAYS = 14

# Demo story: each beat is a real Monday brief (data to the Sunday before). See CONTRACTS.md section 7.
DEMO_MONDAYS = ["2025-06-09", "2025-12-15", "2026-03-09", "2026-06-22", "2026-09-14"]
ROLES = {"infection_control": "Infection control", "ward_doctor": "Ward doctor"}

# ATC codes for reading orders (CDS Hooks MedicationRequest coding). Pivmecillinam is the oral prodrug of mecillinam.
ATC = {"J01CA01": "AMP", "J01CA08": "MEC", "J01CA11": "MEC", "J01CR05": "TZP", "J01DC01": "FOX", "J01DC02": "CXM",
       "J01DD04": "CRO", "J01DD02": "CAZ", "J01DH02": "MEM", "J01MA02": "CIP", "J01EA01": "TMP", "J01XE01": "NIT",
       "J01XA01": "VAN", "J01FF01": "CLI"}
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
BETA_LACTAMS = {"AMP", "MEC", "TZP", "FOX", "CXM", "CRO", "CAZ", "MEM"}
ESBL_IMPLIED_R = {"AMP", "CXM", "CRO", "CAZ"}  # EUCAST expert rule: ESBL -> resistant to penicillins and cephalosporins
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
LOCAL_GUIDE_EXAMPLE = {  # label shown on screen: "Example, to be set by Tyks"
    "uti": ["MEC", "NIT", "TMP"],
    "bloodstream": ["CRO", "TZP", "MEM"],
    "wound": ["FOX", "CLI", "CXM"],
}
KEEP_REASONS = ["Discussed with infectious diseases", "Patient-specific reason", "Previous result supports it", "Other"]

# Demo seeds: infection-control-approved alerts. The numbers in `message` are verified by tests/test_demo_scenarios.py.
DEMO_ALERT_SEEDS = [
    {"id": "seed-uro-esbl-2025", "wards": ["URO"], "drugs": ["CXM", "CRO", "CAZ"], "organism": "Escherichia coli",
     "specimen": "urine", "approved_on": "2025-06-09", "expires_on": "2025-06-23", "approved_by_role": "Infection control",
     "message": "Possible ESBL E. coli cluster, URO: 6 patients in 14 days (usually about 1 a month). Under investigation."},
    {"id": "seed-icu-mrsa-2026", "wards": ["ICU"], "drugs": sorted(BETA_LACTAMS), "organism": "Staphylococcus aureus",
     "specimen": None, "approved_on": "2026-03-09", "expires_on": "2026-03-23", "approved_by_role": "Infection control",
     "message": "Unusual MRSA pattern, ICU: 3 patients with one antibiogram (cefoxitin R, clindamycin R, vancomycin S) "
                "since 3 Mar. Beta-lactams do not cover MRSA. Under investigation; typing advised."},
]
# Doctor's-view demo scenarios (synthetic patients from the dataset; checked by tests/test_demo_scenarios.py)
DEMO_SCENARIOS = [
    {"key": "uro-esbl", "as_of": "2025-06-15", "patient_id": "P002543", "unit": "URO", "indication": "uti", "drug": "CRO",
     "expect": "warning", "why": "approved URO ESBL alert covers ceftriaxone"},
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
