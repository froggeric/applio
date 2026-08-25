#!/usr/bin/env python3
"""Patch: lifecycle gradio toasts for the fork-only silent job-launch points.

2026-08-25: slimmed from 9 targets to the 5 upstream does NOT toast. The
other four (single inference, TTS, train start/finish + preprocess/extract,
model download) were upstreamed via PR #1271 and are now native - patching
them here would double-toast, and their old anchors MISS on the merged code
(exit 2, build-fatal by design). The five below are restored verbatim from
the pre-sync patcher pending a follow-up upstream PR (Track B): voice
blending, plugin install, realtime engine start/failure, model information
and TensorBoard launch. All start (and mostly finish) with no
screen-reader-visible signal - the Textbox outputs they feed are not
announced. gr.Info/gr.Warning toasts are Gradio's announced channel
(role=status, aria-live=polite); this injects them at the exact lifecycle
points, in the wording proven by the a11y VoiceOver passes.

Placement notes (load-bearing):
- The blender/model-info wrappers are injected at the HEAD of their tab
  functions (plugins/realtime wrap at their handler seams instead - see
  below): the click registrations (fn=run_*_script) execute DURING tab
  build, so the wrapper def must already be bound in the function's locals
  - defining it below the rewired line raises UnboundLocalError at app
  startup.
- Core's failure strings ("... failed for model ...") do NOT start with
  "error"; the wrapper predicate is substring-based:
  "error" in s.lower() or "failed" in s.lower().
- The plugin wrapper adds start/error only: save_plugin_dropbox already
  gr.Infos its own "{name} plugin installed ...!" finish (upstream), and
  a second success toast would double-announce. Its gr.Error
  (invalid zip) is re-raised untouched - gradio announces gr.Error
  natively; only NON-gradio failures get the added gr.Warning.
- The realtime wrapper is a GENERATOR (enforce_terms yields): it scans
  each yielded update and warns on failure-looking statuses - start_realtime
  catches its own model-load exceptions and yields "Error: ..." into the
  (unannounced) latency Textbox instead of raising, and also emits
  first-use validation yields ("Please select valid input/output
  devices!" etc.) that never raise, so its marker set is broader than
  the shared return-value predicate.
- Drop confirmations: update_model_fusion feeds BOTH blender dropboxes. The
  download tab's save_drop_model needs nothing here - upstream
  already gr.Infos "{file} saved in {path}".

Run standalone from the repo root:
    venv_macos/bin/python patches/patch_job_toasts.py [base_path]
build_macos.py invokes it once per target with per-file "dir" bases.
Idempotent via the six per-sub-patch markers below (a shared marker
would make later sub-patches see "already" once the first one lands).
"""

import os
import sys

BLENDER_MARKER = "# _APPLIO_TOASTS_BLENDER"
BLEND_DROP_MARKER = "# _APPLIO_TOASTS_BLEND_DROP"
PLUGINS_MARKER = "# _APPLIO_TOASTS_PLUGINS"
REALTIME_MARKER = "# _APPLIO_TOASTS_REALTIME"
MODEL_INFO_MARKER = "# _APPLIO_TOASTS_MODEL_INFO"
TENSORBOARD_MARKER = "# _APPLIO_TOASTS_TENSORBOARD"


def _insert_after(content, anchor, block):
    """content with block inserted right after anchor, or None if absent."""
    idx = content.find(anchor)
    if idx == -1:
        return None
    at = idx + len(anchor)
    return content[:at] + block + content[at:]


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


