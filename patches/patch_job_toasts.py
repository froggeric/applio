#!/usr/bin/env python3
"""Patch: lifecycle gradio toasts for the silent job-launch points.

Single inference, TTS, training start, dataset preprocessing, feature
extraction and model download all start (and mostly finish) with no
screen-reader-visible signal - the Textbox outputs they feed are not
announced. gr.Info/gr.Warning toasts are Gradio's announced channel
(role=status, aria-live=polite); this injects them at the exact lifecycle
points, in the wording proven by the a11y VoiceOver passes.

Placement notes (load-bearing):
- The preprocess/extract/download wrappers are injected at the HEAD of
  train_tab()/download_tab(): their click registrations (fn=run_*_script)
  execute DURING tab build, so the wrapper def must already be bound in
  the function's locals - defining it below the rewired line raises
  UnboundLocalError at app startup.
- enforce_terms_batch (inference.py) gets NO toasts: batch inference is
  announced engine-side (patch_inference_progress / Task 3).
- Core's failure strings ("Preprocessing failed for model ...") do NOT
  start with "error"; the wrapper predicate is substring-based:
  "error" in s.lower() or "failed" in s.lower().

Run standalone from the repo root:
    venv_macos/bin/python patches/patch_job_toasts.py [base_path]
build_macos.py invokes it once per target with per-file "dir" bases.
Idempotent via the six per-sub-patch markers below (a shared marker would
make later sub-patches see "already" once the first one lands).
"""

import os
import sys

INFERENCE_MARKER = "# _APPLIO_TOASTS_INFERENCE"
TTS_MARKER = "# _APPLIO_TOASTS_TTS"
TRAIN_START_MARKER = "# _APPLIO_TOASTS_TRAIN_START"
TRAIN_PRE_MARKER = "# _APPLIO_TOASTS_TRAIN_PRE"
TRAIN_EXT_MARKER = "# _APPLIO_TOASTS_TRAIN_EXT"
DOWNLOAD_MARKER = "# _APPLIO_TOASTS_DOWNLOAD"

INFER_ERROR = (
    "An error occurred during audio conversion. "
    "Please check the console logs for more details."
)
TTS_ERROR = (
    "An error occurred during TTS conversion. "
    "Please check the console logs for more details."
)


def _enforce_terms_body(content):
    """(body_start, body_end) of enforce_terms, or None when absent.

    Def-first, body-bounded scan (mirror of patch_stop_feedback's
    patch_upload): the distinct `return run_*_script(*args)` lines are
    unique today, but bounding keeps a future lookalike (or an upstream
    rename of enforce_terms) from silently relocating the injection -
    a moved/renamed def makes every enforce_terms sub-patch MISS (exit 2)
    instead of patching the wrong function. `def enforce_terms(` does
    not substring-match `def enforce_terms_batch(`.
    """
    idx = content.find("def enforce_terms(terms_accepted, *args):")
    if idx == -1:
        return None
    # Next top-level def (or EOF) bounds the region; nested defs inside
    # the tab function are indented, so "\ndef " skips them.
    end = content.find("\ndef ", idx)
    return idx, len(content) if end == -1 else end


def _patch_enforce_terms_call(content, script, marker, start_msg, error_string):
    """Rewrite enforce_terms' try/except around its single return.

    Both pristine shapes (inference.py, tts.py) are:

        try:
            return run_<script>_script(*args)
        except Exception:
            traceback.print_exc()
            return (
                "<error string>",
                None,
            )

    run_infer_script/run_tts_script have ONE return - the success tuple
    (message, path); every failure raises - so gr.Info(result[0]) can
    never announce an error as info.
    """
    bounds = _enforce_terms_body(content)
    if bounds is None:
        return content, "miss"
    body_start, body_end = bounds
    anchor = f"return run_{script}_script(*args)"
    a = content.find(anchor, body_start, body_end)
    if a == -1:
        return content, "miss"
    line_start = content.rfind("\n", 0, a) + 1
    body_indent = content[line_start:a]  # the return's indent (inside try)
    try_indent = body_indent[:-4]
    old = (
        f"{try_indent}try:\n"
        f"{body_indent}return run_{script}_script(*args)\n"
        f"{try_indent}except Exception:\n"
        f"{try_indent}    traceback.print_exc()\n"
        f"{try_indent}    return (\n"
        f'{body_indent}    "{error_string}",\n'
        f"{body_indent}    None,\n"
        f"{try_indent}    )\n"
    )
    if content.find(old, body_start, body_end) == -1:
        return content, "miss"
    new = (
        f"{try_indent}try:\n"
        f'{body_indent}gr.Info(i18n("{start_msg}"))  {marker}\n'
        f"{body_indent}result = run_{script}_script(*args)\n"
        f"{body_indent}gr.Info(result[0])  {marker}\n"
        f"{body_indent}return result\n"
        f"{try_indent}except Exception:\n"
        f"{try_indent}    traceback.print_exc()\n"
        f"{try_indent}    gr.Warning(  {marker}\n"
        f'{body_indent}    "{error_string}"\n'
        f"{try_indent}    )\n"
        f"{try_indent}    return (\n"
        f'{body_indent}    "{error_string}",\n'
        f"{body_indent}    None,\n"
        f"{try_indent}    )\n"
    )
    return content.replace(old, new, 1), "patched"


