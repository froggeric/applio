# tests/test_inference_progress.py
"""Pure-Python gate for inference-progress stats (no GUI, no AppKit).

Run: venv_macos/bin/python -m pytest tests/test_inference_progress.py -v

Imports ONLY from applio_inference_stats (AppKit-free). The launcher itself
imports AppKit at module top, so it is NOT headless-importable; that is exactly
why the stats math lives in applio_inference_stats.py.
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from applio_inference_stats import compute_inference_stats


def test_progress_pct_and_eta():
    r = {
        "total": 10,
        "processed": 4,
        "converted": 4,
        "skipped": 0,
        "started_at": 1000.0,
    }
    s = compute_inference_stats(r, now=1010.0)
    assert s["pct"] == 40.0 and s["elapsed"] == 10.0
    assert s["eta"] == 15.0  # (10-4)*(10/4)
    assert s["speed"] == 24.0  # 4/(10/60)


def test_zero_converted_no_divzero():
    r = {"total": 5, "processed": 0, "converted": 0, "skipped": 0, "started_at": 1000.0}
    s = compute_inference_stats(r, now=1003.0)
    assert s["eta"] == 0.0 and s["speed"] == 0.0 and s["pct"] == 0.0


def test_completed_uses_ended_at_eta_zero():
    r = {
        "total": 3,
        "processed": 3,
        "converted": 2,
        "skipped": 1,
        "started_at": 1000.0,
        "ended_at": 1010.0,
    }
    s = compute_inference_stats(r, now=9999.0)
    assert s["pct"] == 100.0 and s["eta"] == 0.0 and s["elapsed"] == 10.0


def test_zero_total():
    r = {"total": 0, "processed": 0, "converted": 0, "skipped": 0, "started_at": 1000.0}
    s = compute_inference_stats(r, now=1001.0)
    assert s["pct"] == 0.0 and s["eta"] == 0.0


def test_skip_semantics_eta_uses_converted_only():
    r = {
        "total": 10,
        "processed": 4,
        "converted": 2,
        "skipped": 2,
        "started_at": 1000.0,
    }
    s = compute_inference_stats(r, now=1010.0)
    assert s["pct"] == 40.0  # processed/total (skips count as processed)
    assert (
        s["eta"] == 30.0
    )  # (10-4) * (10/2) — avg from converted, remaining from processed
    assert s["speed"] == 12.0  # 2/(10/60)
