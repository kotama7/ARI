"""Tests for ari-skill-evaluator."""
import json, sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.server import (
    _parse_success_metrics,
    _parse_metric_keyword,
    _parse_min_expected,
    _build_scoring_guide,
)

EXPERIMENT = """
<!-- min_expected_metric: 50000 -->
<!-- metric_keyword: MFLOPS -->

## Success Metrics
- MFLOPS_serial: baseline
- MFLOPS_openmp: parallel peak
- speedup: ratio
- parallel_efficiency: efficiency

## Other Section
"""

def test_parse_metrics():
    m = _parse_success_metrics(EXPERIMENT)
    assert "MFLOPS_serial" in m
    assert "speedup" in m

def test_parse_keyword():
    assert _parse_metric_keyword(EXPERIMENT) == "MFLOPS"

def test_parse_min():
    assert _parse_min_expected(EXPERIMENT) == 50000.0

def test_scoring_guide():
    metrics = ["MFLOPS_serial", "MFLOPS_openmp"]
    guide = _build_scoring_guide(metrics, "MFLOPS", 50000)
    assert "50000" in guide
    assert "MFLOPS" in guide
    assert "MFLOPS_serial" in guide

def test_empty_experiment():
    assert _parse_success_metrics("") == []
    assert _parse_metric_keyword("") is None
    assert _parse_min_expected("") is None

def test_scoring_guide_fallback():
    guide = _build_scoring_guide([], None, None)
    assert "metric" in guide
