"""Shared fixtures for platform tests that run generated projects."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def blocked_env(tmp_path_factory) -> dict:
    """Environment in which importing golden_path fails, even though the
    platform is installed (editable) in this venv."""
    stub_root = tmp_path_factory.mktemp("block-golden-path")
    (stub_root / "golden_path").mkdir()
    (stub_root / "golden_path" / "__init__.py").write_text(
        'raise ImportError("generated projects must not import golden_path")\n'
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update({"PYTHONPATH": str(stub_root), "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def stderr_records(stderr: str) -> list[dict]:
    """Parse typed JSONL stderr (template 0.4.0+). Every line must be JSON."""
    import json

    return [json.loads(line) for line in stderr.splitlines() if line.strip()]


def only_record(stderr: str, record_type: str) -> dict:
    [record] = [r for r in stderr_records(stderr) if r["record"] == record_type]
    return record
