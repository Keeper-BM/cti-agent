"""Disposable HTTPS Compose stack; never uses an operator's database or certificates."""

import base64
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import ssl
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from scripts.operations_backup import write_new
from scripts.postgres_backup import ComposePostgres
from tests.fixtures.compose_accounts import command, require


class HTTPSStack:
    def __init__(self, directory):
        self.directory = directory
        self.project = "cti-https-" + uuid4().hex[:12]
        self.password = secrets.token_urlsafe(32)
        self.dev_token = secrets.token_urlsafe(32)
        self.tls = directory / "tls"
        self.tls.mkdir(mode=0o750)
        self.tls.chmod(0o750)
        self.ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CTI disposable HTTPS test CA")])
        self.ca = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self.ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(False, False, False, False, False, True, True, False, False),
                critical=True,
            )
            .sign(self.ca_key, hashes.SHA256())
        )
        write_new(directory / "ca.pem", self.ca.public_bytes(serialization.Encoding.PEM))
        self.issue_certificate()
        (directory / "ssh-empty").mkdir(mode=0o700)
        self.env_file = directory / "stack.env"
        # Intentionally contradictory auth values: the HTTPS overlay must override them.
        write_new(
            self.env_file,
            (
                "POSTGRES_USER=threat_intel\nPOSTGRES_DB=threat_intel\n"
                f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\nDEV_API_TOKEN={self.dev_token}\n"
                f"SSH_KEY_DIRECTORY={directory / 'ssh-empty'}\n"
                f"TLS_DIRECTORY={self.tls}\nTLS_READ_GID={os.getgid()}\n"
                "HTTPS_PORT=0\nHTTPS_BIND_ADDRESS=127.0.0.1\nAUTH_MODE=token\n"
                "SESSION_COOKIE_SECURE=false\nLLM_BASE_URL=\nLLM_API_KEY=\nLLM_MODEL=\n"
            ).encode(),
        )
        self.compose = [
            "docker",
            "compose",
            "-p",
            self.project,
            "--env-file",
            str(self.env_file),
            "-f",
            "compose.yaml",
            "-f",
            "compose.https.yaml",
        ]

    def issue_certificate(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
            .issuer_name(self.ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(self.ca_key, hashes.SHA256())
        )
        for name, content in {
            "fullchain.pem": cert.public_bytes(serialization.Encoding.PEM),
            "privkey.pem": key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        }.items():
            temporary = self.tls / (name + ".new")
            write_new(temporary, content)
            temporary.chmod(0o640)
            temporary.replace(self.tls / name)
        self.spki = base64.b64encode(
            hashlib.sha256(
                key.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            ).digest()
        ).decode()
        self.fingerprint = cert.fingerprint(hashes.SHA256()).hex()

    def start(self):
        model = json.loads(command([*self.compose, "config", "--format", "json"]))
        for name in ("api", "worker"):
            env = model["services"][name]["environment"]
            require(
                env["AUTH_MODE"] == "accounts" and env["SESSION_COOKIE_SECURE"] == "true",
                "HTTPS overlay did not force secure account mode",
            )
        ports = model["services"]["web"]["ports"]
        require(
            len(ports) == 1 and ports[0]["target"] == 8443 and ports[0]["host_ip"] == "127.0.0.1",
            "Plain HTTP port was retained",
        )
        require(
            all(not model["services"][s].get("ports") for s in ("api", "worker", "db")),
            "Backend service was published",
        )
        command(
            [*self.compose, "up", "--build", "-d", "--wait", "--wait-timeout", "180"], timeout=480
        )
        address = command([*self.compose, "port", "web", "8443"]).decode().strip()
        require(address.startswith("127.0.0.1:"), "Expected loopback HTTPS publication")
        self.port = int(address.rsplit(":", 1)[1])
        self.url = "https://" + address
        self.context = ssl.create_default_context(cafile=str(self.directory / "ca.pem"))
        self.manage_account("https-admin", self.password, "--display-name", "HTTPS administrator")
        self.db = ComposePostgres(self.project, self.env_file)
        self.db.compose = self.compose

    def manage_account(self, username, password, *options):
        command(
            [
                *self.compose,
                "exec",
                "-T",
                "api",
                "python",
                "-m",
                "scripts.manage_users",
                username,
                "--password-file",
                "/dev/stdin",
                *options,
            ],
            input=(password + "\n").encode(),
        )

    def client(self):
        return httpx.Client(base_url=self.url, verify=self.context, timeout=20, trust_env=False)

    def close(self):
        command([*self.compose, "down", "--volumes", "--remove-orphans"], timeout=120)
        shutil.rmtree(self.directory)
