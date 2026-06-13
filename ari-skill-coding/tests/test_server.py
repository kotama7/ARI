"""Tests for ari-skill-coding MCP server tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.server import (
    _emit_results,
    _read_file,
    _run_bash,
    _run_code,
    _truncate,
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


def test_run_bash_uses_container_when_env_set(work_dir, monkeypatch):
    """When ARI_CONTAINER_IMAGE is set, _run_bash must delegate to
    ari.container.run_shell_in_container so commands execute inside the
    configured container — not on the bare host.

    Regression: hpc-skill used to own run_bash with this behavior; after
    moving run_bash to coding-skill, the container-wrap path must stay.
    """
    import subprocess as _sp
    from src import server as _srv

    calls = {"container": 0, "bare": 0}

    def _fake_run_shell(cfg, cmd, *, cwd=None, timeout=60):
        calls["container"] += 1
        return _sp.CompletedProcess(
            args=cmd, returncode=0, stdout="inside-container\n", stderr=""
        )

    def _fake_subprocess_run(*a, **k):
        calls["bare"] += 1
        return _sp.CompletedProcess(args="", returncode=0, stdout="bare\n", stderr="")

    monkeypatch.setenv("ARI_CONTAINER_IMAGE", "ghcr.io/example/img:latest")
    monkeypatch.setenv("ARI_CONTAINER_MODE", "singularity")
    # Patch container helpers at the module the skill imports from so the
    # local import inside _run_bash picks up the fakes. req 09 routes skill
    # access through ``ari.public.container`` (prod prefers it, falling back to
    # ``ari.container``); patch BOTH so the fake is seen regardless of which
    # path resolves. NOTE star-import binds names at import time, so patching
    # ari.container alone would NOT reach the ari.public.container binding.
    import ari.public.container as _ct_pub
    import ari.container as _ct
    monkeypatch.setattr(_ct_pub, "run_shell_in_container", _fake_run_shell)
    monkeypatch.setattr(_ct, "run_shell_in_container", _fake_run_shell)
    monkeypatch.setattr(_srv.subprocess, "run", _fake_subprocess_run)

    result = _srv._run_bash("echo hi", work_dir, timeout=5)
    assert result["exit_code"] == 0
    assert calls["container"] == 1, "container-wrapped path must be taken"
    assert calls["bare"] == 0, "bare subprocess.run must not be used when ARI_CONTAINER_IMAGE is set"
    assert "inside-container" in result["stdout"]


def test_run_bash_falls_back_to_host_without_env(work_dir, monkeypatch):
    """Without ARI_CONTAINER_IMAGE, _run_bash must execute directly on the host."""
    monkeypatch.delenv("ARI_CONTAINER_IMAGE", raising=False)
    result = _run_bash("echo host-ok", work_dir, timeout=10)
    assert result["exit_code"] == 0
    assert "host-ok" in result["stdout"]


def test_truncate_short_text():
    text, truncated = _truncate("hello", 100)
    assert text == "hello"
    assert truncated is False


def test_truncate_long_text_marker():
    long_text = "a" * 5000
    text, truncated = _truncate(long_text, 1000)
    assert truncated is True
    assert "chars truncated" in text
    assert "read_file" in text  # marker hints at the recovery workflow
    # Head and tail are both preserved
    assert text.startswith("a" * 100)
    assert text.endswith("a" * 100)


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
    r = _emit_results(
        params={"M": 120000, "K": 120000, "nnz_per_row": 32, "threads": 8},
        measurements={"GFlops_per_s": 26.864, "GB_per_s": 63.802},
        predictions={"peak_gflops_model": 686.45},
        scores={"_scientific_score": 0.37},
        file="results.json",
        work_dir=work_dir,
    )
    assert r["status"] == "written"
    assert r["schema_version"] == _RESULTS_SCHEMA_VERSION
    assert set(r["params_keys"]) == {"M", "K", "nnz_per_row", "threads"}
    assert set(r["measurements_keys"]) == {"GFlops_per_s", "GB_per_s"}

    payload = _json.loads(Path(r["path"]).read_text())
    assert payload["schema_version"] == _RESULTS_SCHEMA_VERSION
    assert payload["params"]["M"] == 120000
    assert payload["measurements"]["GFlops_per_s"] == 26.864
    assert payload["predictions"]["peak_gflops_model"] == 686.45
    assert payload["scores"]["_scientific_score"] == 0.37


def test_emit_results_writes_provenance(work_dir):
    # The sanctioned reporter must carry _provenance so the hard gate can confirm a
    # measured ceiling / a correctness check (idea-owned requirement flags).
    import json as _json
    r = _emit_results(
        params={}, measurements={"rnorm": 0.8, "peak_bw": 400.0, "max_abs_err": 1e-7},
        predictions={}, scores={},
        provenance={"peak_bw": "microbench", "max_abs_err": "correctness"},
        file="results.json", work_dir=work_dir,
    )
    payload = _json.loads(Path(r["path"]).read_text())
    assert payload["_provenance"] == {"peak_bw": "microbench", "max_abs_err": "correctness"}


def test_emit_results_omits_empty_provenance(work_dir):
    # legacy/theory runs (no provenance) are unaffected — the key is absent.
    import json as _json
    r = _emit_results(
        params={}, measurements={"y": 1.0}, predictions={}, scores={},
        file="r.json", work_dir=work_dir,
    )
    assert "_provenance" not in _json.loads(Path(r["path"]).read_text())


def test_emit_results_provenance_roundtrip_to_gate(work_dir):
    # finding-5 regression: drive the REAL emit_results writer (NOT a hand-built
    # _provenance dict) through the transform-style read into the hard gate, so the
    # "honest run -> PASS" property is exercised on the sanctioned producer path.
    import json as _json
    contract = pytest.importorskip("ari.pipeline.claim_gate.contract")
    mc = {"key": "rnorm", "ceiling_must_be_measured": True, "correctness_required": True}

    def _cfg_from(path):
        rj = _json.loads(Path(path).read_text())
        cfg = {"config_id": "n", "measurements": rj.get("measurements", {})}
        if isinstance(rj.get("_provenance"), dict):  # exactly transform server.py ~586
            cfg["_provenance"] = dict(rj["_provenance"])
        return cfg

    # honest: emit measurements + provenance tags via the sanctioned tool -> PASS
    r = _emit_results(
        params={}, measurements={"rnorm": 0.8, "peak_bw": 400.0, "max_abs_err": 1e-7},
        predictions={}, scores={},
        provenance={"peak_bw": "microbench", "max_abs_err": "correctness"},
        file="results.json", work_dir=work_dir,
    )
    assert contract.check_contract(
        {"metric_contract": mc, "configurations": [_cfg_from(r["path"])]}) == []

    # dodge: same numbers, NO provenance -> the idea-owned flags BLOCK
    r2 = _emit_results(
        params={}, measurements={"rnorm": 0.8, "peak_bw": 400.0, "max_abs_err": 1e-7},
        predictions={}, scores={}, file="r2.json", work_dir=work_dir,
    )
    types = sorted({f["type"] for f in contract.check_contract(
        {"metric_contract": mc, "configurations": [_cfg_from(r2["path"])]})})
    assert types == ["ceiling_unmeasured", "correctness_uncovered"]


def test_emit_results_warns_when_contract_evidence_dropped(work_dir, tmp_path, monkeypatch):
    # regression (real run): the agent VERIFIED its kernel but emitted only
    # throughput -- the paper then blocked at finalize for a check that had passed.
    # emit_results must surface the gate's presence checks AT EMISSION TIME so the
    # agent can immediately re-emit with the evidence it already has.
    import json as _json
    pytest.importorskip("ari.public.claim_gate")
    (tmp_path / "metric_contract.json").write_text(_json.dumps({
        "key": "GFLOP_per_s", "correctness_required": True,
        "claims": [{"claim": "selector improves worst-case",
                    "required_evidence": ["worst_case_on", "worst_case_off"]}]}))
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    r = _emit_results(
        params={}, measurements={"GFlops_per_s": 40.5}, predictions={}, scores={},
        provenance={"GFlops_per_s": "benchmark"},
        file="results.json", work_dir=work_dir,
    )
    assert r["status"] == "written"                      # the write itself is untouched
    warns = r.get("contract_warnings") or []
    assert any("correctness_required" in w for w in warns)
    assert any("worst_case_on" in w for w in warns)      # names the missing evidence


def test_emit_results_no_warnings_when_compliant_or_no_contract(work_dir, tmp_path, monkeypatch):
    import json as _json
    pytest.importorskip("ari.public.claim_gate")
    # no contract -> no key
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    r0 = _emit_results(params={}, measurements={"y": 1.0}, predictions={}, scores={},
                       file="r0.json", work_dir=work_dir)
    assert "contract_warnings" not in r0
    # compliant emission -> no key
    (tmp_path / "metric_contract.json").write_text(_json.dumps({
        "key": "m", "correctness_required": True}))
    r1 = _emit_results(
        params={}, measurements={"m": 0.5, "max_abs_err": 0.0}, predictions={}, scores={},
        provenance={"max_abs_err": "correctness"},
        file="r1.json", work_dir=work_dir,
    )
    assert "contract_warnings" not in r1


def test_emit_results_overwrites_existing(work_dir):
    import json as _json
    _emit_results(
        params={"x": 1}, measurements={"y": 1.0},
        predictions={}, scores={}, file="r.json", work_dir=work_dir,
    )
    _emit_results(
        params={"x": 2}, measurements={"y": 2.0},
        predictions={}, scores={}, file="r.json", work_dir=work_dir,
    )
    payload = _json.loads((Path(work_dir) / "r.json").read_text())
    assert payload["params"]["x"] == 2  # second call wins


def test_emit_results_coerces_non_jsonable(work_dir):
    # pathlib.Path is not directly JSON-serialisable; the helper must
    # str-coerce rather than crash so emit_results never fails the run.
    import json as _json
    r = _emit_results(
        params={"src": Path("/tmp/foo")},
        measurements={"latency": 0.001},
        predictions={}, scores={}, file="r.json", work_dir=work_dir,
    )
    assert r["status"] == "written"
    payload = _json.loads(Path(r["path"]).read_text())
    assert payload["params"]["src"] == "/tmp/foo"


def test_emit_results_refuses_path_traversal(work_dir):
    # ``file`` is normalised to its basename so a malicious agent cannot
    # write outside the node's work_dir via ``../../escape.json``.
    r = _emit_results(
        params={}, measurements={"v": 1.0},
        predictions={}, scores={},
        file="../../escape.json", work_dir=work_dir,
    )
    assert r["status"] == "written"
    assert Path(r["path"]).parent.resolve() == Path(work_dir).resolve()


def test_emit_results_empty_dicts_are_fine(work_dir):
    import json as _json
    r = _emit_results(
        params={}, measurements={}, predictions={}, scores={},
        file="empty.json", work_dir=work_dir,
    )
    assert r["status"] == "written"
    payload = _json.loads(Path(r["path"]).read_text())
    assert payload["params"] == {}
    assert payload["measurements"] == {}
