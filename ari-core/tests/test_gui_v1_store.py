"""gui_refresh task 05 Wave 3b — GUI config document store (ADR-12).

``ari/viz/v1/store.py``: durable GUI-only documents under
``{workspace_root}/gui_store/`` (sibling of ``checkpoints/``) — the single
default project's ``project_config.json`` plus ``run_templates/{id}.json``
and ``run_drafts/{id}.json``.

Covered here:

- envelope roundtrip (``schema_version``/``kind``/``revision``/``body``) and
  monotonic revision increments;
- optimistic concurrency: stale/absent ``expected_revision`` raises
  ``RevisionConflict`` (write and delete), ``0`` == create-only;
- atomic write survives a simulated crash (monkeypatched ``os.replace``
  raising): previous document byte-intact, revision unchanged, no ``*.tmp``
  orphan;
- owner-only mode bits: files ``0o600``, ``gui_store/`` + subdirs ``0o700``;
- deterministic listing (codepoint order by doc_id, corrupt/foreign files
  omitted, byte-stable across repeated calls);
- caller-supplied ID validation (traversal structurally rejected) and kind
  routing (singleton vs listable kinds);
- ``from_env`` resolves the workspace root via the canonical
  ``RuntimePathResolver`` policy (``ARI_CHECKPOINT_DIR`` wins) so
  ``gui_store/`` lands as a sibling of ``checkpoints/``;
- corrupt-document semantics: guarded reads/writes raise
  ``CorruptDocument``; only an unconditional write repairs.

Deterministic: pure tmp_path filesystem, no server, no network, no LLM.
"""
from __future__ import annotations

import json
import os
import stat

import pytest

from ari.viz.v1.store import (
    KIND_PROJECT_CONFIG,
    KIND_RUN_DRAFT,
    KIND_RUN_TEMPLATE,
    CorruptDocument,
    GuiStore,
    RevisionConflict,
)


@pytest.fixture
def store(tmp_path):
    return GuiStore(tmp_path)


# ── roundtrip + revision ────────────────────────────────────────────────────


class TestRoundtrip:
    def test_read_missing_returns_none(self, store):
        assert store.read(KIND_PROJECT_CONFIG) is None
        assert store.read(KIND_RUN_TEMPLATE, "t1") is None

    def test_project_config_roundtrip_envelope(self, store, tmp_path):
        body = {"model": "gpt-x", "retrieval": {"top_k": 5}}
        rev = store.write(KIND_PROJECT_CONFIG, body)
        assert rev == 1
        doc, revision = store.read(KIND_PROJECT_CONFIG)
        assert revision == 1
        assert doc == {
            "schema_version": 1,
            "kind": "project_config",
            "revision": 1,
            "body": body,
        }
        assert (tmp_path / "gui_store" / "project_config.json").is_file()

    def test_template_and_draft_paths(self, store, tmp_path):
        store.write(KIND_RUN_TEMPLATE, {"a": 1}, doc_id="tpl-1")
        store.write(KIND_RUN_DRAFT, {"b": 2}, doc_id="draft_1")
        assert (tmp_path / "gui_store" / "run_templates" / "tpl-1.json").is_file()
        assert (tmp_path / "gui_store" / "run_drafts" / "draft_1.json").is_file()

    def test_revision_increments_monotonically(self, store):
        assert store.write(KIND_RUN_TEMPLATE, {"v": 1}, doc_id="t") == 1
        assert store.write(KIND_RUN_TEMPLATE, {"v": 2}, doc_id="t") == 2
        assert store.write(KIND_RUN_TEMPLATE, {"v": 3}, doc_id="t") == 3
        doc, revision = store.read(KIND_RUN_TEMPLATE, "t")
        assert revision == 3
        assert doc["body"] == {"v": 3}

    def test_serialization_is_deterministic(self, store, tmp_path):
        body = {"z": 1, "a": {"y": 2, "b": 3}}
        store.write(KIND_PROJECT_CONFIG, body)
        first = (tmp_path / "gui_store" / "project_config.json").read_bytes()
        # Same content at the same revision from a fresh store instance.
        store2 = GuiStore(tmp_path)
        store2.write(KIND_PROJECT_CONFIG, body, expected_revision=1)
        second = (tmp_path / "gui_store" / "project_config.json").read_bytes()
        assert first.replace(b'"revision": 1', b"") == second.replace(
            b'"revision": 2', b""
        )
        assert first.endswith(b"\n")

    def test_body_must_be_dict(self, store):
        with pytest.raises(ValueError):
            store.write(KIND_PROJECT_CONFIG, ["not", "a", "dict"])


