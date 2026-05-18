# Clinical Data Standardization Pipeline (Part 1)

This repository implements the **Part 1** ETL pipeline that turns raw MIMIC-IV clinical CSVs into openEHR-compliant compositions stored in EHRbase. Visualization, LLM, and knowledge-graph components ("Part 2") are intentionally excluded so that this pipeline stays focused on trustworthy clinical data preparation.

---

## 1. Project Overview

- **Problem**: Real-world hospital data arrives as loosely structured CSVs with inconsistent timestamps, duplicated rows, and missing relationships. Clinicians cannot trust downstream analytics unless the data is standardized and validated.
- **Goal**: Convert MIMIC-IV admissions, lab events, and prescriptions into canonical `Inpatient_Encounter` compositions so the same records can be queried across EHR systems.
- **Outcome**: A repeatable ETL flow that cleans raw CSVs, performs structural checks, maps each admission to openEHR compositions, stores them in EHRbase, and then validates that nothing was lost or corrupted.

---

## 2. Architecture (Part 1 Only)

| Stage                        | Script            | Purpose                                                         |
| ---------------------------- | ----------------- | --------------------------------------------------------------- |
| (a) Input                    | `clean_json.py`   | Load raw CSVs, subset relevant columns                          |
| (b) Refinement               | `clean_json.py`   | Normalize types, drop duplicates, enforce clinical sanity rules |
| (c.1) Pre-Mapping Validation | `pre_validate.py` | Structural QA on cleaned JSON before mapping                    |
| (c.2) Mapping                | `map.py`          | Build openEHR compositions per admission                        |
| (d) EHRbase Load             | `map.py`          | Create EHRs, cache IDs, post compositions                       |
| (e) Post-Mapping Validation  | `validate.py`     | Count, relationship, and semantic validation versus source CSVs |
| Orchestration                | `run_pipeline.py` | Executes the entire sequence with service health gates          |

Supporting services:

- `src/docker-compose.yaml` launches PostgreSQL + EHRbase.
- `src/backend/server.js` provides a minimal cache to map `patient_id → ehr_id`.
- `src/scripts/service_config.py` centralizes service URLs/env overrides.

---

## 3. Folder Structure

```
Major/
├─ README.md                     # This guide
├─ requirements.txt              # Python dependencies
├─ clean_*.json                  # Outputs from the cleaning stage
├─ mimic-iv-clinical-database-demo-2.2/  # Raw CSVs (patients, admissions, etc.)
└─ src/
   ├─ docker-compose.yaml        # Postgres + EHRbase stack (default host port 8090)
   ├─ request.rest               # Sample REST calls against EHRbase
   ├─ backend/
   │  ├─ package.json
   │  └─ server.js              # Simple Express cache for patient→EHR mapping
   └─ scripts/
      ├─ clean_json.py          # Stages (a)+(b)
      ├─ pre_validate.py        # Stage (c.1)
      ├─ map.py                 # Stages (c.2)+(d)
      ├─ post.py                # Template deployment
      ├─ validate.py            # Stage (e)
      ├─ run_pipeline.py        # Orchestrator
      └─ service_config.py      # Shared configuration helper
```

---

## 4. Setup Instructions

### 4.1 Python Environment

```bash
# From the repository root
python -m venv .venv
. .venv/Scripts/activate   # Windows PowerShell
pip install --upgrade pip
pip install -r requirements.txt
```

> Developed with Python 3.12; any 3.11+ build with pandas ≥2.2 should work.

### 4.2 EHRbase & PostgreSQL

```bash
cd src
# Optional: customize host port (default 8090) before composed up
$env:EHRBASE_HOST_PORT = 8090  # PowerShell example

docker compose up -d
```

Verify health:

```bash
Invoke-WebRequest -UseBasicParsing http://localhost:8090/ehrbase/
```

Use `docker compose down` to stop the stack when finished.

### 4.3 Mapping Backend

Install once:

```bash
cd src/backend
npm install
```

Run for every session:

```bash
cd src/backend
node server.js  # Keep this terminal open (Ctrl+C to stop)
```

The backend exposes `GET/POST /:patient_id` for caching EHR IDs.

### 4.4 Environment Variables

All scripts rely on `service_config.py`; override defaults as needed.

| Variable                  | Default                              | Purpose                                 |
| ------------------------- | ------------------------------------ | --------------------------------------- |
| `EHRBASE_BASE_URL`        | `http://localhost:8090/ehrbase`      | Root of the EHRbase deployment          |
| `EHRBASE_HOST_PORT`       | `8090`                               | Host port forwarded to container `8080` |
| `EHRBASE_API_URL`         | `<EHRBASE_BASE_URL>/rest/openehr/v1` | Direct override for REST base           |
| `EHRBASE_HEALTH_URL`      | `<EHRBASE_BASE_URL>/`                | Health-check endpoint                   |
| `BACKEND_BASE_URL`        | `http://localhost:3000`              | In-memory cache service                 |
| `BACKEND_HEALTH_URL`      | `<BACKEND_BASE_URL>/health`          | Backend health endpoint                 |
| `EHRBASE_REQUEST_TIMEOUT` | `20`                                 | Seconds used by validation AQL queries  |
| `EHRBASE_AQL_RETRIES`     | `3`                                  | Retry count for validation queries      |

---

## 5. Dataset Preparation

1. Download the MIMIC-IV demo (or full) `hosp` CSVs.
2. Place them under `mimic-iv-clinical-database-demo-2.2/hosp/` with the original filenames:
   - `patients.csv`
   - `admissions.csv`
   - `labevents.csv`
   - `prescriptions.csv`
3. Ensure the relative paths in `clean_json.py` remain valid. If you store data elsewhere, update the file paths or add symlinks.

