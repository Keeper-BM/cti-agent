"""Prepare and supervise the local API, optional Worker, and Vite in one terminal."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def runtime(name: str, root: Path = ROOT) -> str:
    located = shutil.which(name)
    if name == "uv" and not located:
        bundled = root / ".tools" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
        if bundled.is_file():
            located = str(bundled)
    if not located:
        raise RuntimeError(f"Missing runtime: {name}. Install uv and Node.js 24 (including npm).")
    return located


def check_port(port: int) -> None:
    if not 1 <= port <= 65535:
        raise RuntimeError("Development ports must be between 1 and 65535.")
    with socket.socket() as instance:
        try:
            instance.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(
                f"Port {port} is busy; stop its process or choose another port."
            ) from None


@contextmanager
def run_lock(root: Path = ROOT):
    """The OS releases this lock even after an interrupted launcher."""
    (root / ".data").mkdir(exist_ok=True)
    with (root / ".data" / "dev.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                "A development launcher is already running for this checkout."
            ) from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class Processes:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.active: list[tuple[str, subprocess.Popen]] = []

    def start(self, name: str, command: list[str], env: dict[str, str] | None = None):
        print(f"Starting {name}…", flush=True)
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        instance = subprocess.Popen(command, cwd=self.root, env=env, **options)
        self.active.append((name, instance))
        return instance

    def run(self, name: str, command: list[str]) -> None:
        instance = self.start(name, command)
        code = instance.wait()
        self.active.remove((name, instance))
        if code:
            raise RuntimeError(f"{name} failed (exit {code}). Check the output above.")

    def check(self) -> None:
        for name, instance in self.active:
            if instance.poll() is not None:
                raise RuntimeError(f"{name} stopped (exit {instance.returncode}).")

    def stop(self) -> None:
        if not self.active:
            return
        print("Stopping development processes…", flush=True)
        for _, instance in reversed(self.active):
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(instance.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    os.killpg(instance.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 8
        for _, instance in reversed(self.active):
            try:
                instance.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            if os.name != "nt":
                try:
                    os.killpg(instance.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            instance.wait()
        self.active.clear()
        print("Development processes stopped.", flush=True)


def wait_for(url: str, processes: Processes, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        processes.check()
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Development server did not become ready. Check the process output above.")


def develop(args: argparse.Namespace) -> None:
    uv, node, npm = runtime("uv"), runtime("node"), runtime("npm")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if version.split(".")[0] != "v24":
        raise RuntimeError("Node.js 24 is required by frontend/package.json.")
    if args.api_port == args.web_port:
        raise RuntimeError("API and web ports must be different.")
    if not args.prepare_only:
        check_port(args.api_port)
        check_port(args.web_port)
    processes = Processes()
    with run_lock():
        try:
            processes.run("configuration", [sys.executable, "scripts/init_env.py"])
            processes.run("Python dependencies", [uv, "sync", "--frozen"])
            processes.run("effective settings", [uv, "run", "python", "scripts/check_env.py"])
            lock = (ROOT / "frontend" / "package-lock.json").read_bytes()
            fingerprint = hashlib.sha256(lock).hexdigest()
            marker = ROOT / "frontend" / "node_modules" / ".blendedmeshup-lock"
            if (
                not marker.is_file()
                or marker.read_text() != fingerprint
                or not (marker.parent / "vite" / "bin" / "vite.js").is_file()
            ):
                processes.run("JavaScript dependencies", [npm, "--prefix", "frontend", "ci"])
                marker.write_text(fingerprint)
            processes.run("database migrations", [uv, "run", "alembic", "upgrade", "head"])
            if args.prepare_only:
                print("Development environment prepared; no servers started.", flush=True)
                return
            check_port(args.api_port)
            check_port(args.web_port)
            processes.start(
                "API",
                [
                    uv,
                    "run",
                    "uvicorn",
                    "backend.api.main:app",
                    "--reload",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.api_port),
                ],
            )
            api_url = f"http://127.0.0.1:{args.api_port}"
            wait_for(f"{api_url}/api/v1/readiness", processes)
            if not args.no_worker:
                processes.start("Worker", [uv, "run", "python", "-m", "backend.worker"])
            processes.start(
                "web",
                [npm, "--prefix", "frontend", "run", "dev", "--", "--port", str(args.web_port)],
                env={**os.environ, "DEV_API_PROXY": api_url},
            )
            web_url = f"http://127.0.0.1:{args.web_port}"
            wait_for(web_url, processes)
            print(f"Ready: {web_url}", flush=True)
            print(f"Synthetic example: {web_url}/#/example", flush=True)
            print(
                "Connect with DEV_API_TOKEN from .env. Press Ctrl+C to stop all processes.",
                flush=True,
            )
            if args.no_worker:
                print(
                    "Worker omitted; system-check jobs will wait until a Worker is started.",
                    flush=True,
                )
            while True:
                processes.check()
                time.sleep(0.3)
        finally:
            processes.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-worker", action="store_true", help="Run API and web only")
    parser.add_argument(
        "--prepare-only", action="store_true", help="Prepare without starting servers"
    )
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=5173)
    args = parser.parse_args()

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        develop(args)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Development startup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
