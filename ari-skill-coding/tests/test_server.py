"""Tests for ari-skill-coding MCP server tools."""

from __future__ import annotations

from pathlib import Path

import pytest

import json

from src.server import (
    _CONTAINER_ROOT,
    _devirtualize,
    _emit_results,
    _read_file,
    _run_bash,
    _run_code,
    _resolve_work_dir,
    _write_code,
    _RESULTS_SCHEMA_VERSION,
    _STDOUT_LIMIT,
)


@pytest.fixture
def work_dir(tmp_path):
    return str(tmp_path)


def test_write_code(work_dir):
    result = _write_code("test.py", "print('hello')", work_dir)
    assert result["status"] == "written"
    assert result["lines"] == 1
    assert Path(result["path"]).read_text() == "print('hello')"


def test_write_code_nested(work_dir):
    result = _write_code("sub/test.py", "x = 1", work_dir)
    assert result["status"] == "written"
    assert Path(result["path"]).exists()


def test_workspace_paths_reject_traversal_and_symlink_escape(work_dir, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = Path(work_dir) / "link.txt"
    link.symlink_to(outside)

    write = _write_code("../escape.py", "bad", work_dir)
    read = _read_file(str(outside), work_dir, offset=0, limit=100)
    run = _run_code("link.txt", work_dir, timeout=1)

    assert "traversal" in write["error"]
    assert "escapes" in read["error"]
    assert "symlink" in run["error"]
    assert outside.read_text(encoding="utf-8") == "secret"


def test_resolve_work_dir_is_bounded_by_core_owned_root(tmp_path, monkeypatch):
    root = tmp_path / "node"
    monkeypatch.setenv("ARI_WORK_DIR", str(root))
    assert Path(_resolve_work_dir("nested")).resolve() == (root / "nested").resolve()
    with pytest.raises(Exception, match="escapes"):
        _resolve_work_dir(str(tmp_path / "other"))
    assert not (tmp_path / "other").exists()
    with pytest.raises(Exception, match="traversal"):
        _resolve_work_dir("../../created-before-rejection")
    assert not (tmp_path.parent / "created-before-rejection").exists()


def test_run_code_success(work_dir):
    _write_code("hello.py", "print('hello world')", work_dir)
    result = _run_code("hello.py", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "hello world" in result["stdout"]


def test_run_code_error(work_dir):
    _write_code("err.py", "raise ValueError('test error')", work_dir)
    result = _run_code("err.py", work_dir, timeout=10)
    assert result["exit_code"] != 0
    assert result["status"] == "failed"


def test_run_code_not_found(work_dir):
    result = _run_code("nonexistent.py", work_dir, timeout=10)
    assert "error" in result


def test_run_bash_success(work_dir):
    result = _run_bash("echo hello", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


def test_run_bash_python(work_dir):
    result = _run_bash("python3 -c 'print(1+1)'", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "2" in result["stdout"]


def test_run_bash_failure(work_dir):
    result = _run_bash("exit 1", work_dir, timeout=10)
    assert result["exit_code"] == 1


def test_run_bash_hides_parent_secrets_and_records_full_log_artifacts(
    work_dir, monkeypatch
):
    import hashlib
    import json

    secret = "coding-parent-secret-must-not-cross"
    monkeypatch.setenv("UNDECLARED_API_TOKEN", secret)
    result = _run_bash(
        'python3 -c \'import os; print(os.getenv("UNDECLARED_API_TOKEN")); '
        'print("x"*12000)\'',
        work_dir,
        timeout=10,
    )

    assert result["status"] == "success"
    assert secret not in result["stdout"]
    assert result["stdout_truncated"] is True
    stdout = next(
        item for item in result["artifacts"] if item["logical_role"] == "stdout"
    )
    full_path = Path(work_dir) / stdout["relative_path"]
    assert full_path.stat().st_size == stdout["size_bytes"]
    assert (
        "sha256:" + hashlib.sha256(full_path.read_bytes()).hexdigest()
        == stdout["digest"]
    )
    assert json.dumps(result).find(secret) == -1


def test_retry_preserves_execution_identity_but_not_attempt(work_dir):
    first = _run_bash("printf stable", work_dir, timeout=10)
    second = _run_bash("printf stable", work_dir, timeout=10)
    assert first["execution_identity"] == second["execution_identity"]
    assert first["attempt_id"] != second["attempt_id"]


def test_run_bash_uses_container_when_env_set(work_dir, monkeypatch):
    """A configured container becomes explicit argv for the common executor."""
    from src import server as _srv

    calls = {"container": 0}

    def _fake_container_argv(cfg, cmd, *, cwd=None, network="inherit"):
        calls["container"] += 1
        assert network == "inherit"
        return ["python3", "-c", "print('inside-container')"]

    monkeypatch.setenv("ARI_CONTAINER_IMAGE", "ghcr.io/example/img:latest")
    monkeypatch.setenv("ARI_CONTAINER_MODE", "singularity")
    import ari.public.container as _ct_pub

    monkeypatch.setattr(_ct_pub, "container_shell_argv", _fake_container_argv)

    result = _srv._run_bash("echo hi", work_dir, timeout=5)
    assert result["exit_code"] == 0
    assert calls["container"] == 1, "container-wrapped path must be taken"
    assert "inside-container" in result["stdout"]
    assert result["container"]["reference"] == "ghcr.io/example/img:latest"
    assert result["container"]["resolution_status"] == "unresolved"


def test_run_bash_falls_back_to_host_without_env(work_dir, monkeypatch):
    """Without ARI_CONTAINER_IMAGE, _run_bash must execute directly on the host."""
    monkeypatch.delenv("ARI_CONTAINER_IMAGE", raising=False)
    result = _run_bash("echo host-ok", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "host-ok" in result["stdout"]


def test_run_code_truncation_flag(work_dir):
    # Generate stdout larger than _STDOUT_LIMIT
    code = f"print('x' * {_STDOUT_LIMIT * 2})"
    _write_code("big.py", code, work_dir)
    result = _run_code("big.py", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert result["truncated"] is True
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is False
    assert "chars truncated" in result["stdout"]


def test_run_code_no_truncation_flag(work_dir):
    _write_code("small.py", "print('hi')", work_dir)
    result = _run_code("small.py", work_dir, timeout=10)
    assert result["truncated"] is False
    assert result["stdout_truncated"] is False
    assert result["stderr_truncated"] is False


def test_read_file_relative(work_dir):
    _write_code("hello.txt", "hello world", work_dir)
    result = _read_file("hello.txt", work_dir, offset=0, limit=8000)
    assert "error" not in result
    assert result["content"] == "hello world"
    assert result["total_chars"] == 11
    assert result["truncated"] is False
    assert result["next_offset"] is None


def test_read_file_absolute(work_dir):
    p = Path(work_dir) / "abs.txt"
    p.write_text("absolute content")
    result = _read_file(str(p), work_dir, offset=0, limit=8000)
    assert result["content"] == "absolute content"


def test_read_file_pagination(work_dir):
    body = "abcdefghij" * 100  # 1000 chars
    _write_code("page.txt", body, work_dir)
    first = _read_file("page.txt", work_dir, offset=0, limit=400)
    assert first["returned_chars"] == 400
    assert first["truncated"] is True
    assert first["next_offset"] == 400
    second = _read_file("page.txt", work_dir, offset=first["next_offset"], limit=400)
    assert second["returned_chars"] == 400
    assert second["next_offset"] == 800
    third = _read_file("page.txt", work_dir, offset=second["next_offset"], limit=400)
    assert third["returned_chars"] == 200
    assert third["truncated"] is False
    assert third["next_offset"] is None
    # Concatenation reproduces the full body
    assert first["content"] + second["content"] + third["content"] == body


def test_read_file_not_found(work_dir):
    result = _read_file("missing.txt", work_dir, offset=0, limit=8000)
    assert "error" in result


def test_read_file_redirect_workflow(work_dir):
    """Round-trip: produce a large stdout via run_bash redirect, then read via read_file."""
    big_payload = "z" * (_STDOUT_LIMIT * 3)
    _write_code("emit.py", f"print('{big_payload}')", work_dir)
    # Use run_bash to redirect output to a file (the truncation-recovery workflow)
    redirect = _run_bash("python3 emit.py > out.log 2>&1", work_dir, timeout=10)
    assert redirect["exit_code"] == 0
    # Now read the full content via read_file
    full = _read_file("out.log", work_dir, offset=0, limit=_STDOUT_LIMIT * 4)
    assert "error" not in full
    assert big_payload in full["content"]


# ── emit_results ──────────────────────────────────────────────────────────


def test_emit_results_writes_typed_payload(work_dir):
    import json as _json

    execution = _run_bash("printf evidence", work_dir, timeout=10)
    r = _emit_results(
        params={"M": 120000, "K": 120000, "nnz_per_row": 32, "threads": 8},
        measurements={"GFlops_per_s": 26.864, "GB_per_s": 63.802},
        predictions={"peak_gflops_model": 686.45},
        scores={"_scientific_score": 0.37},
        units={"GFlops_per_s": "GFLOP/s", "GB_per_s": "GB/s"},
        execution=execution["measurement_execution"],
        file="results.json",
        work_dir=work_dir,
    )
    assert r["status"] == "written"
    assert r["schema_version"] == _RESULTS_SCHEMA_VERSION
    assert set(r["params_keys"]) == {"M", "K", "nnz_per_row", "threads"}
    assert set(r["measurements_keys"]) == {"GFlops_per_s", "GB_per_s"}

    payload = _json.loads(Path(r["path"]).read_text())
    assert payload["schema_version"] == _RESULTS_SCHEMA_VERSION
    assert payload["typed_schema_version"] == "ari.measurement-set/v1"
    measurement_set = payload["measurement_set"]
    assert measurement_set["schema_version"] == "ari.measurement-set/v1"
    assert measurement_set["parameters"]["M"] == 120000
    assert measurement_set["predictions"]["peak_gflops_model"] == 686.45
    assert measurement_set["scores"]["_scientific_score"] == 0.37
    assert {
        item["metric_id"]: item["value"] for item in measurement_set["measurements"]
    }["GFlops_per_s"] == 26.864
    assert {item["unit"] for item in measurement_set["measurements"]} == {
        "GFLOP/s",
        "GB/s",
    }
    assert {
        item["execution_attempt_id"] for item in measurement_set["measurements"]
    } == {execution["attempt_id"]}
    assert r["scientifically_admissible"] is True


def test_emit_results_rejects_forged_receipt_and_changed_artifact(work_dir):
    execution = _run_bash("printf evidence", work_dir, timeout=10)
    context = dict(execution["measurement_execution"])
    context["receipt"] = "0" * 64
    forged = _emit_results(
        params={},
        measurements={"latency": 1.0},
        predictions={},
        scores={},
        units={"latency": "ms"},
        execution=context,
        file="forged.json",
        work_dir=work_dir,
    )
    assert "invalid or mismatched" in forged["error"]
    assert not (Path(work_dir) / "forged.json").exists()

    stdout = next(
        item for item in execution["artifacts"] if item["logical_role"] == "stdout"
    )
    (Path(work_dir) / stdout["relative_path"]).write_text("tampered")
    changed = _emit_results(
        params={},
        measurements={"latency": 1.0},
        predictions={},
        scores={},
        units={"latency": "ms"},
        execution=execution["measurement_execution"],
        file="changed.json",
        work_dir=work_dir,
    )
    assert "artifact verification failed" in changed["error"]
    assert not (Path(work_dir) / "changed.json").exists()


def test_emit_results_marks_missing_execution_context_inadmissible(work_dir):
    result = _emit_results(
        params={},
        measurements={"latency": 1.0},
        predictions={},
        scores={},
        units={"latency": "ms"},
        file="results.json",
        work_dir=work_dir,
    )
    assert result["scientifically_admissible"] is False
    payload = __import__("json").loads(Path(result["path"]).read_text())
    record = payload["measurement_set"]["measurements"][0]
    assert record["execution_status"] == "unreported"


def test_emit_results_writes_provenance(work_dir):
    # The sanctioned reporter must carry _provenance so the hard gate can confirm a
    # measured ceiling / a correctness check (idea-owned requirement flags).
    import json as _json

    r = _emit_results(
        params={},
        measurements={"rnorm": 0.8, "peak_bw": 400.0, "max_abs_err": 1e-7},
        predictions={},
        scores={},
        provenance={"peak_bw": "microbench", "max_abs_err": "correctness"},
        file="results.json",
        work_dir=work_dir,
    )
    payload = _json.loads(Path(r["path"]).read_text())
    provenance = {
        item["metric_id"]: item["provenance"]
        for item in payload["measurement_set"]["measurements"]
        if item["provenance"] is not None
    }
    assert provenance == {
        "peak_bw": "microbench",
        "max_abs_err": "correctness",
    }


def test_emit_results_omits_empty_provenance(work_dir):
    # legacy/theory runs (no provenance) are unaffected — the key is absent.
    import json as _json

    r = _emit_results(
        params={},
        measurements={"y": 1.0},
        predictions={},
        scores={},
        file="r.json",
        work_dir=work_dir,
    )
    payload = _json.loads(Path(r["path"]).read_text())
    assert all(
        item["provenance"] is None
        for item in payload["measurement_set"]["measurements"]
    )


def test_emit_results_provenance_roundtrip_to_gate(work_dir):
    # finding-5 regression: drive the REAL emit_results writer (NOT a hand-built
    # _provenance dict) through the transform-style read into the hard gate, so the
    # "honest run -> PASS" property is exercised on the sanctioned producer path.
    import json as _json

    contract = pytest.importorskip("ari.pipeline.claim_gate.contract")
    mc = {
        "key": "rnorm",
        "ceiling_must_be_measured": True,
        "correctness_required": True,
    }

    def _cfg_from(path):
        from ari.public.execution import parse_measurement_document

        rj = _json.loads(Path(path).read_text())
        measurement_set = parse_measurement_document(rj, allow_legacy=False)
        cfg = {
            "config_id": "n",
            "measurements": {
                item.metric_id: item.value for item in measurement_set.measurements
            },
        }
        provenance = {
            item.metric_id: item.provenance
            for item in measurement_set.measurements
            if item.provenance is not None
        }
        if provenance:
            cfg["_provenance"] = provenance
        return cfg

    # honest: emit measurements + provenance tags via the sanctioned tool -> PASS
    r = _emit_results(
        params={},
        measurements={"rnorm": 0.8, "peak_bw": 400.0, "max_abs_err": 1e-7},
        predictions={},
        scores={},
        provenance={"peak_bw": "microbench", "max_abs_err": "correctness"},
        file="results.json",
        work_dir=work_dir,
    )
    assert (
        contract.check_contract(
            {"metric_contract": mc, "configurations": [_cfg_from(r["path"])]}
        )
        == []
    )

    # dodge: same numbers, NO provenance -> the idea-owned flags BLOCK
    r2 = _emit_results(
        params={},
        measurements={"rnorm": 0.8, "peak_bw": 400.0, "max_abs_err": 1e-7},
        predictions={},
        scores={},
        file="r2.json",
        work_dir=work_dir,
    )
    types = sorted(
        {
            f["type"]
            for f in contract.check_contract(
                {"metric_contract": mc, "configurations": [_cfg_from(r2["path"])]}
            )
        }
    )
    assert types == ["ceiling_unmeasured", "correctness_uncovered"]


def test_emit_results_warns_when_contract_evidence_dropped(
    work_dir, tmp_path, monkeypatch
):
    # regression (real run): the agent VERIFIED its kernel but emitted only
    # throughput -- the paper then blocked at finalize for a check that had passed.
    # emit_results must surface the gate's presence checks AT EMISSION TIME so the
    # agent can immediately re-emit with the evidence it already has.
    import json as _json

    pytest.importorskip("ari.public.claim_gate")
    (tmp_path / "metric_contract.json").write_text(
        _json.dumps(
            {
                "key": "GFLOP_per_s",
                "correctness_required": True,
                "claims": [
                    {
                        "claim": "selector improves worst-case",
                        "required_evidence": ["worst_case_on", "worst_case_off"],
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    r = _emit_results(
        params={},
        measurements={"GFlops_per_s": 40.5},
        predictions={},
        scores={},
        provenance={"GFlops_per_s": "benchmark"},
        file="results.json",
        work_dir=work_dir,
    )
    assert r["status"] == "written"  # the write itself is untouched
    warns = r.get("contract_warnings") or []
    assert any("correctness_required" in w for w in warns)
    assert any("worst_case_on" in w for w in warns)  # names the missing evidence


def test_emit_results_no_warnings_when_compliant_or_no_contract(
    work_dir, tmp_path, monkeypatch
):
    import json as _json

    pytest.importorskip("ari.public.claim_gate")
    # no contract -> no key
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    r0 = _emit_results(
        params={},
        measurements={"y": 1.0},
        predictions={},
        scores={},
        file="r0.json",
        work_dir=work_dir,
    )
    assert "contract_warnings" not in r0
    # compliant emission -> no key
    (tmp_path / "metric_contract.json").write_text(
        _json.dumps({"key": "m", "correctness_required": True})
    )
    r1 = _emit_results(
        params={},
        measurements={"m": 0.5, "max_abs_err": 0.0},
        predictions={},
        scores={},
        provenance={"max_abs_err": "correctness"},
        file="r1.json",
        work_dir=work_dir,
    )
    assert "contract_warnings" not in r1


def test_emit_results_overwrites_existing(work_dir):
    import json as _json

    _emit_results(
        params={"x": 1},
        measurements={"y": 1.0},
        predictions={},
        scores={},
        file="r.json",
        work_dir=work_dir,
    )
    _emit_results(
        params={"x": 2},
        measurements={"y": 2.0},
        predictions={},
        scores={},
        file="r.json",
        work_dir=work_dir,
    )
    payload = _json.loads((Path(work_dir) / "r.json").read_text())
    assert payload["measurement_set"]["parameters"]["x"] == 2  # second call wins


def test_emit_results_rejects_non_jsonable_values(work_dir):
    r = _emit_results(
        params={"src": Path("/tmp/foo")},
        measurements={"latency": 0.001},
        predictions={},
        scores={},
        file="r.json",
        work_dir=work_dir,
    )
    assert "finite JSON values" in r["error"]
    assert not (Path(work_dir) / "r.json").exists()


def test_emit_results_refuses_path_traversal(work_dir):
    # Traversal is rejected rather than silently changing caller intent.
    r = _emit_results(
        params={},
        measurements={"v": 1.0},
        predictions={},
        scores={},
        file="../../escape.json",
        work_dir=work_dir,
    )
    assert "error" in r
    assert "traversal" in r["error"]
    assert not (Path(work_dir).parent.parent / "escape.json").exists()


def test_emit_results_empty_dicts_are_fine(work_dir):
    import json as _json

    r = _emit_results(
        params={},
        measurements={},
        predictions={},
        scores={},
        file="empty.json",
        work_dir=work_dir,
    )
    assert r["status"] == "written"
    payload = _json.loads(Path(r["path"]).read_text())
    assert payload["measurement_set"]["parameters"] == {}
    assert payload["measurement_set"]["measurements"] == []


def test_emit_results_rejects_ambiguous_or_invalid_measurement_metadata(work_dir):
    nonnumeric = _emit_results(
        params={},
        measurements={"latency": "fast"},
        predictions={},
        scores={},
        file="bad.json",
        work_dir=work_dir,
    )
    overlap = _emit_results(
        params={"latency": 1},
        measurements={"latency": 2.0},
        predictions={},
        scores={},
        file="overlap.json",
        work_dir=work_dir,
    )
    unknown_unit = _emit_results(
        params={},
        measurements={"latency": 2.0},
        predictions={},
        scores={},
        units={"throughput": "GB/s"},
        file="unit.json",
        work_dir=work_dir,
    )

    assert "must be numeric" in nonnumeric["error"]
    assert "names overlap" in overlap["error"]
    assert unknown_unit["unknown_units"] == ["throughput"]
    assert not (Path(work_dir) / "bad.json").exists()


# ── Environment Modules reachability ────────────────────────────────────────
# Guard for the gap where `describe_environment` advertised the site's whole
# module tree while the executor scrubbed MODULEPATH and ran bash --noprofile
# --norc, so `module load` failed with "command not found" and a
# module-only toolchain could be neither used nor compared.

def _coding_server_module():
    import importlib.util, pathlib, sys
    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "_coding_srv_modenv", root / "src" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_coding_srv_modenv"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_module_pointers_are_passed_through(monkeypatch):
    srv = _coding_server_module()
    monkeypatch.setenv("MODULESHOME", "/opt/modules")
    monkeypatch.setenv("MODULEPATH", "/opt/modules/files:/site/files")
    env = srv._module_environment()
    assert env["MODULESHOME"] == "/opt/modules"
    assert env["MODULEPATH"] == "/opt/modules/files:/site/files"


def test_unset_module_pointers_are_omitted(monkeypatch):
    # A node with no module system must yield no keys at all rather than
    # empty strings, which would look like a configured-but-blank tree.
    srv = _coding_server_module()
    for name in srv._MODULE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert srv._module_environment() == {}


def test_module_pointers_are_declared_in_the_manifest():
    # The manifest gate (scripts/check_skill_manifests.py) enforces this too;
    # pinning it here makes the coupling visible where the names are defined.
    import pathlib
    import yaml
    srv = _coding_server_module()
    root = pathlib.Path(srv.__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "skill.yaml").read_text(encoding="utf-8"))
    declared = set(manifest.get("optional_env") or [])
    assert set(srv._MODULE_ENV_NAMES) <= declared


def test_init_snippet_is_guarded_and_prefixes_the_command():
    # Must be a no-op (never an error) where there is no module system.
    srv = _coding_server_module()
    assert 'MODULESHOME' in srv._MODULE_INIT_SNIPPET
    assert '|| true' in srv._MODULE_INIT_SNIPPET
    assert srv._MODULE_INIT_SNIPPET.endswith("\n")


def test_module_function_is_defined_for_run_bash(tmp_path, monkeypatch):
    # End-to-end through the real executor: `module` is a SHELL FUNCTION from
    # the init script, so --noprofile --norc leaves it undefined unless the
    # snippet runs. Skipped where the host has no module system.
    import os
    srv = _coding_server_module()
    if not os.environ.get("MODULESHOME"):
        import pytest
        pytest.skip("host has no Environment Modules installation")
    out = srv._run_bash("type module 2>&1 | head -1", str(tmp_path), 60)
    text = (out.get("stdout") or "") + (out.get("stderr") or "")
    assert "function" in text, text


@pytest.mark.asyncio
async def test_every_declared_output_schema_admits_the_error_shape() -> None:
    """A declared outputSchema obliges the handler to return structured content
    and the library validates it, so a schema describing only success would turn
    every tool failure into an output-validation error and discard the message.

    These tools report failure as ``{"error": "<message>"}`` -- a plain string,
    unlike the structured envelope the HPC provider uses -- so the two packages
    need different unions and neither can be assumed from the other.
    """

    import jsonschema

    from server import list_tools

    declared = [t for t in await list_tools() if t.outputSchema]
    assert {t.name for t in declared} == {
        "emit_results",
        "read_file",
        "run_bash",
        "run_code",
        "write_code",
    }
    for tool in declared:
        jsonschema.validate(
            instance={"error": "rejected", "exit_code": -1}, schema=tool.outputSchema
        )
        jsonschema.validate(instance={"error": "rejected"}, schema=tool.outputSchema)


@pytest.mark.asyncio
async def test_the_structured_half_is_scrubbed_like_the_text() -> None:
    """_virtualize exists to keep the real work_dir, $HOME, username and
    hostname off the tool boundary. A declared outputSchema sends a second copy
    of every result to the agent, so parsing it back from the scrubbed text --
    rather than handing over the raw dict -- is what stops the structured twin
    carrying everything the text had removed.
    """

    import inspect

    import server

    source = inspect.getsource(server.call_tool)
    # The structured value returned must be derived from the virtualized text.
    assert "json.loads(text)" in source
    assert "return [TextContent(type=\"text\", text=text)], json.loads(text)" in source
