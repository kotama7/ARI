"""GUI refresh Wave 0 / G0: FROZEN LEGACY Settings API contract.

This module freezes the CURRENT (legacy) behavior of the viz Settings
handlers (``ari/viz/api_settings.py``: ``_api_get_settings`` /
``_api_save_settings``) as golden, per the G0 contract-freeze gate of
``/home/t-kotama/workplace/ARI/docs/plans/gui_refresh/05_configuration_control_plane.md``.

The point is to pin behavior — INCLUDING known quirks/defects — so later
refactors cannot silently drift:

  * GET returns exactly 27 top-level keys ({26 scalar/list} + nested ``ors``
    with exactly 10 sub-keys).
  * GET merge is a shallow ``{**defaults, **saved}`` — unknown saved keys
    survive, known saved keys override.
  * POST is a whole-file replace of settings.json (keys absent from the body
    are erased).
  * ``api_key`` / ``llm_api_key`` are popped and never persisted; a
    plausible key (len>=20, no "test" substring) with a mapped provider
    (openai/anthropic/gemini) is upserted UNQUOTED into the project .env;
    short keys, "test"-containing keys, and unmapped providers (e.g.
    ollama) are SILENTLY dropped.
  * ``letta_api_key`` IS persisted verbatim into settings.json — a frozen
    DEFECT, deliberately not fixed here.
  * POST with no active checkpoint is refused with the exact legacy error
    payload (``_status`` 400) — but the .env api-key upsert still happens
    BEFORE that refusal (another frozen quirk).
  * The frontend Save posts exactly the 24-key flat object pinned in
    ``ari/viz/frontend/src/components/Settings/__tests__/SettingsContract.test.tsx``;
    the backend accepts it and persists exactly those keys minus the popped
    secret key.

Deterministic: no network, no subprocess, no HTTP server — handlers are
called directly with a tmp_path active checkpoint, and all mutated global
state (``ari.viz.state``) is restored on teardown.

DO NOT "fix" any behavior asserted here as part of a refactor. Changing any
of it is a Wave>0 decision that must update this file and the plan doc
together.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ari.viz import api_settings
from ari.viz import state as _st

# ───────────────────────────────────────────────────────────────────────────
# Frozen key inventories (G0 golden lists — assert literally, never derive)
# ───────────────────────────────────────────────────────────────────────────

# GET /api/settings: exactly these 27 top-level keys (sorted).
EXPECTED_TOP_LEVEL_KEYS = [
    "container_image",
    "container_mode",
    "container_pull",
    "letta_api_key",
    "letta_base_url",
    "letta_deployment",
    "letta_deployment_image",
    "letta_deployment_venv",
    "letta_embedding_config",
    "llm_api_key",
    "llm_model",
    "llm_provider",
    "mcp_skills",
    "ollama_host",
    "ors",
    "retrieval_backend",
    "semantic_scholar_key",
    "slurm_cpus",
    "slurm_gpus",
    "slurm_memory_gb",
    "slurm_partition",
    "slurm_walltime",
    "temperature",
    "vlm_review_enabled",
    "vlm_review_max_iter",
    "vlm_review_model",
    "vlm_review_threshold",
]

# Nested "ors" object: exactly these 10 sub-keys (sorted).
EXPECTED_ORS_KEYS = [
    "judge_model",
    "judge_n_runs",
    "phase1_max_runtime_sec",
    "phase1_sandbox_kind",
    "replicator_model",
    "rubric_audit_model",
    "rubric_gen_model",
    "rubric_gen_target_leaves",
    "rubric_gen_temperature",
    "rubric_gen_two_stage",
]

# The exact 24-key flat object the frontend Save button POSTs — mirrored
# verbatim from EXPECTED_KEYS in
# ari/viz/frontend/src/components/Settings/__tests__/SettingsContract.test.tsx
# (already sorted there via .sort()).
FRONTEND_POST_KEYS_24 = sorted([
    "llm_model", "llm_backend", "llm_base_url", "temperature", "llm_api_key",
    "semantic_scholar_key", "retrieval_backend", "ssh_host", "ssh_port",
    "ssh_user", "ssh_path", "ssh_key", "slurm_partitions", "slurm_partition",
    "slurm_cpus", "slurm_memory_gb", "slurm_walltime", "container_mode",
    "container_image", "container_pull", "vlm_review_model", "letta_base_url",
    "letta_api_key", "letta_embedding_config",
])

_FRONTEND_CONTRACT_TSX = (
    Path(__file__).parent.parent
    / "ari/viz/frontend/src/components/Settings/__tests__/SettingsContract.test.tsx"
)

# Environment variables _api_get_settings consults — cleared for determinism
# so the frozen defaults (not the developer's shell) are what gets asserted.
_SETTINGS_ENV_VARS = (
    "ARI_LLM_MODEL",
    "ARI_BACKEND",
    "OLLAMA_HOST",
    "ARI_RETRIEVAL_BACKEND",
    "LETTA_BASE_URL",
    "LETTA_EMBEDDING_CONFIG",
    "ARI_MODEL_REPLICATE",
    "ARI_MODEL_RUBRIC_GEN",
    "ARI_MODEL_RUBRIC_AUDIT",
    "ARI_MODEL_JUDGE",
    "ARI_PHASE1_SANDBOX",
    # _upsert_env_key sets these live in os.environ on the save path.
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
)


# ───────────────────────────────────────────────────────────────────────────
# Fixtures — direct handler calls; global viz state always restored
# ───────────────────────────────────────────────────────────────────────────

@pytest.fixture
def _clean_env(monkeypatch):
    for var in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def active_checkpoint(tmp_path, monkeypatch, _clean_env):
    """tmp_path as the active checkpoint; prior global state restored.

    Also redirects the module-global .env write target so api-key upserts
    never touch the real project .env.
    """
    prev_ckpt = _st._checkpoint_dir
    prev_settings = _st._settings_path
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env", raising=False)
    _st.set_active_checkpoint(tmp_path)
    try:
        yield tmp_path
    finally:
        _st._checkpoint_dir = prev_ckpt
        _st._settings_path = prev_settings


@pytest.fixture
def no_checkpoint(tmp_path, monkeypatch, _clean_env):
    """Detached state (no active project); prior global state restored."""
    prev_ckpt = _st._checkpoint_dir
    prev_settings = _st._settings_path
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env", raising=False)
    _st.set_active_checkpoint(None)
    try:
        yield tmp_path
    finally:
        _st._checkpoint_dir = prev_ckpt
        _st._settings_path = prev_settings


def _post(body: dict) -> dict:
    return api_settings._api_save_settings(json.dumps(body).encode())


# ═══════════════════════════════════════════════════════════════════════════
# 1. GET default payload — exactly 27 top-level keys / 10 ors sub-keys
# ═══════════════════════════════════════════════════════════════════════════

class TestGetDefaultsShape:
    def test_default_payload_has_exactly_27_top_level_keys(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        GET /api/settings on a fresh checkpoint (no settings.json) returns
        exactly the 27 top-level default keys — asserted as a literal
        sorted list, so any key added/removed/renamed fails loudly."""
        out = api_settings._api_get_settings()
        assert sorted(out.keys()) == EXPECTED_TOP_LEVEL_KEYS
        assert len(out) == 27

    def test_ors_nested_object_has_exactly_10_keys(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        the nested 'ors' default object carries exactly 10 sub-keys."""
        out = api_settings._api_get_settings()
        assert sorted(out["ors"].keys()) == EXPECTED_ORS_KEYS
        assert len(out["ors"]) == 10

    def test_frozen_default_values(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        the env-independent default VALUES are pinned too — types and
        magic literals the GUI currently renders. llm_provider/llm_model
        fall back to workflow.yaml (config, not code) so only their
        string-ness is asserted."""
        out = api_settings._api_get_settings()
        assert out["llm_api_key"] == ""
        assert out["ollama_host"] == "http://localhost:11434"
        assert out["temperature"] == 1.0
        assert out["semantic_scholar_key"] == ""
        assert out["retrieval_backend"] == "semantic_scholar"
        assert out["slurm_partition"] == ""
        assert out["slurm_cpus"] is None
        assert out["slurm_memory_gb"] is None
        assert out["slurm_gpus"] == 0
        assert out["slurm_walltime"] == "04:00:00"
        assert out["mcp_skills"] == []
        assert out["container_mode"] == "auto"
        assert out["container_image"] == ""
        assert out["container_pull"] == "on_start"
        assert out["vlm_review_enabled"] is True
        assert out["vlm_review_model"] == "openai/gpt-4o"
        assert out["vlm_review_max_iter"] == 3
        assert out["vlm_review_threshold"] == 0.7
        assert out["letta_deployment"] == "auto"
        assert out["letta_deployment_image"] == ""
        assert out["letta_deployment_venv"] == ""
        assert out["letta_base_url"] == "http://localhost:8283"
        assert out["letta_api_key"] == ""
        assert out["letta_embedding_config"] == "letta-default"
        assert isinstance(out["llm_provider"], str)
        assert isinstance(out["llm_model"], str)
        ors = out["ors"]
        assert ors["replicator_model"] == "claude-opus-4-7"
        assert ors["rubric_gen_model"] == "gemini-2.5-pro"
        assert ors["rubric_audit_model"] == "claude-opus-4-7"
        assert ors["judge_model"] == "gpt-4o-2024-11-20"
        assert ors["rubric_gen_temperature"] == 0.0
        assert ors["rubric_gen_target_leaves"] == 0
        assert ors["rubric_gen_two_stage"] is True
        assert ors["judge_n_runs"] == 3
        assert ors["phase1_max_runtime_sec"] == 21600
        assert ors["phase1_sandbox_kind"] == "auto"

    def test_no_checkpoint_get_returns_same_27_defaults(self, no_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        with NO active checkpoint, GET does not fail — it returns the same
        27-key built-in defaults (reads fall back, only writes refuse)."""
        out = api_settings._api_get_settings()
        assert sorted(out.keys()) == EXPECTED_TOP_LEVEL_KEYS


# ═══════════════════════════════════════════════════════════════════════════
# 2. GET merge semantics — shallow {**defaults, **saved}
# ═══════════════════════════════════════════════════════════════════════════

class TestGetMergeSemantics:
    def test_unknown_saved_key_survives_merge(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        GET merges shallowly as {**defaults, **saved}: a key present in
        settings.json but unknown to the defaults dict is passed through
        to the client verbatim (no schema filtering)."""
        (active_checkpoint / "settings.json").write_text(
            json.dumps({"legacy_unknown_key": "survives", "temperature": 0.25})
        )
        out = api_settings._api_get_settings()
        assert out["legacy_unknown_key"] == "survives"
        # 27 defaults + 1 unknown passthrough
        assert len(out) == 28
        assert sorted(out.keys()) == sorted(
            EXPECTED_TOP_LEVEL_KEYS + ["legacy_unknown_key"]
        )

    def test_saved_known_key_overrides_default(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        a saved known key wins over the built-in default; untouched
        defaults remain visible alongside it."""
        (active_checkpoint / "settings.json").write_text(
            json.dumps({"temperature": 0.25, "slurm_partition": "gpu"})
        )
        out = api_settings._api_get_settings()
        assert out["temperature"] == 0.25
        assert out["slurm_partition"] == "gpu"
        # a default the file did not touch is still served
        assert out["slurm_walltime"] == "04:00:00"

    def test_merge_is_shallow_for_ors(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        the merge is SHALLOW — a saved partial 'ors' object REPLACES the
        whole 10-key default 'ors' (no deep merge). This is a quirk the
        GUI currently depends on defaults-resent-on-save to paper over."""
        (active_checkpoint / "settings.json").write_text(
            json.dumps({"ors": {"judge_n_runs": 5}})
        )
        out = api_settings._api_get_settings()
        assert out["ors"] == {"judge_n_runs": 5}  # other 9 sub-keys GONE


# ═══════════════════════════════════════════════════════════════════════════
# 3. POST whole-file replace
# ═══════════════════════════════════════════════════════════════════════════

class TestPostWholeFileReplace:
    def test_post_erases_keys_absent_from_body(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        POST /api/settings replaces settings.json wholesale — keys that
        were present on disk but absent from the body are ERASED (there
        is no read-modify-write)."""
        sp = active_checkpoint / "settings.json"
        sp.write_text(json.dumps({"stale_key": 1, "temperature": 0.5}))
        out = _post({"llm_model": "model-x"})
        assert out == {"ok": True}
        saved = json.loads(sp.read_text())
        assert saved == {"llm_model": "model-x"}  # stale_key + temperature gone


# ═══════════════════════════════════════════════════════════════════════════
# 4. POST api-key handling (pop / .env upsert / silent drops / letta defect)
# ═══════════════════════════════════════════════════════════════════════════

class TestPostApiKeyHandling:
    def test_api_key_and_llm_api_key_never_persisted(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        'api_key' and 'llm_api_key' are popped from the body and NEVER
        written to settings.json."""
        out = _post({
            "llm_provider": "openai",
            "api_key": "sk-live-aaaaaaaaaaaaaaaaaaaa",
            "llm_api_key": "sk-live-bbbbbbbbbbbbbbbbbbbb",
            "llm_model": "model-x",
        })
        assert out == {"ok": True}
        saved = json.loads((active_checkpoint / "settings.json").read_text())
        assert "api_key" not in saved
        assert "llm_api_key" not in saved
        assert sorted(saved.keys()) == ["llm_model", "llm_provider"]

    def test_valid_openai_key_upserted_into_env_unquoted(
        self, active_checkpoint,
    ):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        a plausible key (len>=20, no 'test' substring) with provider
        'openai' is routed into the project .env as OPENAI_API_KEY in the
        UNQUOTED KEY=value form, and exported live into os.environ."""
        import os
        key = "sk-live-aaaaaaaaaaaaaaaaaaaa"  # 28 chars, no "test"
        out = _post({"llm_provider": "openai", "api_key": key})
        assert out == {"ok": True}
        env_text = (active_checkpoint / ".env").read_text()
        assert f"OPENAI_API_KEY={key}" in env_text
        assert 'OPENAI_API_KEY="' not in env_text  # unquoted form frozen
        assert os.environ.get("OPENAI_API_KEY") == key  # live export quirk

    def test_short_key_silently_dropped(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        a key shorter than 20 chars is SILENTLY dropped — no .env write,
        no error, save still reports ok."""
        out = _post({"llm_provider": "openai", "api_key": "sk-short"})
        assert out == {"ok": True}
        assert not (active_checkpoint / ".env").exists()

    def test_key_containing_test_silently_dropped(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        any key containing the substring 'test' is SILENTLY dropped even
        when len>=20 and the provider is mapped — a substring heuristic,
        frozen as-is."""
        out = _post({
            "llm_provider": "openai",
            "api_key": "sk-testtesttesttesttest-aaaa",  # 28 chars but "test"
        })
        assert out == {"ok": True}
        assert not (active_checkpoint / ".env").exists()

    def test_unmapped_provider_silently_dropped(self, active_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        providers outside {openai, anthropic, gemini} (e.g. 'ollama')
        have no env-var mapping — the key is SILENTLY dropped with no
        .env write and no error."""
        out = _post({
            "llm_provider": "ollama",
            "api_key": "sk-live-aaaaaaaaaaaaaaaaaaaa",
        })
        assert out == {"ok": True}
        assert not (active_checkpoint / ".env").exists()

    def test_letta_api_key_persisted_verbatim_frozen_defect(
        self, active_checkpoint,
    ):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        FROZEN DEFECT — 'letta_api_key' is NOT treated as a secret: it is
        persisted verbatim into plaintext settings.json (unlike
        api_key/llm_api_key which are popped). Do not fix in a refactor;
        fixing is a Wave>0 contract change."""
        out = _post({"letta_api_key": "letta-secret-value-123"})
        assert out == {"ok": True}
        saved = json.loads((active_checkpoint / "settings.json").read_text())
        assert saved["letta_api_key"] == "letta-secret-value-123"


# ═══════════════════════════════════════════════════════════════════════════
# 5. POST with no active checkpoint is refused
# ═══════════════════════════════════════════════════════════════════════════

class TestPostWithoutCheckpoint:
    def test_refused_with_exact_legacy_error_payload(self, no_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        with no active checkpoint there is nowhere to persist — the save
        is refused with this exact error payload and _status 400."""
        out = _post({"llm_model": "model-x"})
        assert out == {
            "ok": False,
            "error": (
                "No active project. Create or select a checkpoint "
                "before saving settings."
            ),
            "_status": 400,
        }

    def test_env_upsert_still_happens_before_refusal(self, no_checkpoint):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        QUIRK — the api-key .env upsert runs BEFORE the checkpoint check,
        so a refused save (400) still writes the key into .env and
        os.environ. Frozen as-is; reordering is a behavior change."""
        import os
        key = "sk-live-aaaaaaaaaaaaaaaaaaaa"
        out = _post({"llm_provider": "openai", "api_key": key})
        assert out["ok"] is False and out["_status"] == 400
        env_text = (no_checkpoint / ".env").read_text()
        assert f"OPENAI_API_KEY={key}" in env_text
        assert os.environ.get("OPENAI_API_KEY") == key


# ═══════════════════════════════════════════════════════════════════════════
# 6. The 24-key frontend POST fixture
# ═══════════════════════════════════════════════════════════════════════════

def _frontend_save_payload() -> dict:
    """A representative body carrying exactly the 24 frontend Save keys."""
    return {
        "llm_model": "gpt-4o-2024-11-20",
        "llm_backend": "openai",
        "llm_base_url": "",
        "temperature": 0.7,
        "llm_api_key": "sk-frontend-aaaaaaaaaaaaaaaa",  # >=20, no "test"
        "semantic_scholar_key": "",
        "retrieval_backend": "semantic_scholar",
        "ssh_host": "hpc.example.org",
        "ssh_port": 22,
        "ssh_user": "ari",
        "ssh_path": "/scratch/ari",
        "ssh_key": "~/.ssh/id_ed25519",
        "slurm_partitions": ["gpu", "cpu"],
        "slurm_partition": "gpu",
        "slurm_cpus": 8,
        "slurm_memory_gb": 64,
        "slurm_walltime": "04:00:00",
        "container_mode": "auto",
        "container_image": "",
        "container_pull": "on_start",
        "vlm_review_model": "openai/gpt-4o",
        "letta_base_url": "http://localhost:8283",
        "letta_api_key": "letta-frontend-secret",
        "letta_embedding_config": "letta-default",
    }


class TestFrontendSavePayload24Keys:
    def test_constant_matches_frontend_contract_tsx(self):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        FRONTEND_POST_KEYS_24 must stay byte-identical to EXPECTED_KEYS
        in SettingsContract.test.tsx — the two sides of the wire contract
        are pinned against each other."""
        src = _FRONTEND_CONTRACT_TSX.read_text()
        m = re.search(
            r"const EXPECTED_KEYS = \[(.*?)\]\.sort\(\)", src, re.DOTALL
        )
        assert m, "EXPECTED_KEYS literal not found in SettingsContract.test.tsx"
        tsx_keys = sorted(re.findall(r"'([^']+)'", m.group(1)))
        assert tsx_keys == FRONTEND_POST_KEYS_24
        assert len(tsx_keys) == 24

    def test_backend_accepts_24_key_body_and_persists_23(
        self, active_checkpoint,
    ):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        _api_save_settings accepts the exact 24-key frontend Save body and
        persists exactly those keys MINUS the popped secret 'llm_api_key'
        (23 keys), with 'letta_api_key' kept verbatim (frozen defect) and
        every other value round-tripped unchanged."""
        payload = _frontend_save_payload()
        assert sorted(payload.keys()) == FRONTEND_POST_KEYS_24  # fixture guard
        out = _post(payload)
        assert out == {"ok": True}
        saved = json.loads((active_checkpoint / "settings.json").read_text())
        expected_persisted = sorted(set(FRONTEND_POST_KEYS_24) - {"llm_api_key"})
        assert sorted(saved.keys()) == expected_persisted
        assert len(saved) == 23
        assert saved["letta_api_key"] == "letta-frontend-secret"  # defect kept
        for k in expected_persisted:
            assert saved[k] == payload[k]

    def test_llm_backend_is_provider_fallback_for_env_upsert(
        self, active_checkpoint,
    ):
        """FROZEN LEGACY contract (gui_refresh Wave 0 / G0, plan doc
        docs/plans/gui_refresh/05_configuration_control_plane.md):
        the frontend body has no 'llm_provider' — the env-upsert path
        falls back to 'llm_backend' ('openai' here), so the popped
        llm_api_key still lands in .env as OPENAI_API_KEY."""
        _post(_frontend_save_payload())
        env_text = (active_checkpoint / ".env").read_text()
        assert "OPENAI_API_KEY=sk-frontend-aaaaaaaaaaaaaaaa" in env_text
