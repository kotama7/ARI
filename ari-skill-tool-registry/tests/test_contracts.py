"""Generated registry contracts remain synchronized with their models."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from admission import AdmissionPolicyV1
from catalog import load_catalog_index, load_catalog_lock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _sync_module():
    path = PACKAGE_ROOT / "scripts" / "sync_contracts.py"
    spec = importlib.util.spec_from_file_location("registry_sync_contracts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_contracts_have_no_drift_and_are_valid_json_schema():
    module = _sync_module()
    assert module.sync(write=False) == []
    for path in sorted((PACKAGE_ROOT / "schemas").glob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(document)
        assert document["$id"].startswith("https://ari.dev/schemas/tool-registry/")


def test_committed_empty_catalog_is_self_authenticating_and_policy_bound():
    lock = load_catalog_lock(PACKAGE_ROOT / "CATALOG.lock")
    index = load_catalog_index(
        PACKAGE_ROOT / "catalog.index.json",
        expected_catalog_digest=lock.catalog_digest,
    )

    assert lock.policy_digest == AdmissionPolicyV1().digest
    assert lock.tools == []
    assert index.entries == []
