"""Fixture tests for patcher correctness (history-write order + bounded scan).
Run: venv_macos/bin/python tests/test_patch_fixtures.py
Reads PRISTINE upstream core.py from the repo; guards against a dirty tree."""

import importlib.util
import os
import py_compile
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patched_core(tracking):
    src = open(os.path.join(REPO, "core.py"), encoding="utf8").read()
    assert "_APPLIO_" not in src and "_track_process(" not in src, (
        "core.py is dirty (patched?) - restore first"
    )
    content = src
    ok = 0
    for fn_name in (
        "patch_run_preprocess_script",
        "patch_run_extract_script",
        "patch_run_train_script",
        "patch_run_index_script",
        "patch_voice_conversion",
    ):
        fn = getattr(tracking, fn_name)
        content, patched = fn(content)
        ok += 1 if patched else 0
    assert ok >= 4, f"expected >=4 patched blocks, got {ok} (anchors drifted?)"
    return content


def test_history_written_before_untrack():
    tracking = _load("patch_process_tracking", "patches/patch_process_tracking.py")
    patched = _patched_core(tracking)
    # Anchored regex = CALL sites only: a def line ("    def _untrack_process(")
    # cannot match ^[ \t]*_untrack_process\(. (A plain find() would also hit
    # the injected helper definitions — that false-positive pattern is why
    # this uses the anchor.)
    sites = list(re.finditer(r"(?m)^[ \t]*_untrack_process\(", patched))
    assert len(sites) >= 4, f"expected >=4 untrack call sites, found {len(sites)}"
    for m in sites:
        u = m.start()
        # enclosing function = nearest preceding top-level def
        fstart = patched.rfind("\ndef ", 0, u)
        fend = patched.find("\ndef ", u)
        body = patched[fstart:fend if fend != -1 else len(patched)]
        h = body.find("_add_to_history(")
        assert h != -1 and h < body.find("_untrack_process("), (
            "untrack precedes history-add inside a tracked function"
        )
    # sanity: the patched output compiles
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(patched)
    py_compile.compile(tf.name, doraise=True)
    os.unlink(tf.name)


def test_upload_scan_bounded_to_function_body():
    stop = _load("patch_stop_feedback", "patches/patch_stop_feedback.py")
    synthetic = (
        "def save_to_wav2(bin_file):\n"
        "    uploaded = bin_file.name\n"
        "\n"
        "def later_function(x):\n"
        "    return x\n"
    )
    content, status = stop.patch_upload(synthetic)
    assert status == "miss", "scan must not cross the function boundary"
    assert "gr.Info" not in content
    good = (
        "def save_to_wav2(bin_file):\n"
        "    uploaded = bin_file.name\n"
        "    return uploaded\n"
    )
    content, status = stop.patch_upload(good)
    assert status == "patched" and "gr.Info" in content


def run_all():
    test_history_written_before_untrack()
    test_upload_scan_bounded_to_function_body()
    print("All patch fixture tests passed (2).")


if __name__ == "__main__":
    run_all()
