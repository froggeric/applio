# tests/test_quit_gate.py
"""Quit-gate detection for in-process conversions (single-process architecture).

Run: venv_macos/bin/python tests/test_quit_gate.py

(Script-style only, like test_menu_jobs: importing applio_launcher under
pytest makes the module-level frozen script-dispatch treat pytest's argv as a
script to run — collection dies in runpy.)

A conversion runs IN-PROCESS on a gradio worker thread, so the quit gates
(applicationShouldTerminate_ + on_window_closing via has_active_processes)
must detect it through inference_progress.json, not active_processes.json.
Covers the helpers behind both gates: _inference_running (the predicate; same
active-status set as _synthesize_inference_proc) and _cancel_inference_and_join
(cancel-flag write + bounded grace wait for the worker to land). Everything
runs against temp files — no real ~/Applio state is read or written.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_launcher


def _write_progress(path, status, **extra):
    rec = {"status": status, "model_name": "voice", "scope": "single"}
    rec.update(extra)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return path


def test_running_detected():
    with tempfile.TemporaryDirectory() as td:
        prog = _write_progress(os.path.join(td, "inference_progress.json"), "running")
        assert applio_launcher._inference_running(prog) is True


def test_cancelling_still_live():
    # "cancelling" = the worker saw the cancel flag but is still winding down
    # between files — its thread is still inside torch. Same active-status set
    # as _synthesize_inference_proc, so the quit gate must see it too.
    with tempfile.TemporaryDirectory() as td:
        prog = _write_progress(
            os.path.join(td, "inference_progress.json"), "cancelling"
        )
        assert applio_launcher._inference_running(prog) is True


def test_terminal_states_not_running():
    # "cancelled" is the state AFTER a cancel-flag write lands; the other
    # terminals need no gate — no live worker thread to quit over.
    with tempfile.TemporaryDirectory() as td:
        prog = os.path.join(td, "inference_progress.json")
        for status in ("completed", "cancelled", "error", "interrupted"):
            _write_progress(prog, status)
            assert applio_launcher._inference_running(prog) is False, status


def test_missing_and_corrupt_files_not_running():
    with tempfile.TemporaryDirectory() as td:
        missing = os.path.join(td, "none.json")
        assert applio_launcher._inference_running(missing) is False
        bad = os.path.join(td, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        assert applio_launcher._inference_running(bad) is False
        # A JSON non-dict must not raise either (predicate never raises).
        with open(bad, "w", encoding="utf-8") as f:
            json.dump(["running"], f)
        assert applio_launcher._inference_running(bad) is False


def test_cancel_and_join_lands():
    with tempfile.TemporaryDirectory() as td:
        prog = _write_progress(os.path.join(td, "inference_progress.json"), "running")

        def _simulated_worker(_secs):
            # The worker notices the flag at its next per-file checkpoint and
            # writes the terminal status.
            _write_progress(prog, "cancelled")

        ok = applio_launcher._cancel_inference_and_join(
            timeout=5.0, data_dir=td, _sleep=_simulated_worker
        )
        assert ok is True
        assert os.path.exists(os.path.join(td, "inference_cancel.flag"))


def test_cancel_and_join_times_out_bounded():
    # A worker that never lands: the grace wait must give up at ``timeout``
    # (fake clock so the test itself stays instant) but still leave the flag.
    class _Clock:
        t = 0.0

        def __call__(self):
            _Clock.t += 0.2
            return _Clock.t

    with tempfile.TemporaryDirectory() as td:
        _write_progress(os.path.join(td, "inference_progress.json"), "running")
        ok = applio_launcher._cancel_inference_and_join(
            timeout=0.25, data_dir=td, _sleep=lambda _s: None, _now=_Clock()
        )
        assert ok is False
        assert os.path.exists(os.path.join(td, "inference_cancel.flag"))


def test_cancel_and_join_flag_write_failure_never_raises():
    with tempfile.TemporaryDirectory() as td:
        blocker = os.path.join(td, "not_a_dir")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("")  # a FILE where the .applio dir should go
        ok = applio_launcher._cancel_inference_and_join(
            timeout=0.05, data_dir=blocker, _sleep=lambda _s: None
        )
        assert ok is False


def test_launcher_delegation_matches_predicate():
    # macos_wrapper.on_window_closing reaches the reader through
    # ApplioLauncher.inference_proc (an instance method that ignores self);
    # pin the module resolver to a temp dir and check it returns the SAME
    # live job the predicate sees (running -> proc, terminal -> None).
    orig = applio_launcher.get_process_state_path
    try:
        with tempfile.TemporaryDirectory() as td:
            applio_launcher.get_process_state_path = lambda: os.path.join(
                td, ".applio", "active_processes.json"
            )
            os.makedirs(os.path.join(td, ".applio"), exist_ok=True)
            prog = _write_progress(
                os.path.join(td, ".applio", "inference_progress.json"), "running"
            )
            assert applio_launcher._inference_running() is True
            proc = applio_launcher.ApplioLauncher.inference_proc(None)
            assert proc is not None and proc.get("_is_inference") is True
            assert proc.get("model_name") == "voice"
            _write_progress(prog, "completed")
            assert applio_launcher.ApplioLauncher.inference_proc(None) is None
    finally:
        applio_launcher.get_process_state_path = orig


def _pin_state_dir(td):
    """Pin the launcher's 3-tier resolver into <td>/.applio for one test.

    Returns the original get_process_state_path for the mandatory finally
    restore (both the progress file and process_history.json derive from it).
    """
    orig = applio_launcher.get_process_state_path
    applio_launcher.get_process_state_path = lambda: os.path.join(
        td, ".applio", "active_processes.json"
    )
    os.makedirs(os.path.join(td, ".applio"), exist_ok=True)
    return orig


def test_stale_cancelling_record_swept():
    # A crash in the tiny cancelling->cancelled window leaves a phantom
    # "cancelling" record that reads as live (quit gate + dashboard) until a
    # new conversion overwrites it — the boot sweep must interrupt it too.
    with tempfile.TemporaryDirectory() as td:
        orig = _pin_state_dir(td)
        try:
            _write_progress(
                os.path.join(td, ".applio", "inference_progress.json"), "cancelling"
            )
            # a stale cancel flag from the interrupted cancel must go too
            flag = os.path.join(td, ".applio", "inference_cancel.flag")
            open(flag, "w").close()
            applio_launcher._sweep_stale_inference_progress()
            with open(os.path.join(td, ".applio", "inference_progress.json")) as f:
                rec = json.load(f)
            assert rec["status"] == "interrupted", rec
            assert rec["error"] == "interrupted by app restart"
            assert not os.path.exists(flag)
            with open(os.path.join(td, ".applio", "process_history.json")) as f:
                hist = json.load(f)
            assert hist["history"], hist
            assert hist["history"][0]["status"] == "interrupted"
            assert hist["history"][0]["type"] == "inference"
        finally:
            applio_launcher.get_process_state_path = orig


def test_sweep_leaves_terminal_records_alone():
    # Terminal records are NOT swept: no rewrite, no history entry.
    with tempfile.TemporaryDirectory() as td:
        orig = _pin_state_dir(td)
        try:
            prog = _write_progress(
                os.path.join(td, ".applio", "inference_progress.json"), "completed"
            )
            applio_launcher._sweep_stale_inference_progress()
            with open(prog) as f:
                assert json.load(f)["status"] == "completed"
            assert not os.path.exists(
                os.path.join(td, ".applio", "process_history.json")
            )
        finally:
            applio_launcher.get_process_state_path = orig


if __name__ == "__main__":
    fns = [
        v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll quit_gate tests passed ({len(fns)}).")
