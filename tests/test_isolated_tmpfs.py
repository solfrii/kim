import os
import tempfile

import pytest

from isotmpfs import IsolatedTmpfs, run_isolated


def test_basic_mount_and_write():
    def _write_and_read(path):
        file_path = os.path.join(path, "hello.txt")
        with open(file_path, "w") as f:
            f.write("hello from isolated tmpfs")
        with open(file_path) as f:
            return f.read()

    result = run_isolated(_write_and_read)
    assert result.ok, result.error
    assert result.payload == "hello from isolated tmpfs"


def test_isolated_from_parent():
    mount_path = tempfile.mkdtemp(prefix="isotmpfs-parent-test-")
    assert os.listdir(mount_path) == []

    def _write_secret(path):
        with open(os.path.join(path, "secret.txt"), "w") as f:
            f.write("visible only inside the child")

    result = run_isolated(_write_secret, mount_path=mount_path)
    assert result.ok, result.error

    # once the child (and its mount namespace) has exited, the tmpfs and
    # everything in it is gone -- the original, empty directory is back
    assert os.listdir(mount_path) == []
    assert not os.path.exists(os.path.join(mount_path, "secret.txt"))


def test_sibling_children_isolated_at_same_path():
    shared_path = tempfile.mkdtemp(prefix="isotmpfs-shared-test-")

    def _write_and_list(path, filename):
        with open(os.path.join(path, filename), "w") as f:
            f.write(filename)
        return sorted(os.listdir(path))

    result_a = run_isolated(_write_and_list, "a.txt", mount_path=shared_path)
    result_b = run_isolated(_write_and_list, "b.txt", mount_path=shared_path)

    assert result_a.ok, result_a.error
    assert result_b.ok, result_b.error
    # same literal mountpoint path in both children, but each only ever
    # sees its own tmpfs -- proves isolation is per-mount, not per-path
    assert result_a.payload == ["a.txt"]
    assert result_b.payload == ["b.txt"]


def test_no_mount_leak_in_parent_mountinfo():
    mount_path = tempfile.mkdtemp(prefix="isotmpfs-mountinfo-test-")

    def _mountinfo_mentions(path):
        with open("/proc/self/mountinfo") as f:
            return path in f.read()

    assert not _mountinfo_mentions(mount_path)
    for _ in range(5):
        result = run_isolated(lambda path: None, mount_path=mount_path)
        assert result.ok, result.error
    assert not _mountinfo_mentions(mount_path)


def test_context_manager_use_raises_typeerror():
    with pytest.raises(TypeError):
        with IsolatedTmpfs():
            pass
