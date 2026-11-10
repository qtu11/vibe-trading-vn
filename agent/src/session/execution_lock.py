"""OS-held execution claims, released automatically when a process exits."""

import os
from pathlib import Path
from typing import BinaryIO


def acquire_execution_lock(path: Path) -> BinaryIO:
    """Return a held nonblocking claim; closing the handle releases it."""
    handle = path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, OSError):
        handle.close()
        raise
    return handle
