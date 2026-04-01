import os
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from service_config import BACKEND_BASE_URL, EHRBASE_API_URL

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

EHRBASE_URL = EHRBASE_API_URL
BACKEND_URL = BACKEND_BASE_URL
TEMPLATE_ID = "Inpatient_Encounter"
REQUEST_TIMEOUT = int(os.environ.get("EHRBASE_REQUEST_TIMEOUT", "20"))
AQL_MAX_RETRIES = int(os.environ.get("EHRBASE_AQL_RETRIES", "3"))
SAMPLE_DEFAULT = 10

ROOT_DIR = Path(__file__).resolve().parents[2]
PATIENTS_FILE = ROOT_DIR / "clean_patients.json"
ADMISSIONS_FILE = ROOT_DIR / "clean_admissions.json"
LABS_FILE = ROOT_DIR / "clean_labs.json"
PRESCRIPTIONS_FILE = ROOT_DIR / "clean_prescriptions.json"

STATUS_PREFIX = {
    "pass": "[PASS]",
    "fail": "[FAIL]",
    "warn": "[WARN]",
}

LAB_ARCHETYPE = "openEHR-EHR-OBSERVATION.laboratory_test_result.v1"
MED_ARCHETYPE = "openEHR-EHR-INSTRUCTION.medication_order.v3"
EPISODE_ARCHETYPE = "openEHR-EHR-ADMIN_ENTRY.episode_institution.v0"


# ---------------------------------------------------------------------------
# SMALL HELPERS
# ---------------------------------------------------------------------------

def _safe_int(value) -> Optional[int]:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _normalize_timestamp(value: Optional[str]) -> Optional[str]:
    if value in (None, "", float("nan")):
        return None
    try:
        dt = pd.to_datetime(value, errors="coerce")
    except Exception:  # pandas already guards most cases, but stay safe
        return None
    if pd.isna(dt):
        return None
    # Drop timezone and milliseconds for easier comparisons
    return dt.tz_localize(None).strftime("%Y-%m-%dT%H:%M:%S")


def _format(status: str, message: str) -> str:
    prefix = STATUS_PREFIX.get(status.lower(), "[INFO]")
    return f"{prefix} {message}"


def _find_item_value(items: List[dict], label: str) -> Optional[str]:
    for item in items or []:
        name = item.get("name", {}).get("value")
        if name == label:
            value = item.get("value") or {}
            if isinstance(value, dict):
                return value.get("value") or value.get("id")
            return value
    return None


def _as_scalar(value, default: int | float = 0):
    if isinstance(value, pd.Series):
        if value.empty:
            return default
        return value.iloc[0]
    if value is None:
        return default
    return value


def _extract_lab_events(composition: dict) -> List[dict]:
    for entry in (composition or {}).get("content", []):
        if entry.get("archetype_node_id") == LAB_ARCHETYPE:
            data = entry.get("data") or {}
            return data.get("events") or []
    return []


def _extract_med_activities(composition: dict) -> List[dict]:
    for entry in (composition or {}).get("content", []):
        if entry.get("archetype_node_id") == MED_ARCHETYPE:
            return entry.get("activities") or []
    return []


def _parse_lab_item_id(test_name: Optional[str]) -> Optional[int]:
    if not test_name:
        return None
    parts = test_name.strip().split()
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def _extract_order_times(activity: dict) -> Tuple[Optional[str], Optional[str]]:
    description = activity.get("description") or {}
    items = description.get("items") or []
    for cluster in items:
        if cluster.get("archetype_node_id") == "at0113":  # Order details cluster
            start_val = _find_item_value(cluster.get("items"), "Order start date/time")
            stop_val = _find_item_value(cluster.get("items"), "Order stop date/time")
            return _normalize_timestamp(start_val), _normalize_timestamp(stop_val)
    return None, None


