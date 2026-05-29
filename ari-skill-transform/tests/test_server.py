import asyncio, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from server import nodes_to_science_data, _robust_extract_json, _default_llm_model

SAMPLE = [
    {'has_real_data': True, 'metrics': {'score': 277573.1}, 'memory': ['config_optimized threads=64'], 'label': 'improve', 'depth': 2, 'node_id': 'abc123', 'id': 'abc123'},
    {'has_real_data': True, 'metrics': {'score': 64662.0}, 'memory': ['config_baseline threads=1'], 'label': 'draft', 'depth': 0, 'node_id': 'xyz', 'id': 'xyz'},
    {'has_real_data': False, 'metrics': {}, 'memory': [], 'label': 'draft', 'depth': 1, 'node_id': 'nnn', 'id': 'nnn'},
]

def _run(coro):
    return asyncio.run(coro)

def test_basic():
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = _run(nodes_to_science_data(f.name))
    assert len(r['configurations']) == 2

def test_strips_internal_fields():
    # ``label`` is intentionally retained (downstream paper writing /
    # reproducibility-check stages associate metrics with the experiment
    # that produced them via the label). Only orchestrator scaffolding —
    # depth, node_id, status — must be stripped.
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = _run(nodes_to_science_data(f.name))
    for cfg in r['configurations']:
        assert 'depth' not in cfg
        assert 'node_id' not in cfg
        assert 'status' not in cfg

def test_empty_nodes_excluded():
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = _run(nodes_to_science_data(f.name))
    assert r['summary_stats']['count'] == 2

def test_sort_order():
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = _run(nodes_to_science_data(f.name))
    assert r['configurations'][0]['metrics']['score'] > r['configurations'][1]['metrics']['score']


def test_summary_stats_omits_naive_best_when_primary_metric_absent():
    # The old behaviour took max() over every per_key_summary entry, which
    # picked input parameters like nnz over real measurements. Without a
    # declared primary_metric the new behaviour must omit the scalar best
    # entirely rather than fabricate one.
    sample = [
        {'has_real_data': True,
         'metrics': {'GFlops_per_s': 26.8, 'nnz': 3840000, 'M': 120000},
         'label': 'draft', 'depth': 0, 'id': 'n1'},
    ]
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(sample, f); f.flush()
        r = _run(nodes_to_science_data(f.name))
    assert 'best' not in r['summary_stats'], r['summary_stats']
    assert 'primary_metric_best' not in r['summary_stats'], r['summary_stats']


def test_summary_stats_uses_primary_metric_with_direction():
    # higher_is_better=True picks max over the primary metric, ignoring
    # other keys (notably nnz=3.84M which used to dominate the old max()).
    sample = [
        {'has_real_data': True,
         'metrics': {'GFlops_per_s': 26.8, 'time_s': 0.0046, 'nnz': 3840000},
         'label': 'draft', 'depth': 0, 'id': 'n1'},
        {'has_real_data': True,
         'metrics': {'GFlops_per_s': 22.3, 'time_s': 0.0089, 'nnz': 3840000},
         'label': 'improve', 'depth': 1, 'id': 'n2'},
    ]
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(sample, f); f.flush()
        r = _run(nodes_to_science_data(
            f.name, primary_metric='GFlops_per_s', higher_is_better='true'
        ))
    ss = r['summary_stats']
    assert ss['primary_metric'] == 'GFlops_per_s'
    assert ss['direction'] == 'higher_is_better'
    assert ss['primary_metric_best'] == 26.8
    assert ss['primary_metric_n'] == 2

    # lower_is_better picks min — important for time_s style metrics.
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(sample, f); f.flush()
        r = _run(nodes_to_science_data(
            f.name, primary_metric='time_s', higher_is_better='false'
        ))
    assert r['summary_stats']['direction'] == 'lower_is_better'
    assert r['summary_stats']['primary_metric_best'] == 0.0046


# ── _robust_extract_json: malformed-output tolerance ──────────────────

def test_extract_strips_code_fences():
    assert _robust_extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_strips_think_tag():
    raw = '<think>plan</think>\n{"a": 1}'
    assert _robust_extract_json(raw) == {"a": 1}


def test_extract_picks_largest_balanced_object():
    # The legacy greedy `\\{.*\\}` would have grabbed both braces and the
    # prose between them, failing to parse. The matched-brace walker must
    # extract the larger valid object on its own.
    raw = '{"first": 1} \n\nNote: also: {"second": {"nested": "ok"}}'
    out = _robust_extract_json(raw)
    assert out == {"second": {"nested": "ok"}}


def test_extract_raises_on_unrecoverable():
    import pytest
    with pytest.raises(ValueError):
        _robust_extract_json('no json here at all')


# ── results.json (D: emit_results contract) integration ────────────────


