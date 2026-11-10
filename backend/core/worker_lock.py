"""Process-lifetime lock for the single SQLite worker on Windows and POSIX."""

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def sqlite_worker_lock(database):
    if not database or database == ":memory:":
        yield
        return
    path = Path(database).resolve().with_suffix(".worker.lock")
    with path.open("a+b") as stream:
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
            raise RuntimeError("A worker is already running for this SQLite database.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
