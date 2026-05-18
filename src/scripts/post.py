"""Upload the Inpatient_Encounter template to EHRbase with retries."""

from pathlib import Path
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from service_config import EHRBASE_API_URL

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ID = "Inpatient_Encounter"
TEMPLATE_PATH = ROOT / "openEHR" / f"{TEMPLATE_ID}.opt"
TEMPLATE_URL = f"{EHRBASE_API_URL}/definition/template/adl1.4"
HTTP_TIMEOUT = 15


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST", "PUT"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = _build_session()


def template_exists() -> bool:
    url = f"{TEMPLATE_URL}/{TEMPLATE_ID}"
    try:
        response = SESSION.get(url, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        print(f"[WARN] Unable to verify template status: {exc}")
        return False

    if response.status_code == 200:
        return True
    if response.status_code == 404:
        return False

    print(f"[WARN] Unexpected status while checking template ({response.status_code}): {response.text}")
    return False


def upload_template() -> int:
    try:
        template_xml = TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"[FAIL] Template file missing at {TEMPLATE_PATH}")
        return 1

    headers = {
        "Content-Type": "application/xml",
        "Accept": "application/json",
    }

    try:
        response = SESSION.post(
            TEMPLATE_URL,
            headers=headers,
            data=template_xml,
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"[FAIL] Template upload failed: {exc}")
        return 1

    if response.status_code in (200, 201):
        print("[PASS] Template uploaded to EHRbase")
        return 0
    if response.status_code == 409:
        print("[SKIP] Template already present on EHRbase (409)")
        return 0

    print(f"[FAIL] Template upload returned {response.status_code}: {response.text}")
    return 1


def main() -> int:
    if template_exists():
        print("[SKIP] Template already registered; no upload needed")
        return 0
    return upload_template()


if __name__ == "__main__":
    sys.exit(main())
