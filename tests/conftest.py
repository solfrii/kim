import os

import pytest

from isotmpfs import run_isolated


@pytest.fixture(autouse=True, scope="session")
def _require_unprivileged_userns():
    """Fail loudly with a clear skip reason if this environment can't do
    unprivileged user namespaces, rather than every test failing opaquely.
    """
    result = run_isolated(lambda path: os.path.ismount(path))
    if not result.ok:
        pytest.skip(f"unprivileged user+mount namespaces unavailable: {result.error}")