# Voice blender: run_model_blender_script returns (message, path) on
# success and RAISES on every failure path (model_blender's early bare
# string returns die in run_model_blender_script's tuple unpack), so the
# wrapper toasts result[0] as info and converts exceptions to a warning
# before re-raising.
BLENDER_WRAPPER = (
    f"    def _applio_blend_toast(*args):  {BLENDER_MARKER}\n"
    f'        gr.Info(i18n("Blending models..."))\n'
    f"        try:\n"
    f"            result = run_model_blender_script(*args)\n"
    f"        except Exception:\n"
    f"            gr.Warning(\n"
    f"                i18n(\n"
    f'                    "An error occurred blending the models. "\n'
    f'                    "Please check the console logs for more details."\n'
    f"                )\n"
    f"            )\n"
    f"            raise\n"
    f"        message = result[0] if isinstance(result, tuple) else result\n"
    f"        if isinstance(message, str):\n"
    f'            if "error" in message.lower() or "failed" in message.lower():\n'
    f"                gr.Warning(message)\n"
    f"            else:\n"
    f"                gr.Info(message)\n"
    f"        return result\n"
    "\n"
)


def _patch_blend_drop(content):
    """Drop confirmation for BOTH blender dropboxes (one shared handler)."""
    if BLEND_DROP_MARKER in content:
        return content, "already"
    old = "def update_model_fusion(dropbox):\n    return dropbox, None\n"
    if content.find(old) == -1:
        return content, "miss"
    new = (
        "def update_model_fusion(dropbox):\n"
        f"    gr.Info(  {BLEND_DROP_MARKER}\n"
        "        i18n(\"Model added. It is now selected in the 'Path to"
        " Model' field.\")\n"
        "    )\n"
        "    return dropbox, None\n"
    )
    return content.replace(old, new, 1), "patched"


def _patch_blend_wrapper(content):
    return _patch_tab_wrapper(
        content,
        BLENDER_MARKER,
        BLENDER_WRAPPER,
        "model_blender",
        "_applio_blend_toast",
        "def voice_blender_tab():\n",
    )


def patch_voice_blender(content):
    statuses = []
    for fn in (_patch_blend_drop, _patch_blend_wrapper):
        content, status = fn(content)
        statuses.append(status)
    if "miss" in statuses:
        return content, "miss"
    if all(s == "already" for s in statuses):
        return content, "already"
    return content, "patched"


# Plugins: the pip install runs INSIDE plugins_core.save_plugin_dropbox,
# so the tab-side fn= rewire is the seam. Start/error only - the handler
# already gr.Infos its own finish (see module docstring).
PLUGINS_WRAPPER = (
    f"    def _applio_plugin_toast(dropbox):  {PLUGINS_MARKER}\n"
    f'        gr.Info(i18n("Installing plugin..."))\n'
    f"        try:\n"
    f"            return plugins_core.save_plugin_dropbox(dropbox)\n"
    f"        except gr.Error:\n"
    f"            raise  # gradio announces gr.Error natively\n"
    f"        except Exception:\n"
    f"            gr.Warning(\n"
    f"                i18n(\n"
    f'                    "An error occurred installing the plugin. "\n'
    f'                    "Please check the console logs for more details."\n'
    f"                )\n"
    f"            )\n"
    f"            raise\n"
    "\n"
)


def patch_plugins(content):
    if PLUGINS_MARKER in content:
        return content, "already"
    new = _insert_after(content, "def plugins_tab():\n", PLUGINS_WRAPPER)
    if new is None or "fn=plugins_core.save_plugin_dropbox,\n" not in new:
        return content, "miss"
    return new.replace(
        "fn=plugins_core.save_plugin_dropbox,\n",
        "fn=_applio_plugin_toast,\n",
        1,
    ), "patched"


