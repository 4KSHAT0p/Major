import requests

# Upload template
with open("Inpatient_Encounter.opt", "r") as f:
    template_xml = f.read()

response = requests.post(
    "http://localhost:8080/ehrbase/rest/openehr/v1/definition/template/adl1.4",
    headers={"Content-Type": "application/xml"},
    data=template_xml,
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