def patch_inference(content):
    """Single-conversion toasts (batch is engine-side - see module doc)."""
    if INFERENCE_MARKER in content:
        return content, "already"
    return _patch_enforce_terms_call(
        content, "infer", INFERENCE_MARKER, "Converting audio...", INFER_ERROR
    )


def patch_tts(content):
    if TTS_MARKER in content:
        return content, "already"
    return _patch_enforce_terms_call(
        content, "tts", TTS_MARKER, "Starting text-to-speech...", TTS_ERROR
    )


def _patch_train_start(content):
    """Training START only - no terminal toast: hours later, and the
    heartbeat / web payload already announce completion."""
    if TRAIN_START_MARKER in content:
        return content, "already"
    bounds = _enforce_terms_body(content)
    if bounds is None:
        return content, "miss"
    body_start, body_end = bounds
    anchor = "return run_train_script(*args)"
    a = content.find(anchor, body_start, body_end)
    if a == -1:
        return content, "miss"
    line_start = content.rfind("\n", 0, a) + 1
    indent = content[line_start:a]
    inject = f'{indent}gr.Info(i18n("Training started..."))  {TRAIN_START_MARKER}\n'
    return content[:line_start] + inject + content[line_start:], "patched"


def _insert_after(content, anchor, block):
    """content with block inserted right after anchor, or None if absent."""
    idx = content.find(anchor)
    if idx == -1:
        return None
    at = idx + len(anchor)
    return content[:at] + block + content[at:]


# Substring failure predicate: core returns "Preprocessing failed for
# model {name}..." / "An error occurred downloading the model..." -
# startswith("error") would never match either.
_PREDICATE = (
    'if "error" in result.lower() or "failed" in result.lower():\n'
    "                gr.Warning(result)\n"
    "            else:\n"
    "                gr.Info(result)\n"
    "        return result\n"
    "\n"
)


def _wrapper(name, marker, start_msg, script):
    return (
        f"    def {name}(*args):  {marker}\n"
        f'        gr.Info(i18n("{start_msg}"))\n'
        f"        result = run_{script}_script(*args)\n"
        "        if isinstance(result, str):\n"
        f"            {_PREDICATE}"
    )


PREPROCESS_WRAPPER = _wrapper(
    "_applio_preprocess_toast",
    TRAIN_PRE_MARKER,
    "Preprocessing dataset...",
    "preprocess",
)
EXTRACT_WRAPPER = _wrapper(
    "_applio_extract_toast",
    TRAIN_EXT_MARKER,
    "Extracting features...",
    "extract",
)
DOWNLOAD_WRAPPER = _wrapper(
    "_applio_download_toast",
    DOWNLOAD_MARKER,
    "Downloading model...",
    "download",
)


def _patch_tab_wrapper(content, marker, wrapper, fn_literal, wrapper_fn, after):
    """Insert one toast wrapper and rewire its click registration.

    Head-of-body placement only: `after` is the def line of the tab
    function (or the sibling wrapper block already sitting at its head).
    """
    if marker in content:
        return content, "already"
    new = _insert_after(content, after, wrapper)
    if new is None or f"fn=run_{fn_literal}_script,\n" not in new:
        return content, "miss"
    rewired = new.replace(f"fn=run_{fn_literal}_script,\n", f"fn={wrapper_fn},\n", 1)
    return rewired, "patched"


def _patch_preprocess_wrapper(content):
    return _patch_tab_wrapper(
        content,
        TRAIN_PRE_MARKER,
        PREPROCESS_WRAPPER,
        "preprocess",
        "_applio_preprocess_toast",
        "def train_tab():\n",
    )


def _patch_extract_wrapper(content):
    # Land directly below the preprocess wrapper when present so the two
    # read in launch order; otherwise at the head of train_tab().
    after = PREPROCESS_WRAPPER if TRAIN_PRE_MARKER in content else "def train_tab():\n"
    return _patch_tab_wrapper(
        content,
        TRAIN_EXT_MARKER,
        EXTRACT_WRAPPER,
        "extract",
        "_applio_extract_toast",
        after,
    )


def patch_train(content):
    statuses = []
    for fn in (_patch_train_start, _patch_preprocess_wrapper, _patch_extract_wrapper):
        content, status = fn(content)
        statuses.append(status)
    if "miss" in statuses:
        return content, "miss"
    if all(s == "already" for s in statuses):
        return content, "already"
    return content, "patched"


def patch_download(content):
    return _patch_tab_wrapper(
        content,
        DOWNLOAD_MARKER,
        DOWNLOAD_WRAPPER,
        "download",
        "_applio_download_toast",
        "def download_tab():\n",
    )


# (repo-relative path, basename, sub-patch fn) - basename is unique per target
TARGETS = [
    ("tabs/inference/inference.py", "inference.py", patch_inference),
    ("tabs/tts/tts.py", "tts.py", patch_tts),
    ("tabs/train/train.py", "train.py", patch_train),
    ("tabs/download/download.py", "download.py", patch_download),
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
            print(f"  [job_toasts] {basename}: skip")
            continue  # this invocation's base covers the other targets
        with open(path, encoding="utf-8") as f:
            content = f.read()
        new, status = fn(content)
        if status == "patched":
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
        elif status == "miss":
            ok = False
        print(f"  [job_toasts] {basename}: {status}")
    return ok


if __name__ == "__main__":
    base = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    sys.exit(0 if apply(base) else 2)
