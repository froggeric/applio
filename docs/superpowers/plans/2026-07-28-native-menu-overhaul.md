# Native macOS Menu Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two divergent native menus with one shared `menu_spec.py` rendered by a PyObjC renderer (launcher, full + dynamic) and a pywebview renderer (standalone wrapper, static subset); add Process/Help menus, Reveal-in-Finder, a real GitHub update check + silent launch-time check; delete the dead Menu B.

**Architecture:** A platform-neutral `menu_spec.py` (no AppKit import → unit-testable) describes the menu as `MenuItem` records keyed by stable action keys. Two thin renderers consume it: `render_pyobjc` (launcher, supports shortcuts + a 2 s timer-driven dynamic-items dict) and `render_pywebview` (standalone wrapper, static subset — pywebview menus are immutable and cannot bind shortcuts). A shared `applio_update_check.py` ports the existing GitHub check with a corrected `packaging.version` comparison, used by both the manual menu item and a launch-time daemon-thread check.

**Tech Stack:** Python 3.10 (`venv_macos`), PyObjC/AppKit, pywebview (WKWebView), PyInstaller, `packaging` (already bundled), `markdown` (build-time, likely already transitive via tensorboard).

**User decisions (already made):**
- Approach A: shared `menu_spec.py` + two renderers (full rebuild).
- Process menu is dashboard-only (no destructive controls in the menu bar).
- No Edit menu; no native Settings panel / `⌘,`.
- Manual `Check for Updates…` (tri-state) + silent launch-time check (alert only if newer).
- Help → Studio Production Guide (bundled HTML).
- Standalone wrapper mode is an accepted static subset.

**Spec:** `docs/superpowers/specs/2026-07-28-native-menu-overhaul-design.md` (v2, post-review).

**Repo constraints (from CLAUDE.md):** All files touched here are **fork-only** (`applio_launcher.py`, `macos_wrapper.py`, `menu_spec.py`, `applio_update_check.py`, `tests/`, `Applio.spec`, `build_macos.py`, `requirements_macos.txt`, docs) — edit directly, **no `patches/` needed, no upstream files**. `build_macos.py` runs the whole build at import time — **never `import build_macos`** to test; test helpers in isolation. After any build, `git status` must be clean.

**Line numbers are pristine-file hints, not anchors.** Every `~LNNNN` was verified against the current `applio_launcher.py` / `macos_wrapper.py` at plan-write time (commit `d58e61ba`). Tasks 3→5 edit `applio_launcher.py` top-to-bottom, so a line cited in Task 4/5 (e.g. `_update_menu_state`, `runEventLoop`) **shifts down** once Task 3 inserts code above it. Always locate an edit site by the **signature or literal string** given alongside the line number (e.g. `def _update_menu_state(self):`, the line `AppHelper.runEventLoop(installInterrupt=True)`, `patched_files = pre_build_patch()`), not by the number.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `menu_spec.py` | The single source of truth: `MenuItem` dataclass, `MENU`, action-key contracts (`LAUNCHER_ACTION_KEYS`, `WRAPPER_ACTION_KEYS`, `DISPLAY_KEYS`), `iter_leaves()`. **No AppKit import.** | NEW |
| `tests/test_menu_spec.py` | Pure-Python gate (no GUI): structure, taxonomy, key contracts, version-compare correctness, guide fallback. Runs with bare `python`. | NEW |
| `applio_update_check.py` | Shared update logic: `fetch_latest_release()`, `is_update_available()` (`packaging.version`, fail-safe), `check_for_updates_interactive()` (background-thread network + main-thread `NSAlert`). Constants `VERSION`/`GITHUB_REPO`/`RELEASES_URL`/`API_URL`. | NEW |
| `applio_launcher.py` | `render_pyobjc` + replace `_setup_menu` body; generalize `_update_menu_state` to a dynamic-items dict; add launcher action methods + `_resolve_data_dir()`; rewire `checkUpdates_`; add launch-time check. | MODIFY |
| `macos_wrapper.py` | `render_pywebview` replaces `get_native_menu()`; `SHOW_DEFAULT_MENUS=False`; delete dead Edit/no-op items; import shared update check. | MODIFY |
| `Applio.spec` | Add `STUDIO_PRODUCTION_GUIDE.html` (+ `.md` fallback) to `datas`. | MODIFY |
| `build_macos.py` | Idempotent `.md → .html` conversion step (skip if newer; fallback to `.md`). | MODIFY |
| `requirements_macos.txt` | Add `markdown` (hygiene). | MODIFY |
| `README_MACOS.md`, `FORK_DIFFERENCES.md`, `CLAUDE.md`, `CHANGELOG.md` | Document the new menu, shared-spec architecture, static standalone subset, update-check fix. | MODIFY |

---

## Task 1: `menu_spec.py` + structure test

**Goal:** Create the platform-neutral menu definition and a pure-Python test that locks its structure, taxonomy, and action-key contracts.

**Files:**
- Create: `menu_spec.py`
- Test: `tests/test_menu_spec.py`

**Acceptance Criteria:**
- [ ] `menu_spec.py` imports with **no AppKit/pywebview dependency** (importable under any Python 3.10).
- [ ] `iter_leaves(MENU)` yields exactly the action/display keys; top-level order is Applio, File, Process, Window, Help.
- [ ] No leaf key equals `"app.settings"`; no top-level title equals `"Edit"`.
- [ ] Every leaf key is in the taxonomy, in `LAUNCHER_ACTION_KEYS`, or in `DISPLAY_KEYS`; `LAUNCHER_ACTION_KEYS ⊆ leaf keys`; `WRAPPER_ACTION_KEYS = LAUNCHER_ACTION_KEYS − {app.about, app.hide, app.hide_others, app.quit}`.
- [ ] `venv_macos/bin/python tests/test_menu_spec.py` exits 0.

**Verify:** `venv_macos/bin/python tests/test_menu_spec.py` → `All menu_spec tests passed.` (exit 0)

**Steps:**

- [ ] **Step 1: Write the failing test**

```python
# tests/test_menu_spec.py
"""Pure-Python gate for menu_spec (no GUI, no AppKit). Run: python tests/test_menu_spec.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from menu_spec import (
    MENU, APP_NAME, APP_MENU_TITLE, PYWEBVIEW_APP_KEY,
    LAUNCHER_ACTION_KEYS, WRAPPER_ACTION_KEYS, DISPLAY_KEYS, TAXONOMY,
    iter_leaves,
)

EXPECTED_TOP_LEVEL = ["Applio", "File", "Process", "Window", "Help"]

def _titles_top_level():
    out = []
    for top in MENU:
        # top-level app menu may carry title via submenu title or APP_MENU_TITLE
        title = top.title or (APP_MENU_TITLE if _is_app_menu(top) else "")
        out.append(title)
    return out

def _is_app_menu(top):
    # The first top-level entry is the app menu (no own title; submenu present)
    return top is MENU[0]

def test_top_level_order():
    titles = _titles_top_level()
    assert titles == EXPECTED_TOP_LEVEL, f"top-level order wrong: {titles}"

def test_no_settings_no_edit():
    for leaf in iter_leaves(MENU):
        assert leaf.key != "app.settings", "app.settings must not exist"
    titles = [t.title for t in MENU]
    assert "Edit" not in titles, "no Edit menu"

def test_keys_are_known():
    # Action keys live in TAXONOMY; display-only items (e.g. process.status)
    # live in DISPLAY_KEYS. A leaf may belong to either.
    for leaf in iter_leaves(MENU):
        if not leaf.key:
            continue
        assert leaf.key in TAXONOMY or leaf.key in DISPLAY_KEYS, f"unknown key {leaf.key!r}"

def test_action_key_contracts():
    leaves = {leaf.key for leaf in iter_leaves(MENU) if leaf.key}
    # every leaf is either a launcher action, or a display-only item
    for k in leaves:
        assert k in LAUNCHER_ACTION_KEYS or k in DISPLAY_KEYS, f"orphan key {k!r}"
    # launcher handles all action keys
    assert LAUNCHER_ACTION_KEYS <= leaves, f"launcher keys missing from MENU: {LAUNCHER_ACTION_KEYS - leaves}"
    # wrapper is the launcher set minus the four pywebview-injected app-menu keys
    injected = {"app.about", "app.hide", "app.hide_others", "app.quit"}
    assert WRAPPER_ACTION_KEYS == LAUNCHER_ACTION_KEYS - injected, "wrapper contract mismatch"
    assert injected <= LAUNCHER_ACTION_KEYS, "injected keys must be in launcher set"

def test_display_keys_are_dynamic():
    for leaf in iter_leaves(MENU):
        if leaf.key in DISPLAY_KEYS:
            assert leaf.dynamic, f"display key {leaf.key!r} must be dynamic"

def test_app_menu_const():
    assert PYWEBVIEW_APP_KEY == "__app__"
    assert APP_NAME == "Applio"

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll menu_spec tests passed ({len(fns)}).")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv_macos/bin/python tests/test_menu_spec.py`
Expected: `ModuleNotFoundError: No module named 'menu_spec'`

