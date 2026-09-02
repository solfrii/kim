# isotmpfs

Per-process isolated tmpfs in Python: give a process its own tmpfs mount
that's invisible to every other process, using Linux mount + user
namespaces. When the process exits, the kernel tears the mount down
automatically.

This is variant 1 of 3 planned implementations:

1. **ctypes direct syscalls** (this one) — `unshare()`/`mount()` called
   directly against libc via ctypes, no external CLI tools.
2. subprocess wrapping the `unshare`/`mount` CLI tools — planned.
3. Hybrid: `os.unshare()` + ctypes `mount()` — planned.

## How it works

`IsolatedTmpfs.run(target, *args, **kwargs)` forks a child process. The
child:

1. Enters a new user + mount namespace (`unshare(CLONE_NEWUSER|CLONE_NEWNS)`).
2. Maps itself to uid/gid 0 inside that namespace (writes to
   `/proc/self/{setgroups,uid_map,gid_map}`), which is what grants an
   unprivileged user permission to mount tmpfs.
3. Marks all mounts `MS_PRIVATE|MS_REC` so nothing propagates in or out of
   the new namespace.
4. Mounts tmpfs at the target path and calls `target(mount_path, ...)`.
5. Reports the return value (or exception) back to the parent over a pipe,
   then exits — which destroys the namespace and everything mounted in it.

No root or sudo is required; this relies on unprivileged user namespaces
being enabled (true on most modern desktop/server Linux distros, including
the one this was built on).

## Setup

```
poetry install
```

Poetry creates the virtualenv outside this directory (under
`~/.cache/pypoetry/virtualenvs` by default), not in a local `.venv/`.

## Run tests

```
poetry run pytest -v
```

If unprivileged user namespaces aren't available on your kernel, the whole
suite will skip with a clear reason rather than failing opaquely.

## Try it interactively

```
poetry run python3 -c "
from isotmpfs import run_isolated
import os
r = run_isolated(lambda p: (p, os.path.ismount(p), os.listdir(p)))
print(r)
"
```
