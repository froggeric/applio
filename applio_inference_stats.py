# applio_inference_stats.py - pure-Python inference-progress stats (no AppKit).
"""Inference-progress math for the Process Dashboard.

Kept AppKit-free so it is pytest-importable (the launcher imports AppKit at
module top and so cannot be imported in a headless test). The launcher imports
``compute_inference_stats`` from here; the test imports it directly.
"""


def compute_inference_stats(record, now):
    """Return {pct, elapsed, eta, speed} for an inference progress record.

    pct = processed/total*100. eta = remaining_files * avg_per_file (avg uses
    converted files only; skips don't cost convert time). speed = files/min.
    All divide-by-zeros guarded to 0.0. On a terminal record, ended_at drives
    elapsed (so `now` is ignored) and eta is 0 once processed >= total.
    """
    total = record.get("total", 0) or 0
    processed = record.get("processed", 0) or 0
    converted = record.get("converted", 0) or 0
    started = record.get("started_at") or now
    pct = (100.0 * processed / total) if total else 0.0
    elapsed = max(0.0, (record.get("ended_at") or now) - started)
    avg = (elapsed / converted) if converted else 0.0
    remaining = max(0, total - processed)
    eta = (remaining * avg) if converted else 0.0
    speed = (converted / (elapsed / 60.0)) if (elapsed > 0 and converted) else 0.0
    return {
        "pct": round(pct, 1),
        "elapsed": round(elapsed, 1),
        "eta": round(eta, 1),
        "speed": round(speed, 1),
    }
