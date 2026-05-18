import requests

from service_config import EHRBASE_API_URL

EHRBASE_URL = EHRBASE_API_URL

aql_list = """
SELECT
    e/ehr_id/value                AS ehr_id,
    c/uid/value                   AS composition_id,
    c/context/start_time/value    AS admit_time,
    c/context/end_time/value      AS discharge_time
FROM EHR e
CONTAINS COMPOSITION c
WHERE c/archetype_details/template_id/value = 'Inpatient_Encounter'
"""

res = requests.post(
    f"{EHRBASE_URL}/query/aql",
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    json={"q": aql_list},
)

data = res.json()
print(f"Total compositions: {len(data['rows'])}\n")
for row in data["rows"]:
    print(f"  EHR:         {row[0]}")
    print(f"  Composition: {row[1]}")
    print(f"  Admit:       {row[2]}")
    print(f"  Discharge:   {row[3]}")
    print()
