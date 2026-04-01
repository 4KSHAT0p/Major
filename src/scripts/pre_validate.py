"""Pre-Mapping Validation (Stage c.1)

Ensures cleaned CSV extracts satisfy structural and semantic constraints
before mapping into openEHR compositions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PATIENTS_FILE = ROOT / "clean_patients.json"
ADMISSIONS_FILE = ROOT / "clean_admissions.json"
LABS_FILE = ROOT / "clean_labs.json"
PRESCRIPTIONS_FILE = ROOT / "clean_prescriptions.json"

CRITICAL_PATIENT_COLS = {"patient_id", "gender", "age"}
CRITICAL_ADMISSION_COLS = {
    "patient_id",
    "admission_id",
    "admit_time",
    "discharge_time",
}
CRITICAL_LAB_COLS = {
    "patient_id",
    "admission_id",
    "lab_item_id",
    "observation_time",
}
CRITICAL_RX_COLS = {
    "patient_id",
    "admission_id",
    "drug",
    "med_start_time",
}

STATUS_PREFIX = {
    True: "[PASS]",
    False: "[FAIL]",
}


def load_dataframe(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file {path}")
    return pd.read_json(path)


def report(condition: bool, message: str) -> Tuple[bool, str]:
    return condition, f"{STATUS_PREFIX[condition]} {message}"


def check_required_columns(df: pd.DataFrame, required: set[str], name: str) -> Tuple[bool, str]:
    missing = required - set(df.columns)
    return report(not missing, f"{name}: required columns present" if not missing else f"{name}: missing columns {sorted(missing)}")


def check_not_empty(df: pd.DataFrame, name: str) -> Tuple[bool, str]:
    return report(len(df) > 0, f"{name}: contains {len(df)} rows")


def check_unique(df: pd.DataFrame, column: str, name: str) -> Tuple[bool, str]:
    duplicates = df[column].duplicated().sum()
    return report(duplicates == 0, f"{name}: unique {column}" if duplicates == 0 else f"{name}: duplicate {column} values={duplicates}")


def check_referential_integrity(child: pd.DataFrame, parent: pd.DataFrame, child_key: str, parent_key: str, label: str) -> Tuple[bool, str]:
    parent_ids = set(parent[parent_key].dropna().tolist())
    missing = child[~child[child_key].isin(parent_ids)]
    return report(missing.empty, f"{label}: all {child_key} reference existing {parent_key}" if missing.empty else f"{label}: {len(missing)} rows reference missing {parent_key}")


def check_time_order(admissions: pd.DataFrame) -> Tuple[bool, str]:
    mask = (
        admissions["discharge_time"].notna()
        & (admissions["discharge_time"] < admissions["admit_time"])
    )
    invalid = admissions[mask]
    return report(invalid.empty, "Admissions: discharge >= admit" if invalid.empty else f"Admissions: {len(invalid)} rows have discharge before admit")


def check_numeric_positive(series: pd.Series, label: str) -> Tuple[bool, str]:
    values = series.dropna()
    violations = values <= 0
    return report(not violations.any(), f"{label}: all values positive" if not violations.any() else f"{label}: {int(violations.sum())} non-positive values")


def run_pre_validation() -> int:
    patients = load_dataframe(PATIENTS_FILE)
    admissions = load_dataframe(ADMISSIONS_FILE)
    labs = load_dataframe(LABS_FILE)
    prescriptions = load_dataframe(PRESCRIPTIONS_FILE)

    # Normalize key columns for safe comparisons
    for df, column in (
        (patients, "patient_id"),
        (admissions, "patient_id"),
        (admissions, "admission_id"),
        (labs, "patient_id"),
        (labs, "admission_id"),
        (prescriptions, "patient_id"),
        (prescriptions, "admission_id"),
    ):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    admissions["admit_time"] = pd.to_datetime(admissions["admit_time"], errors="coerce")
    admissions["discharge_time"] = pd.to_datetime(admissions["discharge_time"], errors="coerce")
    labs["observation_time"] = pd.to_datetime(labs["observation_time"], errors="coerce")
    prescriptions["med_start_time"] = pd.to_datetime(prescriptions["med_start_time"], errors="coerce")

    checks: List[Tuple[bool, str]] = []

    checks.append(check_not_empty(patients, "Patients"))
    checks.append(check_not_empty(admissions, "Admissions"))
    checks.append(check_not_empty(labs, "Lab events"))
    checks.append(check_not_empty(prescriptions, "Prescriptions"))

    checks.append(check_required_columns(patients, CRITICAL_PATIENT_COLS, "Patients"))
    checks.append(check_required_columns(admissions, CRITICAL_ADMISSION_COLS, "Admissions"))
    checks.append(check_required_columns(labs, CRITICAL_LAB_COLS, "Lab events"))
    checks.append(check_required_columns(prescriptions, CRITICAL_RX_COLS, "Prescriptions"))

    checks.append(check_unique(patients, "patient_id", "Patients"))
    checks.append(check_unique(admissions, "admission_id", "Admissions"))

    checks.append(check_referential_integrity(admissions, patients, "patient_id", "patient_id", "Admissions"))
    checks.append(check_referential_integrity(labs, admissions, "admission_id", "admission_id", "Lab events"))
    checks.append(check_referential_integrity(prescriptions, admissions, "admission_id", "admission_id", "Prescriptions"))

    checks.append(check_time_order(admissions))

    if "valuenum" in labs.columns:
        checks.append(report(labs["valuenum"].notna().all(), "Lab events: numeric values present" if labs["valuenum"].notna().all() else "Lab events: missing numeric values"))

    if "dose_value" in prescriptions.columns:
        checks.append(check_numeric_positive(prescriptions["dose_value"], "Prescriptions dose_value"))

    failed = False
    for ok, message in checks:
        print(message)
        failed = failed or not ok

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_pre_validation())