def test_results_json_populates_parameters_and_filters_per_key_summary():
    # Simulate a checkpoint layout:
    #   {tmp}/checkpoints/{run_id}/tree.json
    #   {tmp}/experiments/{run_id}/{node_id}/results.json
    # `nodes_to_science_data` should pick up results.json, set parameters
    # from results.params, and EXCLUDE those keys from per_key_summary so
    # input sizes (nnz, M, K) can never dominate the best-of reduction.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_id = "20260505_test_run"
        ck = root / "checkpoints" / run_id
        ck.mkdir(parents=True)
        wd = root / "experiments" / run_id / "node_a"
        wd.mkdir(parents=True)

        sample = [
            {'has_real_data': True, 'id': 'node_a',
             'metrics': {'GFlops_per_s': 26.8, 'nnz': 3840000, 'M': 120000},
             'label': 'draft', 'depth': 0},
            {'has_real_data': True, 'id': 'node_b',
             'metrics': {'GFlops_per_s': 22.3, 'nnz': 3840000, 'M': 120000},
             'label': 'improve', 'depth': 1},
        ]
        tree = ck / "tree.json"
        tree.write_text(json.dumps(sample))

        # Only node_a emits a typed results.json — node_b is "legacy" with
        # no results.json so its metrics dict is treated as-is.
        (wd / "results.json").write_text(json.dumps({
            "schema_version": "1.0",
            "params": {"M": 120000, "nnz": 3840000},
            "measurements": {"GFlops_per_s": 26.8},
            "predictions": {},
            "scores": {},
        }))

        r = _run(nodes_to_science_data(
            str(tree),
            primary_metric='GFlops_per_s', higher_is_better='true',
        ))

        # node_a: parameters populated from results.params
        cfg_a = next(c for c in r['configurations'] if c['label'] == 'draft')
        assert cfg_a['parameters'] == {"M": 120000, "nnz": 3840000}
        assert cfg_a['measurements'] == {"GFlops_per_s": 26.8}
        # node_b: no results.json → parameters stays empty (legacy path)
        cfg_b = next(c for c in r['configurations'] if c['label'] == 'improve')
        assert cfg_b['parameters'] == {}

        # per_key_summary must exclude the declared input params (nnz, M).
        # GFlops_per_s remains because it is not in any node's params set.
        assert 'GFlops_per_s' in r['per_key_summary']
        assert 'nnz' not in r['per_key_summary']
        assert 'M' not in r['per_key_summary']

        # summary_stats.primary_metric_best is computed only over GFlops_per_s
        # → 26.8 (max of 26.8, 22.3), never the 3,840,000 input size.
        assert r['summary_stats']['primary_metric_best'] == 26.8


def test_llm_evaluator_typed_split_populates_parameters_when_no_results_json():
    # When results.json (D path) is absent but the LLM evaluator emitted
    # the typed _params_dict / _measurements_dict (C path), nodes_to_
    # science_data must still populate configurations[*].parameters and
    # exclude the param keys from per_key_summary.
    sample = [
        {'has_real_data': True, 'id': 'node_a',
         'metrics': {
             'GFlops_per_s': 26.8, 'nnz': 3840000, 'M': 120000,
             '_params_dict': {'M': 120000, 'nnz': 3840000},
             '_measurements_dict': {'GFlops_per_s': 26.8},
             '_scientific_score': 0.4,
         },
         'label': 'draft', 'depth': 0},
    ]
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(sample, f); f.flush()
        r = _run(nodes_to_science_data(
            f.name, primary_metric='GFlops_per_s', higher_is_better='true',
        ))
    cfg = r['configurations'][0]
    assert cfg['parameters'] == {'M': 120000, 'nnz': 3840000}
    assert cfg['measurements'] == {'GFlops_per_s': 26.8}
    assert cfg.get('_typed_source') == 'llm_evaluator'
    # Reserved underscore keys + declared params must be excluded from
    # per_key_summary so primary_metric_best can never pick them up.
    assert 'nnz' not in r['per_key_summary']
    assert 'M' not in r['per_key_summary']
    assert '_params_dict' not in r['per_key_summary']
    assert '_scientific_score' not in r['per_key_summary']
    assert 'GFlops_per_s' in r['per_key_summary']
    # typed_split_coverage tracks adoption of the emit_results contract.
    assert r['summary_stats']['typed_split_coverage']['llm_evaluator'] == 1
    assert r['summary_stats']['typed_split_coverage']['results.json'] == 0
    assert r['summary_stats']['typed_split_coverage']['none'] == 0


def test_typed_split_coverage_legacy_run_reports_none():
    # A run with no typed split anywhere should still surface coverage
    # stats, with everything in the "none" bucket. This lets dashboards
    # show "0/N nodes adopted the contract" rather than failing silently.
    sample = [
        {'has_real_data': True, 'id': 'na',
         'metrics': {'GFlops_per_s': 26.8},
         'label': 'draft', 'depth': 0},
    ]
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(sample, f); f.flush()
        r = _run(nodes_to_science_data(f.name))
    cov = r['summary_stats']['typed_split_coverage']
    assert cov['none'] == 1
    assert cov['results.json'] == 0
    assert cov['llm_evaluator'] == 0