# Realtime: enforce_terms is the non-client-mode click handler and a
# GENERATOR - the wrapper must yield too. It suppresses the start toast
# when terms were not accepted (upstream already gr.Infos the terms
# message). Yield scanning uses a BROADER marker set than the shared
# return-value predicate: start_realtime both catches its model-load
# exceptions into "Error: ..." yields AND emits first-use validation
# statuses that never raise ("Please select valid input/output
# devices!", "Please select a valid monitor device!", "Model path not
# provided. Aborting conversion.", "Incorrectly formatted audio device.
# Stopping.") - without the extra markers the user hears the start toast
# and then silence.
REALTIME_ANCHOR = (
    "        def enforce_terms(terms_accepted, *args):\n"
    "            if not terms_accepted:\n"
    '                message = "You must agree to the Terms of Use to proceed."\n'
    "                gr.Info(message)\n"
    "                yield message, interactive_true, interactive_false\n"
    "                return\n"
    "            yield from start_realtime(*args)\n"
)
REALTIME_WRAPPER = (
    f"        def _applio_realtime_toast(terms_accepted, *args):  {REALTIME_MARKER}\n"
    f"            if terms_accepted:\n"
    f'                gr.Info(i18n("Starting real-time conversion..."))\n'
    f"            failures = (\n"
    f'                "error",\n'
    f'                "failed",\n'
    f'                "stopping",\n'
    f'                "aborting",\n'
    f'                "please select",\n'
    f'                "not provided",\n'
    f"            )\n"
    f"            try:\n"
    f"                for update in enforce_terms(terms_accepted, *args):\n"
    f"                    status = update[0] if isinstance(update, tuple) else update\n"
    f"                    if isinstance(status, str) and any(\n"
    f"                        marker in status.lower() for marker in failures\n"
    f"                    ):\n"
    f"                        gr.Warning(status)\n"
    f"                    yield update\n"
    f"            except Exception:\n"
    f"                gr.Warning(\n"
    f"                    i18n(\n"
    f'                        "An error occurred during real-time conversion. "\n'
    f'                        "Please check the console logs for more details."\n'
    f"                    )\n"
    f"                )\n"
    f"                raise\n"
    "\n"
)


def patch_realtime(content):
    if REALTIME_MARKER in content:
        return content, "already"
    new = _insert_after(content, REALTIME_ANCHOR, REALTIME_WRAPPER)
    if new is None or "fn=enforce_terms,\n" not in new:
        return content, "miss"
    return new.replace(
        "fn=enforce_terms,\n", "fn=_applio_realtime_toast,\n", 1
    ), "patched"


# Model information: run_model_information_script returns a ~10-line
# report (always far past toast length), so finish-only with a short
# message; the full report lands in the Output Information Textbox.
MODEL_INFO_WRAPPER = (
    f"    def _applio_model_info_toast(pth_path):  {MODEL_INFO_MARKER}\n"
    f"        result = run_model_information_script(pth_path)\n"
    f'        gr.Info(i18n("Model information loaded."))\n'
    f"        return result\n"
    "\n"
)


def patch_model_info(content):
    return _patch_tab_wrapper(
        content,
        MODEL_INFO_MARKER,
        MODEL_INFO_WRAPPER,
        "model_information",
        "_applio_model_info_toast",
        "def processing_tab():\n",
    )


def patch_tensorboard(content):
    """Toast when the TensorBoard URL resolves (launch_and_get_url's
    success branch); the failure branch still feeds the (hidden) URL
    Textbox only."""
    if TENSORBOARD_MARKER in content:
        return content, "already"
    old = '        if url and not url.startswith("Error"):\n            return (\n'
    if content.find(old) == -1:
        return content, "miss"
    new = (
        '        if url and not url.startswith("Error"):\n'
        f'            gr.Info(i18n("TensorBoard ready."))  {TENSORBOARD_MARKER}\n'
        "            return (\n"
    )
    return content.replace(old, new, 1), "patched"


# (repo-relative path, basename, sub-patch fn) - basename is unique per target
TARGETS = [
    ("tabs/voice_blender/voice_blender.py", "voice_blender.py", patch_voice_blender),
    ("tabs/plugins/plugins.py", "plugins.py", patch_plugins),
    ("tabs/realtime/realtime.py", "realtime.py", patch_realtime),
    ("tabs/extra/sections/processing.py", "processing.py", patch_model_info),
    ("tabs/tensorboard/tensorboard.py", "tensorboard.py", patch_tensorboard),
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
