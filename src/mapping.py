"""
MIMIC-IV to OpenEHR Mapping Script
===================================
Maps cleaned MIMIC JSON files to openEHR compositions and uploads to EHRbase.

Authors: Akshat Singh, Arya Verma
Date: February 2026
"""



# ============================================================================
# STEP 3: MAP ADMISSION TO COMPOSITION
# ============================================================================


def create_composition(
    admission: Dict,
    patient: Dict,
    admission_labs: List[Dict],
    admission_meds: List[Dict],
) -> Dict:
    """
    Create openEHR composition for one admission
    """

    composition = {
        "_type": "COMPOSITION",
        "name": {"_type": "DV_TEXT", "value": "Inpatient Encounter"},
        "archetype_details": {
            "archetype_id": {
                "_type": "ARCHETYPE_ID",
                "value": "openEHR-EHR-COMPOSITION.encounter.v1",
            },
            "template_id": {"_type": "TEMPLATE_ID", "value": TEMPLATE_ID},
            "rm_version": "1.0.4",
        },
        "language": {
            "_type": "CODE_PHRASE",
            "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "ISO_639-1"},
            "code_string": "en",
        },
        "territory": {
            "_type": "CODE_PHRASE",
            "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "ISO_3166-1"},
            "code_string": "US",
        },
        "category": {
            "_type": "DV_CODED_TEXT",
            "value": "event",
            "defining_code": {
                "_type": "CODE_PHRASE",
                "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "openehr"},
                "code_string": "433",
            },
        },
        "composer": {"_type": "PARTY_IDENTIFIED", "name": "MIMIC-IV Pipeline"},
        "context": {
            "_type": "EVENT_CONTEXT",
            "start_time": {"_type": "DV_DATE_TIME", "value": admission["admit_time"]},
            "end_time": {"_type": "DV_DATE_TIME", "value": admission["discharge_time"]},
            "setting": {
                "_type": "DV_CODED_TEXT",
                "value": "hospital",
                "defining_code": {
                    "_type": "CODE_PHRASE",
                    "terminology_id": {"_type": "TERMINOLOGY_ID", "value": "openehr"},
                    "code_string": "229",
                },
            },
        },
        "content": [],
    }

    # Add admission details (Episode of care archetype)
    admission_entry = {
        "_type": "ADMIN_ENTRY",
        "name": {"_type": "DV_TEXT", "value": "Hospital Episode"},
        "archetype_details": {
            "archetype_id": {
                "_type": "ARCHETYPE_ID",
                "value": "openEHR-EHR-ADMIN_ENTRY.episode_of_care.v0",
            },
            "rm_version": "1.0.4",
        },
        "data": {
            "_type": "ITEM_TREE",
            "items": [
                {
                    "_type": "ELEMENT",
                    "name": {"_type": "DV_TEXT", "value": "Admission type"},
                    "value": {"_type": "DV_TEXT", "value": admission["admission_type"]},
                },
                {
                    "_type": "ELEMENT",
                    "name": {"_type": "DV_TEXT", "value": "Admission source"},
                    "value": {
                        "_type": "DV_TEXT",
                        "value": admission["admission_location"],
                    },
                },
                {
                    "_type": "ELEMENT",
                    "name": {"_type": "DV_TEXT", "value": "Discharge destination"},
                    "value": {
                        "_type": "DV_TEXT",
                        "value": admission["discharge_location"],
                    },
                },
            ],
        },
    }

    composition["content"].append(admission_entry)

    # Add lab results
    for lab in admission_labs:
        lab_observation = {
            "_type": "OBSERVATION",
            "name": {"_type": "DV_TEXT", "value": f"Lab Test {lab['lab_item_id']}"},
            "archetype_details": {
                "archetype_id": {
                    "_type": "ARCHETYPE_ID",
                    "value": "openEHR-EHR-OBSERVATION.laboratory_test_result.v1",
                },
                "rm_version": "1.0.4",
            },
            "data": {
                "_type": "HISTORY",
                "origin": {"_type": "DV_DATE_TIME", "value": lab["observation_time"]},
                "events": [
                    {
                        "_type": "POINT_EVENT",
                        "time": {
                            "_type": "DV_DATE_TIME",
                            "value": lab["observation_time"],
                        },
                        "data": {
                            "_type": "ITEM_TREE",
                            "items": [
                                {
                                    "_type": "ELEMENT",
                                    "name": {
                                        "_type": "DV_TEXT",
                                        "value": "Test result",
                                    },
                                    "value": {
                                        "_type": "DV_QUANTITY",
                                        "magnitude": lab["valuenum"],
                                        "units": lab["unit"],
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        }

        composition["content"].append(lab_observation)

    # Add medications
    for med in admission_meds:
        med_instruction = {
            "_type": "INSTRUCTION",
            "name": {"_type": "DV_TEXT", "value": f"Medication: {med['drug']}"},
            "archetype_details": {
                "archetype_id": {
                    "_type": "ARCHETYPE_ID",
                    "value": "openEHR-EHR-INSTRUCTION.medication_order.v3",
                },
                "rm_version": "1.0.4",
            },
            "narrative": {
                "_type": "DV_TEXT",
                "value": f"{med['drug']} {med['dose_value']}{med['dose_unit']} {med['route']}",
            },
            "activities": [
                {
                    "_type": "ACTIVITY",
                    "description": {
                        "_type": "ITEM_TREE",
                        "items": [
                            {
                                "_type": "ELEMENT",
                                "name": {
                                    "_type": "DV_TEXT",
                                    "value": "Medication item",
                                },
                                "value": {"_type": "DV_TEXT", "value": med["drug"]},
                            },
                            {
                                "_type": "ELEMENT",
                                "name": {"_type": "DV_TEXT", "value": "Dose amount"},
                                "value": {
                                    "_type": "DV_QUANTITY",
                                    "magnitude": med["dose_value"],
                                    "units": med["dose_unit"],
                                },
                            },
                            {
                                "_type": "ELEMENT",
                                "name": {"_type": "DV_TEXT", "value": "Route"},
                                "value": {"_type": "DV_TEXT", "value": med["route"]},
                            },
                        ],
                    },
                }
            ],
        }

        composition["content"].append(med_instruction)

    return composition


# ============================================================================
# STEP 4: UPLOAD COMPOSITIONS
# ============================================================================


def upload_composition(ehr_id: str, composition: Dict) -> Optional[str]:
    """Upload composition to EHRbase"""

    url = f"{EHRBASE_URL}/ehr/{ehr_id}/composition"

    response = requests.post(
        url,
        json=composition,
        headers={"Content-Type": "application/json", "Prefer": "return=representation"},
    )

    if response.status_code == 201:
        comp_data = response.json()
        return comp_data["uid"]["value"]
    else:
        raise Exception(f"Upload failed: {response.text}")


# ============================================================================
# STEP 5: PROCESS ALL ADMISSIONS
# ============================================================================

print("\n" + "=" * 80)
print("PROCESSING ADMISSIONS")
print("=" * 80)

successful = []
failed = []

for admission in admissions:
    patient_id = admission["patient_id"]
    admission_id = admission["admission_id"]

    # Skip if no EHR created
    if patient_id not in ehr_mapping:
        print(f"⊗ Skipping admission {admission_id} - no EHR for patient {patient_id}")
        failed.append((admission_id, "No EHR"))
        continue

    try:
        # Get patient data
        patient = next((p for p in patients if p["patient_id"] == patient_id), None)
        if not patient:
            raise Exception("Patient not found")

        # Get labs for this admission
        admission_labs = [l for l in labs if l["admission_id"] == admission_id]

        # Get meds for this admission
        admission_meds = [m for m in prescriptions if m["admission_id"] == admission_id]

        # Create composition
        composition = create_composition(
            admission, patient, admission_labs, admission_meds
        )

        # Upload to EHRbase
        ehr_id = ehr_mapping[patient_id]
        comp_id = upload_composition(ehr_id, composition)

        successful.append(admission_id)
        print(
            f"✓ Admission {admission_id}: {len(admission_labs)} labs, {len(admission_meds)} meds → {comp_id}"
        )

    except Exception as e:
        failed.append((admission_id, str(e)))
        print(f"✗ Admission {admission_id} failed: {e}")

# ============================================================================
# STEP 6: SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"✓ Successfully processed: {len(successful)} admissions")
print(f"✗ Failed: {len(failed)} admissions")

if failed:
    print("\nFailed admissions:")
    for adm_id, error in failed[:10]:  # Show first 10
        print(f"  - {adm_id}: {error}")

print("\n" + "=" * 80)
print("PIPELINE COMPLETE!")
print("=" * 80)

# Save results
results = {
    "timestamp": datetime.now().isoformat(),
    "ehr_count": len(ehr_mapping),
    "successful_admissions": len(successful),
    "failed_admissions": len(failed),
    "ehr_mapping": ehr_mapping,
    "successful_ids": successful,
    "failed_details": failed,
}

with open("pipeline_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("✓ Results saved to: pipeline_results.json")