def _run_aql(query: str) -> Tuple[List[dict], Optional[str]]:
    last_error: Optional[str] = None
    for attempt in range(1, AQL_MAX_RETRIES + 1):
        try:
            response = requests.post(
                f"{EHRBASE_URL}/query/aql",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={"q": query},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            break
        except requests.RequestException as exc:
            last_error = f"EHRbase request failed (attempt {attempt}): {exc}"
            if attempt < AQL_MAX_RETRIES:
                time.sleep(min(2 * attempt, 5))
        except ValueError:
            return [], "EHRbase returned non-JSON payload"
    else:
        return [], last_error or "EHRbase request failed"

    columns = [col.get("name") for col in payload.get("columns", [])]
    rows = []
    for raw_row in payload.get("rows", []):
        row_dict = {}
        for idx, column in enumerate(columns):
            row_dict[column] = raw_row[idx]
        rows.append(row_dict)
    return rows, None


# ---------------------------------------------------------------------------
# CORE CONTEXT HOLDER
# ---------------------------------------------------------------------------

class ValidationContext:
    def __init__(self):
        self.patients_df = self._load_dataframe(PATIENTS_FILE)
        self.admissions_df = self._load_dataframe(ADMISSIONS_FILE)
        self.labs_df = self._load_dataframe(LABS_FILE)
        self.prescriptions_df = self._load_dataframe(PRESCRIPTIONS_FILE)

        for df, column in (
            (self.patients_df, "patient_id"),
            (self.admissions_df, "patient_id"),
            (self.admissions_df, "admission_id"),
            (self.labs_df, "patient_id"),
            (self.labs_df, "admission_id"),
            (self.prescriptions_df, "patient_id"),
            (self.prescriptions_df, "admission_id"),
        ):
            if column in df.columns:
                df[column] = df[column].apply(_safe_int)

        # Normalize timestamps for easier comparisons
        if "admit_time" in self.admissions_df.columns:
            self.admissions_df["admit_time"] = pd.to_datetime(self.admissions_df["admit_time"], errors="coerce")
        if "discharge_time" in self.admissions_df.columns:
            self.admissions_df["discharge_time"] = pd.to_datetime(self.admissions_df["discharge_time"], errors="coerce")
        if "observation_time" in self.labs_df.columns:
            self.labs_df["observation_time"] = pd.to_datetime(self.labs_df["observation_time"], errors="coerce")
        if "med_start_time" in self.prescriptions_df.columns:
            self.prescriptions_df["med_start_time"] = pd.to_datetime(self.prescriptions_df["med_start_time"], errors="coerce")
        if "med_stop_time" in self.prescriptions_df.columns:
            self.prescriptions_df["med_stop_time"] = pd.to_datetime(self.prescriptions_df["med_stop_time"], errors="coerce")

        self.patient_ehr_map = self._fetch_patient_ehr_map()
        self.ehr_to_patient = {ehr_id: patient_id for patient_id, ehr_id in self.patient_ehr_map.items()}

        self.remote_records: List[dict] = []
        self.remote_error: Optional[str] = None
        self.compositions_by_admission: Dict[int, dict] = {}
        self._load_remote_state()

    @staticmethod
    def _load_dataframe(path: Path) -> pd.DataFrame:
        if not path.exists():
            raise FileNotFoundError(f"Missing input file: {path}")
        return pd.read_json(path)

    def _fetch_patient_ehr_map(self) -> Dict[int, str]:
        mapping: Dict[int, str] = {}
        for patient_id in self.patients_df["patient_id"].dropna().unique():
            try:
                response = requests.get(
                    f"{BACKEND_URL}/{int(patient_id)}",
                    timeout=REQUEST_TIMEOUT,
                )
            except requests.RequestException as exc:
                print(f"[WARN] Backend lookup failed for patient {patient_id}: {exc}")
                continue

            if response.status_code == 200:
                try:
                    ehr_id = response.json()
                except ValueError:
                    print(f"[WARN] Backend returned invalid JSON for patient {patient_id}")
                    continue
                if isinstance(ehr_id, str):
                    mapping[int(patient_id)] = ehr_id
            else:
                print(f"[WARN] Missing EHR mapping for patient {patient_id} (status {response.status_code})")
        return mapping

    def _load_remote_state(self) -> None:
        query = f"""
        SELECT
            e/ehr_id/value                          AS ehr_id,
            c/uid/value                             AS composition_id,
            c/content[{EPISODE_ARCHETYPE}]/data[at0001]/items[at0014]/value/id AS admission_id,
            c/context/start_time/value              AS admit_time,
            c/context/end_time/value                AS discharge_time,
            c                                        AS composition
        FROM EHR e
        CONTAINS COMPOSITION c
        WHERE c/archetype_details/template_id/value = '{TEMPLATE_ID}'
        """

        rows, error = _run_aql(query)
        if error:
            self.remote_error = error
            return

        for row in rows:
            composition = row.get("composition") or {}
            admission_id = _safe_int(row.get("admission_id"))
            ehr_id = row.get("ehr_id")
            patient_id = self.ehr_to_patient.get(ehr_id)
            lab_events = _extract_lab_events(composition)
            med_activities = _extract_med_activities(composition)

            record = {
                "ehr_id": ehr_id,
                "patient_id": patient_id,
                "composition_id": row.get("composition_id"),
                "admission_id": admission_id,
                "admit_time": row.get("admit_time"),
                "discharge_time": row.get("discharge_time"),
                "composition": composition,
                "lab_events": lab_events,
                "med_activities": med_activities,
                "lab_event_count": len(lab_events),
                "med_event_count": len(med_activities),
            }
            self.remote_records.append(record)
            if admission_id is not None:
                self.compositions_by_admission[admission_id] = record


# ---------------------------------------------------------------------------
# VALIDATION FUNCTIONS
# ---------------------------------------------------------------------------

def validate_counts(ctx: ValidationContext) -> List[str]:
    messages: List[str] = []

    csv_counts = {
        "patients": ctx.patients_df["patient_id"].nunique(),
        "admissions": ctx.admissions_df["admission_id"].nunique(),
        "labs": len(ctx.labs_df),
        "prescriptions": len(ctx.prescriptions_df),
    }

    open_ehr_counts = {
        "patients": len(ctx.patient_ehr_map),
        "admissions": len(ctx.remote_records),
        "labs": sum(record["lab_event_count"] for record in ctx.remote_records),
        "prescriptions": sum(record["med_event_count"] for record in ctx.remote_records),
    }

    messages.append(
        _format(
            "pass" if csv_counts["patients"] == open_ehr_counts["patients"] else "fail",
            f"Patient count CSV={csv_counts['patients']} vs EHR={open_ehr_counts['patients']}",
        )
    )

    messages.append(
        _format(
            "pass" if csv_counts["admissions"] == open_ehr_counts["admissions"] else "fail",
            f"Admission count CSV={csv_counts['admissions']} vs EHR={open_ehr_counts['admissions']}",
        )
    )

    messages.append(
        _format(
            "pass" if csv_counts["labs"] == open_ehr_counts["labs"] else "fail",
            f"Lab event count CSV={csv_counts['labs']} vs EHR={open_ehr_counts['labs']}",
        )
    )

    messages.append(
        _format(
            "pass" if csv_counts["prescriptions"] == open_ehr_counts["prescriptions"] else "fail",
            f"Prescription count CSV={csv_counts['prescriptions']} vs EHR={open_ehr_counts['prescriptions']}",
        )
    )

    if ctx.remote_error:
        messages.append(_format("fail", f"Unable to query EHRbase: {ctx.remote_error}"))

    return messages


def validate_relationships(ctx: ValidationContext) -> List[str]:
    messages: List[str] = []
    if ctx.remote_error:
        return [_format("fail", f"Relationship validation skipped: {ctx.remote_error}")]

    remote_df = pd.DataFrame(ctx.remote_records)

    csv_admissions_per_patient = (
        ctx.admissions_df.dropna(subset=["patient_id"])
        .groupby("patient_id")["admission_id"]
        .nunique()
    )

    remote_admissions_per_patient = (
        remote_df.dropna(subset=["patient_id"])
        .groupby("patient_id")["admission_id"]
        .nunique()
    )

    patient_mismatches = []
    for patient_id, csv_count in csv_admissions_per_patient.items():
        remote_count = int(_as_scalar(remote_admissions_per_patient.get(patient_id), 0))
        if csv_count != remote_count:
            patient_mismatches.append((patient_id, csv_count, remote_count))
            print(
                f"[REL] Patient {patient_id}: admissions CSV={csv_count} vs EHR={remote_count}"
            )

    messages.append(
        _format(
            "pass" if not patient_mismatches else "fail",
            "Admissions per patient match" if not patient_mismatches else
            f"Admissions per patient mismatch for {len(patient_mismatches)} patient(s)",
        )
    )

    csv_labs_per_admission = ctx.labs_df.groupby("admission_id").size()
    remote_labs_per_admission = remote_df.set_index("admission_id")["lab_event_count"]

    lab_mismatches = []
    for admission_id, csv_count in csv_labs_per_admission.items():
        remote_count = int(_as_scalar(remote_labs_per_admission.get(admission_id), 0))
        if csv_count != remote_count:
            lab_mismatches.append((admission_id, csv_count, remote_count))
            print(
                f"[REL] Admission {admission_id}: labs CSV={csv_count} vs EHR={remote_count}"
            )

    messages.append(
        _format(
            "pass" if not lab_mismatches else "fail",
            "Lab events per admission match" if not lab_mismatches else
            f"Lab events mismatch for {len(lab_mismatches)} admission(s)",
        )
    )

    csv_meds_per_admission = ctx.prescriptions_df.groupby("admission_id").size()
    remote_meds_per_admission = remote_df.set_index("admission_id")["med_event_count"]

    med_mismatches = []
    for admission_id, csv_count in csv_meds_per_admission.items():
        remote_count = int(_as_scalar(remote_meds_per_admission.get(admission_id), 0))
        if csv_count != remote_count:
            med_mismatches.append((admission_id, csv_count, remote_count))
            print(
                f"[REL] Admission {admission_id}: meds CSV={csv_count} vs EHR={remote_count}"
            )

    messages.append(
        _format(
            "pass" if not med_mismatches else "fail",
            "Medications per admission match" if not med_mismatches else
            f"Medication mismatch for {len(med_mismatches)} admission(s)",
        )
    )

    return messages


def _match_lab_record(csv_row: pd.Series, lab_events: List[dict]) -> Optional[str]:
    expected_id = _safe_int(csv_row.get("lab_item_id"))
    expected_time = _normalize_timestamp(csv_row.get("observation_time"))
    expected_value = None
    if pd.notna(csv_row.get("valuenum")):
        unit_raw = csv_row.get("unit")
        unit = "" if pd.isna(unit_raw) else str(unit_raw).strip()
        expected_value = f"{csv_row.get('valuenum')} {unit}".strip()
    elif pd.notna(csv_row.get("value")):
        expected_value = str(csv_row.get("value"))

    for event in lab_events:
        event_time = _normalize_timestamp(event.get("time", {}).get("value"))
        event_items = event.get("data", {}).get("items", [])
        test_name = _find_item_value(event_items, "Test name")
        event_id = _parse_lab_item_id(test_name)

        if event_id == expected_id and event_time == expected_time:
            conclusion = _find_item_value(event_items, "Conclusion") or ""
            if expected_value and not _value_matches_conclusion(expected_value, conclusion):
                return (
                    f"Lab {expected_id} at {expected_time}: value '{expected_value}' missing in composition"
                )
            return None
    return f"Lab {expected_id} at {expected_time} missing in composition"


def _value_matches_conclusion(expected_value: str, conclusion: str, tolerance: float = 1e-6) -> bool:
    """Return True if the numeric/unit portion of expected_value is found in conclusion."""
    if not conclusion:
        return False

    expected_norm = expected_value.strip()
    conclusion_norm = conclusion.strip()

    if not expected_norm:
        return True
    if expected_norm.lower() in conclusion_norm.lower():
        return True

    exp_tokens = expected_norm.split()
    try:
        exp_number = float(exp_tokens[0])
    except (ValueError, IndexError):
        return False

    actual_tokens = conclusion_norm.split()
    try:
        actual_number = float(actual_tokens[0])
    except (ValueError, IndexError):
        return False

    if abs(exp_number - actual_number) > tolerance:
        return False

    if len(exp_tokens) > 1:
        expected_unit = exp_tokens[1].lower()
        if expected_unit and expected_unit not in conclusion_norm.lower():
            return False

    return True


def _match_medication_record(csv_row: pd.Series, med_activities: List[dict]) -> Optional[str]:
    expected_drug = str(csv_row.get("drug", "")).strip().lower()
    expected_start = _normalize_timestamp(csv_row.get("med_start_time"))

    for activity in med_activities:
        description = activity.get("description", {})
        med_name = _find_item_value(description.get("items"), "Medication item")
        med_name_norm = (med_name or "").strip().lower()
        start_time, _ = _extract_order_times(activity)

        if med_name_norm == expected_drug:
            if expected_start and start_time and expected_start != start_time:
                continue
            return None
    return f"Medication '{expected_drug}' missing or timestamp mismatch"


def validate_sample_values(ctx: ValidationContext, sample_size: int = SAMPLE_DEFAULT) -> List[str]:
    if ctx.remote_error:
        return [_format("fail", f"Sample validation skipped: {ctx.remote_error}")]

    available_admissions = set(ctx.admissions_df["admission_id"].dropna())
    remote_admissions = set(ctx.compositions_by_admission.keys())
    shared_admissions = list(available_admissions & remote_admissions)

    if not shared_admissions:
        return [_format("warn", "No overlapping admissions to sample")] 

    sample = random.sample(
        shared_admissions,
        k=min(sample_size, len(shared_admissions)),
    )

    mismatches: List[str] = []
    for admission_id in sample:
        record = ctx.compositions_by_admission.get(admission_id)
        csv_admission = ctx.admissions_df[ctx.admissions_df["admission_id"] == admission_id]
        csv_lab_rows = ctx.labs_df[ctx.labs_df["admission_id"] == admission_id]
        csv_med_rows = ctx.prescriptions_df[ctx.prescriptions_df["admission_id"] == admission_id]

        if csv_admission.empty or record is None:
            mismatches.append(f"Admission {admission_id}: missing data on one side")
            continue

        csv_start = _normalize_timestamp(csv_admission.iloc[0].get("admit_time"))
        ehr_start = _normalize_timestamp(record.get("admit_time"))
        if csv_start != ehr_start:
            mismatches.append(
                f"Admission {admission_id}: admit time CSV={csv_start} vs EHR={ehr_start}"
            )

        if not csv_lab_rows.empty:
            for _, row in csv_lab_rows.head(3).iterrows():
                issue = _match_lab_record(row, record.get("lab_events", []))
                if issue:
                    mismatches.append(f"Admission {admission_id}: {issue}")
                    break
        elif record.get("lab_events"):
            mismatches.append(f"Admission {admission_id}: labs exist in EHR but not CSV")

        if not csv_med_rows.empty:
            for _, row in csv_med_rows.head(3).iterrows():
                issue = _match_medication_record(row, record.get("med_activities", []))
                if issue:
                    mismatches.append(f"Admission {admission_id}: {issue}")
                    break
        elif record.get("med_activities"):
            mismatches.append(f"Admission {admission_id}: meds exist in EHR but not CSV")

    status = "pass" if not mismatches else "fail"
    message = (
        "Sample value validation passed" if not mismatches else
        f"Sample value mismatches detected ({len(mismatches)} issue(s))"
    )

    report = [_format(status, message)]
    for detail in mismatches:
        print(f"[SAMPLE] {detail}")
    return report


def validate_edge_cases(ctx: ValidationContext) -> List[str]:
    messages: List[str] = []

    missing_patient_ids = ctx.patients_df["patient_id"].isna().sum()
    missing_admission_patients = ctx.admissions_df["patient_id"].isna().sum()
    missing_admission_ids = ctx.admissions_df["admission_id"].isna().sum()

    messages.append(
        _format(
            "pass" if missing_patient_ids == 0 else "fail",
            f"Patients missing IDs: {missing_patient_ids}",
        )
    )

    missing_links = missing_admission_patients + missing_admission_ids
    messages.append(
        _format(
            "pass" if missing_links == 0 else "fail",
            f"Admissions missing patient/admission IDs: {missing_links}",
        )
    )

    dose_series = ctx.prescriptions_df.get("dose_value")
    negative_doses = int(((dose_series <= 0).sum()) if dose_series is not None else 0)
    messages.append(
        _format(
            "pass" if negative_doses == 0 else "fail",
            f"Prescriptions with non-positive doses: {int(negative_doses)}",
        )
    )

    empty_compositions = [
        record["composition_id"]
        for record in ctx.remote_records
        if not (record.get("composition") or {}).get("content")
    ]
    messages.append(
        _format(
            "pass" if not empty_compositions else "fail",
            "No empty compositions" if not empty_compositions else
            f"Empty compositions detected: {len(empty_compositions)}",
        )
    )

    return messages


# ---------------------------------------------------------------------------
# PUBLIC ENTRYPOINT
# ---------------------------------------------------------------------------

def run_all_validations(sample_size: int = SAMPLE_DEFAULT) -> List[str]:
    ctx = ValidationContext()

    report: List[str] = []
    report.extend(validate_counts(ctx))
    report.extend(validate_relationships(ctx))
    report.extend(validate_sample_values(ctx, sample_size))
    report.extend(validate_edge_cases(ctx))

    for line in report:
        print(line)

    return report


if __name__ == "__main__":
    run_all_validations()
