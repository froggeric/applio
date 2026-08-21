"""Native macOS file/folder picker for Applio's accessibility Browse buttons.

Gradio event handlers run on worker threads; NSOpenPanel must run on the
main AppKit thread. native_browse() marshals the modal panel there with
AppHelper.callAfter and blocks the calling worker thread on an Event.

Availability is an EXPLICIT flag: PyObjC materializes a non-None NSApp proxy
even with no run loop, so "NSApp is None" cannot detect a headless/dev
process. The launcher calls mark_native_loop_available() during startup;
without it (plain `python app.py`, tests) native_browse reports
("unavailable", None) immediately instead of blocking for the timeout.
"""

import logging
import threading

PICK_TIMEOUT_S = 600  # user staring at the panel is normal; match wrapper norms

_native_loop_available = False


def mark_native_loop_available():
    """Called once by the native launcher at startup: an AppKit run loop now
    services AppHelper.callAfter, so panels can actually appear."""
    global _native_loop_available
    _native_loop_available = True


def pick_ui_config(mode):
    """Pure panel-config mapping. Raises ValueError on unknown mode."""
    if mode == "folder":
        return {"files": False, "dirs": True, "allowed": None}
    if mode == "file":
        return {"files": True, "dirs": False, "allowed": None}
    if mode == "pth":
        return {"files": True, "dirs": False, "allowed": ["pth"]}
    raise ValueError(f"unknown picker mode: {mode!r}")


def native_browse(mode, prompt=None, timeout=PICK_TIMEOUT_S):
    """Open a native NSOpenPanel. Returns ("ok", path) | ("cancel", None) |
    ("unavailable", None). Safe to call from any thread; never raises."""
    try:
        cfg = pick_ui_config(mode)
    except ValueError:
        logging.debug("[Picker] bad mode %r", mode)
        return ("unavailable", None)
    if not _native_loop_available:
        logging.debug("[Picker] no native loop (dev/test) - unavailable")
        return ("unavailable", None)
    try:
        from AppKit import NSOpenPanel
        from PyObjCTools import AppHelper
    except Exception as exc:  # pragma: no cover - AppKit always present in venv
        logging.debug("[Picker] AppKit unavailable: %s", exc)
        return ("unavailable", None)

    result = {}
    done = threading.Event()

    def _run_panel():
        try:
            panel = NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(cfg["files"])
            panel.setCanChooseDirectories_(cfg["dirs"])
            panel.setAllowsMultipleSelection_(False)
            panel.setResolvesAliases_(True)
            if cfg["allowed"]:
                panel.setAllowedFileTypes_(cfg["allowed"])
            if prompt:
                panel.setMessage_(prompt)
            response = panel.runModal()
            if response == 1 and panel.URLs():
                result["path"] = panel.URLs()[0].path()
        except Exception:
            logging.exception("[Picker] panel failed")
        finally:
            done.set()

    AppHelper.callAfter(_run_panel)
    if not done.wait(timeout=timeout):
        logging.debug("[Picker] timed out after %ss", timeout)
        return ("cancel", None)
    if "path" in result:
        return ("ok", result["path"])
    return ("cancel", None)
