import errno

import pytest

from isotmpfs import _libc


def test_mount_nonexistent_target_raises_mounterror():
    with pytest.raises(_libc.MountError) as exc_info:
        _libc.mount("tmpfs", "/nonexistent/deeply/nested/isotmpfs-test-path", "tmpfs", 0)
    assert exc_info.value.errno in (errno.ENOENT, errno.EPERM)


def test_umount2_nonmountpoint_raises_mounterror():
    with pytest.raises(_libc.MountError) as exc_info:
        _libc.umount2("/nonexistent/deeply/nested/isotmpfs-test-path")
    assert exc_info.value.errno in (errno.ENOENT, errno.EINVAL)