# ── _default_llm_model: backend-aware fallback ──────────────────────────────
# Why: when ARI_BACKEND=cli-shim, the litellm injector auto-fills api_base
# with the shim's URL for every call (see ari/cost_tracker.py). The historical
# default "gpt-4o-mini" is then rejected by the shim with
# "unknown model 'gpt-4o-mini'; expected one of claude-cli, ...", surfacing as
# experiment_context.error in science_data.json. The fallback must line up
# with what the shim actually serves.

def test_default_llm_model_openai_when_no_backend(monkeypatch):
    monkeypatch.delenv('ARI_BACKEND', raising=False)
    assert _default_llm_model() == 'gpt-4o-mini'


def test_default_llm_model_falls_back_to_claude_cli_when_shim(monkeypatch):
    monkeypatch.setenv('ARI_BACKEND', 'cli-shim')
    assert _default_llm_model() == 'claude-cli'


def test_default_llm_model_tolerates_cli_shim_underscore_variant(monkeypatch):
    # ari.cost_tracker accepts both spellings ("cli-shim" / "cli_shim"); mirror that.
    monkeypatch.setenv('ARI_BACKEND', 'cli_shim')
    assert _default_llm_model() == 'claude-cli'


def test_default_llm_model_case_insensitive(monkeypatch):
    monkeypatch.setenv('ARI_BACKEND', 'CLI-SHIM')
    assert _default_llm_model() == 'claude-cli'


def test_default_llm_model_other_backends_untouched(monkeypatch):
    # openai / anthropic / ollama keep the OpenAI-name default — those callers
    # have working litellm routes for gpt-4o-mini (or override via LLM_MODEL).
    for b in ('openai', 'anthropic', 'ollama', ''):
        monkeypatch.setenv('ARI_BACKEND', b)
        assert _default_llm_model() == 'gpt-4o-mini'


def test_explicit_llm_model_overrides_default(monkeypatch):
    # nodes_to_science_data(llm_model="...") must win over the backend-aware
    # fallback so workflow.yaml / callers can still pin a specific model.
    monkeypatch.setenv('ARI_BACKEND', 'cli-shim')
    monkeypatch.delenv('LLM_MODEL', raising=False)
    # Spy on litellm.acompletion to capture the model that actually reaches it.
    import server as _srv
    captured: dict = {}

    class _FakeMsg:
        content = '{"experiment_context": {"hardware": "test"}}'

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        choices = [_FakeChoice()]

    async def _fake_acompletion(**kw):
        captured.update(kw)
        return _FakeResp()

    monkeypatch.setattr(_srv.litellm, 'acompletion', _fake_acompletion)
    sample = [{'has_real_data': True, 'metrics': {'x': 1.0},
               'label': 'draft', 'depth': 0, 'id': 'n1'}]
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(sample, f); f.flush()
        _run(nodes_to_science_data(f.name, llm_model='gpt-4o'))
    assert captured.get('model') == 'gpt-4o'


def test_env_llm_model_overrides_default(monkeypatch):
    # LLM_MODEL env precedes the backend-aware fallback.
    monkeypatch.setenv('ARI_BACKEND', 'cli-shim')
    monkeypatch.setenv('LLM_MODEL', 'custom-name')
    import server as _srv
    captured: dict = {}

    class _FakeMsg:
        content = '{"experiment_context": {}}'

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        choices = [_FakeChoice()]

    async def _fake_acompletion(**kw):
        captured.update(kw)
        return _FakeResp()

    monkeypatch.setattr(_srv.litellm, 'acompletion', _fake_acompletion)
    sample = [{'has_real_data': True, 'metrics': {'x': 1.0},
               'label': 'draft', 'depth': 0, 'id': 'n1'}]
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(sample, f); f.flush()
        _run(nodes_to_science_data(f.name))
    assert captured.get('model') == 'custom-name'


def test_shim_backend_actually_routes_to_claude_cli(monkeypatch):
    # End-to-end: with ARI_BACKEND=cli-shim and no explicit args, the model
    # that reaches litellm.acompletion is "claude-cli", NOT "gpt-4o-mini".
    # This is the regression guard for the 2026-05-28 incident where
    # workflow.yaml's transform_data stage produced LLM analysis failed:
    # unknown model 'gpt-4o-mini'.
    monkeypatch.setenv('ARI_BACKEND', 'cli-shim')
    monkeypatch.delenv('LLM_MODEL', raising=False)
    import server as _srv
    captured: dict = {}

    class _FakeMsg:
        content = '{"experiment_context": {}}'

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        choices = [_FakeChoice()]

    async def _fake_acompletion(**kw):
        captured.update(kw)
        return _FakeResp()

    monkeypatch.setattr(_srv.litellm, 'acompletion', _fake_acompletion)
    sample = [{'has_real_data': True, 'metrics': {'x': 1.0},
               'label': 'draft', 'depth': 0, 'id': 'n1'}]
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(sample, f); f.flush()
        _run(nodes_to_science_data(f.name))
    assert captured.get('model') == 'claude-cli'