The cleaning stage writes JSON artifacts (`clean_patients.json`, etc.) at the repository root; mapping/validation consume those files.

---

## 6. Running the Pipeline

### One-shot execution

```bash
cd <repo-root>
python src/scripts/run_pipeline.py
```

This command executes every stage in order:

1. **Clean** (`clean_json.py`) – standardizes CSVs.
2. **Pre-validate** (`pre_validate.py`) – ensures data is structurally sane.
3. **Template deploy** (`post.py`) – registers the `Inpatient_Encounter` template in EHRbase (idempotent).
4. **Map & Load** (`map.py`) – creates EHRs, builds compositions, skips duplicates via existing-admission lookup.
5. **Post-validate** (`validate.py`) – confirms semantic parity.

### Running an individual stage

Each script can be invoked independently, e.g.

```bash
python src/scripts/clean_json.py
python src/scripts/pre_validate.py
python src/scripts/map.py
python src/scripts/validate.py
```

This is useful while iterating on a specific transformation.

### Stopping services

```bash
# Stop backend (from the terminal running node)
Ctrl+C

# Stop EHRbase stack
cd src
docker compose down
```

---

## 7. Validation Guide

The validation phase prints `[PASS]`/`[FAIL]` lines for each check:

- **Count validation**: Patient, admission, lab, and prescription totals must match between CSV and EHRbase. Any mismatch indicates dropped or duplicated records during mapping.
- **Relationship validation**: Compares derived aggregations (admissions per patient, labs per admission, meds per admission) so referential integrity survives the ETL.
- **Sample validation**: Random admissions are sampled, then lab values, medication names, and timestamps are compared field-by-field. A tolerant numeric comparison prevents false alarms caused by floating-point formatting.
- **Edge checks**: Flags missing IDs, non-positive doses, or empty compositions to catch silent corruption.

Interpreting output:

- `[PASS]` means counts aligned or no anomalies were found.
- `[FAIL]` includes a short reason; rerun the upstream stage after addressing the issue.
- `[SAMPLE] ...` lines (only shown on mismatches) identify the exact admission and measurement that failed.

---

## 8. Design Decisions & Rationale

- **pandas for preprocessing**: Provides vectorized datetime/number handling, deduplication, and CSV parsing needed for clinical sanity checks without writing imperative loops.
- **Grouping by `admission_id`**: Admissions are the natural unit of care. Labs and meds are linked via `hadm_id`, so grouping ensures each composition contains exactly the events observed during that hospital stay.
- **One admission = one composition**: Aligns with the `Inpatient_Encounter` template and mirrors how clinicians reason about episodes of care; also simplifies downstream AQL queries and deduplication logic.
- **openEHR + EHRbase instead of raw storage**: The archetype/template layer enforces clinical semantics (units, terminology bindings) and enables interoperable queries; raw SQL tables would lose this semantic contract.
- **Multi-level validation**: Pure record counts cannot catch swapped lab values or broken relationships. Combining counts, relationship checks, and sampled semantic compares guarantees both coverage (counts) and depth (content-level parity).
- **Service health gates**: `run_pipeline.py` waits for the mapping backend and EHRbase before launching dependent stages so faults are caught early.
- **Idempotent mapping**: `map.py` fetches existing admission IDs and skips duplicates, allowing safe re-runs without wiping EHRbase.
- **Config abstraction**: `service_config.py` centralizes URLs so switching hosts/ports for docker vs. remote deployments only requires environment variables.

---

## 9. Troubleshooting

| Symptom                                            | Cause                                                               | Fix                                                                                           |
| -------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `port is already allocated` when starting docker   | Another service uses the port, or an old container is still running | `docker compose down`, adjust `EHRBASE_HOST_PORT`, then `docker compose up -d`                |
| `Mapping backend is not reachable` during pipeline | `node server.js` not running                                        | Start the backend in a dedicated terminal; confirm `http://localhost:3000/health` returns 200 |
| Template upload returns 409                        | Template already registered                                         | Safe to ignore; `[SKIP]` indicates idempotent success                                         |
| Validation `[FAIL]` counts                         | Cleaning or mapping dropped rows                                    | Re-run `clean_json.py`; check docker/EHRbase logs for rejected compositions                   |
| `[FAIL] Sample value`                              | A lab/med did not match                                             | Inspect `[SAMPLE]` output, verify raw CSV vs. EHRbase via `request.rest` queries              |
| Requests time out                                  | EHRbase under heavy load                                            | Increase `EHRBASE_REQUEST_TIMEOUT`/`EHRBASE_AQL_RETRIES`, or ensure docker has enough memory  |
| Backend returns 403 on POST                        | Trying to cache an already-known `patient_id`                       | Safe to ignore; map.py logs it but still proceeds                                             |

---

## 10. Quick Command Reference

```bash
# 0) Install Python deps
pip install -r requirements.txt

# 1) Launch databases (inside src/)
docker compose up -d

# 2) Start backend cache
cd src/backend
node server.js

# 3) Run everything (new terminal)
cd <repo-root>
python src/scripts/run_pipeline.py

# 4) Tear down
#   - Ctrl+C backend
cd src
docker compose down
```

For ad-hoc debugging, use VS Code's REST client (`src/request.rest`) or run `python src/scripts/validate.py` to re-check the EHRbase state without remapping data.

---

## 11. Final Notes

- This README documents **only** the clinical data standardization pipeline. LLM dashboards or knowledge-graph consumers are out of scope.
- All transformations preserve clinical meaning: timestamps stay in ISO8601, dosage units remain attached, and admissions never mix across patients.
- Each script contains inline comments explaining non-obvious logic; consult them when extending the pipeline.

Happy mapping!
