import json
from collections import defaultdict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from service_config import BACKEND_BASE_URL, EHRBASE_API_URL

# ============================================================================
# CONFIGURATION
# ============================================================================

TEMPLATE_ID = "Inpatient_Encounter"
EPISODE_ARCHETYPE = "openEHR-EHR-ADMIN_ENTRY.episode_institution.v0"


PATIENTS_FILE = "clean_patients.json"
ADMISSIONS_FILE = "clean_admissions.json"
LABS_FILE = "clean_labs.json"
PRESCRIPTIONS_FILE = "clean_prescriptions.json"
HTTP_TIMEOUT = 20


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = _build_session()

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


def create_ehr() -> str:
    url = f"{EHRBASE_API_URL}/ehr"

    try:
        response = SESSION.post(url, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to create EHR: {exc}") from exc

    if response.status_code == 201:
        location = response.headers.get("Location", "")
        ehr_id = location.rstrip("/").split("/")[-1]
        if not ehr_id:
            raise RuntimeError("EHRbase returned 201 but no Location header")
        return ehr_id

    raise RuntimeError(
        f"EHR creation failed with {response.status_code}: {response.text}"
    )


def cache_ehr_id(patient_id: int, ehr_id: str) -> bool:
    try:
        response = SESSION.post(
            f"{BACKEND_BASE_URL}/{patient_id}",
            json={"ehr_id": ehr_id},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"✗ Unable to cache EHR ID for patient {patient_id}: {exc}")
        return False

    if response.status_code in (200, 201):
        return True
    if response.status_code == 403:
        print(f"✗ Backend already has mapping for patient {patient_id}")
        return False

    print(
        f"✗ Backend rejected mapping for patient {patient_id} "
        f"({response.status_code}): {response.text}"
    )
    return False



def commit_composition(ehr_id: str, composition: dict) -> str:
    """
    POST a composition to EHRbase.
    Returns the versioned_object_uid (from ETag header) on success.
    Raises on failure.
    """
    url = f"{EHRBASE_API_URL}/ehr/{ehr_id}/composition"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }

    try:
        response = SESSION.post(
            url,
            json=composition,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Request to EHRbase failed for EHR {ehr_id}: {exc}") from exc

    if response.status_code == 201:
        # ETag looks like: "abc123::local.ehrbase.org::1"
        # Strip the surrounding quotes EHRbase adds
        versioned_uid = response.headers.get("ETag", "").strip('"')
        return versioned_uid
    else:
        raise RuntimeError(
            f"Failed to commit composition for EHR {ehr_id}: "
            f"{response.status_code} — {response.text}"
        )


# after loading


def fetch_existing_admissions() -> set[int]:
    """Return admission_ids that already have compositions in EHRbase."""
    query = f"""
    SELECT
        c/content[{EPISODE_ARCHETYPE}]/data[at0001]/items[at0014]/value/id AS admission_id
    FROM EHR e
    CONTAINS COMPOSITION c
    WHERE c/archetype_details/template_id/value = '{TEMPLATE_ID}'
    """

    try:
        response = SESSION.post(
            f"{EHRBASE_API_URL}/query/aql",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"q": query},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        print(f"✗ Unable to fetch existing admissions from EHRbase: {exc}")
        return set()

    idx = 0
    for i, col in enumerate(payload.get("columns", [])):
        if col.get("name") == "admission_id":
            idx = i
            break

    existing = set()
    for row in payload.get("rows", []):
        value = row[idx]
        if value is None:
            continue
        try:
            existing.add(int(value))
        except (TypeError, ValueError):
            continue
    return existing


def get_ehr_id_from_cache(patient_id: int, *, log_missing: bool = True) -> str | None:
    try:
        response = SESSION.get(
            f"{BACKEND_BASE_URL}/{patient_id}", timeout=HTTP_TIMEOUT
        )
    except requests.RequestException as exc:
        print(f"✗ Unable to reach backend for patient {patient_id}: {exc}")
        return None

    if response.status_code == 404:
        if log_missing:
            print(f"✗ Missing EHR mapping for patient {patient_id}")
        return None

    if response.status_code != 200:
        print(
            f"✗ Backend returned {response.status_code} for patient {patient_id}: {response.text}"
        )
        return None

    try:
        payload = response.json()
    except ValueError:
        print(f"✗ Backend returned invalid JSON for patient {patient_id}")
        return None

    if isinstance(payload, str):
        return payload

    print(f"✗ Unexpected backend payload for patient {patient_id}: {payload}")
    return None


print("\nCreating EHRs for all patients...")

for patient in patients:
    patient_id = int(patient["patient_id"])

    cached_ehr = get_ehr_id_from_cache(patient_id, log_missing=False)

    if cached_ehr:
        print(f"○ EHR already exists for patient {patient_id}: {cached_ehr}")
        continue

    try:
        ehr_id = create_ehr()
    except RuntimeError as exc:
        print(f"✗ Failed to create EHR for patient {patient_id}: {exc}")
        continue

    if cache_ehr_id(patient_id, ehr_id):
        print(f"✓ Created EHR for patient {patient_id}: {ehr_id}")

# -------------------------------------------------
# STEP 2: Build Lookup Maps
# -------------------------------------------------

# A) Labs grouped by admission_id
labs_by_admission = defaultdict(list)

for lab in labs:
    admission_id = lab.get("admission_id")

    if admission_id is None:
        continue

    # Convert float IDs like 29600294.0 → 29600294
    admission_id = int(admission_id)

    labs_by_admission[admission_id].append(lab)


# B) Prescriptions grouped by admission_id
prescriptions_by_admission = defaultdict(list)

for rx in prescriptions:
    admission_id = rx.get("admission_id")

    if admission_id is None:
        continue

    admission_id = int(admission_id)

    prescriptions_by_admission[admission_id].append(rx)


# C) Admissions grouped by patient_id
admissions_by_patient = defaultdict(list)

for admission in admissions:
    patient_id = admission.get("patient_id")
    admission_id = admission.get("admission_id")

    if patient_id is None or admission_id is None:
        continue

    patient_id = int(patient_id)
    admission["admission_id"] = int(admission_id)

    admissions_by_patient[patient_id].append(admission)


print("Lookup maps built successfully.")


# -------------------------------------------------
# OPTIONAL: Verify structure
# -------------------------------------------------

# Example: print first patient's grouped data
# if patients:
#     sample_patient_id = int(patients[1]["patient_id"])

#     print(f"\nPatient ID: {sample_patient_id}")

#     patient_admissions = admissions_by_patient.get(sample_patient_id, [])
#     print(f"Admissions count: {len(patient_admissions)}")

#     for adm in patient_admissions:
#         adm_id = adm["admission_id"]

#         lab_count = len(labs_by_admission.get(adm_id, []))
#         rx_count = len(prescriptions_by_admission.get(adm_id, []))

#         print(f"  Admission {adm_id}: {lab_count} labs, {rx_count} prescriptions")


"""
build_composition.py
Builds an openEHR COMPOSITION from MIMIC-IV style admission/labs/prescriptions records.
Field names match the exact JSON shapes:

  admission:    patient_id, admission_id, admit_time, discharge_time, death_time,
                admission_type, admission_location, discharge_location, hospital_expired

  lab:          patient_id, admission_id, lab_item_id, observation_time,
                value, valuenum, unit, ref_range_lower, ref_range_upper, flag

  prescription: patient_id, admission_id, med_start_time, med_stop_time,
                drug_type, drug, dose_value, dose_unit, doses_per_24_hrs, route
"""


# ---------------------------------------------------------------------------
# Shared openEHR constants
# ---------------------------------------------------------------------------

_LANGUAGE = {
    "_type": "CODE_PHRASE",
    "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "ISO_639-1"},
    "code_string": "en"
}

_ENCODING = {
    "_type": "CODE_PHRASE",
    "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "IANA_character-sets"},
    "code_string": "ISO-10646-UTF-1"
}

_PARTY_SELF = {"_type": "PARTY_SELF"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(value: str) -> str:
    """Strip milliseconds: '2196-02-24T14:38:00.000' → '2196-02-24T14:38:00'"""
    if value and "." in value:
        value = value.split(".")[0]
    return value


def _id_str(value) -> str:
    """Convert float IDs (e.g. 29600294.0) to clean int strings."""
    return str(int(float(value)))


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_composition(admission: dict, labs: list, prescriptions: list) -> dict:
    """
    Parameters
    ----------
    admission     : single admission record dict
    labs          : list of lab records for this admission (may be empty)
    prescriptions : list of prescription records for this admission (may be empty)

    Returns
    -------
    dict : openEHR COMPOSITION ready to POST to EHRbase
    """

    admit_time     = _dt(admission["admit_time"])
    discharge_time = _dt(admission["discharge_time"]) if admission.get("discharge_time") else admit_time

    # ======================================================================
    # COMPOSITION root
    # ======================================================================

    composition = {
        "_type": "COMPOSITION",
        "name": {"_type": "DV_TEXT", "value": "Inpatient_Encounter"},
        "archetype_details": {
            "archetype_id": {"value": "openEHR-EHR-COMPOSITION.encounter.v1"},
            "template_id":  {"value": "Inpatient_Encounter"},
            "rm_version":   "1.0.4"
        },
        "language":  _LANGUAGE,
        "territory": {
            "_type": "CODE_PHRASE",
            "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "ISO_3166-1"},
            "code_string": "IN"
        },
        "category": {
            "_type": "DV_CODED_TEXT",
            "value": "event",
            "defining_code": {
                "_type": "CODE_PHRASE",
                "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "openehr"},
                "code_string": "433"
            }
        },
        "composer": {"_type": "PARTY_IDENTIFIED", "name": "System Migration Service"},
        "context": {
            "_type": "EVENT_CONTEXT",
            "start_time": {"_type": "DV_DATE_TIME", "value": admit_time},
            "end_time":   {"_type": "DV_DATE_TIME", "value": discharge_time},
            "setting": {
                "_type": "DV_CODED_TEXT",
                "value": "other care",
                "defining_code": {
                    "_type": "CODE_PHRASE",
                    "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "openehr"},
                    "code_string": "238"
                }
            }
        },
        "archetype_node_id": "openEHR-EHR-COMPOSITION.encounter.v1",
        "content": []
    }

    # ======================================================================
    # 1  Episode of Care  (ADMIN_ENTRY)
    # ======================================================================

    episode_items = []

    # Episode ID  <- admission_id
    episode_items.append({
        "_type": "ELEMENT",
        "name":  {"_type": "DV_TEXT", "value": "Episode ID"},
        "value": {"_type": "DV_IDENTIFIER", "id": _id_str(admission["admission_id"])},
        "archetype_node_id": "at0014"
    })

    # Admission date  <- admit_time
    episode_items.append({
        "_type": "ELEMENT",
        "name":  {"_type": "DV_TEXT", "value": "Admission date"},
        "value": {"_type": "DV_DATE_TIME", "value": admit_time},
        "archetype_node_id": "at0004"
    })

    # Reason for admission  <- admission_type  (e.g. "URGENT")
    if admission.get("admission_type"):
        episode_items.append({
            "_type": "ELEMENT",
            "name":  {"_type": "DV_TEXT", "value": "Reason for admission"},
            "value": {"_type": "DV_TEXT", "value": admission["admission_type"]},
            "archetype_node_id": "at0008"
        })

    # Source category  <- admission_location  (e.g. "TRANSFER FROM HOSPITAL")
    if admission.get("admission_location"):
        episode_items.append({
            "_type": "ELEMENT",
            "name":  {"_type": "DV_TEXT", "value": "Source category"},
            "value": {"_type": "DV_TEXT", "value": admission["admission_location"]},
            "archetype_node_id": "at0007"
        })

    # Separation date  <- discharge_time
    if admission.get("discharge_time"):
        episode_items.append({
            "_type": "ELEMENT",
            "name":  {"_type": "DV_TEXT", "value": "Separation date"},
            "value": {"_type": "DV_DATE_TIME", "value": discharge_time},
            "archetype_node_id": "at0002"
        })

    # Destination category  <- discharge_location  (e.g. "SKILLED NURSING FACILITY")
    if admission.get("discharge_location"):
        episode_items.append({
            "_type": "ELEMENT",
            "name":  {"_type": "DV_TEXT", "value": "Destination category"},
            "value": {"_type": "DV_TEXT", "value": admission["discharge_location"]},
            "archetype_node_id": "at0003"
        })

    episode = {
        "_type": "ADMIN_ENTRY",
        "name": {"_type": "DV_TEXT", "value": "Episode of care - institution"},
        "archetype_details": {
            "archetype_id": {"value": "openEHR-EHR-ADMIN_ENTRY.episode_institution.v0"},
            "rm_version":   "1.0.4"
        },
        "language": _LANGUAGE,
        "encoding": _ENCODING,
        "subject":  _PARTY_SELF,
        "provider": _PARTY_SELF,
        "data": {
            "_type": "ITEM_TREE",
            "name": {"_type": "DV_TEXT", "value": "Item tree"},
            "archetype_node_id": "at0001",
            "items": episode_items
        },
        "archetype_node_id": "openEHR-EHR-ADMIN_ENTRY.episode_institution.v0"
    }

    composition["content"].append(episode)

    # ======================================================================
    # 2  Laboratory Test Result  (OBSERVATION)
    # ======================================================================

    if labs:
        lab_events = []

        for lab in labs:
            obs_time  = _dt(lab["observation_time"])
            item_name = f"Lab Item {_id_str(lab['lab_item_id'])}"

            analyte_items = [
                # at0005 — Test name  <- lab_item_id
                {
                    "_type": "ELEMENT",
                    "name":  {"_type": "DV_TEXT", "value": "Test name"},
                    "value": {"_type": "DV_TEXT", "value": item_name},
                    "archetype_node_id": "at0005"
                }
            ]

            # at0057 — Conclusion  <- result value + unit + reference range + flag
            # NOTE: at0073 (Overall test status) is locked to "Registered"/at0107
            # in this template and cannot accept "abnormal" or other MIMIC flags.
            # We fold the flag into the Conclusion text instead.
            conclusion_parts = []
            if lab.get("valuenum") is not None:
                conclusion_parts.append(f"{lab['valuenum']} {lab.get('unit', '')}".strip())
            elif lab.get("value"):
                conclusion_parts.append(str(lab["value"]))

            lo = lab.get("ref_range_lower")
            hi = lab.get("ref_range_upper")
            if lo is not None and hi is not None:
                conclusion_parts.append(f"ref: {lo}–{hi} {lab.get('unit', '')}".strip())

            flag_val = str(lab.get("flag", "")).strip().lower()
            if flag_val and flag_val != "nan":
                conclusion_parts.append(f"flag: {flag_val}")

            if conclusion_parts:
                analyte_items.append({
                    "_type": "ELEMENT",
                    "name":  {"_type": "DV_TEXT", "value": "Conclusion"},
                    "value": {"_type": "DV_TEXT", "value": " | ".join(conclusion_parts)},
                    "archetype_node_id": "at0057"
                })

            lab_events.append({
                "_type": "INTERVAL_EVENT",
                "name":  {"_type": "DV_TEXT", "value": "Any event"},
                "time":  {"_type": "DV_DATE_TIME", "value": obs_time},
                "data": {
                    "_type": "ITEM_TREE",
                    "name": {"_type": "DV_TEXT", "value": "Tree"},
                    "archetype_node_id": "at0003",
                    "items": analyte_items
                },
                # Required by openEHR RM for INTERVAL_EVENT
                "width": {"_type": "DV_DURATION", "value": "PT42H"},
                "math_function": {
                    "_type": "DV_CODED_TEXT",
                    "value": "minimum",
                    "defining_code": {
                        "_type": "CODE_PHRASE",
                        "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "openehr"},
                        "code_string": "145"
                    }
                },
                "archetype_node_id": "at0002"
            })

        composition["content"].append({
            "_type": "OBSERVATION",
            "name": {"_type": "DV_TEXT", "value": "Laboratory test result"},
            "archetype_details": {
                "archetype_id": {"value": "openEHR-EHR-OBSERVATION.laboratory_test_result.v1"},
                "rm_version":   "1.0.4"
            },
            "language": _LANGUAGE,
            "encoding": _ENCODING,
            "subject":  _PARTY_SELF,
            "data": {
                # No _type key here — matches template serialisation
                "name":   {"_type": "DV_TEXT", "value": "Event Series"},
                "origin": {"_type": "DV_DATE_TIME", "value": admit_time},
                "archetype_node_id": "at0001",
                "events": lab_events
            },
            "archetype_node_id": "openEHR-EHR-OBSERVATION.laboratory_test_result.v1"
        })

    # ======================================================================
    # 3  Medication Order  (INSTRUCTION)
    # ======================================================================

    if prescriptions:
        activities = []

        for rx in prescriptions:
            start_time = _dt(rx.get("med_start_time", ""))
            stop_time  = _dt(rx.get("med_stop_time", ""))

            # Dose string  e.g. "330.0 mg iv"
            dose_parts = []
            if rx.get("dose_value") is not None:
                dose_parts.append(str(rx["dose_value"]))
            if rx.get("dose_unit"):
                dose_parts.append(rx["dose_unit"])
            if rx.get("route"):
                dose_parts.append(rx["route"])
            dose_str = " ".join(dose_parts)

            # Frequency string  e.g. "1.0 dose(s) per 24h"
            freq_str = ""
            if rx.get("doses_per_24_hrs") is not None:
                freq_str = f"{rx['doses_per_24_hrs']} dose(s) per 24h"

            description_items = [
                # at0070 — Medication item  <- drug name
                {
                    "_type": "ELEMENT",
                    "name":  {"_type": "DV_TEXT", "value": "Medication item"},
                    "value": {"_type": "DV_TEXT", "value": rx["drug"]},
                    "archetype_node_id": "at0070"
                }
            ]

            # at0091 — Route  <- route
            # (at0054 is not in this template; route lives at at0091 here)
            if rx.get("route"):
                description_items.append({
                    "_type": "ELEMENT",
                    "name":  {"_type": "DV_TEXT", "value": "Route"},
                    "value": {"_type": "DV_TEXT", "value": rx["route"]},
                    "archetype_node_id": "at0091"
                })

            # at0009 — Overall directions description  <- dose + freq as one summary
            # (at0109 "Dose description" and at0054 "Route" are not in this template)
            overall_parts = []
            if dose_str:
                overall_parts.append(dose_str)
            if freq_str:
                overall_parts.append(freq_str)
            if overall_parts:
                description_items.append({
                    "_type": "ELEMENT",
                    "name":  {"_type": "DV_TEXT", "value": "Overall directions description"},
                    "value": {"_type": "DV_TEXT", "value": " | ".join(overall_parts)},
                    "archetype_node_id": "at0009"
                })

            # Order details cluster  <- med_start_time / med_stop_time
            order_items = []
            if start_time:
                order_items.append({
                    "_type": "ELEMENT",
                    "name":  {"_type": "DV_TEXT", "value": "Order start date/time"},
                    "value": {"_type": "DV_DATE_TIME", "value": start_time},
                    "archetype_node_id": "at0012"
                })
            if stop_time:
                order_items.append({
                    "_type": "ELEMENT",
                    "name":  {"_type": "DV_TEXT", "value": "Order stop date/time"},
                    "value": {"_type": "DV_DATE_TIME", "value": stop_time},
                    "archetype_node_id": "at0013"
                })
            if order_items:
                description_items.append({
                    "_type": "CLUSTER",
                    "name":  {"_type": "DV_TEXT", "value": "Order details"},
                    "items": order_items,
                    "archetype_node_id": "at0113"
                })

            activities.append({
                "_type": "ACTIVITY",
                "name": {"_type": "DV_TEXT", "value": "Order"},
                "description": {
                    "_type": "ITEM_TREE",
                    "name": {"_type": "DV_TEXT", "value": "Tree"},
                    "archetype_node_id": "at0002",
                    "items": description_items
                },
                # Required by openEHR RM for ACTIVITY
                "timing": {
                    "_type": "DV_PARSABLE",
                    "value": freq_str or "R1",
                    "formalism": "timing"
                },
                "action_archetype_id": "/.*/",
                "archetype_node_id": "at0001"
            })

        composition["content"].append({
            "_type": "INSTRUCTION",
            "name": {"_type": "DV_TEXT", "value": "Medication order"},
            "archetype_details": {
                "archetype_id": {"value": "openEHR-EHR-INSTRUCTION.medication_order.v3"},
                "rm_version":   "1.0.4"
            },
            "language": _LANGUAGE,
            "encoding": _ENCODING,
            "subject":  _PARTY_SELF,
            # Required by openEHR RM for INSTRUCTION
            "narrative": {"_type": "DV_TEXT", "value": "Medication order"},
            "activities": activities,
            "archetype_node_id": "openEHR-EHR-INSTRUCTION.medication_order.v3"
        })

    return composition



# for patient in patients:
#     patient_id = int(patient["patient_id"])
#     ehr_id = get_ehr_id(patient_id)  # your mapping

#     for admission in admissions_by_patient.get(patient_id, []):
#         admission_id = admission["admission_id"]

#         labs = labs_by_admission.get(admission_id, [])
#         prescriptions = prescriptions_by_admission.get(admission_id, [])

#         composition = build_composition(admission, labs, prescriptions)

#         commit_to_ehrbase(ehr_id, composition)


print("\nSubmitting admissions to EHRbase...")
existing_admissions = fetch_existing_admissions()
if existing_admissions:
    print(f"→ Found {len(existing_admissions)} admission(s) already stored — will skip duplicates")

for patient in patients:
    patient_id = int(patient["patient_id"])
    ehr_id = get_ehr_id_from_cache(patient_id)
    if not ehr_id:
        continue

    patient_admissions = admissions_by_patient.get(patient_id, [])
    if not patient_admissions:
        continue

    print(f"\nPatient {patient_id}: {len(patient_admissions)} admission(s) to process")

    for admission in patient_admissions:
        admission_id = admission["admission_id"]
        if admission_id in existing_admissions:
            print(f"  • Admission {admission_id} already committed; skipping")
            continue

        labs = labs_by_admission.get(admission_id, [])
        prescriptions = prescriptions_by_admission.get(admission_id, [])

        composition = build_composition(admission, labs, prescriptions)

        try:
            version_uid = commit_composition(ehr_id, composition)
            existing_admissions.add(admission_id)
            print(
                f"  ✓ Admission {admission_id} committed ({len(labs)} labs, {len(prescriptions)} meds)"
                f" → {version_uid}"
            )
        except Exception as exc:
            print(f"  ✗ Admission {admission_id} failed: {exc}")