# ── optimistic concurrency ──────────────────────────────────────────────────


class TestRevisionConflict:
    def test_stale_revision_raises(self, store):
        store.write(KIND_RUN_DRAFT, {"v": 1}, doc_id="d")
        store.write(KIND_RUN_DRAFT, {"v": 2}, doc_id="d", expected_revision=1)
        with pytest.raises(RevisionConflict) as ei:
            store.write(KIND_RUN_DRAFT, {"v": 3}, doc_id="d", expected_revision=1)
        assert ei.value.expected == 1
        assert ei.value.actual == 2
        # The conflicting write changed nothing.
        doc, revision = store.read(KIND_RUN_DRAFT, "d")
        assert revision == 2
        assert doc["body"] == {"v": 2}

    def test_expected_zero_is_create_only(self, store):
        assert store.write(
            KIND_RUN_TEMPLATE, {"v": 1}, doc_id="t", expected_revision=0
        ) == 1
        with pytest.raises(RevisionConflict):
            store.write(
                KIND_RUN_TEMPLATE, {"v": 2}, doc_id="t", expected_revision=0
            )

    def test_expected_on_missing_doc_raises(self, store):
        with pytest.raises(RevisionConflict) as ei:
            store.write(
                KIND_RUN_TEMPLATE, {"v": 1}, doc_id="nope", expected_revision=3
            )
        assert ei.value.actual == 0

    def test_delete_optimistic(self, store):
        store.write(KIND_RUN_DRAFT, {"v": 1}, doc_id="d")
        with pytest.raises(RevisionConflict):
            store.delete(KIND_RUN_DRAFT, "d", expected_revision=9)
        assert store.delete(KIND_RUN_DRAFT, "d", expected_revision=1) is True
        assert store.read(KIND_RUN_DRAFT, "d") is None
        # Missing doc: unconditional delete is a no-op False; expected!=0 raises.
        assert store.delete(KIND_RUN_DRAFT, "d") is False
        with pytest.raises(RevisionConflict):
            store.delete(KIND_RUN_DRAFT, "d", expected_revision=1)


# ── atomic write / simulated crash ──────────────────────────────────────────


class TestAtomicWrite:
    def test_crash_before_replace_keeps_original(
        self, store, tmp_path, monkeypatch
    ):
        store.write(KIND_PROJECT_CONFIG, {"v": "original"})
        path = tmp_path / "gui_store" / "project_config.json"
        original = path.read_bytes()

        def boom(src, dst):  # simulated crash between tmp write and publish
            raise OSError("simulated crash during replace")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="simulated crash"):
            store.write(KIND_PROJECT_CONFIG, {"v": "clobbered"})
        monkeypatch.undo()

        # Previous document byte-intact, revision unchanged, no tmp orphan.
        assert path.read_bytes() == original
        doc, revision = store.read(KIND_PROJECT_CONFIG)
        assert revision == 1
        assert doc["body"] == {"v": "original"}
        leftovers = [
            p for p in path.parent.iterdir() if p.name != "project_config.json"
        ]
        assert [p for p in leftovers if p.is_file()] == []

    def test_crash_on_create_leaves_no_document(
        self, store, tmp_path, monkeypatch
    ):
        def boom(src, dst):
            raise OSError("simulated crash during replace")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            store.write(KIND_RUN_TEMPLATE, {"v": 1}, doc_id="t")
        monkeypatch.undo()
        assert store.read(KIND_RUN_TEMPLATE, "t") is None
        tpl_dir = tmp_path / "gui_store" / "run_templates"
        assert [p for p in tpl_dir.iterdir() if p.is_file()] == []


# ── permissions ─────────────────────────────────────────────────────────────


