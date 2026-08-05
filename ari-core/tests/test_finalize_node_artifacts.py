"""The score must be attributable to specific bytes.

The sterility gate hashed exactly the scored files and then threw the hashes
away, so a node_report recorded a number with no way to say which source
produced it. Finalize runs after the agent stops and before scoring, so it costs
no ReAct budget, and it must never turn a measured node into a failed one.
"""
import json

from ari.cli.bfts_loop import finalize_node_artifacts


def test_records_size_and_digest_for_each_declared_input(tmp_path):
    (tmp_path / "candidate_gemm.c").write_text("void gemm(){}\n")
    (tmp_path / "candidate_flags.txt").write_text("-O3\n")
    out = finalize_node_artifacts(
        tmp_path, ("candidate_gemm.c", "candidate_flags.txt"), node_id="n1")
    assert out["complete"] is True
    for rel in ("candidate_gemm.c", "candidate_flags.txt"):
        e = out["score_inputs"][rel]
        assert e["present"] and e["bytes"] > 0 and len(e["sha256"]) == 64
    on_disk = json.loads((tmp_path / "finalize.json").read_text())
    assert on_disk == out, "the written record differs from the returned one"


def test_a_missing_input_is_reported_not_hidden(tmp_path):
    (tmp_path / "candidate_gemm.c").write_text("void gemm(){}\n")
    out = finalize_node_artifacts(
        tmp_path, ("candidate_gemm.c", "candidate_flags.txt"), node_id="n2")
    assert out["complete"] is False
    assert out["score_inputs"]["candidate_flags.txt"]["present"] is False


def test_digest_changes_with_the_content(tmp_path):
    f = tmp_path / "candidate_a.c"
    f.write_text("int a;")
    d1 = finalize_node_artifacts(tmp_path, ("candidate_a.c",))["score_inputs"]["candidate_a.c"]["sha256"]
    f.write_text("int b;")
    d2 = finalize_node_artifacts(tmp_path, ("candidate_a.c",))["score_inputs"]["candidate_a.c"]["sha256"]
    assert d1 != d2


def test_no_declared_inputs_is_not_reported_as_complete(tmp_path):
    out = finalize_node_artifacts(tmp_path, ())
    assert out["complete"] is False and out["score_inputs"] == {}


def test_an_unwritable_directory_does_not_raise(tmp_path):
    missing = tmp_path / "gone"
    out = finalize_node_artifacts(missing, ("candidate_a.c",))
    assert out["score_inputs"]["candidate_a.c"]["present"] is False
