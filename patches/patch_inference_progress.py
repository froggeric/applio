"""
Patch to add progress tracking + cooperative cancel to batch inference in infer.py.

This patch:
1. Injects helper functions for writing ~/Applio/.applio/inference_progress.json
   (atomic os.replace writes, 0o600 perms), reading a cancel flag, and appending
   schema-compatible history entries to process_history.json (fcntl LOCK_EX,
   matching applio_launcher.add_to_history).
2. Rewrites VoiceConverter.convert_audio_batch to:
   - reject concurrent batches (status == "running"),
   - emit per-file progress (processed/converted/skipped/current_file),
   - cooperatively cancel via inference_cancel.flag (no PID kill),
   - append a completed/cancelled/error entry to process_history.json,
   - normalise terminal status (running->completed, cancelling->cancelled),
   - clear a stale cancel flag at start (robust against a stray Stop click).
3. Removes the broken infer_pid.txt logic (frozen-CWD write was wrong; and in
   single-process os.getpid() == the whole app, so PID-kill quit the app).

Modeled on patches/patch_refinegan_legacy_infer.py (same base_path arg contract:
opens os.path.join(base_path, "infer.py")).
"""

import os
import re

_HELPERS_MARKER = "# === Inference Progress Tracking (injected by patch) ==="
_BATCH_MARKER = "_infer_cancel_requested()"


INFER_PROGRESS_HELPERS = r"""
# === Inference Progress Tracking (injected by patch) ===
import json as _infer_json
import time as _infer_time
import os as _infer_os
import datetime as _infer_dt

_INFER_HIST_MAX = 50

def _infer_data_dir():
    # 2-tier, matching patches/patch_process_tracking.py._get_process_state_path.
    # In the frozen app, macos_wrapper.start_gui sets APPLIO_DATA_PATH in-process
    # before Gradio runs, so the in-process Gradio thread sees the same env the
    # launcher reads (env-first). Dev defaults to ~/Applio, matching the launcher fallback.
    return _infer_os.environ.get("APPLIO_DATA_PATH") or _infer_os.path.expanduser("~/Applio")

def _infer_progress_path():
    return _infer_os.path.join(_infer_data_dir(), ".applio", "inference_progress.json")

def _infer_cancel_path():
    return _infer_os.path.join(_infer_data_dir(), ".applio", "inference_cancel.flag")

def _read_infer_progress():
    try:
        with open(_infer_progress_path(), "r", encoding="utf-8") as f:
            return _infer_json.load(f)
    except (IOError, _infer_json.JSONDecodeError):
        return None

def _write_infer_progress(record):
    # Best-effort: tracking must NEVER block inference. Single writer + atomic
    # os.replace => no lock (POSIX/APFS atomic rename). A reader sees the whole
    # old or new file, never a torn write.
    try:
        path = _infer_progress_path()
        _infer_os.makedirs(_infer_os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        fd = _infer_os.open(tmp, _infer_os.O_WRONLY | _infer_os.O_CREAT | _infer_os.O_TRUNC, 0o600)
        with _infer_os.fdopen(fd, "w", encoding="utf-8") as f:
            _infer_json.dump(record, f)
        _infer_os.replace(tmp, path)
    except OSError:
        pass

def _infer_cancel_requested():
    return _infer_os.path.exists(_infer_cancel_path())

def _infer_add_to_history(entry):
    # Schema-compatible with applio_launcher.load_process_history/add_to_history
    # (required: type, started_at, completed_at). fcntl LOCK_EX on <hist>.lock
    # matches the launcher writer (which may read/write concurrently).
    try:
        import fcntl as _infer_fcntl
        hist_path = _infer_os.path.join(_infer_data_dir(), ".applio", "process_history.json")
        _infer_os.makedirs(_infer_os.path.dirname(hist_path), exist_ok=True)
        lock_path = hist_path + ".lock"
        with open(lock_path, "a") as _lf:
            _infer_fcntl.flock(_lf.fileno(), _infer_fcntl.LOCK_EX)
            try:
                hist = {"version": 1, "history": []}
                if _infer_os.path.exists(hist_path):
                    try:
                        with open(hist_path, "r", encoding="utf-8") as f:
                            hist = _infer_json.load(f) or hist
                    except _infer_json.JSONDecodeError:
                        pass
                entry["process_id"] = "inference-%s" % entry.get("started_at")
                hist.setdefault("history", []).insert(0, entry)
                hist["history"] = hist["history"][:_INFER_HIST_MAX]
                tmp = hist_path + ".tmp"
                fd = _infer_os.open(tmp, _infer_os.O_WRONLY | _infer_os.O_CREAT | _infer_os.O_TRUNC, 0o600)
                with _infer_os.fdopen(fd, "w", encoding="utf-8") as f:
                    _infer_json.dump(hist, f, indent=2)
                _infer_os.replace(tmp, hist_path)
            finally:
                _infer_fcntl.flock(_lf.fileno(), _infer_fcntl.LOCK_UN)
    except OSError:
        pass
# === End Inference Progress Tracking ===
"""


