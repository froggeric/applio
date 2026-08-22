# tests/test_inference_progress.py
"""Pure-Python gate for inference-progress stats + batch-toast injection.

Run: venv_macos/bin/python -m pytest tests/test_inference_progress.py -v

Imports ONLY from applio_inference_stats (AppKit-free). The launcher itself
imports AppKit at module top, so it is NOT headless-importable; that is exactly
why the stats math lives in applio_inference_stats.py.

The batch-toast tests run patches/patch_inference_progress.py against a temp
copy of the PRISTINE rvc/infer/infer.py (never the repo file) and assert on
the generated engine code.
"""

import importlib.util
import py_compile
import shutil
import sys, os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from applio_inference_stats import compute_inference_stats

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _patched_infer_source():
    """Run patch_infer_py on a temp copy of pristine rvc/infer/infer.py."""
    spec = importlib.util.spec_from_file_location(
        "patch_inference_progress",
        os.path.join(REPO, "patches", "patch_inference_progress.py"),
    )
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    src_path = os.path.join(REPO, "rvc", "infer", "infer.py")
    src = open(src_path, encoding="utf-8").read()
    assert "Inference Progress Tracking" not in src, (
        "rvc/infer/infer.py is dirty (patched?) - restore first"
    )
    with tempfile.TemporaryDirectory() as td:
        shutil.copy(src_path, os.path.join(td, "infer.py"))
        assert patcher.patch_infer_py(td), "patcher anchor missed (upstream drift?)"
        with open(os.path.join(td, "infer.py"), encoding="utf-8") as f:
            patched = f.read()
    # The generated engine code must at least be syntactically valid.
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(patched)
    try:
        py_compile.compile(tf.name, doraise=True)
    finally:
        os.unlink(tf.name)
    return patched


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


def test_batch_toast_calls_in_patched_engine():
    patched = _patched_infer_source()
    # Start toast: after the counters (+ milestone init), before the initial write.
    counters = patched.index("processed = converted = skipped = 0")
    milestone_init = patched.index("_next_milestone = 25")
    start_toast = patched.index(
        '_infer_toast(f"Batch conversion started: {total} files")'
    )
    initial_write = patched.index('"processed": 0, "converted": 0, "skipped": 0,')
    assert counters < milestone_init < start_toast < initial_write
    # Milestone toast: threshold-first-crossing guard at the loop tail (after
    # the per-file write). total>=8 keeps small batches spam-free; the
    # processed<total term suppresses the 100% milestone double-announcement.
    per_file_write = patched.index('"current_file": nxt,')
    guard = patched.index("and processed * 100 // total >= _next_milestone")
    assert per_file_write < guard
    assert "total >= 8" in patched and "and processed < total" in patched
    milestone_msg = 'f"{processed}/{total} files converted ({_next_milestone}%)"'
    assert milestone_msg in patched
    assert patched.index(milestone_msg) < patched.index("_next_milestone += 25")
    # Terminal toast: after the terminal write, before the history append.
    terminal_write = patched.index(
        '"ended_at": ended_at, "elapsed": elapsed, "error": None,'
    )
    terminal_toast = patched.index(
        'f"Batch conversion {status}: {converted} converted, {skipped} skipped in {elapsed:.0f}s"'
    )
    first_hist_call = patched.index("_infer_add_to_history({")
    assert terminal_write < terminal_toast < first_hist_call
    # Error site 1: the except handler, BEFORE the re-raise (variable is
    # _infer_exc — never e).
    exc_toast = patched.index(
        '_infer_toast("Batch conversion failed: " + str(_infer_exc))'
    )
    assert patched.index("except Exception as _infer_exc:") < exc_toast
    # Error site 2: the concurrent-run raise sits BEFORE the body's try, so the
    # except handler can never cover it — the toast must precede that raise.
    conc_toast = patched.index(
        "Batch conversion failed: another batch inference is already running."
        " Stop it first from the Process Dashboard."
    )
    conc_raise = patched.index("raise RuntimeError(")
    assert conc_toast < conc_raise
    assert "_infer_toast(" in patched  # helper is defined and used


def test_gradio_import_only_inside_toast_helper():
    patched = _patched_infer_source()
    gradio_lines = [ln for ln in patched.splitlines() if "import gradio" in ln]
    assert len(gradio_lines) == 1, (
        f"expected exactly 1 gradio import (lazy, inside _infer_toast), "
        f"got {gradio_lines}"
    )
    assert gradio_lines[0] == "        import gradio as gr"  # indented = function-local
    # ...and it lives inside the _infer_toast body (never at module top of the
    # generated engine code): after its def, before the class injection point.
    toast_def = patched.index("def _infer_toast(")
    gradio_imp = patched.index("import gradio as gr")
    class_idx = patched.index("class VoiceConverter:")
    assert toast_def < gradio_imp < class_idx
    assert patched[:toast_def].count("import gradio") == 0
    assert "gr.Info(msg)" in patched
