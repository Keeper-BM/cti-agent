"""Exercise a running HTTP stack and its separate SSH worker against an explicit test VM.

Creates a test asset, SSH profiles and collection history. The VM receives only fixed
read commands. Use a disposable stack; credentials come from DEV_API_TOKEN/.env.
"""

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

import httpx

from backend.api.schemas.collections import SSHProfileInput
from backend.collectors.ssh_protocol import COMMANDS, CommandResult
from backend.core.config import get_settings


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fetch(client, method, path, expected=200, **kwargs):
    response = client.request(method, path, **kwargs)
    require(response.status_code == expected, f"{method} {path}: HTTP {response.status_code}")
    return response.json()


def collect(client, base, profile_id, timeout):
    key = str(uuid4())
    kwargs = {"headers": {"Idempotency-Key": key}, "json": {"profile_id": profile_id}}
    run = fetch(client, "POST", base + "/collections", 202, **kwargs)
    repeated = fetch(client, "POST", base + "/collections", 202, **kwargs)
    require(run["id"] == repeated["id"], "Idempotent request created a second collection")
    deadline = time.monotonic() + timeout
    path = base + "/collections/" + run["id"]
    while time.monotonic() < deadline:
        detail = fetch(client, "GET", path)
        if detail["job"]["status"] not in {"QUEUED", "RUNNING"}:
            return path, detail
        time.sleep(0.5)
    raise RuntimeError("Separate worker did not finish the collection before the deadline")


def verify_snapshots(client, snapshots):
    require(isinstance(snapshots, dict) and snapshots, "Evidence contains no snapshots")
    for path, expected in snapshots.items():
        # Evidence files must never turn an authenticated request into an external URL.
        require(
            re.fullmatch(
                r"/api/v1/assets/[0-9a-f-]{36}/(?:collections|inventories)/[0-9a-f-]{36}", path
            ),
            "Invalid snapshot API path",
        )
        require(fetch(client, "GET", path) == expected, f"Saved response changed: {path}")


def run_collection(client, profile, *, partial, timeout):
    fetch(client, "GET", "/api/v1/readiness")
    settings = fetch(client, "GET", "/api/v1/collections/settings")
    host = f"[{profile.host}]" if ":" in profile.host else profile.host
    require(f"{host}:{profile.port}" in settings["allowed_targets"], "VM target is not allowed")
    require(profile.key_alias in settings["key_aliases"], "VM key is not available to the API")
    asset = fetch(
        client,
        "POST",
        "/api/v1/assets",
        201,
        json={
            "asset_name": "compose-ssh-" + uuid4().hex[:12],
            "exposure_source": "isolated HTTP/SSH acceptance test",
        },
    )
    base = "/api/v1/assets/" + asset["id"]
    good_profile = fetch(client, "PUT", base + "/ssh-profile", json=profile.model_dump())
    good_path, good = collect(client, base, good_profile["id"], timeout)
    require(good["job"]["status"] == ("PARTIAL" if partial else "SUCCEEDED"), "Unexpected status")
    require(good["inventory_id"], "Successful package collection did not save an inventory")
    inventory_path = base + "/inventories/" + good["inventory_id"]
    inventory = fetch(client, "GET", inventory_path)
    require(inventory["collection_method"] == "SSH", "Inventory did not originate from SSH")
    require(inventory["is_synthetic"] is False, "Real VM inventory was marked synthetic")
    require(inventory["collection_status"] == "COMPLETE", "Package inventory is incomplete")
    require(inventory["coverage"]["package_list_complete"], "Package coverage is incomplete")
    require(inventory["os"]["id"] == "ubuntu", "Expected an Ubuntu test VM")
    for package in ("apache2-bin", "mysql-server-8.0"):
        require(
            any(
                p["binary_name"] == package and p["install_status"] == "installed"
                for p in inventory["packages"]
            ),
            f"Required lab package is absent: {package}",
        )
    evidence = good["evidence"]
    require(evidence["verified_host_fingerprint"] == profile.host_fingerprint, "Host key differs")
    commands = [CommandResult.model_validate(value) for value in evidence["commands"]]
    require([c.name for c in commands] == list(COMMANDS), "Unexpected collector command set")
    wire = "\n".join(command.model_dump_json() for command in commands)
    require(hashlib.sha256(wire.encode()).hexdigest() == evidence["output_sha256"], "Hash differs")
    services = {s["unit"]: s for s in evidence["services"]}
    require(set(services) == {"apache2.service", "mysql.service"}, "Missing service observations")
    if partial:
        require(
            any(s["status"] == "UNKNOWN" for s in services.values()), "Expected service failure"
        )
    else:
        require(all(c.exit_code == 0 for c in commands), "Collector command failed")
        require(
            all(
                s["status"] == "OBSERVED" and s["active_state"] == "active"
                for s in services.values()
            ),
            "Both lab services must be active",
        )
    bad_fingerprint = (
        "SHA256:" + ("B" if profile.host_fingerprint == "SHA256:" + "A" * 43 else "A") * 43
    )
    try:
        bad_profile = fetch(
            client,
            "PUT",
            base + "/ssh-profile",
            json={**profile.model_dump(), "host_fingerprint": bad_fingerprint},
        )
        failed_path, failed = collect(client, base, bad_profile["id"], timeout)
        require(failed["job"]["status"] == "FAILED", "Wrong host key did not fail")
        require(failed["job"]["error_code"] == "SSH_HOST_KEY_MISMATCH", "Unexpected SSH failure")
        require(failed["inventory_id"] is None, "Failed SSH created an inventory")
    finally:
        # Keep the asset usable after the negative test; historical profiles are immutable.
        fetch(client, "PUT", base + "/ssh-profile", json=profile.model_dump())
    require(fetch(client, "GET", base + "/inventories")["total"] == 1, "Extra inventory created")
    snapshots = {good_path: good, inventory_path: inventory, failed_path: failed}
    verify_snapshots(client, snapshots)
    return {
        "schema": "ssh-http-acceptance/1",
        "asset_id": asset["id"],
        "expected_status": "PARTIAL" if partial else "SUCCEEDED",
        "package_count": len(inventory["packages"]),
        "snapshots": snapshots,
    }


def save_evidence(path, evidence):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["collect", "verify"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expect-partial", action="store_true")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if args.action == "collect" and (args.profile is None or args.evidence.exists()):
        parser.error("collect requires --profile and a new --evidence path")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds")
    token = get_settings().dev_api_token.get_secret_value()
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=10
    ) as client:
        if args.action == "verify":
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            require(evidence.get("schema") == "ssh-http-acceptance/1", "Unknown evidence schema")
            verify_snapshots(client, evidence["snapshots"])
            print("PASS: saved collection, failed job and inventory responses are unchanged")
        else:
            profile = SSHProfileInput.model_validate_json(args.profile.read_text(encoding="utf-8"))
            evidence = run_collection(
                client, profile, partial=args.expect_partial, timeout=args.timeout
            )
            save_evidence(args.evidence, evidence)
            print(f"PASS: HTTP → separate Worker → SSH VM; {evidence['package_count']} packages")
            print("PASS: pinned host-key rejection, idempotency and previous snapshot preservation")


if __name__ == "__main__":
    main()
