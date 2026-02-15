"""
MIMIC-IV to OpenEHR Pipeline - Phase 1: Data Exploration
=========================================================

This script performs initial data profiling and exploration of the MIMIC-IV demo dataset.

Authors: Akshat Singh, Arya Verma
Date: February 2026
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import warnings

warnings.filterwarnings("ignore")

# Set display options
pd.set_option("display.max_columns", None)
pd.set_option("display.width", None)

# ============================================================================
# 1. LOAD DATA
# ============================================================================

print("=" * 80)
print("MIMIC-IV DATA LOADING")
print("=" * 80)

# Load admissions
df_admission = pd.read_csv(
    "mimic-iv-clinical-database-demo-2.2/hosp/admissions.csv",
    usecols=[
        "subject_id",
        "hadm_id",
        "admittime",
        "dischtime",
        "deathtime",
        "admission_type",
        "admission_location",
        "discharge_location",
        "hospital_expire_flag",
    ],
)

df_admission = df_admission.rename(
    columns={
        "subject_id": "patient_id",
        "hadm_id": "admission_id",
        "admittime": "admit_time",
        "dischtime": "discharge_time",
        "deathtime": "death_time",
        "hospital_expire_flag": "hospital_expired",
    }
)

# Load lab events
df_lab = pd.read_csv(
    "mimic-iv-clinical-database-demo-2.2/hosp/labevents.csv",
    usecols=[
        "subject_id",
        "hadm_id",
        "itemid",
        "charttime",
        "value",
        "valuenum",
        "valueuom",
        "ref_range_lower",
        "ref_range_upper",
        "flag",
    ],
)

df_lab = df_lab.rename(
    columns={
        "subject_id": "patient_id",
        "hadm_id": "admission_id",
        "itemid": "lab_item_id",
        "charttime": "observation_time",
        "valueuom": "unit",
    }
)

df_lab = df_lab[df_lab["valuenum"].notna()]

# Load prescriptions
df_pres = pd.read_csv(
    "mimic-iv-clinical-database-demo-2.2/hosp/prescriptions.csv",
    usecols=[
        "subject_id",
        "hadm_id",
        "starttime",
        "stoptime",
        "drug",
        "drug_type",
        "dose_val_rx",
        "dose_unit_rx",
        "route",
        "doses_per_24_hrs",
    ],
)

df_pres = df_pres.rename(
    columns={
        "subject_id": "patient_id",
        "hadm_id": "admission_id",
        "starttime": "med_start_time",
        "stoptime": "med_stop_time",
        "dose_val_rx": "dose_value",
        "dose_unit_rx": "dose_unit",
    }
)

df_pres = df_pres[df_pres["dose_value"].notna()]

# Load patients
df_pat = pd.read_csv(
    "mimic-iv-clinical-database-demo-2.2/hosp/patients.csv",
    usecols=["subject_id", "gender", "anchor_age", "dod"],
)

df_pat = df_pat.rename(
    columns={"subject_id": "patient_id", "anchor_age": "age", "dod": "death_date"}
)

print("\n✓ Data loaded successfully!\n")

# ============================================================================
# 2. DATA PROFILING FUNCTION
# ============================================================================


def profile_dataset(df, name):
    """Generate comprehensive data profile for a dataset"""
    print("=" * 80)
    print(f"DATASET PROFILE: {name}")
    print("=" * 80)

    # Basic info
    print(f"\n📊 BASIC INFORMATION")
    print(f"   Shape: {df.shape[0]:,} rows × {df.shape[1]} columns")
    print(f"   Memory usage: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")

    # Column info
    print(f"\n📋 COLUMNS")
    for col in df.columns:
        print(f"   - {col}: {df[col].dtype}")

    # Missing values
    print(f"\n❓ MISSING VALUES")
    missing = df.isnull().sum()
    missing_pct = (missing / len(df)) * 100
    missing_df = pd.DataFrame(
        {
            "Column": missing.index,
            "Missing Count": missing.values,
            "Missing %": missing_pct.values,
        }
    )
    missing_df = missing_df[missing_df["Missing Count"] > 0].sort_values(
        "Missing %", ascending=False
    )

    if len(missing_df) > 0:
        print(missing_df.to_string(index=False))
    else:
        print("   ✓ No missing values!")

    # Duplicates
    duplicates = df.duplicated().sum()
    print(f"\n🔁 DUPLICATES")
    print(f"   Total duplicate rows: {duplicates:,} ({duplicates/len(df)*100:.2f}%)")

    # Unique values for categorical columns
    print(f"\n🏷️  CATEGORICAL COLUMNS (if any)")
    categorical_cols = df.select_dtypes(include=["object"]).columns
    for col in categorical_cols:
        n_unique = df[col].nunique()
        if n_unique <= 20:  # Only show if reasonable number
            print(f"\n   {col}: {n_unique} unique values")
            value_counts = df[col].value_counts()
            for val, count in value_counts.head(10).items():
                print(f"      - {val}: {count:,} ({count/len(df)*100:.1f}%)")

    # Numeric statistics
    print(f"\n📈 NUMERIC STATISTICS")
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        print(df[numeric_cols].describe().to_string())
    else:
        print("   No numeric columns")

    print("\n" + "=" * 80 + "\n")


# ============================================================================
# 3. RUN PROFILING FOR ALL DATASETS
# ============================================================================

profile_dataset(df_admission, "ADMISSIONS")
profile_dataset(df_lab, "LAB EVENTS")
profile_dataset(df_pres, "PRESCRIPTIONS")
profile_dataset(df_pat, "PATIENTS")

# ============================================================================
# 4. DATA QUALITY CHECKS
# ============================================================================

print("=" * 80)
print("DATA QUALITY CHECKS")
print("=" * 80)

# Check 1: Referential integrity
print("\n1️⃣  REFERENTIAL INTEGRITY")

patients_in_pat = set(df_pat["patient_id"].unique())
patients_in_adm = set(df_admission["patient_id"].unique())
patients_in_lab = set(df_lab["patient_id"].unique())
patients_in_pres = set(df_pres["patient_id"].unique())

print(f"   Patients in patients table: {len(patients_in_pat):,}")
print(f"   Patients in admissions: {len(patients_in_adm):,}")
print(f"   Patients in labs: {len(patients_in_lab):,}")
print(f"   Patients in prescriptions: {len(patients_in_pres):,}")

orphaned_adm = patients_in_adm - patients_in_pat
orphaned_lab = patients_in_lab - patients_in_pat
orphaned_pres = patients_in_pres - patients_in_pat

print(f"\n   ⚠️  Admissions with no patient record: {len(orphaned_adm)}")
print(f"   ⚠️  Lab events with no patient record: {len(orphaned_lab)}")
print(f"   ⚠️  Prescriptions with no patient record: {len(orphaned_pres)}")

# Check admission references
admissions_in_adm = set(df_admission["admission_id"].unique())
admissions_in_lab = set(df_lab["admission_id"].dropna().unique())
admissions_in_pres = set(df_pres["admission_id"].dropna().unique())

orphaned_lab_adm = admissions_in_lab - admissions_in_adm
orphaned_pres_adm = admissions_in_pres - admissions_in_adm

print(f"\n   ⚠️  Lab events with no admission record: {len(orphaned_lab_adm)}")
print(f"   ⚠️  Prescriptions with no admission record: {len(orphaned_pres_adm)}")

# Check 2: Temporal consistency
print("\n2️⃣  TEMPORAL CONSISTENCY")

# Convert to datetime
df_admission["admit_time"] = pd.to_datetime(df_admission["admit_time"])
df_admission["discharge_time"] = pd.to_datetime(df_admission["discharge_time"])

# Check for invalid date ranges
invalid_dates = df_admission[
    df_admission["discharge_time"] < df_admission["admit_time"]
]
print(f"   ⚠️  Admissions with discharge before admit: {len(invalid_dates)}")

# Calculate length of stay
df_admission["length_of_stay_hours"] = (
    df_admission["discharge_time"] - df_admission["admit_time"]
).dt.total_seconds() / 3600

print(
    f"   Average length of stay: {df_admission['length_of_stay_hours'].mean():.1f} hours"
)
print(
    f"   Median length of stay: {df_admission['length_of_stay_hours'].median():.1f} hours"
)
print(f"   Max length of stay: {df_admission['length_of_stay_hours'].max():.1f} hours")

# Check 3: Lab value ranges
print("\n3️⃣  LAB VALUE QUALITY")

# Count labs with reference ranges
labs_with_lower = df_lab["ref_range_lower"].notna().sum()
labs_with_upper = df_lab["ref_range_upper"].notna().sum()

print(
    f"   Labs with lower reference range: {labs_with_lower:,} ({labs_with_lower/len(df_lab)*100:.1f}%)"
)
print(
    f"   Labs with upper reference range: {labs_with_upper:,} ({labs_with_upper/len(df_lab)*100:.1f}%)"
)

# Count abnormal flags
if "flag" in df_lab.columns:
    abnormal_count = (df_lab["flag"] == "abnormal").sum()
    print(
        f"   Labs flagged as abnormal: {abnormal_count:,} ({abnormal_count/len(df_lab)*100:.1f}%)"
    )

# Check 4: Medication data quality
print("\n4️⃣  MEDICATION DATA QUALITY")

print(f"   Unique drugs: {df_pres['drug'].nunique():,}")
print(f"   Unique drug types: {df_pres['drug_type'].nunique()}")
print(f"   Unique routes: {df_pres['route'].nunique()}")
print(f"   Unique dose units: {df_pres['dose_unit'].nunique()}")

# ============================================================================
# 5. KEY STATISTICS
# ============================================================================

print("\n" + "=" * 80)
print("KEY STATISTICS")
print("=" * 80)

print(f"\n📊 OVERVIEW")
print(f"   Total patients: {len(df_pat):,}")
print(f"   Total admissions: {len(df_admission):,}")
print(f"   Total lab events: {len(df_lab):,}")
print(f"   Total prescriptions: {len(df_pres):,}")

print(f"\n👥 PATIENT DEMOGRAPHICS")
print(f"   Gender distribution:")
print(df_pat["gender"].value_counts().to_string())
print(f"\n   Age statistics:")
print(df_pat["age"].describe().to_string())

print(f"\n🏥 ADMISSION TYPES")
print(df_admission["admission_type"].value_counts().to_string())

print(f"\n🧪 TOP 10 LAB TESTS")
top_labs = df_lab["lab_item_id"].value_counts().head(10)
for lab_id, count in top_labs.items():
    print(f"   Lab {lab_id}: {count:,} tests")

print(f"\n💊 TOP 10 MEDICATIONS")
top_meds = df_pres["drug"].value_counts().head(10)
for drug, count in top_meds.items():
    print(f"   {drug}: {count:,} prescriptions")

# ============================================================================
# 6. SAVE SUMMARY REPORT
# ============================================================================

print("\n" + "=" * 80)
print("GENERATING SUMMARY REPORT")
print("=" * 80)

with open("data_profile_summary.txt", "w") as f:
    f.write("MIMIC-IV DATA PROFILING SUMMARY\n")
    f.write("=" * 80 + "\n")
    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    f.write("DATASET OVERVIEW\n")
    f.write("-" * 80 + "\n")
    f.write(f"Patients: {len(df_pat):,}\n")
    f.write(f"Admissions: {len(df_admission):,}\n")
    f.write(f"Lab Events: {len(df_lab):,}\n")
    f.write(f"Prescriptions: {len(df_pres):,}\n\n")

    f.write("DATA QUALITY ISSUES\n")
    f.write("-" * 80 + "\n")
    f.write(f"Orphaned admissions: {len(orphaned_adm)}\n")
    f.write(f"Orphaned lab events (patient): {len(orphaned_lab)}\n")
    f.write(f"Orphaned lab events (admission): {len(orphaned_lab_adm)}\n")
    f.write(f"Orphaned prescriptions (patient): {len(orphaned_pres)}\n")
    f.write(f"Orphaned prescriptions (admission): {len(orphaned_pres_adm)}\n")
    f.write(f"Invalid date ranges: {len(invalid_dates)}\n\n")

    f.write("NEXT STEPS\n")
    f.write("-" * 80 + "\n")
    f.write("1. Resolve referential integrity issues\n")
    f.write("2. Fix temporal inconsistencies\n")
    f.write("3. Create lab item mapping table\n")
    f.write("4. Standardize medication names\n")
    f.write("5. Document data cleaning decisions\n")

print("\n✓ Summary report saved to: data_profile_summary.txt")

# ============================================================================
# 7. CREATE VISUALIZATIONS
# ============================================================================

print("\n" + "=" * 80)
print("CREATING VISUALIZATIONS")
print("=" * 80)

# Set style
plt.style.use("default")
sns.set_palette("husl")

# Figure 1: Age distribution
fig, axes = plt.subplots(2, 2, figsize=(15, 12))

axes[0, 0].hist(df_pat["age"], bins=20, edgecolor="black", alpha=0.7)
axes[0, 0].set_xlabel("Age")
axes[0, 0].set_ylabel("Frequency")
axes[0, 0].set_title("Patient Age Distribution")
axes[0, 0].grid(alpha=0.3)

# Figure 2: Admission types
admission_counts = df_admission["admission_type"].value_counts()
axes[0, 1].bar(range(len(admission_counts)), admission_counts.values, alpha=0.7)
axes[0, 1].set_xticks(range(len(admission_counts)))
axes[0, 1].set_xticklabels(admission_counts.index, rotation=45, ha="right")
axes[0, 1].set_ylabel("Count")
axes[0, 1].set_title("Admission Types")
axes[0, 1].grid(alpha=0.3)

# Figure 3: Length of stay distribution
axes[1, 0].hist(
    df_admission["length_of_stay_hours"].dropna(), bins=30, edgecolor="black", alpha=0.7
)
axes[1, 0].set_xlabel("Length of Stay (hours)")
axes[1, 0].set_ylabel("Frequency")
axes[1, 0].set_title("Length of Stay Distribution")
axes[1, 0].grid(alpha=0.3)

# Figure 4: Gender distribution
gender_counts = df_pat["gender"].value_counts()
axes[1, 1].pie(
    gender_counts.values, labels=gender_counts.index, autopct="%1.1f%%", startangle=90
)
axes[1, 1].set_title("Gender Distribution")

plt.tight_layout()
plt.savefig("data_overview.png", dpi=300, bbox_inches="tight")
print("✓ Visualizations saved to: data_overview.png")

plt.close()

# ============================================================================
# 8. FINAL SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("DATA EXPLORATION COMPLETE!")
print("=" * 80)
print("\n📁 Generated Files:")
print("   1. data_profile_summary.txt - Text summary of findings")
print("   2. data_overview.png - Visualization of key metrics")
print("\n📋 Next Steps:")
print("   1. Review the data quality issues identified")
print("   2. Create a lab item mapping table (d_labitems.csv)")
print("   3. Begin data cleaning and refinement")
print("   4. Document all cleaning decisions")
print("\n" + "=" * 80 + "\n")