class TestModeBits:
    @staticmethod
    def _mode(path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_owner_only_file_and_dirs(self, store, tmp_path):
        store.write(KIND_PROJECT_CONFIG, {"v": 1})
        store.write(KIND_RUN_TEMPLATE, {"v": 1}, doc_id="t")
        gui = tmp_path / "gui_store"
        assert self._mode(gui) == 0o700
        assert self._mode(gui / "run_templates") == 0o700
        assert self._mode(gui / "project_config.json") == 0o600
        assert self._mode(gui / "run_templates" / "t.json") == 0o600

    def test_rewrite_reasserts_modes(self, store, tmp_path):
        store.write(KIND_PROJECT_CONFIG, {"v": 1})
        gui = tmp_path / "gui_store"
        os.chmod(gui, 0o755)
        os.chmod(gui / "project_config.json", 0o644)
        store.write(KIND_PROJECT_CONFIG, {"v": 2})
        assert self._mode(gui) == 0o700
        assert self._mode(gui / "project_config.json") == 0o600


# ── listing ─────────────────────────────────────────────────────────────────


class TestList:
    def test_empty_when_dir_absent(self, store):
        assert store.list(KIND_RUN_TEMPLATE) == []
        assert store.list(KIND_RUN_DRAFT) == []

    def test_deterministic_codepoint_order(self, store):
        for doc_id in ("b2", "a10", "a2", "Z1"):  # non-sorted insertion order
            store.write(KIND_RUN_TEMPLATE, {"id": doc_id}, doc_id=doc_id)
        listing = store.list(KIND_RUN_TEMPLATE)
        assert [doc_id for doc_id, _ in listing] == ["Z1", "a10", "a2", "b2"]
        for doc_id, doc in listing:
            assert doc["kind"] == "run_template"
            assert doc["body"] == {"id": doc_id}
        # Byte-stable across repeated calls.
        assert json.dumps(listing, sort_keys=True) == json.dumps(
            store.list(KIND_RUN_TEMPLATE), sort_keys=True
        )

    def test_foreign_and_corrupt_files_omitted(self, store, tmp_path):
        store.write(KIND_RUN_DRAFT, {"v": 1}, doc_id="good")
        d = tmp_path / "gui_store" / "run_drafts"
        (d / "notes.txt").write_text("not a doc")
        (d / "bad.json").write_text("{ this is not json")
        (d / "noenvelope.json").write_text('{"no": "revision"}')
        assert [doc_id for doc_id, _ in store.list(KIND_RUN_DRAFT)] == ["good"]

    def test_singleton_kind_not_listable(self, store):
        with pytest.raises(ValueError):
            store.list(KIND_PROJECT_CONFIG)


# ── ID / kind validation ────────────────────────────────────────────────────


class TestValidation:
    @pytest.mark.parametrize(
        "doc_id",
        ["../evil", "a/b", "a\\b", "", ".", "..", ".hidden", "a.json",
         "sp ace", "x" * 65, None],
    )
    def test_bad_ids_rejected(self, store, doc_id):
        with pytest.raises(ValueError):
            store.write(KIND_RUN_TEMPLATE, {}, doc_id=doc_id)

    def test_traversal_never_escapes_root(self, store, tmp_path):
        with pytest.raises(ValueError):
            store.read(KIND_RUN_DRAFT, "../../checkpoints/run1")
        assert list(tmp_path.iterdir()) == []  # nothing was created anywhere

    def test_singleton_rejects_doc_id(self, store):
        with pytest.raises(ValueError):
            store.write(KIND_PROJECT_CONFIG, {}, doc_id="x")

    def test_unknown_kind_rejected(self, store):
        with pytest.raises(ValueError):
            store.write("mystery_kind", {}, doc_id="x")


# ── workspace-root resolution ───────────────────────────────────────────────


class TestFromEnv:
    def test_checkpoint_dir_env_wins(self, tmp_path, monkeypatch):
        ckpt = tmp_path / "checkpoints" / "20260723-run1"
        ckpt.mkdir(parents=True)
        monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(ckpt))
        store = GuiStore.from_env()
        assert store.root == tmp_path / "gui_store"  # sibling of checkpoints/
        store.write(KIND_PROJECT_CONFIG, {"v": 1})
        assert (tmp_path / "gui_store" / "project_config.json").is_file()
        # Checkpoint tree untouched (GUI-only layer, ADR-12).
        assert list(ckpt.iterdir()) == []


# ── corrupt documents ───────────────────────────────────────────────────────


class TestCorruptDocument:
    def _corrupt(self, tmp_path):
        gui = tmp_path / "gui_store"
        gui.mkdir()
        (gui / "project_config.json").write_text("{ not json")

    def test_read_raises(self, store, tmp_path):
        self._corrupt(tmp_path)
        with pytest.raises(CorruptDocument):
            store.read(KIND_PROJECT_CONFIG)

    def test_guarded_write_raises_unconditional_repairs(self, store, tmp_path):
        self._corrupt(tmp_path)
        with pytest.raises(CorruptDocument):
            store.write(KIND_PROJECT_CONFIG, {"v": 1}, expected_revision=1)
        assert store.write(KIND_PROJECT_CONFIG, {"v": 1}) == 1  # repair path
        doc, revision = store.read(KIND_PROJECT_CONFIG)
        assert (doc["body"], revision) == ({"v": 1}, 1)
