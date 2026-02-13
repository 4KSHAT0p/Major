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
        "hospital_expire_flag"
    ]
)

# Optional: rename to cleaner names
df_admission = df_admission.rename(columns={
    "subject_id": "patient_id",
    "hadm_id": "admission_id",
    "admittime": "admit_time",
    "dischtime": "discharge_time",
    "deathtime": "death_time",
    "hospital_expire_flag": "hospital_expired"
})


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
        "flag"
    ]
)

# Rename for clarity
df_lab = df_lab.rename(columns={
    "subject_id": "patient_id",
    "hadm_id": "admission_id",
    "itemid": "lab_item_id",
    "charttime": "observation_time",
    "valueuom": "unit"
})

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
        "doses_per_24_hrs"
    ]
)

# Rename for clarity
df_pres = df_pres.rename(columns={
    "subject_id": "patient_id",
    "hadm_id": "admission_id",
    "starttime": "med_start_time",
    "stoptime": "med_stop_time",
    "dose_val_rx": "dose_value",
    "dose_unit_rx": "dose_unit"
})

# Optional: drop rows without dose info
df_pres = df_pres[df_pres["dose_value"].notna()]


df_pat = pd.read_csv(
    "mimic-iv-clinical-database-demo-2.2/hosp/patients.csv",
    usecols=[
        "subject_id",
        "gender",
        "anchor_age",
        "dod"
    ]
)

df_pat = df_pat.rename(columns={
    "subject_id": "patient_id",
    "anchor_age": "age",
    "dod": "death_date"
})



print(df_pat.columns)

