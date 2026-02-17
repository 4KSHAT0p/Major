import pandas as pd

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

# Optional: rename to cleaner names
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

# Rename for clarity
df_lab = df_lab.rename(
    columns={
        "subject_id": "patient_id",
        "hadm_id": "admission_id",
        "itemid": "lab_item_id",
        "charttime": "observation_time",
        "valueuom": "unit",
    }
)

# Optional: keep only numeric labs
df_lab = df_lab[df_lab["valuenum"].notna()]


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

# Rename for clarity
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

# Optional: drop rows without dose info
df_pres = df_pres[df_pres["dose_value"].notna()]


df_pat = pd.read_csv(
    "mimic-iv-clinical-database-demo-2.2/hosp/patients.csv",
    usecols=["subject_id", "gender", "anchor_age", "dod"],
)

df_pat = df_pat.rename(
    columns={"subject_id": "patient_id", "anchor_age": "age", "dod": "death_date"}
)

# ================================
# GENERAL CLEANING FUNCTION
# ================================

def basic_cleaning(df):
    df = df.copy()
    
    # Remove exact duplicates
    df = df.drop_duplicates()
    
    # Strip spaces from string columns
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()
    
    return df


# ================================
# ADMISSIONS CLEANING
# ================================

df_admission = basic_cleaning(df_admission)

# Convert datetime
datetime_cols = ["admit_time", "discharge_time", "death_time"]
for col in datetime_cols:
    df_admission[col] = pd.to_datetime(df_admission[col], errors="coerce")

# Remove rows missing critical fields
df_admission = df_admission.dropna(subset=["patient_id", "admission_id", "admit_time"])

# Remove impossible discharge < admit
df_admission = df_admission[
    (df_admission["discharge_time"].isna()) |
    (df_admission["discharge_time"] >= df_admission["admit_time"])
]

# Ensure hospital_expired is 0/1
df_admission["hospital_expired"] = df_admission["hospital_expired"].fillna(0).astype(int)


# ================================
# LAB EVENTS CLEANING
# ================================

df_lab = basic_cleaning(df_lab)

df_lab["observation_time"] = pd.to_datetime(df_lab["observation_time"], errors="coerce")

# Remove rows missing critical fields
df_lab = df_lab.dropna(subset=["patient_id", "admission_id", "lab_item_id", "valuenum"])

# Convert numeric safely
df_lab["valuenum"] = pd.to_numeric(df_lab["valuenum"], errors="coerce")


# Standardize units
df_lab["unit"] = df_lab["unit"].str.lower()


# ================================
# PRESCRIPTIONS CLEANING
# ================================

df_pres = basic_cleaning(df_pres)

df_pres["med_start_time"] = pd.to_datetime(df_pres["med_start_time"], errors="coerce")
df_pres["med_stop_time"] = pd.to_datetime(df_pres["med_stop_time"], errors="coerce")

# Remove rows missing critical fields
df_pres = df_pres.dropna(subset=["patient_id", "admission_id", "drug", "dose_value"])

# Convert dose to numeric
df_pres["dose_value"] = pd.to_numeric(df_pres["dose_value"], errors="coerce")

# Remove negative or zero doses
df_pres = df_pres[df_pres["dose_value"] > 0]

# Remove impossible stop < start
df_pres = df_pres[
    (df_pres["med_stop_time"].isna()) |
    (df_pres["med_stop_time"] >= df_pres["med_start_time"])
]

df_pres["dose_unit"] = df_pres["dose_unit"].str.lower()
df_pres["route"] = df_pres["route"].str.lower()


# ================================
# PATIENTS CLEANING
# ================================

df_pat = basic_cleaning(df_pat)

df_pat["death_date"] = pd.to_datetime(df_pat["death_date"], errors="coerce")

# Remove invalid ages
df_pat = df_pat[(df_pat["age"] >= 0) & (df_pat["age"] <= 120)]

# Standardize gender
df_pat["gender"] = df_pat["gender"].str.upper()
df_pat = df_pat[df_pat["gender"].isin(["M", "F"])]


# ================================
# FINAL CONSISTENCY CHECK
# ================================

# Keep only admissions with valid patients
df_admission = df_admission[df_admission["patient_id"].isin(df_pat["patient_id"])]

# Keep labs & prescriptions linked to valid admissions
valid_admissions = df_admission["admission_id"].unique()

df_lab = df_lab[df_lab["admission_id"].isin(valid_admissions)]
df_pres = df_pres[df_pres["admission_id"].isin(valid_admissions)]



df_admission.to_json("clean_admissions.json", orient="records", date_format="iso")
df_lab.to_json("clean_labs.json", orient="records", date_format="iso")
df_pres.to_json("clean_prescriptions.json", orient="records", date_format="iso")
df_pat.to_json("clean_patients.json", orient="records", date_format="iso")


print("✅ Data cleaned and standardized successfully.")
