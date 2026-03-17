import sys
import re
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'src'))
import pytest

SAMPLE_OUTPUT = "MFLOPS: 269200.07\nREPRO_EXIT_CODE:0\n"
SAMPLE_OUTPUT_2 = "Throughput: 12345.6 items/sec\nREPRO_EXIT_CODE:0\n"

def _extract_metric(actual_output, metric_name):
    _pat = (rf"{re.escape(metric_name)}[\s:]+([\d,]+(?:\.[\d]+)?)"
            rf"|([\d,]+(?:\.[\d]+)?)\s*{re.escape(metric_name)}")
    _raw = re.findall(_pat, actual_output, re.IGNORECASE)
    vals = [float((g1 or g2).replace(",","")) for g1,g2 in _raw if (g1 or g2)]
    return max(vals) if vals else None

def test_extract_mflops_colon():
    assert abs(_extract_metric(SAMPLE_OUTPUT, "MFLOPS") - 269200.07) < 1.0

def test_extract_mflops_space():
    assert abs(_extract_metric("269200.07 MFLOPS\n", "MFLOPS") - 269200.07) < 1.0

def test_extract_not_found():
    assert _extract_metric("random text\n", "MFLOPS") is None

def test_extract_custom_metric():
    assert abs(_extract_metric(SAMPLE_OUTPUT_2, "Throughput") - 12345.6) < 1.0

def test_verdict_within_tolerance():
    claimed, actual, tol = 277573.1, 269200.07, 5.0
    diff = abs(actual - claimed) / claimed * 100
    assert diff < tol  # 3.0% < 5.0%

def test_verdict_partial():
    claimed, actual, tol = 277573.1, 240000.0, 5.0
    diff = abs(actual - claimed) / claimed * 100
    verdict = "REPRODUCED" if diff <= tol else ("PARTIAL" if diff <= 20 else "NOT_REPRODUCED")
    assert verdict == "PARTIAL"
