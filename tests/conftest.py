"""Pytest configuration: isolate persistence to a temp dir and clear settings
cache between tests so environment-driven state never leaks across cases."""

import pytest

from driftlab.config import get_settings


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTLAB_DATA_DIR", str(tmp_path / ".driftlab"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()