import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from server import nodes_to_science_data

SAMPLE = [
    {'has_real_data': True, 'metrics': {'MFLOPS': 277573.1}, 'memory': ['-O3 -ffast-math OMP_NUM_THREADS=64'], 'label': 'improve', 'depth': 2, 'node_id': 'abc123'},
    {'has_real_data': True, 'metrics': {'MFLOPS': 64662.0}, 'memory': ['-O2 OMP_NUM_THREADS=1'], 'label': 'draft', 'depth': 0, 'node_id': 'xyz'},
    {'has_real_data': False, 'metrics': {}, 'memory': [], 'label': 'draft', 'depth': 1, 'node_id': 'nnn'},
]

def test_basic():
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = nodes_to_science_data(f.name)
    assert len(r['configurations']) == 2
    assert r['metric_name'] == 'MFLOPS'

def test_strips_internal_fields():
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = nodes_to_science_data(f.name)
    for cfg in r['configurations']:
        assert 'label' not in cfg
        assert 'depth' not in cfg
        assert 'node_id' not in cfg
        assert 'status' not in cfg

def test_empty_nodes_excluded():
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = nodes_to_science_data(f.name)
    assert r['summary_stats']['count'] == 2

def test_sort_order():
    with tempfile.NamedTemporaryFile(suffix='.json', mode='w') as f:
        json.dump(SAMPLE, f); f.flush()
        r = nodes_to_science_data(f.name)
    assert r['configurations'][0]['metrics']['MFLOPS'] > r['configurations'][1]['metrics']['MFLOPS']
