"""Replace the API in an explicitly selected disposable Compose stack; check DNS recovery.

This interrupts that stack's API. Never point it at a shared or production project.
It reserves the previous IP so recreation cannot accidentally hide stale Nginx DNS.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx


def run(args, *, capture=False):
    return subprocess.run(
        args, check=True, text=True, stdout=subprocess.PIPE if capture else None, timeout=120
    ).stdout


def inspect_container(container):
    return json.loads(run(["docker", "inspect", container], capture=True))[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    compose = ["docker", "compose", "-p", args.project_name, "--env-file", str(args.env_file)]
    api = inspect_container(run([*compose, "ps", "-q", "api"], capture=True).strip())
    web = inspect_container(run([*compose, "ps", "-q", "web"], capture=True).strip())
    networks = api["NetworkSettings"]["Networks"]
    if len(networks) != 1:
        raise RuntimeError("This smoke test requires the single-network reference Compose stack")
    network, address = next(iter(networks.items()))
    old_ip = address["IPAddress"]
    if not old_ip:
        raise RuntimeError("A running IPv4 API container is required")
    holder = f"{args.project_name}-ip-holder-{uuid4().hex[:8]}"
    httpx.get(args.base_url.rstrip("/") + "/api/v1/readiness", timeout=5).raise_for_status()
    api_ready = False
    holder_created = False
    try:
        run([*compose, "stop", "api"])
        run([*compose, "rm", "-f", "api"])
        # Reuse the existing image, with no application credentials or mounted volumes.
        holder_created = True
        run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                holder,
                "--network",
                network,
                "--ip",
                old_ip,
                api["Image"],
                "sleep",
                "120",
            ],
            capture=True,
        )
        run([*compose, "up", "-d", "--no-deps", "--wait", "--wait-timeout", "60", "api"])
        api_ready = True
        replacement = inspect_container(run([*compose, "ps", "-q", "api"], capture=True).strip())
        if replacement["NetworkSettings"]["Networks"][network]["IPAddress"] == old_ip:
            raise RuntimeError("API address did not change; the DNS test is inconclusive")
        with httpx.Client(base_url=args.base_url, timeout=3) as client:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    response = client.get("/api/v1/readiness")
                    if response.status_code == 200 and response.json() == {"status": "ready"}:
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError("Web proxy did not recover after the API address changed")
        current_web = inspect_container(run([*compose, "ps", "-q", "web"], capture=True).strip())
        if (
            web["Id"] != current_web["Id"]
            or web["State"]["StartedAt"] != current_web["State"]["StartedAt"]
        ):
            raise RuntimeError("Web restarted; this does not prove live DNS recovery")
        print("PASS: API IP changed; web recovered without restarting Nginx")
    finally:
        if holder_created:
            subprocess.run(
                ["docker", "rm", "-f", holder], check=False, capture_output=True, timeout=30
            )
        if not api_ready:
            run([*compose, "up", "-d", "--no-deps", "--wait", "--wait-timeout", "60", "api"])


if __name__ == "__main__":
    main()
