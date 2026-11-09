"""Create a symlink, or skip the test when the host forbids it.

Windows only grants the symlink privilege to administrators and to
developers who enabled Developer Mode, so a checkout that otherwise
passes everywhere raises ``WinError 1314`` (``OSError``) from
``Path.symlink_to``. POSIX hosts that lack the filesystem support
raise ``ENOSYS``/``ENOTSUP``/``EOPNOTSUPP``.

Both cases mean "this host cannot express the filesystem shape the
test needs", not "the product misbehaves", so the test is skipped
instead of failed. Any other OSError is a real failure and is
re-raised.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

# Windows: ERROR_PRIVILEGE_NOT_HELD.
_WINDOWS_PRIVILEGE_ERROR = 1314
# POSIX: the filesystem or kernel does not implement symlinks.
_UNSUPPORTED_ERRNOS = {
    errno.ENOSYS,
    errno.ENOTSUP,
    errno.EOPNOTSUPP,
}


def symlink_or_skip(
    link: Path,
    target: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    """Create ``link`` -> ``target``, skipping the test if that is impossible.

    Args:
        link: The path to create as a symlink.
        target: The path the symlink points at.
        target_is_directory: Whether the target is a directory, which
            Windows requires to be declared explicitly.
    """
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if getattr(exc, "winerror", None) == _WINDOWS_PRIVILEGE_ERROR or exc.errno in _UNSUPPORTED_ERRNOS:
            pytest.skip(f"Host cannot create the symlink this test needs: {exc}")
        raise


def symlinks_supported() -> bool:
    """Whether this host can create a symlink at all.

    Used to skip a whole parametrization instead of each case.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="vt-symlink-probe-") as folder:
        probe = Path(folder)
        try:
            (probe / "link").symlink_to(probe / "target")
        except OSError as exc:
            return not (
                getattr(exc, "winerror", None) == _WINDOWS_PRIVILEGE_ERROR
                or exc.errno in _UNSUPPORTED_ERRNOS
            )
        return True


__all__ = ["symlink_or_skip", "symlinks_supported", "os"]
