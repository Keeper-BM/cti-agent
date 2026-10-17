"""Check a running stack through HTTP; adds one infrastructure-check job."""

import os
import time
from uuid import uuid4

import httpx

from backend.core.config import get_settings

base_url = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8080")
headers = {"Authorization": f"Bearer {get_settings().dev_api_token.get_secret_value()}"}
with httpx.Client(base_url=base_url, timeout=10, headers=headers) as client:
    client.get("/api/v1/readiness").raise_for_status()
    client.get("/api/v1/assets").raise_for_status()
    example = client.get("/api/v1/examples/assessment")
    example.raise_for_status()
    if example.json().get("is_synthetic") is not True:
        raise SystemExit("Development example must be explicitly synthetic")
    response = client.post("/api/v1/jobs/system-checks", headers={"Idempotency-Key": str(uuid4())})
    response.raise_for_status()
    job_id = response.json()["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] == "SUCCEEDED":
            print("PASS: HTTP → API → database → worker → HTTP")
            break
        if job["status"] == "FAILED":
            raise SystemExit(f"Worker failed: {job['error_code']}")
        time.sleep(0.5)
    else:
        raise SystemExit("Worker did not complete within 30 seconds")
