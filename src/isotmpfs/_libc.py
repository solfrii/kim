"""ctypes bindings for the mount(2)/umount2(2) syscalls.

Python's stdlib exposes os.unshare()/os.CLONE_NEWNS/os.CLONE_NEWUSER but has
no wrapper for mount(2) or umount2(2), so those two are bound here directly
against libc. The flag constants below are part of the stable Linux UAPI
(linux/mount.h) and have been unchanged since their introduction; they do
not depend on which -devel/headers packages happen to be installed.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os

_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)

_libc.mount.argtypes = [
    ctypes.c_char_p,  # source
    ctypes.c_char_p,  # target
    ctypes.c_char_p,  # filesystemtype
    ctypes.c_ulong,  # mountflags
    ctypes.c_void_p,  # data
]
_libc.mount.restype = ctypes.c_int

_libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
_libc.umount2.restype = ctypes.c_int

# mount(2) mountflags -- linux/mount.h, ABI-stable since 2.6
MS_RDONLY = 1 << 0
MS_NOSUID = 1 << 1
MS_NODEV = 1 << 2
MS_NOEXEC = 1 << 3
MS_REMOUNT = 1 << 5
MS_REC = 1 << 14
MS_PRIVATE = 1 << 18
MS_SLAVE = 1 << 19
MS_SHARED = 1 << 20

# umount2(2) flags
MNT_DETACH = 2


class MountError(OSError):
    """Raised when a raw mount(2)/umount2(2) call fails."""


def _check(ret: int, call: str, *args: object) -> None:
    if ret != 0:
        errno_val = ctypes.get_errno()
        raise MountError(errno_val, f"{call}{args!r} failed: {os.strerror(errno_val)}")


def mount(
    source: str | None,
    target: str,
    fstype: str | None,
    flags: int,
    data: str | None = None,
) -> None:
    ret = _libc.mount(
        source.encode() if source is not None else None,
        target.encode(),
        fstype.encode() if fstype is not None else None,
        flags,
        data.encode() if data is not None else None,
    )
    _check(ret, "mount", source, target, fstype, flags, data)


def umount2(target: str, flags: int = MNT_DETACH) -> None:
    _check(_libc.umount2(target.encode(), flags), "umount2", target, flags)
