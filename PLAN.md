# Per-process isolated tmpfs (Python, ctypes variant)

## Context

Goal: a small Python project in `/home/nice/kim` (empty dir, not a git repo; Fedora 44 aarch64, Python 3.14.6) that implements and tests **per-process isolated tmpfs** — each process gets its own tmpfs mount invisible to other processes, using Linux mount namespaces.

Three mechanism variants were discussed with the user and are worth remembering for future work (saved to memory as `project-isolated-tmpfs`):
1. **ctypes direct syscalls** — building this one first.
2. subprocess wrapping the `unshare`/`mount` CLI tools — later.
3. Hybrid (`os.unshare()` + ctypes `mount()`) — later.

Environment facts verified via read-only checks (do not re-verify):
- `os.unshare`, `os.CLONE_NEWNS`, `os.CLONE_NEWUSER` exist in Python 3.14 stdlib. No `mount()`/`umount2()` wrapper in stdlib — needs ctypes.
- No passwordless sudo. Unprivileged user+mount namespaces work: `unshare --mount --user --map-root-user echo ok` succeeds as uid 1000 (`nice`). `sysctl user.max_user_namespaces` = 47665 (plenty).
- `pytest` is not yet installed — needs a venv.
- `/proc/self/mountinfo` shows most mounts as `shared:N` propagation on this system — the classic "leaks by default" hazard that must be defended against with `MS_PRIVATE|MS_REC` before mounting tmpfs.

Decisions already confirmed with the user:
- Privilege model: **unprivileged only** (CLONE_NEWUSER + CLONE_NEWNS with manual uid_map/setgroups/gid_map writes, mirroring `unshare --map-root-user`). No root/privileged code path.
- Deliverable: a reusable Python module/package (`isotmpfs`) with an `IsolatedTmpfs`-style abstraction, plus a pytest suite proving real isolation — not just demo scripts.
- A Plan agent produced a detailed design (ctypes signatures, exact unshare/id-map/mount sequence, API shape, concrete test cases) which this plan follows.

## Design summary

