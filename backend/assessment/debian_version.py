"""Compare Debian package versions according to Debian Policy section 5.6.12."""

import re

_UPSTREAM = re.compile(r"^[0-9][A-Za-z0-9.+:~\-]*$")
_REVISION = re.compile(r"^[A-Za-z0-9+.~]+$")


def _parts(version: str) -> tuple[int, str, str]:
    if not version or len(version) > 200 or not version.isascii():
        raise ValueError("Invalid Debian package version")
    epoch = 0
    rest = version
    if ":" in version:
        prefix, rest = version.split(":", 1)
        if not prefix.isdigit():
            raise ValueError("Invalid Debian version epoch")
        epoch = int(prefix)
    if "-" in rest:
        upstream, revision = rest.rsplit("-", 1)
        if not _REVISION.fullmatch(revision):
            raise ValueError("Invalid Debian revision")
    else:
        upstream, revision = rest, "0"
    if not _UPSTREAM.fullmatch(upstream):
        raise ValueError("Invalid Debian upstream version")
    return epoch, upstream, revision


def _order(char: str) -> int:
    if char == "~":
        return -1
    if not char or char.isdigit():
        return 0
    return ord(char) if char.isalpha() else ord(char) + 256


def _compare_part(left: str, right: str) -> int:
    i = j = 0
    while i < len(left) or j < len(right):
        while (i < len(left) and not left[i].isdigit()) or (
            j < len(right) and not right[j].isdigit()
        ):
            a = _order(left[i] if i < len(left) else "")
            b = _order(right[j] if j < len(right) else "")
            if a != b:
                return -1 if a < b else 1
            if i < len(left) and not left[i].isdigit():
                i += 1
            if j < len(right) and not right[j].isdigit():
                j += 1

        while i < len(left) and left[i] == "0":
            i += 1
        while j < len(right) and right[j] == "0":
            j += 1
        left_start, right_start = i, j
        while i < len(left) and left[i].isdigit():
            i += 1
        while j < len(right) and right[j].isdigit():
            j += 1
        a, b = left[left_start:i], right[right_start:j]
        if len(a) != len(b):
            return -1 if len(a) < len(b) else 1
        if a != b:
            return -1 if a < b else 1
    return 0


def compare_versions(left: str, right: str) -> int:
    """Return -1, 0 or 1. Invalid or incomplete versions raise ValueError."""
    left_epoch, left_upstream, left_revision = _parts(left)
    right_epoch, right_upstream, right_revision = _parts(right)
    if left_epoch != right_epoch:
        return -1 if left_epoch < right_epoch else 1
    return _compare_part(left_upstream, right_upstream) or _compare_part(
        left_revision, right_revision
    )
