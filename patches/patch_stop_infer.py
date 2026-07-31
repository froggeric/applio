"""
Patch to rewrite upstream `stop_infer` in tabs/settings/sections/restart.py
to use cooperative cancellation instead of killing a PID.

Upstream `stop_infer` reads `assets/infer_pid.txt` and SIGKILLs every PID
listed there. In single-process mode (the default since Phase 2) the recorded
PID is the *whole app's* process, so clicking the inference Stop button kills
Applio outright.

This patcher replaces the body of `stop_infer` with code that writes a cancel
flag file (`<data_path>/.applio/inference_cancel.flag`). The patched
`convert_audio_batch` loop (see `patches/patch_inference_progress.py`) checks
this flag per file and exits cleanly. The replacement:

- Does NOT kill any PID.
- Does NOT depend on `now_dir` (frozen-CWD safe; uses `APPLIO_DATA_PATH`).
- Is best-effort and silent when no inference job is running.

`import psutil` is preserved because `stop_train` in the same module still
uses it.
"""

import os
import re


STOP_INFER_REPLACEMENT = '''def stop_infer():
    # Cooperative cancellation (3.6.3.7): write the cancel flag; the patched
    # convert_audio_batch loop checks it per file and exits cleanly. Does NOT
    # kill a PID (single-process: the PID is the whole app). Best-effort; silent
    # no-op if no job is running. Path is absolute (frozen-CWD safe).
    import os as _si_os
    data_path = _si_os.environ.get("APPLIO_DATA_PATH") or _si_os.expanduser("~/Applio")
    cancel_flag = _si_os.path.join(data_path, ".applio", "inference_cancel.flag")
    try:
        _si_os.makedirs(_si_os.path.dirname(cancel_flag), exist_ok=True)
        open(cancel_flag, "w").close()
    except OSError:
        pass
'''


def patch_restart_py(base_path: str) -> bool:
    """Patch restart.py to rewrite `stop_infer` for cooperative cancellation.

    Args:
        base_path: Directory containing restart.py
                   (e.g., tabs/settings/sections).

    Returns:
        True if patched successfully (or already patched), False otherwise.
    """
    restart_path = os.path.join(base_path, "restart.py")

    if not os.path.exists(restart_path):
        raise FileNotFoundError(f"restart.py not found at {restart_path}")

    with open(restart_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency: own marker is the flag filename we write.
    if "inference_cancel.flag" in content:
        print("  [stop_infer] Already patched, skipping.")
        return True

    print("  [stop_infer] Patching...")

    # Match `def stop_infer():` up to (but not including) `def restart_applio():`.
    new_content, n = re.subn(
        r"def stop_infer\(\):.*?(?=\ndef restart_applio\(\))",
        STOP_INFER_REPLACEMENT,
        content,
        count=1,
        flags=re.DOTALL,
    )

    if n != 1:
        print(
            f"  [stop_infer] Pattern not found (expected 1 match, got {n}). "
            "Upstream may have changed the anchor."
        )
        return False

    with open(restart_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print("  [stop_infer] Patched successfully")
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python patch_stop_infer.py <base_path>")
        sys.exit(1)

    base_path = sys.argv[1]
    success = patch_restart_py(base_path)
    sys.exit(0 if success else 1)