- [ ] **Step 3: Write `menu_spec.py`**

```python
# menu_spec.py
"""The single source of truth for Applio's native macOS menu.

Platform-neutral: NO AppKit/pywebview imports, so it is unit-testable under any
Python 3.10. Two thin renderers consume MENU:
  - render_pyobjc  (launcher): full menu, shortcuts, dynamic items (NSTimer-driven)
  - render_pywebview (standalone wrapper): static subset (pywebview Menu is immutable
    and cannot bind shortcuts; pywebview auto-injects the standard app-menu items).

See docs/superpowers/specs/2026-07-28-native-menu-overhaul-design.md.
"""
from dataclasses import dataclass, field

APP_NAME = "Applio"
APP_MENU_TITLE = "Applio"          # PyObjC renderer: bold app-name menu
PYWEBVIEW_APP_KEY = "__app__"      # pywebview renderer: literal title for the app menu

# Modifier tokens (renderer translates to platform masks). Keeps this module AppKit-free.
def CMD():     return ("cmd",)
def SHIFT():   return ("shift",)
def OPTION():  return ("option",)

@dataclass
class MenuItem:
    key: str = ""                       # action key; "" for pure separators
    title: str = ""
    shortcut: str = ""                  # key equivalent e.g. "q", "p" (PyObjC only)
    mods: tuple = ()                    # ("cmd",) / ("cmd","shift") / ("cmd","option") (PyObjC only)
    dynamic: str = ""                   # launcher-only hint: "status" | "exists:<subpath>" | ""
    submenu: list = field(default_factory=list)
    separator: bool = False


# ---- Action-key taxonomy ---------------------------------------------------
APP_KEYS = {"app.about", "app.check_updates", "app.hide", "app.hide_others", "app.quit"}
FILE_KEYS = {
    "file.set_data_location", "file.reveal_logs", "file.reveal_datasets",
    "file.reveal_pretraineds", "file.reveal_inference", "file.reveal_root",
}
PROCESS_KEYS = {"process.open_dashboard", "process.open_logs"}
WINDOW_KEYS = {"window.minimize", "window.zoom", "window.show_main", "window.bring_all_to_front"}
HELP_KEYS = {"help.guide", "help.docs", "help.report_issue", "help.discord"}
TAXONOMY = APP_KEYS | FILE_KEYS | PROCESS_KEYS | WINDOW_KEYS | HELP_KEYS

# Display-only items (no dispatch; rendered disabled, mutated by the launcher timer).
DISPLAY_KEYS = {"process.status"}

# Keys the launcher renderer must wire dispatch for.
LAUNCHER_ACTION_KEYS = (APP_KEYS | FILE_KEYS | PROCESS_KEYS | WINDOW_KEYS | HELP_KEYS) - set()
# Standalone wrapper handles everything EXCEPT the four app-menu items pywebview injects
# (About / Hide / Hide Others / Quit). Verified: webview/platforms/cocoa.py _add_app_menu
# runs unconditionally and provides those.
WRAPPER_ACTION_KEYS = LAUNCHER_ACTION_KEYS - {"app.about", "app.hide", "app.hide_others", "app.quit"}

# Reveal targets (relative to the resolved data dir).
REVEAL_PATHS = {
    "file.reveal_logs": "logs",
    "file.reveal_datasets": "assets/datasets",
    "file.reveal_pretraineds": "rvc/models/pretraineds",
    "file.reveal_inference": "assets/audios",
    "file.reveal_root": "",
}

# Standard AppKit selectors handled by the responder chain / NSApp (no custom target).
# Shared so both renderers agree which keys are "system" actions. Every standard
# selector key MUST appear here, or _fill_ns_menu renders it disabled with no action.
STANDARD_SELECTOR_KEYS = {
    "app.hide": "hide:",
    "app.hide_others": "hideOtherApplications:",   # ⌥⌘H — NSApp responder chain
    "app.quit": "terminate:",
    "window.minimize": "performMiniaturize:",
    "window.zoom": "performZoom:",
    "window.bring_all_to_front": "arrangeInFront:",
}

# ---- THE menu --------------------------------------------------------------
MENU = [
    # App menu (first). PyObjC: untitled top-level item -> bold app menu.
    #            pywebview: renderer wraps this submenu with title "__app__".
    MenuItem(submenu=[
        MenuItem(key="app.about", title="About Applio"),
        MenuItem(separator=True),
        MenuItem(key="app.check_updates", title="Check for Updates…"),
        MenuItem(separator=True),
        MenuItem(key="app.hide", title="Hide Applio", shortcut="h", mods=("cmd",)),
        MenuItem(key="app.hide_others", title="Hide Others", shortcut="h", mods=("cmd", "option")),
        MenuItem(separator=True),
        MenuItem(key="app.quit", title="Quit Applio", shortcut="q", mods=("cmd",)),
    ]),
    MenuItem(title="File", submenu=[
        MenuItem(key="file.set_data_location", title="Set Data Location…"),
        MenuItem(separator=True),
        MenuItem(title="Reveal in Finder", submenu=[
            MenuItem(key="file.reveal_logs", title="Training Models (logs/)", dynamic="exists:logs"),
            MenuItem(key="file.reveal_datasets", title="Datasets", dynamic="exists:assets/datasets"),
            MenuItem(key="file.reveal_pretraineds", title="Pretrained Models", dynamic="exists:rvc/models/pretraineds"),
            MenuItem(key="file.reveal_inference", title="Inference Outputs", dynamic="exists:assets/audios"),
            MenuItem(separator=True),
            MenuItem(key="file.reveal_root", title="Root Data Folder"),
        ]),
    ]),
    MenuItem(title="Process", submenu=[
        MenuItem(key="process.status", title="No active processes", dynamic="status"),
        MenuItem(separator=True),
        MenuItem(key="process.open_dashboard", title="Open Progress Dashboard", shortcut="p", mods=("cmd", "shift")),
        MenuItem(key="process.open_logs", title="Open Training Logs…"),
    ]),
    MenuItem(title="Window", submenu=[
        MenuItem(key="window.minimize", title="Minimize", shortcut="m", mods=("cmd",)),
        MenuItem(key="window.zoom", title="Zoom"),
        MenuItem(separator=True),
        MenuItem(key="window.show_main", title="Show Main Window"),
        MenuItem(key="window.bring_all_to_front", title="Bring All to Front"),
    ]),
    MenuItem(title="Help", submenu=[
        MenuItem(key="help.guide", title="Studio Production Guide"),
        MenuItem(key="help.docs", title="Applio Help"),
        MenuItem(key="help.report_issue", title="Report an Issue"),
        MenuItem(separator=True),
        MenuItem(key="help.discord", title="Applio Discord"),
    ]),
]


def iter_leaves(menu):
    """Yield every non-separator MenuItem at any depth."""
    for item in menu:
        if item.separator:
            continue
        if item.submenu:
            yield from iter_leaves(item.submenu)
        else:
            yield item
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv_macos/bin/python tests/test_menu_spec.py`
Expected: `All menu_spec tests passed (6).` (exit 0)

- [ ] **Step 5: Commit**

```bash
git add menu_spec.py tests/test_menu_spec.py
git commit -m "feat(menu): add platform-neutral menu_spec + structure test"
```

---

## Task 2: `applio_update_check.py` + version-compare test

**Goal:** Port the existing GitHub update check into a shared module with a corrected `packaging.version` comparison, and lock the comparison with tests.

**Files:**
- Create: `applio_update_check.py`
- Modify: `tests/test_menu_spec.py` (append version-compare tests)
- Reference (port source): `macos_wrapper.py:729-830` (`check_for_updates`), `197-229` (`_get_version_info`, constants)

