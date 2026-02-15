import json
import requests
from datetime import datetime
from typing import Dict, List, Optional

# ============================================================================
# CONFIGURATION
# ============================================================================

EHRBASE_URL = "http://localhost:8080/ehrbase/rest/openehr/v1"
TEMPLATE_ID = "Inpatient_Encounter"  # Match your template name
BACKEND_URL = "http://localhost:3000"


# File paths - UPDATE THESE
PATIENTS_FILE = "clean_patients.json"
ADMISSIONS_FILE = "clean_admissions.json"
LABS_FILE = "clean_labs.json"
PRESCRIPTIONS_FILE = "clean_prescriptions.json"

# ============================================================================
# STEP 1: LOAD DATA
# ============================================================================


def load_json_file(filepath):
    """Load JSON file"""
    with open(filepath, "r") as f:
        return json.load(f)


print("Loading data...")
patients = load_json_file(PATIENTS_FILE)
admissions = load_json_file(ADMISSIONS_FILE)
labs = load_json_file(LABS_FILE)
prescriptions = load_json_file(PRESCRIPTIONS_FILE)

print(f"✓ Loaded {len(patients)} patients")
print(f"✓ Loaded {len(admissions)} admissions")
print(f"✓ Loaded {len(labs)} lab events")
print(f"✓ Loaded {len(prescriptions)} prescriptions")

# ============================================================================
# STEP 2: CREATE EHRs FOR PATIENTS
# ============================================================================

# ehr_mapping = {}  # Maps patient_id -> ehr_id


def create_ehr() -> str:
    url = f"{EHRBASE_URL}/ehr"

    response = requests.post(url)

    if response.status_code == 201:
        # EHR ID is in Location header
        location = response.headers["Location"]
        ehr_id = location.split("/")[-1]
        return ehr_id
    else:
        raise Exception(response.text)


print("\nCreating EHRs for all patients...")

for patient in patients:
    patient_id = patient["patient_id"]

    try:
        # Check if exists first
        response = requests.get(f"{BACKEND_URL}/{patient_id}")
        if response.status_code == 200:
            print(f"○ EHR already exists for patient {patient_id}: {response.json}")

        else:
            ehr_id = create_ehr()  # ← pass patient_id
            print(f"✓ Created EHR for patient {patient_id}: {ehr_id}")
            response = requests.post(
                f"{BACKEND_URL}/{patient_id}",
                json={"ehr_id": ehr_id},
            )

    except Exception as e:
        print(f"✗ Failed for patient {patient_id}: {e}")


# print(f"\n✓ Created {len()} EHRs")
