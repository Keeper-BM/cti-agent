"""Static program sent by the verifier to /usr/bin/python3. No file writes or shell inputs."""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys

MAX_INPUT = 512 * 1024
MAX_TOTAL = 512 * 1024 * 1024
PREFIXES = (
    "/usr/",
    "/lib/",
    "/lib64/",
    "/bin/",
    "/sbin/",
    "/etc/apache2/",
    "/etc/mysql/",
    "/var/www/html/",
)
FORMAT = (
    "${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\t"
    "${Architecture}\t${db:Status-Status}\t${db:Status-Eflag}\n"
)


def package_state():
    result = subprocess.run(
        ["/usr/bin/dpkg-query", "--show", "--showformat=" + FORMAT],
        capture_output=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
        check=True,
    )
    if len(result.stdout) > 2 * 1024 * 1024:
        raise ValueError("package output limit")
    return result.stdout.decode("utf-8")


def apache_runtime(expected_hash):
    path = "/usr/local/libexec/cti-apache-observer.py"
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
        return {"status": "UNAVAILABLE"}
    try:
        for entry in ("/usr", "/usr/local", "/usr/local/libexec", path):
            info = os.lstat(entry)
            if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
                return {"status": "UNAVAILABLE"}
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32768:
            return {"status": "UNAVAILABLE"}
        with open(path, "rb") as source:
            if hashlib.sha256(source.read(32769)).hexdigest() != expected_hash:
                return {"status": "UNAVAILABLE"}
        result = subprocess.run(
            [
                "/usr/bin/sudo",
                "-n",
                "/usr/bin/python3",
                "-I",
                path,
            ],
            capture_output=True,
            timeout=14,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if result.returncode or len(result.stdout) > 16384:
            return {"status": "UNAVAILABLE"}
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "UNAVAILABLE"}


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("input limit")
    request = json.loads(raw)
    paths = request["paths"]
    if not isinstance(paths, list) or len(paths) > 6000 or len(set(paths)) != len(paths):
        raise ValueError("file limit")
    before, result, total = package_state(), {}, 0
    for path in paths:
        if (
            not isinstance(path, str)
            or len(path) > 500
            or ".." in path.split("/")
            or any(ord(c) < 32 for c in path)
        ):
            raise ValueError("invalid path")
        if not path.startswith(PREFIXES):
            result[path] = {"status": "UNSUPPORTED"}
            continue
        try:
            initial = os.lstat(path)
            if stat.S_ISLNK(initial.st_mode):
                result[path] = {"status": "OK", "kind": "symlink", "target": os.readlink(path)}
                continue
            if not stat.S_ISREG(initial.st_mode) or initial.st_size > 128 * 1024 * 1024:
                result[path] = {"status": "UNSUPPORTED"}
                continue
            if not os.path.realpath(path).startswith(PREFIXES):
                result[path] = {"status": "UNSUPPORTED"}
                continue
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_ino != initial.st_ino
                    or opened.st_dev != initial.st_dev
                ):
                    result[path] = {"status": "UNREADABLE"}
                    continue
                digest = hashlib.sha256()
                read = 0
                while chunk := stream.read(65536):
                    read += len(chunk)
                    total += len(chunk)
                    if read > 128 * 1024 * 1024 or total > MAX_TOTAL:
                        raise ValueError("read limit")
                    digest.update(chunk)
                final = os.fstat(stream.fileno())
            last = os.lstat(path)
            fields = ("st_ino", "st_dev", "st_size", "st_mtime_ns", "st_ctime_ns")
            if any(
                getattr(initial, f) != getattr(final, f) or getattr(final, f) != getattr(last, f)
                for f in fields
            ):
                result[path] = {"status": "UNREADABLE"}
                continue
            result[path] = {
                "status": "OK",
                "kind": "file",
                "sha256": digest.hexdigest(),
                "mode": stat.S_IMODE(final.st_mode),
                "uid": final.st_uid,
                "gid": final.st_gid,
            }
        except FileNotFoundError:
            result[path] = {"status": "MISSING"}
        except OSError:
            result[path] = {"status": "UNREADABLE"}
    runtime = apache_runtime(request.get("observer_sha256"))
    print(
        json.dumps(
            {
                "before": before,
                "after": package_state(),
                "files": result,
                "apache_runtime": runtime,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