# Anchor regex: spans the method BODY only (the def + docstring L345-360 are preserved).
INFER_BATCH_ANCHOR = re.compile(
    r"        pid = os\.getpid\(\)\n        try:.*?"
    r'os\.remove\(os\.path\.join\(now_dir, "assets", "infer_pid\.txt"\)\)\n',
    re.DOTALL,
)


INFER_BATCH_REPLACEMENT = r"""        # Inference progress tracking (3.6.3.7): cooperative cancel + progress file.
        # Replaces the PID-file mechanism (frozen-CWD write was broken; and in
        # single-process os.getpid() == the whole app, so PID-kill quit the app).
        existing = _read_infer_progress()
        if existing and existing.get("status") == "running":
            raise RuntimeError(
                "Another batch inference is already running. Stop it first from the Process Dashboard."
            )
        _model_name = _infer_os.path.basename(kwargs.get("model_path") or "")
        start_time = _infer_time.time()
        print(f"Converting audio batch '{audio_input_paths}'...")
        audio_files = [
            f
            for f in _infer_os.listdir(audio_input_paths)
            if f.lower().endswith(
                (
                    "wav", "mp3", "flac", "ogg", "opus", "m4a", "mp4",
                    "aac", "alac", "wma", "aiff", "webm", "ac3",
                )
            )
        ]
        print(f"Detected {len(audio_files)} audio files for inference.")
        total = len(audio_files)
        processed = converted = skipped = 0
        status = "running"
        _write_infer_progress({
            "version": 1, "type": "inference", "status": status,
            "model_name": _model_name, "input_folder": audio_input_paths,
            "output_folder": audio_output_path, "total": total,
            "processed": 0, "converted": 0, "skipped": 0,
            "current_file": audio_files[0] if audio_files else "",
            "started_at": start_time, "ended_at": None, "elapsed": None, "error": None,
        })
        # Clear any stale cancel flag left by a Stop click on a PREVIOUS, already-
        # finished batch (otherwise this batch would cancel on its first file).
        try:
            _infer_os.remove(_infer_cancel_path())
        except OSError:
            pass
        try:
            # Ensure the output folder exists (otherwise the first convert fails
            # with an opaque soundfile "System error" when the output path does
            # not exist yet). exist_ok=True is a no-op when it already exists.
            # A genuine creation failure (permissions) raises here and is caught
            # below as a clear error instead of soundfile's opaque message.
            _infer_os.makedirs(audio_output_path, exist_ok=True)
            for idx, a in enumerate(audio_files):
                if _infer_cancel_requested():
                    status = "cancelling"
                    _write_infer_progress({
                        "version": 1, "type": "inference", "status": status,
                        "model_name": _model_name, "input_folder": audio_input_paths,
                        "output_folder": audio_output_path, "total": total,
                        "processed": processed, "converted": converted, "skipped": skipped,
                        "current_file": a, "started_at": start_time,
                        "ended_at": None, "elapsed": None, "error": None,
                    })
                    break
                new_input = _infer_os.path.join(audio_input_paths, a)
                new_output = _infer_os.path.splitext(a)[0] + "_output.wav"
                new_output = _infer_os.path.join(audio_output_path, new_output)
                if _infer_os.path.exists(new_output):
                    skipped += 1
                    processed += 1
                else:
                    self.convert_audio(
                        audio_input_path=new_input,
                        audio_output_path=new_output,
                        **kwargs,
                    )
                    converted += 1
                    processed += 1
                nxt = audio_files[idx + 1] if idx + 1 < total else ""
                _write_infer_progress({
                    "version": 1, "type": "inference", "status": status,
                    "model_name": _model_name, "input_folder": audio_input_paths,
                    "output_folder": audio_output_path, "total": total,
                    "processed": processed, "converted": converted, "skipped": skipped,
                    "current_file": nxt, "started_at": start_time,
                    "ended_at": None, "elapsed": None, "error": None,
                })
            # Normalise terminal status (loop exited without raise).
            if status == "running":
                status = "completed"
            elif status == "cancelling":
                status = "cancelled"
            ended_at = _infer_time.time()
            elapsed = ended_at - start_time
            _write_infer_progress({
                "version": 1, "type": "inference", "status": status,
                "model_name": _model_name, "input_folder": audio_input_paths,
                "output_folder": audio_output_path, "total": total,
                "processed": processed, "converted": converted, "skipped": skipped,
                "current_file": "", "started_at": start_time,
                "ended_at": ended_at, "elapsed": elapsed, "error": None,
            })
            if status == "completed":
                print(f"Conversion completed at '{audio_input_paths}'.")
                print(f"Batch conversion completed in {elapsed:.2f} seconds.")
            _infer_add_to_history({
                "type": "inference", "model_name": _model_name,
                "started_at": _infer_dt.datetime.fromtimestamp(start_time).isoformat(),
                "completed_at": _infer_dt.datetime.fromtimestamp(ended_at).isoformat(),
                "status": status, "total": total,
                "converted": converted, "skipped": skipped,
            })
        except Exception as _infer_exc:
            ended_at = _infer_time.time()
            elapsed = ended_at - start_time
            _write_infer_progress({
                "version": 1, "type": "inference", "status": "error",
                "model_name": _model_name, "input_folder": audio_input_paths,
                "output_folder": audio_output_path, "total": total,
                "processed": processed, "converted": converted, "skipped": skipped,
                "current_file": "", "started_at": start_time,
                "ended_at": ended_at, "elapsed": elapsed, "error": str(_infer_exc),
            })
            _infer_add_to_history({
                "type": "inference", "model_name": _model_name,
                "started_at": _infer_dt.datetime.fromtimestamp(start_time).isoformat(),
                "completed_at": _infer_dt.datetime.fromtimestamp(ended_at).isoformat(),
                "status": "error", "total": total,
                "converted": converted, "skipped": skipped,
            })
            raise
        finally:
            # Always remove the cancel flag (a post-completion Stop click is a no-op;
            # a fresh batch is not cancelled by a leftover flag - the start-clear above
            # also covers this, but finally makes it robust even if start-clear raced).
            try:
                _infer_os.remove(_infer_cancel_path())
            except OSError:
                pass
"""