**Acceptance Criteria:**
- [ ] `is_update_available(current)` returns `(True, latest, url)` only when `latest > current` via `packaging.version.parse`; unparseable tags → `(False, …)` (fail-safe).
- [ ] `fetch_latest_release()` returns the parsed JSON dict or `None` on network/HTTP/JSON error (no raise).
- [ ] `check_for_updates_interactive()` runs the network call on a background thread and shows the `NSAlert` on the main thread (no event-loop blocking).
- [ ] `VERSION`/`GITHUB_REPO`/`RELEASES_URL`/`API_URL` resolve identically to today (`_get_version_info` ported verbatim).
- [ ] Appended tests pass: `3.6.9`→`3.6.10` True; equal False; `3.6.9`→`3.6.8` False; `v3.6.3-rc1`/`latest` → False.

**Verify:** `venv_macos/bin/python tests/test_menu_spec.py` → exit 0 (incl. version-compare tests).

**Steps:**

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_menu_spec.py` (before the `__main__` block):

```python
# ---- version-compare tests (applio_update_check) ----
from applio_update_check import is_update_available

def test_update_available_basic():
    assert is_update_available("3.6.9", "3.6.10")[0] is True

def test_update_equal():
    assert is_update_available("3.6.9", "3.6.9")[0] is False

def test_update_downgrade():
    assert is_update_available("3.6.9", "3.6.8")[0] is False

def test_update_double_digit():
    # lexical string compare would get this wrong: "3.6.10" > "3.6.9"
    assert is_update_available("3.6.9", "3.6.10")[0] is True
    assert is_update_available("3.6.10", "3.6.9")[0] is False

def test_update_malformed_tag_failsafe():
    assert is_update_available("3.6.9", "v3.6.3-rc1")[0] is False
    assert is_update_available("3.6.9", "latest")[0] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv_macos/bin/python tests/test_menu_spec.py`
Expected: `ModuleNotFoundError: No module named 'applio_update_check'`

- [ ] **Step 3: Write `applio_update_check.py`**

```python
# applio_update_check.py
"""Shared GitHub update check for Applio (fork-only).

Used by:
  - the launcher's manual "Check for Updates…" menu item (tri-state NSAlert)
  - the launcher's silent launch-time check (alert only if newer)

Ports macos_wrapper.py:check_for_updates() but FIXES the version comparison:
the original used a string `!=` (macos_wrapper.py:806) which flagged downgrades
as updates and mis-handled 3.6.10 vs 3.6.9. We use packaging.version (already a
PyInstaller hiddenimport — Applio.spec).
"""
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request

try:
    from packaging.version import parse as _parse_version
except Exception:  # pragma: no cover - packaging is bundled, but stay safe
    _parse_version = None


def _get_version_info():
    """Read the full build version from build_info.json (ported verbatim from
    macos_wrapper.py:197)."""
    for _rel in ("build_info.json", os.path.join("assets", "build_info.json")):
        _candidate = os.path.join(_base_path(), _rel)
        try:
            with open(_candidate, "r", encoding="utf-8") as f:
                _info = json.load(f)
                _full = _info.get("full_version") or _info.get("version")
                if _full:
                    return _full
        except Exception:
            continue
    for _cfg in ("assets/config.json", "assets/config_template.json"):
        try:
            with open(os.path.join(_base_path(), _cfg), "r", encoding="utf-8") as f:
                return json.load(f).get("version", "3.6.3")
        except Exception:
            continue
    return "3.6.3"


def _base_path():
    """Frozen-CWD-safe base (sys._MEIPASS when frozen, else this file's dir).
    `sys` is imported at module top (used at call time, not import time)."""
    return getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))


VERSION = _get_version_info()
GITHUB_REPO = "froggeric/applio-macOS-native-app"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def is_update_available(current_version, latest_version=None, release_url=None):
    """Return (bool, latest_version, release_url).

    If latest_version is None, only does the comparison (used by tests + the
    launch-time check after a fetch). Fail-safe: unparseable tags => no update.
    """
    if not latest_version or not current_version:
        return (False, latest_version, release_url or RELEASES_URL)
    if _parse_version is None:
        # Without packaging, fall back to a strict "different AND not a downgrade
        # heuristic" — but packaging is bundled, so this is defensive only.
        return (latest_version != current_version, latest_version, release_url or RELEASES_URL)
    try:
        return (_parse_version(latest_version) > _parse_version(current_version),
                latest_version, release_url or RELEASES_URL)
    except Exception:
        return (False, latest_version, release_url or RELEASES_URL)


