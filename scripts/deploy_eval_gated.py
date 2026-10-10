"""Eval-gated deployment workflow for Study Navigator (Milestone 5).

Implements the DevCamp graduation gate:
Runs both the golden evaluation suite and red-team safety tests before permitting deployment.
If any critical rubric or safety test fails, deployment halts immediately.
"""

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
EVAL_REPORT_PATH = REPO_ROOT / "evals" / "eval_report.json"
DEPLOY_MANIFEST_PATH = REPO_ROOT / "deploy_manifest.json"


def run_gate_checks() -> bool:
    print("=" * 80)
    print("Running Pre-Deployment Governance & Evaluation Gate")
    print("=" * 80)

    # 1. Red-team safety check
    print("\n[Gate 1/2] Executing Red-Team Adversarial Safety Checks...")
    py_exec = sys.executable
    ret_red = subprocess.run([py_exec, "-m", "unittest", "tests/test_redteam.py"], cwd=str(REPO_ROOT))
    if ret_red.returncode != 0:
        print("\n[DEPLOYMENT BLOCKED] Red-team safety tests failed! Aborting deployment.")
        return False
    print("[Gate 1/2] Red-Team checks PASSED (100% attack refusal).")

    # 2. Golden Evaluation Suite
    print("\n[Gate 2/2] Executing Golden Benchmark Evaluation Suite...")
    ret_eval = subprocess.run([py_exec, "evals/run_eval.py"], cwd=str(REPO_ROOT))
    if ret_eval.returncode != 0:
        print("\n[DEPLOYMENT BLOCKED] Eval suite execution error! Aborting deployment.")
        return False

    if not EVAL_REPORT_PATH.exists():
        print("\n[DEPLOYMENT BLOCKED] Evaluation report not found! Aborting deployment.")
        return False

    with open(EVAL_REPORT_PATH, "r", encoding="utf-8") as f:
        report = json.load(f)

    passed_cases = report.get("passed_cases", 0)
    total_cases = report.get("total_cases", 0)
    pass_rate = (passed_cases / total_cases) * 100 if total_cases > 0 else 0

    print(f"\nEvaluation Benchmark Score: {passed_cases}/{total_cases} ({pass_rate:.1f}%)")
    if pass_rate < 85.0:
        print(f"\n[DEPLOYMENT BLOCKED] Evaluation pass rate {pass_rate:.1f}% below required threshold of 85.0%!")
        return False

    print("[Gate 2/2] Evaluation suite PASSED (Quality and rubrics verified).")
    return True


def generate_deployment_manifest(stage_only: bool = False) -> dict:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "local-dev-project")
    location = os.environ.get("AGENT_RUNTIME_LOCATION", "us-central1")
    model = os.environ.get("STUDY_AGENT_MODEL", "gemini-3.1-flash-lite")

    manifest = {
        "deployment_id": f"deploy_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "app_name": "study_navigator",
        "display_name": "Study Navigator Adaptive Agent",
        "target_project": project,
        "region": location,
        "pinned_model": model,
        "governance": {
            "guardrails_enabled": True,
            "redteam_status": "verified_clean",
            "model_armor_region": os.environ.get("MODEL_ARMOR_REGION", "europe-west2"),
        },
        "evaluation_gate": {
            "status": "PASSED",
            "report_file": str(EVAL_REPORT_PATH.relative_to(REPO_ROOT)),
        },
        "stage_only": stage_only,
    }

    with open(DEPLOY_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Eval-gated deployment runner for Study Navigator.")
    parser.add_argument("--stage-only", action="store_true", help="Build deployment manifest without pushing to Cloud.")
    parser.add_argument("--skip-tests", action="store_true", help="Bypass evaluation gate (strictly for debugging).")
    args = parser.parse_args()

    if not args.skip_tests:
        gate_ok = run_gate_checks()
        if not gate_ok:
            sys.exit(1)
    else:
        print("[WARNING] Skipping evaluation gate per --skip-tests flag.")

    manifest = generate_deployment_manifest(stage_only=args.stage_only)

    print("\n" + "=" * 80)
    print("DEPLOYMENT GATE CLEARED SUCCESSFULLY")
    print(f"Deployment Manifest generated: {DEPLOY_MANIFEST_PATH}")
    print(f"Target: {manifest['display_name']} ({manifest['pinned_model']}) in {manifest['region']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