def patch_infer_py(base_path: str) -> bool:
    """Patch infer.py to add batch-inference progress tracking + cancel + history.

    Args:
        base_path: Directory containing infer.py (e.g., rvc/infer/)

    Returns:
        True if patched successfully (or already patched), False if the anchor
        could not be found.
    """
    infer_path = os.path.join(base_path, "infer.py")

    if not os.path.exists(infer_path):
        raise FileNotFoundError(f"infer.py not found at {infer_path}")

    with open(infer_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency: both the helpers marker AND the batch-rewrite marker must be
    # present to consider the file fully patched. Use the patcher's OWN specific
    # markers (NOT a shared early-return marker).
    helpers_done = _HELPERS_MARKER in content
    batch_done = _BATCH_MARKER in content
    if helpers_done and batch_done:
        print("[infer.py inference-progress] Already patched, skipping.")
        return True

    changed = False

    # (a) Inject helpers before `class VoiceConverter` (unique + stable anchor).
    if not helpers_done:
        if "class VoiceConverter:" not in content:
            print("[infer.py inference-progress] Could not find class VoiceConverter")
            return False
        content = content.replace(
            "class VoiceConverter:",
            INFER_PROGRESS_HELPERS + "\n\nclass VoiceConverter:",
            1,
        )
        changed = True

    # (b) Replace the batch body (regex; the body has a 13-element tuple that
    # makes a literal match fragile).
    if not batch_done:
        new_content, n = INFER_BATCH_ANCHOR.subn(
            INFER_BATCH_REPLACEMENT, content, count=1
        )
        if n == 0:
            print(
                "[infer.py inference-progress] Could not find convert_audio_batch anchor"
            )
            return False
        content = new_content
        changed = True

    if changed:
        with open(infer_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("[infer.py inference-progress] Patched successfully")
    else:
        print("[infer.py inference-progress] Already patched, skipping.")
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python patch_inference_progress.py <base_path>")
        sys.exit(1)

    base_path = sys.argv[1]
    success = patch_infer_py(base_path)
    sys.exit(0 if success else 1)
