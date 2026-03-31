import asyncio, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from server import nodes_to_science_data

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
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = _run(nodes_to_science_data(f.name))
    for cfg in r['configurations']:
        assert 'label' not in cfg
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
