#!/usr/bin/env python3
"""Patch: announced feedback for Stop Training and audio upload.

Upstream computes these messages but leaves them commented out (restart.py
stop_train) or emits nothing (inference.py save_to_wav2). gr.Info/gr.Warning
toasts are Gradio's screen-reader-announced channel (role=status,
aria-live=polite) — see ACCESSIBILITY_AUDIT.md (toast-transience gap noted
there; wording kept short on purpose).

Run standalone from the repo root:
    venv_macos/bin/python patches/patch_stop_feedback.py [base_path]
build_macos.py invokes it twice with per-file "dir" bases.
Idempotent via per-file markers below.
"""

import os
import re
import sys

STOP_TRAIN_MARKER = "# _APPLIO_A11Y_STOP_TRAIN"
UPLOAD_MARKER = "# _APPLIO_A11Y_UPLOAD"

# The commented block sits at try-body indent (8 spaces in the current file):
#         # if killed > 0:
#         #    gr.Info(f"Training stopped successfully (...)")
#         # else:
#         #    gr.Info("No active training processes found")
# Indent capture is HORIZONTAL-ONLY (\n([ \t]+)) per CLAUDE.md: (\n\s+) would
# grab the preceding blank line's newline and shift every injected line.
STOP_TRAIN_RE = re.compile(r"\n([ \t]+)# if killed > 0:\n(?:[ \t]+#[^\n]*\n)+")
# Each replacement reproduces exactly ONE leading newline (the one the regex
# consumed); the blank line + `except:` that follow the block stay untouched.
STOP_TRAIN_REPLACEMENT = (
    "\n\\1if killed > 0:\n"
    '\\1    gr.Info(f"Stopped training ({killed} process(es) terminated).")\n'
    "\\1else:\n"
    '\\1    gr.Warning("No active training processes were found.")\n'
    f"\\1{STOP_TRAIN_MARKER}"
)


def patch_stop_train(content):
    """Returns (new_content, status): 'patched' / 'already' / 'miss'."""
    if STOP_TRAIN_MARKER in content:
        return content, "already"
    new, n = STOP_TRAIN_RE.subn(STOP_TRAIN_REPLACEMENT, content, count=1)
    if n != 1:
        return content, "miss"
    return new, "patched"


def patch_upload(content):
    """Inject gr.Info before save_to_wav2's single return."""
    if UPLOAD_MARKER in content:
        return content, "already"
    idx = content.find("def save_to_wav2(")
    if idx == -1:
        return content, "miss"
    # Bound the scan to save_to_wav2's body: an unbounded find() would inject
    # the toast into whatever LATER function owns the next "\n    return".
    body_end = content.find("\ndef ", idx)
    if body_end == -1:
        body_end = len(content)
    ret = content.find("\n    return", idx, body_end)
    if ret == -1:
        return content, "miss"
    insert_at = ret + 1
    inject = (
        f"    {UPLOAD_MARKER}\n"
        '    gr.Info("Audio uploaded. It is now selected in the '
        "'Select Audio' dropdown.\")\n"
    )
    return content[:insert_at] + inject + content[insert_at:], "patched"


# (repo-relative path, basename, sub-patch fn) — basename is unique per target
TARGETS = [
    ("tabs/settings/sections/restart.py", "restart.py", patch_stop_train),
    ("tabs/inference/inference.py", "inference.py", patch_upload),
]


def apply(base_path):
    """Patch whichever targets resolve under base_path; report per file."""
    ok = True
    for repo_rel, basename, fn in TARGETS:
        candidates = [
            os.path.join(base_path, basename),  # dir-type base from build_macos
            os.path.join(base_path, repo_rel),  # repo-root base (standalone)
        ]
        path = next((p for p in candidates if os.path.isfile(p)), None)
        if path is None:
            continue  # this invocation's base covers the other target
        with open(path, encoding="utf-8") as f:
            content = f.read()
        new, status = fn(content)
        if status == "patched":
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
        elif status == "miss":
            ok = False
        print(f"  [stop_feedback] {basename}: {status}")
    return ok


if __name__ == "__main__":
    base = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    sys.exit(0 if apply(base) else 1)
