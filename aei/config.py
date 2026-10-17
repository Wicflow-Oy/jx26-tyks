"""Single source of configuration. Change the product name, windows, thresholds and local-guide content here only."""
import os
from pathlib import Path

APP_NAME = "Strainwatch"  # placeholder; the team decides the final name

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("AEI_DATA_DIR", Path(__file__).resolve().parents[3] / "context" / "data" / "synthetic_microbiology_dataset"))
CACHE_DIR = Path(os.environ.get("AEI_CACHE_DIR", ROOT / ".cache"))

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
