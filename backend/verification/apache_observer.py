"""Optional root-owned observer. Fixed inputs, read-only files and one normal loopback HEAD.

Install as /usr/local/libexec/cti-apache-observer.py, root:root 0755.
Invoke only with: /usr/bin/python3 -I /usr/local/libexec/cti-apache-observer.py
No arguments, stdin, arbitrary URLs, shells, configuration parsing, or exploit requests.
"""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}
EXE = "/usr/sbin/apache2"
MODULE = "/usr/lib/apache2/modules/mod_http2.so"


def command(args, timeout=4):
    result = subprocess.run(args, capture_output=True, timeout=timeout, env=ENV, check=True)
    if len(result.stdout) > 65536:
        raise ValueError("output limit")
    return result.stdout.decode("ascii").strip()


def identity(path):
    with open(path, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 32 * 1024 * 1024:
            raise ValueError("file limit")
        digest = hashlib.sha256()
        size = 0
        while block := stream.read(65536):
            size += len(block)
            if size > 32 * 1024 * 1024:
                raise ValueError("read limit")
            digest.update(block)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, name) != getattr(after, name) for name in fields):
        raise ValueError("file changed")
    return digest.hexdigest(), tuple(getattr(after, name) for name in fields)


def service_pid():
    text = command(
        ["/usr/bin/systemctl", "show", "apache2.service", "--property=MainPID,ActiveState"]
    )
    values = dict(line.split("=", 1) for line in text.splitlines())
    pid = int(values["MainPID"])
    if values.get("ActiveState") != "active" or pid < 1:
        raise ValueError("inactive")
    return pid


def process_signature(pid):
    value = Path(f"/proc/{pid}/stat").read_text()
    # comm may contain spaces/parentheses; starttime is field 22, tail starts at field 3.
    return int(value.rsplit(")", 1)[1].split()[19])


def mapped_module(pid, expected):
    lines = Path(f"/proc/{pid}/maps").read_text().splitlines()
    for line in lines:
        parts = line.split(None, 5)
        if len(parts) == 6 and parts[5] == MODULE:
            major, minor = (int(v, 16) for v in parts[3].split(":"))
            if int(parts[4]) == expected[1] and os.makedev(major, minor) == expected[0]:
                return True
    return False


def owns_loopback_listener(pid):
    inodes = set()
    for entry in Path(f"/proc/{pid}/fd").iterdir():
        try:
            match = re.fullmatch(r"socket:\[(\d+)\]", os.readlink(entry))
            if match:
                inodes.add(match.group(1))
        except FileNotFoundError:
            continue
    # Fixed IPv4 loopback listener. A different host/port requires a separately reviewed collector.
    return any(
        len(parts) > 9 and parts[1] == "0100007F:0050" and parts[3] == "0A" and parts[9] in inodes
        for parts in (
            line.split() for line in Path(f"/proc/{pid}/net/tcp").read_text().splitlines()[1:]
        )
    )


def observe():
    if len(sys.argv) != 1 or os.geteuid() != 0:
        raise ValueError("fixed privileged invocation required")
    pid = service_pid()
    ticks = process_signature(pid)
    if os.readlink(f"/proc/{pid}/exe") != EXE:
        raise ValueError("different executable")
    executable, executable_identity = identity(f"/proc/{pid}/exe")
    if identity(EXE) != (executable, executable_identity):
        raise ValueError("running executable differs from disk")
    module, module_identity = identity(MODULE)
    if not mapped_module(pid, module_identity) or not owns_loopback_listener(pid):
        raise ValueError("module or listener not observed")
    response = command(
        [
            "/usr/bin/curl",
            "--silent",
            "--show-error",
            "--noproxy",
            "*",
            "--http2-prior-knowledge",
            "--head",
            "--connect-timeout",
            "2",
            "--max-time",
            "4",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_version} %{http_code}",
            "http://127.0.0.1:80/",
        ],
        timeout=5,
    )
    if response != "2 200":
        raise ValueError("HTTP/2 response not observed")
    if (
        service_pid() != pid
        or process_signature(pid) != ticks
        or identity(f"/proc/{pid}/exe") != (executable, executable_identity)
        or identity(MODULE) != (module, module_identity)
        or not mapped_module(pid, module_identity)
        or not owns_loopback_listener(pid)
    ):
        raise ValueError("process or files changed")
    return {
        "observer_version": "apache-runtime/1.0",
        "observed_at": datetime.now(UTC).isoformat(),
        "main_pid": pid,
        "process_start_ticks": ticks,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "service_active": True,
        "module_loaded": True,
        "listener_owned": True,
        "process_unchanged": True,
        "endpoint": "http://127.0.0.1:80/",
        "http_version": "2",
        "http_status": 200,
        "executable_sha256": executable,
        "module_sha256": module,
    }


if __name__ == "__main__":
    try:
        print(json.dumps({"status": "OK", "observation": observe()}))
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        print(json.dumps({"status": "UNAVAILABLE"}))
