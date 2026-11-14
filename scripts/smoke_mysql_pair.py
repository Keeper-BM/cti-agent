"""Collect and compare a disposable Ubuntu 24.04 MySQL VM through the HTTP worker.

VM installation/upgrades/snapshots are separate administrator operations. This
script only requests the existing fixed-command collector and analysis APIs.
"""

import argparse
import json
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from backend.api.schemas.collections import SSHProfileInput
from backend.core.config import get_settings
from scripts.smoke_ssh_http import collect, fetch, require, save_evidence, verify_snapshots

CVE = "CVE-2024-20994"
FIXED_VERSION = "8.0.37-0ubuntu0.24.04.1"


def package_state(packages):
    # IDs identify the new collection, not a change in the installed package state.
    return sorted(
        (
            {k: v for k, v in p.items() if k not in {"package_id", "origin_evidence_ref"}}
            for p in packages
        ),
        key=lambda p: (p["binary_name"], p["architecture"] or ""),
    )


def wait(client, path, timeout, *, job_only=False):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fetch(client, "GET", path)
        job = value if job_only else value["job"]
        if job["status"] not in {"QUEUED", "RUNNING"}:
            require(job["status"] == "SUCCEEDED", f"Worker failed: {job.get('error_code')}")
            return value
        time.sleep(0.5)
    raise RuntimeError("Worker operation exceeded the deadline")


def enqueue(client, path, payload):
    return fetch(
        client,
        "POST",
        path,
        202,
        headers={"Idempotency-Key": str(uuid4())},
        json=payload,
    )


def verify_findings(findings, expected):
    require(bool(findings), "No findings for the selected MySQL CVE")
    require(any(f["package_name"] == "mysql-server-8.0" for f in findings), "Server finding absent")
    for finding in findings:
        require(finding["cve_id"] == CVE, "Unexpected CVE")
        require(finding["fixed_version"] == FIXED_VERSION, "Official fixed version changed")
        require(finding["version_comparison"] == expected, "Unexpected version comparison")
        require(finding["origin_status"] == "UNKNOWN", "SSH must not certify package origin")
        require(finding["verdict"] == "NEEDS_REVIEW", "Version alone must not certify verdict")


def run(client, profile, *, baseline=None, restored=False, timeout=180):
    if baseline:
        require(baseline.get("schema") == "mysql-version-pair/1", "Invalid baseline schema")
        asset_id = str(UUID(baseline["asset_id"]))
        analysis_id = str(UUID(baseline["analysis"]["id"]))
        verify_snapshots(client, baseline["snapshots"])
    else:
        asset_id = fetch(
            client,
            "POST",
            "/api/v1/assets",
            201,
            json={
                "asset_name": "mysql-version-pair-" + uuid4().hex[:8],
                "exposure_source": "isolated MySQL CVE version comparison VM",
            },
        )["id"]
    base = "/api/v1/assets/" + asset_id
    saved = fetch(client, "PUT", base + "/ssh-profile", json=profile.model_dump())
    collection_path, collection = collect(client, base, saved["id"], timeout)
    require(collection["job"]["status"] == "SUCCEEDED", "SSH collection failed")
    inventory_path = base + "/inventories/" + collection["inventory_id"]
    inventory = fetch(client, "GET", inventory_path)
    require(
        inventory["os"]["id"] == "ubuntu" and inventory["os"]["version_id"] == "24.04",
        "Wrong Ubuntu release",
    )
    require(
        inventory["collection_method"] == "SSH" and not inventory["is_synthetic"],
        "Expected real SSH inventory",
    )
    require(inventory["collection_status"] == "COMPLETE", "Incomplete inventory")
    require(
        collection["evidence"]["verified_host_fingerprint"] == profile.host_fingerprint,
        "Host key differs",
    )
    mysql = [
        {k: v for k, v in p.items() if k != "package_id"}
        for p in inventory["packages"]
        if p["source_name"] == "mysql-8.0"
    ]
    require(any(p["binary_name"] == "mysql-server-8.0" for p in mysql), "MySQL server absent")
    require(
        all(p["origin_status"] == "UNKNOWN" and p["install_status"] == "installed" for p in mysql),
        "Unexpected MySQL origin or installation status",
    )
    service = next(s for s in collection["evidence"]["services"] if s["unit"] == "mysql.service")
    require(
        service["status"] == "OBSERVED" and service["active_state"] == "active",
        "MySQL is not active",
    )
    result = {
        "schema": "mysql-version-pair/1",
        "asset_id": asset_id,
        "cve_id": CVE,
        "fixed_version": FIXED_VERSION,
        "mysql_packages": mysql,
        "snapshots": {collection_path: collection, inventory_path: inventory},
    }
    if baseline:
        comparison = enqueue(
            client,
            "/api/v1/comparisons",
            {
                "baseline_analysis_id": analysis_id,
                "target_inventory_id": inventory["inventory_id"],
            },
        )
        comparison = wait(client, "/api/v1/comparisons/" + comparison["id"], timeout)
        rows = [r for r in comparison["result"]["rows"] if r["cve_id"] == CVE]
        verify_findings([f for r in rows for f in r["before"]], "BELOW_FIX")
        verify_findings(
            [f for r in rows for f in r["after"]], "BELOW_FIX" if restored else "MEETS_FIX"
        )
        if restored:
            require(
                package_state(mysql) == package_state(baseline["mysql_packages"]),
                "Restored package inventory differs",
            )
        require(
            sorted(comparison["result"]["source_snapshot_ids"])
            == sorted(s["id"] for s in baseline["analysis"]["sources"]),
            "Comparison feed was not frozen",
        )
        verify_snapshots(client, baseline["snapshots"])
        result["comparison"] = comparison
    else:
        source = enqueue(
            client, "/api/v1/sources/ubuntu/sync", {"release": "24.04", "package": "mysql-8.0"}
        )
        result["source_job"] = wait(client, "/api/v1/jobs/" + source["id"], timeout, job_only=True)
        analysis = enqueue(client, "/api/v1/analyses", {"inventory_id": inventory["inventory_id"]})
        analysis = wait(client, "/api/v1/analyses/" + analysis["id"], timeout)
        findings = fetch(
            client,
            "GET",
            "/api/v1/findings",
            params={"analysis_id": analysis["id"], "search": CVE, "limit": 100},
        )
        require(findings["total"] == len(findings["items"]), "Findings exceed one page")
        verify_findings(findings["items"], "BELOW_FIX")
        result.update(analysis=analysis, findings=findings)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["baseline", "upgraded", "restored"])
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if args.evidence.exists() or args.evidence.is_symlink() or not 1 <= args.timeout <= 300:
        parser.error("Use a new evidence path and a timeout between 1 and 300 seconds")
    if (args.action != "baseline") != bool(args.baseline):
        parser.error("Only upgraded/restored actions require --baseline")
    profile = SSHProfileInput.model_validate_json(args.profile.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    token = get_settings().dev_api_token.get_secret_value()
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=15
    ) as client:
        evidence = run(
            client,
            profile,
            baseline=baseline,
            restored=args.action == "restored",
            timeout=args.timeout,
        )
    save_evidence(args.evidence, evidence)
    print(
        f"PASS: {args.action} real SSH MySQL collection and {CVE} comparison; "
        "origin remains UNKNOWN"
    )


if __name__ == "__main__":
    main()