def fetch_latest_release():
    """GET the latest release JSON from GitHub. Returns dict or None on error."""
    try:
        request = urllib.request.Request(
            API_URL, headers={"User-Agent": f"Applio/{VERSION}"}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logging.warning(f"[Update] HTTP error: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        logging.warning(f"[Update] network error: {e.reason}")
    except json.JSONDecodeError as e:
        logging.warning(f"[Update] bad JSON: {e}")
    except Exception as e:
        logging.warning(f"[Update] failed: {e}")
    return None


def _fetch_result():
    """Return (latest_version, release_url, error_message)."""
    data = fetch_latest_release()
    if data is None:
        return (None, RELEASES_URL, "Could not reach GitHub.")
    tag = (data.get("tag_name") or "").lstrip("v")
    return (tag or None, data.get("html_url", RELEASES_URL), None)


def _run_async_on_main(work, on_main):
    """Run blocking `work()` on a daemon thread; pass its result to `on_main()`
    on the main thread via AppHelper.callAfter. Wraps work in an NSAutoreleasePool."""
    import threading

    def _runner():
        result = None
        try:
            from Foundation import NSAutoreleasePool
            pool = NSAutoreleasePool.alloc().init()
            try:
                result = work()
            finally:
                del pool
        except ImportError:
            result = work()
        except Exception as e:
            logging.error(f"[Update] background work failed: {e}")
            result = None
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(on_main, result)
        except Exception:
            on_main(result)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()


def check_for_updates_interactive():
    """Manual menu item: tri-state NSAlert. Network runs off the main thread so
    the 2 s menu timer / event loop never blocks (worst case = the 10 s timeout)."""
    try:
        from AppKit import (NSAlert, NSAlertFirstButtonReturn, NSAlertStyleInformational,
                            NSAlertStyleWarning)
        from PyObjCTools import AppHelper
    except ImportError:
        logging.warning("[Update] AppKit unavailable; skipping interactive check")
        return

    def _on_main(result):
        latest_version, release_url, error_message = result
        alert = NSAlert.alloc().init()
        if error_message or not latest_version:
            alert.setMessageText_("Could Not Check for Updates")
            alert.setInformativeText_(
                f"An error occurred while checking for updates.\n\n"
                f"{error_message or 'No release tag found.'}\n\n"
                "You can manually check for updates on GitHub."
            )
            alert.addButtonWithTitle_("Open GitHub Releases")
            alert.addButtonWithTitle_("OK")
            alert.setAlertStyle_(NSAlertStyleWarning)
            if alert.runModal() == NSAlertFirstButtonReturn:
                subprocess.Popen(['open', release_url])
        elif is_update_available(VERSION, latest_version, release_url)[0]:
            alert.setMessageText_("Update Available")
            alert.setInformativeText_(
                f"A new version of Applio is available.\n\n"
                f"Current version: v{VERSION}\n"
                f"Latest version: v{latest_version}\n\n"
                "Would you like to download the update?"
            )
            alert.addButtonWithTitle_("Download Update")
            alert.addButtonWithTitle_("Later")
            alert.setAlertStyle_(NSAlertStyleInformational)
            if alert.runModal() == NSAlertFirstButtonReturn:
                subprocess.Popen(['open', release_url])
        else:
            alert.setMessageText_("You're Up to Date")
            alert.setInformativeText_(
                f"Applio is running the latest version.\n\nVersion {VERSION}"
            )
            alert.addButtonWithTitle_("OK")
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.runModal()

    _run_async_on_main(_fetch_result, _on_main)


def check_for_updates_at_launch():
    """Silent unless a newer version exists. Network on a daemon thread; the alert
    (if any) is shown on the main thread."""
    def _on_main(result):
        latest_version, release_url, error_message = result
        if error_message or not latest_version:
            return  # silent on error / offline
        available, _, url = is_update_available(VERSION, latest_version, release_url)
        if not available:
            return  # silent when up to date
        try:
            from AppKit import NSAlert, NSAlertFirstButtonReturn, NSAlertStyleInformational
        except ImportError:
            return
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Update Available")
        alert.setInformativeText_(
            f"A new version of Applio is available (v{latest_version}).\n\n"
            f"You are running v{VERSION}."
        )
        alert.addButtonWithTitle_("Open GitHub Releases")
        alert.addButtonWithTitle_("Later")
        alert.setAlertStyle_(NSAlertStyleInformational)
        if alert.runModal() == NSAlertFirstButtonReturn:
            subprocess.Popen(['open', url])

    _run_async_on_main(_fetch_result, _on_main)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv_macos/bin/python tests/test_menu_spec.py`
Expected: `All menu_spec tests passed (11).` (exit 0)

- [ ] **Step 5: Commit**

```bash
git add applio_update_check.py tests/test_menu_spec.py
git commit -m "feat(update): shared update check with packaging.version compare"
```

---

## Task 3: Launcher PyObjC renderer + action wiring

**Goal:** Render `MENU` with PyObjC in the launcher (shortcuts + standard selectors + a tag-based custom dispatch), replace `_setup_menu`'s hand-built body, add the launcher action methods (hide/zoom/guide/reveal/open-logs + `_resolve_data_dir`), and rewire `checkUpdates_` to the shared interactive check. Disable data-location/reveal until first-run completes.

**Files:**
- Modify: `applio_launcher.py`
  - AppKit import block (~L79): add `NSAlternateKeyMask`
  - `MenuActionHandler` (~L2836-2902): add `runDispatch_:` + `_dispatch_table`
  - `_setup_menu` (~L3405-3534): replace the hand-built body with a spec-driven build
  - new module-level helpers `_mods_to_mask`, `_fill_ns_menu`, `_find_item_by_tag`
  - new launcher methods: `_resolve_data_dir`, `_first_run_done`, `_reveal`, `_open_guide`, `_open_training_logs`, `_open_url`, and standard-action wiring for hide/zoom/show-main/bring-to-front
  - `checkUpdates_` (~L3726): rewire to `applio_update_check.check_for_updates_interactive()`
  - `setDataLocation_` (~L3743): guard on `_first_run_done()`

**Acceptance Criteria:**
- [ ] Running the launcher shows the full menu in order Applio/File/Process/Window/Help with working shortcuts ⌘Q, ⌘H, ⌥⌘H, ⌘M, ⌘⇧P.
- [ ] `Check for Updates…` opens the real tri-state alert (no longer the passive "visit the URL" alert).
- [ ] `File → Set Data Location…` and `Reveal in Finder ▸` are **disabled** until the wrapper has completed first-run (`runtime_paths.json` exists); after first-run they enable and reveal resolves the **current** data dir (fresh per click).
- [ ] `Help → Studio Production Guide` opens the bundled HTML (once Task 7 lands; before then it logs a clear "guide not bundled" warning and does not crash).
- [ ] `git status` is clean (no upstream files touched).

**Verify:** Launch from a foreground terminal: `venv_macos/bin/python applio_launcher.py` → menu bar shows Applio/File/Process/Window/Help; ⌘H hides, ⌘Q quits with the training confirmation if a job is active. Then `git status -sb` → clean.

**Steps:**

- [ ] **Step 1: Add `NSAlternateKeyMask` to the AppKit import**

In `applio_launcher.py` ~L79, the import already includes `NSCommandKeyMask, NSShiftKeyMask`. Add `NSAlternateKeyMask` to that same `from AppKit import (...)` list.

- [ ] **Step 2: Add module-level renderer helpers** (place just above the `MenuActionHandler` class ~L2833)

```python
def _mods_to_mask(mods):
    """Translate menu_spec mod tokens to a PyObjC key-equivalent modifier mask."""
    from AppKit import NSCommandKeyMask, NSShiftKeyMask, NSAlternateKeyMask
    mask = 0
    if "cmd" in mods:
        mask |= NSCommandKeyMask
    if "shift" in mods:
        mask |= NSShiftKeyMask
    if "option" in mods:
        mask |= NSAlternateKeyMask
    return mask


def _fill_ns_menu(spec_menu, ns_menu, target, dispatch, tag_counter, dynamic_out, key_to_tag=None):
    """Fill the passed-in `ns_menu` with items from a list of menu_spec.MenuItem.

    Recursion: submenus are built by calling _fill_ns_menu on a fresh NSMenu
    (no item-by-item moving). The FIRST top-level submenu is the app menu; leave
    it UNTITLED so macOS renders the bold app name from the bundle (matches the
    original _setup_menu + spec §5.1 — do NOT setTitle_ it).

    Per leaf:
    - dispatch[key] == str  -> standard AppKit selector, target None (responder chain)
    - dispatch[key] callable -> tagged item, action runDispatch:, target = target;
      also records key_to_tag[key] = tag (so the timer can find items by action key)
    - dispatch[key] missing  -> display-only item (e.g. process.status): disabled, no action
    - dynamic items are recorded in dynamic_out[key] = (ns_item, hint)
    """
    from AppKit import NSMenuItem
    for mi in spec_menu:
        if mi.separator:
            ns_menu.addItem_(NSMenuItem.separatorItem())
            continue
        if mi.submenu:
            from AppKit import NSMenu
            sub = NSMenu.alloc().init()
            if mi.title:
                sub.setTitle_(mi.title)
            _fill_ns_menu(mi.submenu, sub, target, dispatch, tag_counter, dynamic_out, key_to_tag)
            parent_item = NSMenuItem.alloc().init()
            parent_item.setSubmenu_(sub)
            ns_menu.addItem_(parent_item)
            continue
        # leaf
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            mi.title, "", mi.shortcut or ""
        )
        if mi.shortcut and mi.mods:
            item.setKeyEquivalentModifierMask_(_mods_to_mask(mi.mods))
        handler = dispatch.get(mi.key)
        if isinstance(handler, str):
            item.setAction_(handler)
            item.setTarget_(None)
        elif callable(handler):
            tag = next(tag_counter)
            item.setTag_(tag)
            item.setAction_("runDispatch:")
            item.setTarget_(target)
            target._dispatch_table[tag] = handler
            if key_to_tag is not None and mi.key:
                key_to_tag[mi.key] = tag
        else:
            # display-only (status) item: disabled, no action
            item.setEnabled_(False)
        if mi.dynamic and mi.key:
            dynamic_out[mi.key] = (item, mi.dynamic)
        ns_menu.addItem_(item)
```

- [ ] **Step 3: Add `runDispatch_` + `_dispatch_table` to `MenuActionHandler`** (~L2836, in `initWithLauncher_`)

In `MenuActionHandler.initWithLauncher_`, after `self._launcher_ref = weakref.ref(launcher)`, add:
```python
            self._dispatch_table = {}
```
Add a new method to the class:
```python
    def runDispatch_(self, sender):
        """Generic menu dispatch keyed by the NSMenuItem's tag."""
        fn = getattr(self, "_dispatch_table", {}).get(sender.tag() if sender else None)
        if callable(fn):
            try:
                fn()
            except Exception as e:
                logging.error(f"[Launcher] menu dispatch failed: {e}")
```

- [ ] **Step 4: Replace the hand-built body of `_setup_menu`** (~L3430-3534, keep the app/delegate setup at the top of the method)

Keep everything in `_setup_menu` up to and including `app.setDelegate_(self._app_delegate)` and `app.setActivationPolicy_(...)` (this includes the existing `if not self._menu_handler: self._menu_handler = MenuActionHandler.alloc().initWithLauncher_(self)` block, so the handler already exists here). Replace the menu construction (from `main_menu = NSMenu.alloc().init()` through `NSApp.setMainMenu_(main_menu)`) with:

```python
        import itertools
        from AppKit import NSMenu

        self._dynamic_items = {}   # action_key -> (NSMenuItem, hint); mutated by the 2 s timer
        self._key_to_tag = {}      # action_key -> NSMenuItem tag; lets the timer find items
        tag_counter = itertools.count(1)
        dispatch = self._build_launcher_dispatch()

        main_menu = NSMenu.alloc().init()
        _fill_ns_menu(
            menu_spec.MENU, main_menu, self._menu_handler, dispatch,
            tag_counter, self._dynamic_items, self._key_to_tag,
        )
        # The FIRST top-level submenu (MENU[0]) was built with no title on purpose:
        # an untitled first main-menu submenu is rendered by macOS as the bold
        # app-name menu (from CFBundleName). Do NOT setTitle_ it — that contradicts
        # spec §5.1 and the original _setup_menu behavior.

        NSApp.setMainMenu_(main_menu)
        self._update_menu_state()
        self._start_menu_update_timer()
        logging.info("[Launcher] Menu bar setup complete (spec-driven)")
```

At the top of `applio_launcher.py` add `import menu_spec` to the module imports (it is AppKit-free, so a top-level import is safe). All menu_spec references below use the `menu_spec.X` form.

Delete the now-unused `self.progress_menu_item = ...` assignment in `_setup_menu` (~L3495) AND the `self.progress_menu_item = None` initializer in `__init__` (~L3030); remove its remaining uses (they are all inside the old `_update_menu_state`, which Task 4 replaces). If you are doing Task 3 without Task 4 yet, leave a stub `self.progress_menu_item = None` in `__init__` until Task 4 removes the last reference.

- [ ] **Step 5: Add `_build_launcher_dispatch` + action methods** to `ApplioLauncher` (near the other menu action methods ~L3678)

```python
    def _build_launcher_dispatch(self):
        """Map action keys -> handler (callable) or standard selector (str).

        IMPORTANT: every callable is invoked by runDispatch_ as `fn()` with NO
        arguments. The AppKit-style methods (showAbout_/checkUpdates_/etc.) are
        defined as `def X_(self, sender)`, so they MUST be wrapped to drop sender.
        """
        d = {}
        # Standard AppKit actions (responder chain / NSApp) — these use the
        # selector string form, so they never go through runDispatch_.
        for key, sel in menu_spec.STANDARD_SELECTOR_KEYS.items():
            d[key] = sel
        # Custom actions — ALL zero-arg callables.
        d["app.about"] = lambda: self.showAbout_(None)
        d["app.check_updates"] = lambda: self.checkUpdates_(None)
        d["file.set_data_location"] = lambda: self.setDataLocation_(None)
        d["process.open_dashboard"] = lambda: self.showProgressMonitor_(None)
        d["process.open_logs"] = self._open_training_logs     # already zero-arg
        d["window.show_main"] = lambda: self.showMainWindow_(None)
        d["help.guide"] = self._open_guide                     # already zero-arg
        d["help.docs"] = lambda: self._open_url("https://docs.applio.org")
        d["help.report_issue"] = lambda: self._open_url("https://github.com/froggeric/applio-macOS-native-app/issues")
        d["help.discord"] = lambda: self._open_url("https://discord.gg/IAHispano")
        for key in ("file.reveal_logs", "file.reveal_datasets", "file.reveal_pretraineds",
                    "file.reveal_inference", "file.reveal_root"):
            d[key] = (lambda k=key: self._reveal(k))
        return d

    def _resolve_data_dir(self):
        """Fresh data-dir resolution (env -> runtime_paths.json -> ~/Applio).
        NOT a captured startup value (the env var is stale until restart)."""
        env = os.environ.get("APPLIO_DATA_PATH")
        if env:
            return env
        for cfg in (os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
                    os.path.expanduser("~/.applio/runtime_paths.json")):
            if os.path.exists(cfg):
                try:
                    with open(cfg, "r") as f:
                        dp = json.load(f).get("data_path")
                        if dp:
                            return dp
                except (json.JSONDecodeError, IOError):
                    pass
        return os.path.expanduser("~/Applio")

    def _first_run_done(self):
        """True once the wrapper has written runtime_paths.json (first-run complete)."""
        for cfg in (os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
                    os.path.expanduser("~/.applio/runtime_paths.json")):
            if os.path.exists(cfg):
                return True
        return False

    def _reveal(self, action_key):
        sub = menu_spec.REVEAL_PATHS.get(action_key, "")
        path = os.path.join(self._resolve_data_dir(), sub) if sub else self._resolve_data_dir()
        try:
            os.makedirs(path, exist_ok=True)
            subprocess.Popen(["open", path])
        except Exception as e:
            logging.error(f"[Launcher] reveal {action_key} failed: {e}")

    def _open_training_logs(self):
        logs = os.path.expanduser("~/Library/Logs/Applio")
        try:
            subprocess.Popen(["open", logs])
        except Exception as e:
            logging.error(f"[Launcher] open logs failed: {e}")

    def _open_guide(self):
        path = os.path.join(BASE_PATH, "STUDIO_PRODUCTION_GUIDE.html")
        if not os.path.exists(path):
            path = os.path.join(BASE_PATH, "STUDIO_PRODUCTION_GUIDE.md")
        if not os.path.exists(path):
            logging.warning("[Launcher] Studio Production Guide is not bundled")
            return
        try:
            subprocess.Popen(["open", path])
        except Exception as e:
            logging.error(f"[Launcher] open guide failed: {e}")

    def _open_url(self, url):
        try:
            subprocess.Popen(["open", url])
        except Exception as e:
            logging.error(f"[Launcher] open url failed: {e}")
```

Add a tiny import shim near the top of the file (after the existing imports) so the dispatch can reference the shared module without a heavy import at module load:
```python
def _update_check():
    import applio_update_check
    return applio_update_check
```

- [ ] **Step 6: Rewire `checkUpdates_` and guard `setDataLocation_`**

Locate `checkUpdates_` by signature (`def checkUpdates_(self, sender):` — the method whose body currently builds a passive "visit the URL" `NSAlert`; it is NOT the `MenuActionHandler.checkUpdates_` forwarder). Replace its body with:
```python
    def checkUpdates_(self, sender):
        """Check for updates — real GitHub check (shared module)."""
        _update_check().check_for_updates_interactive()
```

In `setDataLocation_` (`def setDataLocation_(self, sender):`), immediately after the existing `if not NATIVE_APIS_AVAILABLE: return` guard, add:
```python
        if not self._first_run_done():
            from AppKit import NSAlert, NSAlertStyleInformational
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Choose a Data Location First")
            alert.setInformativeText_(
                "Applio is asking you to choose where to store its data. "
                "Please complete that prompt first, then you can change it here."
            )
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.addButtonWithTitle_("OK")
            alert.runModal()
            return
```

- [ ] **Step 7: Update the static import list + verify**

Add `import menu_spec` to the module imports in `applio_launcher.py` (AppKit-free, so a direct top-level import is safe — no try/except needed). Confirm `BASE_PATH`, `json`, `subprocess`, `logging`, `os` are already imported (they are: `os`/`logging`/`subprocess`/`json` at L23-54, `BASE_PATH` at L132/135).

- [ ] **Step 8: Smoke-test and commit**

Run: `venv_macos/bin/python applio_launcher.py` (foreground). Confirm menu order + shortcuts + `Check for Updates…` shows the real alert + data items disabled before first-run. Quit. Then:
```bash
git status -sb   # expect clean (only applio_launcher.py modified)
git add applio_launcher.py
git commit -m "feat(menu): spec-driven PyObjC launcher menu + shared update check"
```

---

## Task 4: Launcher dynamic state (generalize `_update_menu_state`)

**Goal:** Drive `process.status` and the `exists:` reveal items from the 2 s timer via the `self._dynamic_items` dict.

**Files:**
- Modify: `applio_launcher.py` — the method defined as `def _update_menu_state(self):` (was at L3634 in the pristine file; Task 3 added code above it, so locate by signature, not line number).

**Acceptance Criteria:**
- [ ] With no active job, Process menu shows `No active processes`; with a running training job it shows `● Training: <model_name>` (no epoch/ETA).
- [ ] The `process.status` line stays **disabled** (it is a status line with no action); only its title changes.
- [ ] `Reveal in Finder ▸ → Inference Outputs` is disabled until `<data_dir>/assets/audios` exists; enabled once it does. Other reveal items follow their `exists:` path.
- [ ] The 2 s timer never raises (missing items are skipped gracefully).

**Verify:** Launch the app, start a training run → Process menu status line updates to `● Training: <name>` within ~2 s; create `<data_dir>/assets/audios` → Inference Outputs enables. No exceptions in `~/Library/Logs/Applio/`.

**Steps:**

- [ ] **Step 1: Rewrite `_update_menu_state`** (locate by `def _update_menu_state(self):`; keep the existing IPC-signal + wrapper-hidden handling that opens the dashboard/progress window, replace only the `self.progress_menu_item` tail with the dynamic-items logic below)

```python
    def _update_menu_state(self):
        """Update dynamic menu items from the 2 s timer."""
        # Keep existing IPC + hidden-window handling (was already here).
        if self._check_show_progress_monitor_signal():
            try:
                if not self._dashboard_controller:
                    self._create_dashboard()
                if self._dashboard_controller:
                    self._dashboard_controller.update_process_list()
                    self._dashboard_controller.show()
            except Exception as e:
                logging.error(f"[Launcher] dashboard via IPC failed: {e}")
        if self._check_wrapper_window_hidden():
            active = get_active_processes()
            if active:
                try:
                    self._show_progress_window_for_processes(active)
                except Exception as e:
                    logging.error(f"[Launcher] progress window failed: {e}")

        dyn = getattr(self, "_dynamic_items", {})
        if not dyn:
            return

        # process.status — TITLE ONLY (a display line; built disabled, stays disabled).
        # model_name from active_processes.json (no epoch/ETA; those require log parsing
        # that belongs in the dashboard, not the menu).
        status = dyn.get("process.status")
        if status:
            item, _hint = status
            active = get_active_processes()
            if active:
                name = (active[0].get("model_name") or "active job").strip() or "active job"
                item.setTitle_(f"● Training: {name}")
            else:
                item.setTitle_("No active processes")

        first_run = self._first_run_done()
        data_dir = self._resolve_data_dir() if first_run else None
        # Drive exists:<subpath> reveal items + first-run gating. SKIP status items
        # here — their enabled state is "disabled" (set at build time) and must not
        # be flipped on by the else branch.
        for key, (item, hint) in dyn.items():
            if hint == "status":
                continue
            if not first_run:
                item.setEnabled_(False)
                continue
            if hint and hint.startswith("exists:"):
                sub = hint.split("exists:", 1)[1]
                item.setEnabled_(os.path.exists(os.path.join(data_dir, sub)))
            else:
                item.setEnabled_(True)
        # set_data_location is a callable-dispatch item but not dynamic-flagged; gate it directly.
        sdl = self._find_item_by_key("file.set_data_location")
        if sdl is not None:
            sdl.setEnabled_(first_run)
```

- [ ] **Step 2: Add `_find_item_by_key` + module-level walker**

`self._key_to_tag` is already populated during menu build (Task 3 Step 2's `_fill_ns_menu` fills it; Task 3 Step 4 passes `self._key_to_tag` in). So the helper is just a tag lookup + menu walk:

```python
    def _find_item_by_key(self, key):
        """Find the live NSMenuItem for an action key via self._key_to_tag, else None."""
        target_tag = getattr(self, "_key_to_tag", {}).get(key)
        if target_tag is None:
            return None
        from AppKit import NSApp
        main = NSApp.mainMenu()
        return _find_item_by_tag(main, target_tag)
```

Module-level walker (place near `_fill_ns_menu`):
```python
def _find_item_by_tag(ns_menu, tag):
    for i in range(ns_menu.numberOfItems()):
        item = ns_menu.itemAtIndex_(i)
        if item.tag() == tag and item.action() is not None:
            return item
        sub = item.submenu()
        if sub:
            found = _find_item_by_tag(sub, tag)
            if found is not None:
                return found
    return None
```

- [ ] **Step 3: Smoke-test and commit**

Run: `venv_macos/bin/python applio_launcher.py`; start training → status line + reveal enabling behave. `git status -sb` clean.
```bash
git add applio_launcher.py
git commit -m "feat(menu): dynamic Process status + reveal exists-state from timer"
```

---

## Task 5: Launch-time update check

**Goal:** On launcher startup, silently check GitHub on a daemon thread and alert only if newer.

**Files:**
- Modify: `applio_launcher.py` `run()` — the line `AppHelper.runEventLoop(installInterrupt=True)` (locate by this exact string; was ~L3119 in the pristine file). Add the hook; add `_launch_time_update_check`.

**Acceptance Criteria:**
- [ ] On launch with the current version, no alert appears (silent).
- [ ] With a fake-low `VERSION`, an "Update Available" alert appears once shortly after the menu is up.
- [ ] Offline at launch → silent (no error dialog).
- [ ] The check does not block app startup or the 2 s timer.

**Verify:** Temporarily force a low version (e.g. set `VERSION` in `applio_update_check` to `"0.0.1"` via an env override or a one-line local edit, then revert) and launch → alert appears; restore → silent.

**Steps:**

- [ ] **Step 1: Add the hook in `run()`** — immediately before `AppHelper.runEventLoop(installInterrupt=True)` (~L3119):

```python
        # Silent launch-time update check (daemon thread; alert only if newer).
        AppHelper.callAfter(self._launch_time_update_check)
        AppHelper.runEventLoop(installInterrupt=True)
```

- [ ] **Step 2: Add the method** to `ApplioLauncher`:

```python
    def _launch_time_update_check(self):
        """Silent at-launch update check. Alert only if a newer version exists."""
        try:
            _update_check().check_for_updates_at_launch()
        except Exception as e:
            logging.warning(f"[Launcher] launch-time update check failed: {e}")
```

- [ ] **Step 3: Smoke-test (fake-low version) and commit**

Temporarily edit `applio_update_check.py` to force `VERSION = "0.0.1"` (after `_get_version_info`), launch → confirm one alert; revert the edit. Then:
```bash
git add applio_launcher.py
git commit -m "feat(update): silent launch-time update check"
```

---

## Task 6: Wrapper pywebview renderer (standalone static subset)

**Goal:** Replace `get_native_menu()` with a spec-driven static pywebview renderer, suppress the auto View/Edit menus, and use the shared update check.

**Files:**
- Modify: `macos_wrapper.py:1629-1687` (`get_native_menu` → `render_pywebview`); the `webview.start(...)` site (~L1996); import shared update check.

**Acceptance Criteria:**
- [ ] `python macos_wrapper.py` (no launcher env) shows the menu in order Applio/File/Process/Window/Help, a single bold app menu (no duplicate "Applio"), **no View/Edit menus**.
- [ ] `Check for Updates…` uses the shared real check.
- [ ] No `lambda: None` no-op items remain; the dead `get_native_menu` body is gone.
- [ ] Standalone Window menu = `Minimize`, `Show Main Window` (both real pywebview actions); `Zoom` and `Bring All to Front` are omitted (no pywebview API) rather than shipped as no-ops.

**Verify:** `venv_macos/bin/python macos_wrapper.py` → menu bar correct, no Edit menu, no duplicate app menu. `rg -n "lambda: None" macos_wrapper.py` → no menu-related matches.

**Steps:**

- [ ] **Step 1: Replace `get_native_menu` with `render_pywebview`** (L1629-1687)

```python
def render_pywebview():
    """Build the standalone pywebview menu from menu_spec (static subset).

    pywebview Menu/MenuAction are immutable and cannot bind shortcuts; the menu
    rebuilds only on windowDidBecomeKey (webview/platforms/cocoa.py). So this is
    a STATIC render: no dynamic status, no shortcuts. pywebview's unconditional
    _add_app_menu already injects About/Hide/HideOthers/Quit, so the __app__
    payload carries only the Applio-specific app-menu item (Check for Updates).
    """
    from webview.menu import Menu, MenuAction, MenuSeparator
    from menu_spec import MENU, PYWEBVIEW_APP_KEY, REVEAL_PATHS

    def open_in_finder(subpath: str):
        if ApplioApp.DATA_PATH:
            full_path = os.path.join(ApplioApp.DATA_PATH, subpath)
            FinderHelper.open_path(full_path)

    def change_data_location():
        new_path = select_data_folder(ApplioApp.DATA_PATH)
        if new_path and new_path != ApplioApp.DATA_PATH:
            PreferencesManager().set_data_path(new_path)
            logging.info(f"Data location changed to: {new_path} (restart required)")

    dispatch = _build_wrapper_dispatch(open_in_finder, change_data_location)

    def build(nodes, is_app_payload=False):
        items = []
        for mi in nodes:
            if mi.separator:
                # Collapse leading/consecutive separators. The app-menu payload omits
                # about/hide/hide_others/quit (pywebview injects them), which would
                # otherwise leave dangling separators between "About" and "Services".
                if items and not isinstance(items[-1], MenuSeparator):
                    items.append(MenuSeparator())
                continue
            if mi.submenu:
                items.append(Menu(mi.title, build(mi.submenu)))
                continue
            if not mi.key:
                # display-only status line: pywebview can't mutate it; skip
                continue
            fn = dispatch.get(mi.key)
            if fn is None:
                continue  # keys pywebview injects (about/hide/hide_others/quit) -> omit
            items.append(MenuAction(mi.title, (lambda f=fn: f())))
        if items and isinstance(items[-1], MenuSeparator):
            items.pop()  # drop a trailing separator
        return items

    out = []
    for idx, top in enumerate(MENU):
        if idx == 0:
            # app menu -> __app__ payload (only our custom app-menu items)
            out.append(Menu(PYWEBVIEW_APP_KEY, build(top.submenu, is_app_payload=True)))
        else:
            out.append(Menu(top.title, build(top.submenu)))
    return out


def _build_wrapper_dispatch(open_in_finder, change_data_location):
    import applio_update_check
    d = {}
    d["app.check_updates"] = applio_update_check.check_for_updates_interactive
    d["file.set_data_location"] = change_data_location
    for key, sub in REVEAL_PATHS.items():
        d[key] = (lambda s=sub: open_in_finder(s))
    d["process.open_dashboard"] = _show_progress_monitor_info
    d["process.open_logs"] = lambda: subprocess.Popen(["open", os.path.expanduser("~/Library/Logs/Applio")])
    # pywebview Window exposes show()/restore()/minimize() (webview/window.py:350/398/405).
    # Wire the two window actions we CAN implement; OMIT window.zoom and
    # window.bring_all_to_front (no pywebview API) rather than ship no-ops.
    d["window.minimize"] = _minimize_main_window
    d["window.show_main"] = _focus_main_window
    d["help.guide"] = lambda: _open_bundled_guide()
    d["help.docs"] = lambda: webbrowser.open("https://docs.applio.org")
    d["help.report_issue"] = lambda: webbrowser.open("https://github.com/froggeric/applio-macOS-native-app/issues")
    d["help.discord"] = lambda: webbrowser.open("https://discord.gg/IAHispano")
    return d


def _focus_main_window():
    """Best-effort: restore + show the first pywebview window (standalone)."""
    try:
        for w in webview.windows:
            try:
                w.restore()
            except Exception:
                pass
            w.show()
    except Exception as e:
        logging.warning(f"[Wrapper] show main window failed: {e}")


def _minimize_main_window():
    """Best-effort: minimize the first pywebview window (standalone)."""
    try:
        for w in webview.windows:
            w.minimize()
    except Exception as e:
        logging.warning(f"[Wrapper] minimize failed: {e}")


def _open_bundled_guide():
    for name in ("STUDIO_PRODUCTION_GUIDE.html", "STUDIO_PRODUCTION_GUIDE.md"):
        p = os.path.join(BASE_PATH, name)
        if os.path.exists(p):
            webbrowser.open("file://" + p)
            return
    logging.warning("[Wrapper] Studio Production Guide is not bundled")
```

**Add top-level imports** (verified: `macos_wrapper.py` imports `os`/`json`/`logging` at top but only has LOCAL `import subprocess` at L786/L1458, and no `webbrowser` at all). Add both at the top of `macos_wrapper.py`:
```python
import subprocess
import webbrowser
```
`render_pywebview`/`_build_wrapper_dispatch` use `subprocess.Popen` (open logs) and `webbrowser.open` (guide/docs/discord), and the standalone `_open_bundled_guide` uses `webbrowser.open`.

- [ ] **Step 2: Suppress View/Edit + use the renderer at `webview.start`** (locate the line `webview.start(menu=get_native_menu(), debug=False)`, ~L1996)

**Verified pywebview API (venv_macos):** `webview.start()`'s signature is `(func, args, localization, gui, debug, http_server, http_port, user_agent, private_mode, storage_path, menu, server, server_args, ssl, icon)` — there is **NO `webview_settings` kwarg**, and there is **no `webview.menu` attribute** to assign. `SHOW_DEFAULT_MENUS` lives in the `webview.settings` `ImmutableDict` (`webview/__init__.py:129`); `ImmutableDict.__setitem__` (`webview/util.py:61`) refuses NEW keys but **allows mutating EXISTING ones**, so `webview.settings['SHOW_DEFAULT_MENUS'] = False` works. `cocoa.py:18` does `from webview import settings as webview_settings` and gates View/Edit on it at `cocoa.py:1050`. So the definitive, no-hedge form is:

```python
    import webview
    webview.settings['SHOW_DEFAULT_MENUS'] = False   # suppress auto View/Edit menus
    webview.start(menu=render_pywebview(), debug=False)
```

Set the setting BEFORE `webview.start` (the cocoa renderer reads it when it builds menus, which happens during `start`).

- [ ] **Step 3: Remove the now-dead `get_native_menu`** — it was fully replaced by `render_pywebview`. Confirm no other references: `rg -n "get_native_menu" macos_wrapper.py` (should be none). The old menu also wired `_menu_callback_about` (L1494) and `_menu_callback_check_updates` (L1518); check for other references with `rg -n "_menu_callback_about|_menu_callback_check_updates" macos_wrapper.py` and, if the menu was the only caller, delete them. **Do NOT delete `_request_launcher_quit` (L262)** — pywebview's auto app-menu Quit uses `terminate:`, but `_request_launcher_quit` may be referenced by other lifecycle code; leave it in place.

- [ ] **Step 4: Smoke-test and commit**

Run: `venv_macos/bin/python macos_wrapper.py` (standalone) → correct menu, no Edit, no duplicate app menu.
```bash
git add macos_wrapper.py
git commit -m "feat(menu): spec-driven pywebview static menu for standalone wrapper"
```

---

## Task 7: Bundle the Studio Production Guide

**Goal:** Ship `STUDIO_PRODUCTION_GUIDE.html` (build-time conversion) and wire `datas`.

**Files:**
- Modify: `Applio.spec:4` (`datas`), `build_macos.py` (add conversion step), `requirements_macos.txt` (add `markdown`).

**Acceptance Criteria:**
- [ ] After `venv_macos/bin/python build_macos.py`, `dist/Applio.app/Contents/Resources/STUDIO_PRODUCTION_GUIDE.html` exists and renders the guide formatted.
- [ ] The conversion is idempotent (re-running doesn't fail / doesn't touch tracked `.md`) and falls back to copying the `.md` if `markdown` is unavailable.
- [ ] `Help → Studio Production Guide` (Tasks 3 & 6) opens it.

**Verify:** `venv_macos/bin/python build_macos.py` (cert-free) then `ls dist/Applio.app/Contents/Resources/STUDIO_PRODUCTION_GUIDE.html` and `open` it → formatted guide.

**Steps:**

- [ ] **Step 1: Add `markdown` to `requirements_macos.txt`**

Append (alphabetical if the file is sorted):
```
markdown
```

- [ ] **Step 2: Add the conversion function in `build_macos.py`** (near the other pre-build helpers; call it from the build before PyInstaller runs — right after the existing `patched_files = pre_build_patch()` line, which is at ~L737)

```python
def render_guide_html(repo_root=None):
    """Convert STUDIO_PRODUCTION_GUIDE.md -> .html (idempotent; fallback to copy).

    `repo_root` defaults to the directory containing this script — build_macos.py
    lives at the repo root, so this is correct regardless of CWD. (There is no
    `now_dir` variable in build_macos.py; the build runs at module scope with
    CWD = repo root and uses relative paths like 'dist'.)
    """
    if repo_root is None:
        repo_root = os.path.dirname(os.path.abspath(__file__))
    md = os.path.join(repo_root, "STUDIO_PRODUCTION_GUIDE.md")
    html = os.path.join(repo_root, "STUDIO_PRODUCTION_GUIDE.html")
    if not os.path.exists(md):
        print("[build] STUDIO_PRODUCTION_GUIDE.md not found; skipping guide render")
        return
    # Idempotent: skip if html is newer than md (so a build with unchanged md
    # leaves the committed html untouched → `git status` stays clean).
    if os.path.exists(html) and os.path.getmtime(html) >= os.path.getmtime(md):
        print("[build] guide html up to date")
        return
    try:
        import markdown as _md  # noqa
        with open(md, "r", encoding="utf-8") as f:
            body = _md.markdown(f.read(), extensions=["fenced_code", "tables"])
        doc = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>body{font:15px -apple-system,Helvetica,Arial,sans-serif;"
            "max-width:780px;margin:32px auto;padding:0 16px;color:#222;"
            "line-height:1.5}pre{background:#f4f4f4;padding:10px;overflow:auto;"
            "border-radius:6px}code{font:13px Menlo,monospace}table{border-collapse:collapse}"
            "th,td{border:1px solid #ccc;padding:6px 10px}h1,h2,h3{color:#111}</style>"
            f"</head><body>{body}</body></html>"
        )
        with open(html, "w", encoding="utf-8") as f:
            f.write(doc)
        print("[build] rendered STUDIO_PRODUCTION_GUIDE.html")
    except Exception as e:
        print(f"[build] markdown render failed ({e}); copying .md as fallback")
        import shutil
        shutil.copyfile(md, html)
```

Call site: find the line `patched_files = pre_build_patch()` (~L737; `rg -n "patched_files = pre_build_patch" build_macos.py`) and add on the NEXT line:
```python
render_guide_html()
```

`markdown` is already importable transitively in `venv_macos` (verified: `Markdown 3.10.2`, via tensorboard). The `pip install markdown` in Step 4 is therefore a confirm/no-op; adding it to `requirements_macos.txt` is hygiene that makes the dependency explicit.

- [ ] **Step 3: Add the guide to `Applio.spec` datas** (L4)

Change:
```python
datas = [('assets', 'assets'), ('logs', 'logs'), ('tabs', 'tabs'), ('core.py', '.'), ('app.py', '.'), ('macos_wrapper.py', '.'), ('rvc', 'rvc')]
```
to:
```python
datas = [('assets', 'assets'), ('logs', 'logs'), ('tabs', 'tabs'), ('core.py', '.'), ('app.py', '.'), ('macos_wrapper.py', '.'), ('rvc', 'rvc'), ('STUDIO_PRODUCTION_GUIDE.html', '.'), ('STUDIO_PRODUCTION_GUIDE.md', '.')]
```

- [ ] **Step 4: Build and verify, then commit**

```bash
venv_macos/bin/pip install markdown   # confirm only — already transitive (Markdown 3.10.2)
venv_macos/bin/python build_macos.py
ls dist/Applio.app/Contents/Resources/STUDIO_PRODUCTION_GUIDE.html
git status -sb   # build_macos.py runs post_build_restore(patched_files) at ~L754, so upstream
                 # sources are auto-restored. Expect ONLY: build_macos.py / Applio.spec /
                 # requirements_macos.txt / (STUDIO_PRODUCTION_GUIDE.html if first render or md changed)
git add Applio.spec build_macos.py requirements_macos.txt STUDIO_PRODUCTION_GUIDE.html
git commit -m "feat(guide): bundle Studio Production Guide as rendered HTML"
```

If `STUDIO_PRODUCTION_GUIDE.html` shows as **modified** after a build, the `.md` (or markdown lib) changed since the last commit — **re-commit it**, do not `git checkout` it. If it shows **unchanged**, the idempotent skip fired (html newer than md) and `git status` is clean — also correct.

---

## Task 8: Documentation

**Goal:** Document the new menu architecture, the static standalone subset, the update-check move + version-compare fix, and the guide, across the fork docs and CLAUDE.md.

**Files:**
- Modify: `README_MACOS.md`, `FORK_DIFFERENCES.md`, `CLAUDE.md`, `CHANGELOG.md`

**Acceptance Criteria:**
- [ ] `README_MACOS.md` describes the new menu (Applio/File/Process/Window/Help), the shared `menu_spec` + two-renderer architecture, the static standalone subset, the guide, and the real update check.
- [ ] `FORK_DIFFERENCES.md` lists `menu_spec.py`, `applio_update_check.py`, `tests/test_menu_spec.py`, `STUDIO_PRODUCTION_GUIDE.html` in the fork-only files; corrects the menu description.
- [ ] `CLAUDE.md` gains: the `menu_spec.py` single-source-of-truth rule; the "standalone pywebview menu is static / use `__app__` / `SHOW_DEFAULT_MENUS=False`" gotcha; the "version compare must use `packaging.version`" note; the launch-time check.
- [ ] `CHANGELOG.md` `[Unreleased]` gets an entry.

**Verify:** Read-through; `rg -n "menu_spec" README_MACOS.md FORK_DIFFERENCES.md CLAUDE.md` shows the new references.

**Steps:**

- [ ] **Step 1: `CHANGELOG.md`** — add under `## [Unreleased]` → `### Added`:
```
- **Native menu overhaul:** one shared `menu_spec.py` rendered by a PyObjC renderer
  (launcher) and a pywebview static-subset renderer (standalone). New Process + Help
  menus; Reveal-in-Finder rescued; Hide ⌘H / Minimize ⌘M; the dead Menu B deleted.
- **Real update checking:** manual `Check for Updates…` queries GitHub releases, and a
  silent launch-time check alerts only if a newer version exists. Version comparison
  fixed (was a buggy string compare; now `packaging.version`).
- **Studio Production Guide** bundled (rendered HTML) under Help.
- `tests/test_menu_spec.py` — pure-Python structure + version-compare gate.
```

- [ ] **Step 2: `CLAUDE.md`** — in the "Pywebview gotchas" section append:
```
- **Menu is spec-driven (`menu_spec.py`):** ONE source of truth rendered by both
  processes. The launcher renders the full dynamic menu (PyObjC); the standalone
  wrapper renders a STATIC subset (pywebview `Menu`/`MenuAction` are immutable and
  cannot bind shortcuts — `webview/menu.py`). Standalone renderer MUST: title the app
  menu `__app__` (NOT "Applio" — that duplicates it), set
  `webview_settings['SHOW_DEFAULT_MENUS']=False` (else pywebview auto-adds View/Edit),
  and omit `app.about/hide/hide_others/quit` (pywebview's unconditional `_add_app_menu`
  injects them). Verify the menu with `venv_macos/bin/python tests/test_menu_spec.py`.
- **Update-check version compare must use `packaging.version`** (already a hiddenimport).
  The old `check_for_updates` used string `!=` (flagged downgrades as updates).
```

- [ ] **Step 3: `FORK_DIFFERENCES.md`** — add `menu_spec.py`, `applio_update_check.py`, `tests/test_menu_spec.py`, `STUDIO_PRODUCTION_GUIDE.html` to the fork-only files table; update the "Native macOS dialogs / menu" bullet to describe the new Applio/File/Process/Window/Help menu and the shared-spec architecture.

- [ ] **Step 4: `README_MACOS.md`** — add a "Native Menu" subsection: the five menus, the Process dashboard-only status line, Reveal-in-Finder, the guide, and the update check (manual + launch-time). Note the standalone dev menu is a static subset.

- [ ] **Step 5: Commit**

```bash
git add README_MACOS.md FORK_DIFFERENCES.md CLAUDE.md CHANGELOG.md
git commit -m "docs(menu): document the overhauled native menu + update-check fix"
```

---

## Self-Review (run before handoff)

**Spec coverage:**
- §5.1 `menu_spec.py` → Task 1 ✓
- §5.2 taxonomy → Task 1 ✓
- §5.3 two renderers + dispatch → Tasks 3 (launcher) + 6 (wrapper) ✓
- §5.4 dynamic (launcher-only) → Task 4 ✓
- §6 menu tree → Tasks 1 (spec) + 3/6 (render) ✓
- §7.1 update check + version fix → Task 2 ✓
- §7.2 launch-time check → Task 5 ✓
- §7.3 guide → Task 7 ✓
- §8.1 no Edit (standalone SHOW_DEFAULT_MENUS=False) → Task 6 ✓
- §8.8 first-run race → Task 3 (guard) + Task 4 (disable) ✓
- §8.7 threading/pool → Task 2 (`_run_async_on_main`) ✓
- §9 all files → Tasks 1-8 ✓
- §10 automated gate → Tasks 1-2 (`tests/test_menu_spec.py`) ✓

**Placeholder scan:** no TBD/TODO/“add error handling” left; every code step shows the code.

**Type consistency:** `MenuItem` fields (`key/title/shortcut/mods/dynamic/submenu/separator`) match across `menu_spec.py`, `_fill_ns_menu` (launcher), and `render_pywebview` (wrapper). `LAUNCHER_ACTION_KEYS`/`WRAPPER_ACTION_KEYS`/`DISPLAY_KEYS`/`REVEAL_PATHS`/`STANDARD_SELECTOR_KEYS` defined in Task 1, consumed in Tasks 3/6. `_fill_ns_menu` populates `self._key_to_tag` + `self._dynamic_items` (Task 3); Task 4's `_find_item_by_key` reads `self._key_to_tag` and the timer mutates `self._dynamic_items`. `_run_async_on_main`, `is_update_available`, `check_for_updates_interactive`, `check_for_updates_at_launch` defined in Task 2, used in Tasks 3/5/6. Every launcher dispatch callable is **zero-arg** (`runDispatch_` calls `fn()`); the AppKit-style `*_` methods are wrapped as `lambda: self.X_(None)`.

**Notes for the implementer:**
- Tasks 1-2 are pure-Python and fully tested — do them first.
- Tasks 3-6 modify GUI code; the repo has no GUI test harness, so their verification is the documented manual smoke test + the `tests/test_menu_spec.py` gate.
- After Task 7's build, run `git status -sb` and restore any patched upstream files (`git checkout -- <file>`) — the build applies/restores patches but verify.
- Never `import build_macos` to test (it runs the whole build); test `render_guide_html` by copying it to a temp script.
