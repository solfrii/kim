"""Per-process isolated tmpfs.

IsolatedTmpfs.run(target, *args, **kwargs) forks a child process, gives it
its own private mount+user namespace with a tmpfs mounted at a path of your
choosing, calls target(mount_path, *args, **kwargs) inside that child, and
reports the result back to the parent over a pipe.

This always forks rather than mutating the calling process's own
namespaces. unshare(CLONE_NEWUSER|CLONE_NEWNS) is one-directional -- a
process cannot cleanly return to its original mount namespace afterwards --
so a context-manager-in-the-current-process API would permanently and
irreversibly change whatever process happened to open it (including, if
used naively, pytest's own process). Forking makes the isolation and its
teardown unconditional: when the child exits, the kernel destroys its mount
namespace and everything mounted only within it, automatically.

Because this uses raw os.fork() rather than the multiprocessing module's
spawn-based Process, `target` may be a closure or lambda -- fork copies the
whole process image, so nothing needs to be pickled except the *return
value*, which crosses the pipe back to the parent.
"""

from __future__ import annotations

import dataclasses
import os
import pickle
import select
import signal
import tempfile
from typing import Callable

from isotmpfs.backend import CtypesBackend, MountBackend


@dataclasses.dataclass
class IsolatedTmpfsResult:
    ok: bool
    error: str | None
    payload: object | None


class IsolatedTmpfs:
    def __init__(
        self,
        mount_path: str | None = None,
        *,
        size: str | None = None,
        backend: MountBackend | None = None,
    ) -> None:
        self.mount_path = mount_path or tempfile.mkdtemp(prefix="isotmpfs-")
        self.size = size
        self.backend = backend or CtypesBackend()

    def __enter__(self):
        raise TypeError(
            "IsolatedTmpfs is not a context manager for the calling process "
            "(namespace isolation is one-directional and per-process); use "
            "IsolatedTmpfs(...).run(target) to execute code inside the "
            "isolated child instead."
        )

    def __exit__(self, *exc_info):
        return False

    def run(
        self,
        target: Callable[..., object],
        *args: object,
        timeout: float | None = None,
        **kwargs: object,
    ) -> IsolatedTmpfsResult:
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            self._run_child(write_fd, target, args, kwargs)
            os._exit(1)  # unreachable: _run_child always calls os._exit()
        os.close(write_fd)
        try:
            return self._read_result(read_fd, pid, timeout)
        finally:
            os.close(read_fd)

    def _run_child(self, write_fd: int, target, args: tuple, kwargs: dict) -> None:
        try:
            self.backend.enter_isolated_namespace()
            self.backend.make_private("/")
            self.backend.mount_tmpfs(self.mount_path, size=self.size)
            payload = target(self.mount_path, *args, **kwargs)
            result = IsolatedTmpfsResult(ok=True, error=None, payload=payload)
        except BaseException as exc:
            result = IsolatedTmpfsResult(ok=False, error=f"{type(exc).__name__}: {exc}", payload=None)
        finally:
            try:
                self.backend.defensive_unmount(self.mount_path)
            except Exception:
                pass
        data = pickle.dumps(result)
        os.write(write_fd, len(data).to_bytes(8, "big") + data)
        os.close(write_fd)
        os._exit(0 if result.ok else 1)

    def _read_result(self, read_fd: int, pid: int, timeout: float | None) -> IsolatedTmpfsResult:
        ready, _, _ = select.select([read_fd], [], [], timeout)
        if not ready:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            raise TimeoutError(f"isolated child (pid {pid}) did not finish within {timeout}s")
        length_bytes = _read_exact(read_fd, 8)
        _, status = os.waitpid(pid, 0)
        if not length_bytes:
            return IsolatedTmpfsResult(
                ok=False,
                error=f"child exited without reporting a result (wait status {status})",
                payload=None,
            )
        length = int.from_bytes(length_bytes, "big")
        data = _read_exact(read_fd, length)
        return pickle.loads(data)


def _read_exact(fd: int, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def run_isolated(
    target: Callable[..., object],
    *args: object,
    mount_path: str | None = None,
    size: str | None = None,
    timeout: float | None = None,
    **kwargs: object,
) -> IsolatedTmpfsResult:
    return IsolatedTmpfs(mount_path, size=size).run(target, *args, timeout=timeout, **kwargs)
