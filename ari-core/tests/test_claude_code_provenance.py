"""Tests for ari.llm.claude_code.provenance — per-call artifact sandbox."""

from __future__ import annotations

import hashlib
import json

from ari.llm.claude_code.provenance import (
    ProvenanceWriter,
    new_call_id,
    resolve_provenance_root,
    sha256_text,
)


def test_new_call_id_unique_and_slugged():
    a = new_call_id("bfts expand!")
    b = new_call_id("bfts expand!")
    assert a != b
    assert "bfts_expand_" in a


def test_resolve_provenance_root_explicit(tmp_path):
    assert resolve_provenance_root(tmp_path) == tmp_path


def test_resolve_provenance_root_from_checkpoint_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    root = resolve_provenance_root(None)
    assert root == tmp_path / "claude_code"


def test_resolve_provenance_root_none_without_checkpoint(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    assert resolve_provenance_root(None) is None


def test_writer_persists_all_artifacts_and_hashes(tmp_path):
    w = ProvenanceWriter(tmp_path / "call1")
    w.write_input(
        messages=[{"role": "user", "content": "hi"}],
        prompt="PROMPT",
        system="SYSTEM",
        schema_json='{"type": "object"}',
    )
    w.write_command(argv=("claude", "-p"), cwd="/tmp/cwd")
    w.write_env_allowlist({"PATH": "<inherited>"})
    w.write_claude_version("9.9.9 (Claude Code)")
    w.write_output(stdout='{"result": "ok"}', stderr="warn", returncode=0)
    w.write_result({"text": "ok"})
    w.write_validation({"schema_used": True, "valid": True})
    w.write_provenance({"provider": "claude_code"})
    w.append_trace({"event": "ResultMessage"})

    d = tmp_path / "call1"
    for rel in (
        "input/messages.json",
        "prompt.txt",
        "system.txt",
        "schema.json",
        "command.json",
        "env_allowlist.json",
        "claude_version.txt",
        "stdout.json",
        "stderr.log",
        "result.json",
        "validation.json",
        "input_hashes.json",
        "output_hashes.json",
        "provenance.json",
        "trace.jsonl",
    ):
        assert (d / rel).exists(), rel

    in_hashes = json.loads((d / "input_hashes.json").read_text())
    assert in_hashes["prompt.txt"] == hashlib.sha256(b"PROMPT").hexdigest()
    assert in_hashes["system.txt"] == sha256_text("SYSTEM")
    out_hashes = json.loads((d / "output_hashes.json").read_text())
    assert out_hashes["stdout.json"] == sha256_text('{"result": "ok"}')
    assert out_hashes["returncode"] == "0"
    cmd = json.loads((d / "command.json").read_text())
    assert cmd["argv"] == ["claude", "-p"]
    assert cmd["stdin_from"] == "prompt.txt"


def test_attempt_and_cwd_dirs(tmp_path):
    w = ProvenanceWriter(tmp_path / "call2")
    assert w.cwd_dir().is_dir()
    a2 = w.attempt_dir(2)
    assert a2 == tmp_path / "call2" / "attempt_2"
    assert a2.is_dir()
