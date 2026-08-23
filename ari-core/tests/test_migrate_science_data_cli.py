from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from ari.public.science_data import parse_science_data


SCRIPT = Path(__file__).parents[2] / "scripts" / "migrate_science_data.py"
SPEC = importlib.util.spec_from_file_location("migrate_science_data_cli", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_offline_converter_is_explicit_and_atomic(tmp_path: Path):
    source = tmp_path / "science_data.legacy.json"
    output = tmp_path / "science_data.v1.json"
    source.write_text(
        json.dumps(
            {
                "configurations": [
                    {"rank": 1, "config_id": "cfg1", "metrics": {"x": 1.0}}
                ]
            }
        )
    )
    assert MODULE.main([str(source), str(output), "--run-id", "old-run"]) == 0
    parsed = parse_science_data(json.loads(output.read_text()))
    assert parsed.migration_status == "legacy-explicit"
    assert not list(tmp_path.glob("*.tmp-*"))
    with pytest.raises(FileExistsError):
        MODULE.migrate_file(source, output, run_id="old-run")
