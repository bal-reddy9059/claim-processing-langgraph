"""
Quick test script — runs against the locally running server.
Usage:
    python test_pipeline.py                          # uses sample.pdf
    python test_pipeline.py final_image_protected.pdf
"""

import json
import sys
import os
import requests

BASE_URL = "http://localhost:8000"


def check_health():
    r = requests.get(f"{BASE_URL}/health")
    print("Health:", r.json())


def show_workflow():
    r = requests.get(f"{BASE_URL}/api/workflow-info")
    print("\nWorkflow Info:")
    print(json.dumps(r.json(), indent=2))


def process_pdf(pdf_path: str, claim_id: str = "CLM-TEST-001"):
    if not os.path.exists(pdf_path):
        print(f"❌ File not found: {pdf_path}")
        return

    print(f"\n📄 Processing: {pdf_path}  (claim_id={claim_id})")
    with open(pdf_path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/api/process",
            data={"claimId": claim_id},
            files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
            timeout=300,
        )

    if response.status_code == 200:
        result = response.json()
        print("\n✅ SUCCESS")
        print(json.dumps(result, indent=2))

        meta = result.get("processing_metadata", {})
        print("\n--- Summary ---")
        print(f"Total pages     : {meta.get('total_pages')}")
        print(f"Processing time : {meta.get('processing_time_seconds')}s")
        print(f"Pages by type   : {meta.get('pages_by_type')}")
        print(f"Agents invoked  : {meta.get('agents_invoked')}")
    else:
        print(f"\n❌ ERROR {response.status_code}")
        print(response.json())


if __name__ == "__main__":
    pdf_file = sys.argv[1] if len(sys.argv) > 1 else "final_image_protected.pdf"
    check_health()
    show_workflow()
    process_pdf(pdf_file)
