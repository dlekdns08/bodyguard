"""Shared fixtures. All data here is synthetic."""

import json

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Point cache + config at tmp, disable background refresh, clear fake."""
    monkeypatch.setenv("BODYGUARD_CACHE", str(tmp_path / "vitals.json"))
    monkeypatch.setenv("BODYGUARD_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("BODYGUARD_NO_BACKGROUND", "1")
    monkeypatch.delenv("BODYGUARD_FAKE", raising=False)
    return tmp_path


def fake(**kwargs) -> str:
    """Build a BODYGUARD_FAKE value."""
    return json.dumps(kwargs)
