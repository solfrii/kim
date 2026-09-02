"""Pluggable mount-namespace backend interface.

Only a ctypes/os.unshare-based backend is implemented for now. The seam
here (the MountBackend protocol + the `backend=` constructor argument on
IsolatedTmpfs) exists so a subprocess-CLI-wrapping backend and a hybrid
backend can be added later without changing IsolatedTmpfs itself.
"""

from __future__ import annotations

import os
from typing import Protocol

from isotmpfs import _libc

# os.unshare()/os.CLONE_NEWUSER/os.CLONE_NEWNS only exist on Python 3.12+;
# fall back to the ctypes binding in _libc on older interpreters.
_unshare = getattr(os, "unshare", _libc.unshare)
_CLONE_NEWUSER = getattr(os, "CLONE_NEWUSER", _libc.CLONE_NEWUSER)
_CLONE_NEWNS = getattr(os, "CLONE_NEWNS", _libc.CLONE_NEWNS)


class MountBackend(Protocol):
    def enter_isolated_namespace(self) -> None: ...
    def make_private(self, path: str) -> None: ...
    def mount_tmpfs(self, target: str, *, size: str | None = None) -> None: ...
    def defensive_unmount(self, target: str) -> None: ...


class CtypesBackend:
    """Enters an unprivileged user+mount namespace and mounts tmpfs via
    direct ctypes calls into libc. Must run inside a freshly forked child
    process -- see isolated_tmpfs.IsolatedTmpfs for why.
    """

    def enter_isolated_namespace(self) -> None:
        # Must read our real uid/gid *before* unshare(): once inside the
        # new user namespace and before uid_map/gid_map are written,
        # os.getuid()/os.getgid() report the unmapped overflow id (65534,
        # "nobody"), not the real caller id -- confirmed empirically.
        uid = os.getuid()
        gid = os.getgid()
        _unshare(_CLONE_NEWUSER | _CLONE_NEWNS)
        self._write_id_maps(uid, gid)

    def _write_id_maps(self, uid: int, gid: int) -> None:
        # setgroups must be disabled before gid_map can be written by an
        # unprivileged process (user_namespaces(7)); uid_map has no such
        # ordering constraint, so setgroups -> uid_map -> gid_map is safe.
        with open("/proc/self/setgroups", "w") as f:
            f.write("deny")
        with open("/proc/self/uid_map", "w") as f:
            f.write(f"0 {uid} 1")
        with open("/proc/self/gid_map", "w") as f:
            f.write(f"0 {gid} 1")

    def make_private(self, path: str) -> None:
        # Recursively mark every mount private so nothing mounted inside
        # this namespace propagates out, and nothing from the parent
        # propagates in.
        _libc.mount(None, path, None, _libc.MS_PRIVATE | _libc.MS_REC)

    def mount_tmpfs(self, target: str, *, size: str | None = None) -> None:
        os.makedirs(target, exist_ok=True)
        data = f"size={size}" if size else None
        _libc.mount("tmpfs", target, "tmpfs", _libc.MS_NOSUID | _libc.MS_NODEV, data)

    def defensive_unmount(self, target: str) -> None:
        _libc.umount2(target, _libc.MNT_DETACH)
