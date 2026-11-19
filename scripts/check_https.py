"""Check the certificate served to a client and the application's public readiness path."""

import argparse
import json
import ssl
import time
from datetime import UTC, datetime
from http.client import HTTPException, HTTPSConnection
from urllib.parse import urlsplit


def check(origin, ca_file, min_days):
    url = urlsplit(origin)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
        or url.port == 0
    ):
        raise ValueError("Expected an HTTPS origin")
    if min_days < 0:
        raise ValueError("Expected a nonnegative certificate lifetime")
    context = ssl.create_default_context(cafile=ca_file)
    connection = HTTPSConnection(url.hostname, url.port, timeout=10, context=context)
    try:
        connection.connect()
        expiry = ssl.cert_time_to_seconds(connection.sock.getpeercert()["notAfter"])
        if expiry - time.time() < min_days * 86400:
            raise ValueError("Certificate expires before the requested threshold")
        connection.request("GET", "/api/v1/readiness", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"Readiness returned HTTP {response.status}")
        body = response.read(4097)
        if len(body) > 4096:
            raise ValueError("Readiness response exceeds size limit")
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError) as exc:
            raise ValueError("Invalid readiness response") from exc
        if not isinstance(payload, dict) or payload.get("status") != "ready":
            raise ValueError("API did not report ready")
        return datetime.fromtimestamp(expiry, UTC).isoformat()
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="HTTPS origin, including a port when needed")
    parser.add_argument("--ca-file", help="PEM CA bundle (default: system trust)")
    parser.add_argument("--min-days", type=int, default=14, help="Minimum remaining days (14)")
    args = parser.parse_args()
    try:
        expiry = check(args.origin, args.ca_file, args.min_days)
    except ssl.SSLCertVerificationError:
        parser.exit(1, "TLS certificate verification failed\n")
    except (OSError, HTTPException):
        parser.exit(1, "HTTPS connection or response failed; check CA file and endpoint\n")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps({"status": "ready", "certificate_expires_at": expiry}))


if __name__ == "__main__":
    main()