**Why fork internally rather than a context manager in the calling process:** `unshare(CLONE_NEWUSER|CLONE_NEWNS)` is one-directional — a process can't cleanly return to its original mount namespace. A `with IsolatedTmpfs(): ...` API that unshares the *current* process would permanently mutate that process's ambient namespace (a footgun, especially if used naively inside pytest's own process). So `IsolatedTmpfs.run(target, *args, **kwargs)` forks a child, isolates+mounts tmpfs *inside the child*, calls `target(mount_path, *args, **kwargs)` there, and reports the result back over a pipe (not through the tmpfs — the pipe is a plain fd pair, unaffected by the mount namespace). `IsolatedTmpfs.__enter__` raises `TypeError` with an explanatory message to head off misuse. When the child exits, the kernel automatically destroys its mount namespace and unmounts everything mounted only within it — no explicit cleanup is required, though the child defensively calls `umount2(..., MNT_DETACH)` before exit for cleanliness/fail-fast behavior.

**Sequence inside the forked child** (see `CtypesBackend.enter_isolated_namespace`/`mount_tmpfs`):
1. `os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)`.
2. Write `"deny"` to `/proc/self/setgroups`, then `f"0 {uid} 1"` to `/proc/self/uid_map`, then `f"0 {gid} 1"` to `/proc/self/gid_map` (setgroups must precede gid_map per `user_namespaces(7)`; uid_map has no such ordering constraint). This makes the process appear as uid 0 *inside* the new user namespace, sufficient to mount tmpfs.
3. `mount(NULL, "/", NULL, MS_PRIVATE|MS_REC, NULL)` — recursively make every mount private so nothing propagates in/out of this namespace. Critical given this system's default `shared:N` propagation.
4. `os.makedirs(target, exist_ok=True)`; `mount("tmpfs", target, "tmpfs", MS_NOSUID|MS_NODEV, data)`.
5. Run the caller's `target` function, capture return value or exception.
6. Defensive `umount2(target, MNT_DETACH)`, pickle the result, write length-prefixed bytes to the pipe, `os._exit()`.

**Pluggable seam (not over-built):** `backend.py` defines a `MountBackend` Protocol (`enter_isolated_namespace`, `make_private`, `mount_tmpfs`, `defensive_unmount`) with one implementation, `CtypesBackend`, injected via `IsolatedTmpfs(backend=...)` defaulting to `CtypesBackend()`. This is just enough of a seam for variants 2/3 later — no registry/plugin system.

## Files

Already created:
- `/home/nice/kim/pyproject.toml` — src-layout setuptools config, `requires-python = ">=3.12"`, `[tool.pytest.ini_options] testpaths = ["tests"]`.
- `/home/nice/kim/.gitignore` — `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`.
- `/home/nice/kim/src/isotmpfs/_libc.py` — ctypes bindings for `mount()`/`umount2()` only (stdlib already covers `unshare`), `MountError(OSError)` with errno, `MS_*`/`MNT_DETACH` constants (hardcoded stable UAPI values: `MS_NOSUID=1<<1`, `MS_NODEV=1<<2`, `MS_REC=1<<14`, `MS_PRIVATE=1<<18`, etc.).

Still to create:
- `/home/nice/kim/src/isotmpfs/backend.py` — `MountBackend` Protocol + `CtypesBackend` (as described above; id-map writing lives inside `CtypesBackend.enter_isolated_namespace`, not as a separate method on `IsolatedTmpfs`, since a future CLI-wrapping backend would handle id-mapping differently).
- `/home/nice/kim/src/isotmpfs/isolated_tmpfs.py` — `IsolatedTmpfsResult` dataclass (`ok`, `error`, `payload`), `IsolatedTmpfs` class (`__init__(mount_path=None, *, size=None, backend=None)`, `run()` fork+pipe orchestration with `timeout` support via `select.select`, `__enter__` raising `TypeError`), module-level `run_isolated(target, *args, mount_path=None, size=None, timeout=None, **kwargs)` convenience function.
- `/home/nice/kim/src/isotmpfs/__init__.py` — re-exports `IsolatedTmpfs`, `IsolatedTmpfsResult`, `run_isolated`, `MountBackend`, `CtypesBackend`, `MountError`.
- `/home/nice/kim/tests/conftest.py` — session-scoped autouse fixture that runs a trivial `run_isolated(...)` and `pytest.skip()`s the whole session with a clear reason if unprivileged namespaces are unavailable, rather than every test failing opaquely.
- `/home/nice/kim/tests/test_libc_bindings.py` — narrow unit tests of `_libc.mount`/`umount2` error paths (bogus path → `MountError` with the expected `errno`), run directly in-process since they're expected to fail before touching anything real.
- `/home/nice/kim/tests/test_isolated_tmpfs.py` — the real isolation proofs:
  - `test_basic_mount_and_write` — sanity write/read round-trip inside one isolated child.
  - `test_isolated_from_parent` — parent can't see files a child wrote into its tmpfs, neither during nor after the child's lifetime (dir is empty again once the child exits).
  - `test_sibling_children_isolated_at_same_path` — two separate forked children, same literal mount path string, each only ever sees its own file (`a.txt` vs `b.txt`) — proves isolation is per-mount-namespace, not per-path.
  - `test_no_mount_leak_in_parent_mountinfo` — parent's `/proc/self/mountinfo` never mentions the child's mount path, before or after running several isolated children in a loop.
  - `test_context_manager_use_raises_typeerror` — `with IsolatedTmpfs(): ...` raises `TypeError` (guards against the footgun).
- `/home/nice/kim/README.md` — short: what this proves, no-sudo setup/run instructions, note on the 3 planned variants and that this is variant 1.

## Verification

1. `cd /home/nice/kim && python3 -m venv .venv && .venv/bin/pip install -e . pytest`
2. `.venv/bin/pytest -v` — should pass entirely as uid 1000, no sudo. Every test that touches namespaces does so inside a forked child (via `run_isolated`), so pytest's own process never unshares anything.
3. Manually sanity-check one property interactively, e.g.:
   ```
   .venv/bin/python3 -c "
   from isotmpfs import run_isolated
   import os
   r = run_isolated(lambda p: (p, os.path.ismount(p), os.listdir(p)))
   print(r)
   "
   ```
4. If `MS_NOSUID`/`MS_NODEV`/etc. bit values ever look wrong (mount fails with `EINVAL`), cross-check against `/proc/self/mountinfo` output for an existing tmpfs (e.g. `/dev/shm`) and `man 7 mount_namespaces`.
