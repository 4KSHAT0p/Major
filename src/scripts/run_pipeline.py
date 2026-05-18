"""Full orchestration script for the clinical data standardisation pipeline.

Stages follow the architecture diagram:
  (a) Input            – load raw CSV (implicit inside cleaning script)
  (b) Refinement       – data cleaning / normalization
  (c.1) Pre-validation – structural checks before mapping
  (c.2) Mapping        – build openEHR compositions
  (d) EHRbase Load     – create EHRs & commit compositions (handled by map.py)
  (e) Post-validation  – semantic parity checks
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import List

import requests

from service_config import BACKEND_HEALTH_URL, EHRBASE_HEALTH_URL

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "src" / "scripts"
PYTHON_BIN = sys.executable

TEMPLATE_SCRIPT = "post.py"

STAGES = [
    ("(a)+(b) Input & Refinement", [PYTHON_BIN, str(SCRIPTS_DIR / "clean_json.py")]),
    ("(c.1) Pre-Mapping Validation", [PYTHON_BIN, str(SCRIPTS_DIR / "pre_validate.py")]),
    # Template upload ensures EHRbase knows about the composition structure before mapping
    ("Template deployment", [PYTHON_BIN, str(SCRIPTS_DIR / TEMPLATE_SCRIPT)]),
    ("(c.2)+(d) Mapping & EHRbase load", [PYTHON_BIN, str(SCRIPTS_DIR / "map.py")]),
    ("(e) Post-Mapping Validation", [PYTHON_BIN, str(SCRIPTS_DIR / "validate.py")]),
]

SERVICE_CHECKS = {
    "Template deployment": [("EHRbase", EHRBASE_HEALTH_URL)],
    "(c.2)+(d) Mapping & EHRbase load": [
        ("Mapping backend", BACKEND_HEALTH_URL),
        ("EHRbase", EHRBASE_HEALTH_URL),
    ],
    "(e) Post-Mapping Validation": [("EHRbase", EHRBASE_HEALTH_URL)],
}


class PipelineError(Exception):
    pass


def wait_for_service(name: str, url: str, timeout: int = 60) -> None:
    print(f"Checking {name} at {url} ...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"[PASS] {name} is reachable")
                return
        except requests.RequestException:
            time.sleep(2)
            continue
        time.sleep(2)
    raise PipelineError(f"{name} not reachable within {timeout}s — please start it before rerunning")


def run_stage(label: str, command: List[str]) -> None:
    print("\n============================================================")
    print(f"Running stage {label}")
    print("Command:", " ".join(command))
    print("============================================================")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        raise PipelineError(f"Stage '{label}' failed with exit code {result.returncode}")


def main() -> int:
    try:
        for label, command in STAGES:
            for service_name, service_url in SERVICE_CHECKS.get(label, []):
                wait_for_service(service_name, service_url)
            run_stage(label, command)
    except PipelineError as exc:
        print(f"[FAIL] {exc}")
        return 1
    except KeyboardInterrupt:
        print("Pipeline interrupted by user")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
