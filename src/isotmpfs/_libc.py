"""ctypes bindings for the unshare(2)/mount(2)/umount2(2) syscalls.

mount(2) and umount2(2) have no stdlib wrapper at all, so they're bound
here directly against libc. unshare(2) does have a stdlib wrapper
(os.unshare(), added in Python 3.12) -- backend.py prefers that when it's
available and falls back to the ctypes binding here on older Pythons. The
flag constants below are part of the stable Linux UAPI (linux/sched.h,
linux/mount.h) and have been unchanged since their introduction; they do
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

_libc.unshare.argtypes = [ctypes.c_int]
_libc.unshare.restype = ctypes.c_int

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

# clone(2)/unshare(2) namespace flags -- linux/sched.h, ABI-stable UAPI.
# Match os.CLONE_NEWUSER/os.CLONE_NEWNS on Pythons that have them (3.12+).
CLONE_NEWNS = 0x00020000
CLONE_NEWUSER = 0x10000000


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


def unshare(flags: int) -> None:
    _check(_libc.unshare(flags), "unshare", flags)
