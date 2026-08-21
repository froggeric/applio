# Accessibility Phase 1 — Native Wrapper Foundation (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Applio's native macOS app usable without sight at the structural level: announced job lifecycle (start/pause/resume/terminal), non-visual completion cues (dock badge, attention request), webview boundary repairs (Tab traversal, downloads, AX resync), an accessible boot/loading experience, a truthful accessibility tree on the dashboard and progress window, safe dialogs, and announced Stop/upload feedback via one build-time patcher.

**Architecture:** All work is fork-owned files (`applio_launcher.py`, `macos_wrapper.py`, `menu_spec.py`, `applio_a11y.py` [new], `assets/loading.html`, `build_macos.py`, `patches/`) except three tiny injections into upstream files, which go through one new patcher (`patches/patch_stop_feedback.py`) per the fork's build-time patch system. A new AppKit-free module `applio_a11y.py` holds the pure announcement-decision logic (testable like `applio_inference_stats.py`) plus a thin poster; the existing 2-second `menuUpdateTimerFired_` heartbeat — which already runs regardless of whether the dashboard is open — drives it.

**Tech Stack:** Python 3.10, PyObjC/AppKit, pywebview 6.2.1 (WKWebView/cocoa), Gradio 6.20.0 (only via the patcher), plain-script tests (`python tests/test_x.py` style — this repo does not use pytest).

**Global Constraints:**
- **Never edit upstream files directly** (upstream = anything in `git ls-tree upstream/main`); upstream changes go through `patches/*.py` patchers only. After testing a patcher, restore sources: `git checkout -- assets core.py rvc tabs`. `git status` must show no patch markers in upstream files before any commit.
- **Never `import build_macos`** for testing — it runs the whole build at module level. Safe checks: `venv_macos/bin/python build_macos.py --help` (exits before the build).
- **All AppKit mutations on the main thread** — from background/daemon threads marshal with `AppHelper.callAfter` (macos_wrapper's `monitor_transition`/`tail_logs` run on daemon threads).
- **Announcements: AX channel only in Phase 1.** No `AVSpeechSynthesizer`/`NSSpeechSynthesizer` — speech would collide with the converted audio the user is evaluating. No per-tick chatter: lifecycle events only.
- **An explicit `setAccessibilityLabel_` overrides the title forever** — every later `setTitle_` on a control that has an explicit label MUST be paired with `setAccessibilityLabel_`.
- **`menu_spec.py` stays AppKit-free** (platform-neutral, unit-testable) — new native behavior belongs in the renderers, not the spec.
- **Line numbers cited below were verified against main HEAD `df9ff52b` on 2026-08-21** (post-review revision); still re-locate anchors by content before editing — upstream syncs land between plan and execution.
- New user-visible native strings are English in Phase 1 (i18n wiring is Phase 2).
- Commits: fork-conventional messages (`feat(a11y): …`), one per task. Black formatting runs via CI on push.

**User decisions (already made):**
- The three improvement vectors (wrapper / build-patch / upstream PR) are combined; this plan is wrapper + one patcher; upstream PRs are a separate later plan.
- Phase 1 has no announcement settings UI and no speech synthesis (defaults only); verbosity/sound/braille options are Phase 2.
- "No implementation yet" — this plan is written for later execution.
- **Phase 0 dependency:** the audit's Phase 0 (live VoiceOver reality checks, audit §6) is folded into Task 15's checklist instead of running as a separate pre-plan gate. If the human prefers the audit's "decision-critical before investing" ordering, run Task 15 checklist items 1–2 (clipboard reality, export-link download) against the CURRENT build before starting Tasks 1–14 — those two checks calibrate the value of the Edit-menu and ALLOW_DOWNLOADS tasks.

**Review provenance (2026-08-21):** all load-bearing code claims were re-verified against the working tree before this revision (function scopes, attribute names, line regions, PyObjC/AppKit selector availability in `venv_macos`, pywebview 6.2.1 internals, NSAlert key-equivalent behavior). Facts stated as "verified" below were checked, not guessed.

**Verification base for every task:** `venv_macos/bin/python -m py_compile <changed .py files>` plus the task's own `Verify` command. Menu-spec tasks additionally run `venv_macos/bin/python tests/test_menu_spec.py`.

---

### Task 1: `applio_a11y.py` — announcement engine (pure logic + poster)

**Goal:** Create the fork-owned accessibility engine: a snapshot-diff `AnnouncementPolicy` that decides which job-lifecycle messages to announce, and a `post_announcement` poster mirroring the launcher's verified `_announce_for_accessibility` implementation.

**Files:**
- Create: `applio_a11y.py`
- Test: `tests/test_applio_a11y.py`
- Modify: `build_macos.py` (HIDDEN_IMPORTS list, ≈L505-573 — add `"applio_a11y"` next to `"applio_update_check"`)

**Acceptance Criteria:**
- [ ] `AnnouncementPolicy.events(snapshot)` returns start/terminal/pause/resume events and a "finished" event when a running process disappears from the snapshot
- [ ] Steady-state snapshots (no change) produce zero events
- [ ] `post_announcement` is a silent no-op when AppKit is unavailable or posting fails
- [ ] `venv_macos/bin/python tests/test_applio_a11y.py` passes all tests
- [ ] `applio_a11y` appears in `build_macos.py` HIDDEN_IMPORTS (belt-and-suspenders: Task 2 imports it at the TOP LEVEL of `applio_launcher.py`, so PyInstaller already traces it — but it is lazy-import-safe only if listed, same reasoning as `menu_spec` at `build_macos.py:540`. No `datas` entry is needed: it is a traced importable module, not an unimported data file like `rvc/lib/tools/process_log_parser`)

**Verify:** `venv_macos/bin/python tests/test_applio_a11y.py` → `All applio_a11y tests passed (N).`

**Steps:**

- [ ] **Step 1: Write the failing tests** — `tests/test_applio_a11y.py`, script-style like `tests/test_menu_spec.py`:

```python
# tests/test_applio_a11y.py
"""Pure-Python gate for applio_a11y (no GUI, no AppKit needed for the policy).
Run: venv_macos/bin/python tests/test_applio_a11y.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from applio_a11y import AnnouncementPolicy

SNAP = {
    "myvoice": {"type": "training", "name": "myvoice", "status": "running"},
}


def test_new_running_announces_start():
    p = AnnouncementPolicy()
    evts = p.events(SNAP)
    assert ("start", "Started training: myvoice") in evts, evts


def test_steady_state_no_events():
    p = AnnouncementPolicy()
    p.events(SNAP)
    assert p.events(SNAP) == [], "no announcements without a state change"


def test_terminal_transition():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events({"myvoice": {"type": "training", "name": "myvoice", "status": "completed"}})
    assert evts == [("terminal", "training: myvoice completed")], evts


def test_failed_is_terminal():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events({"myvoice": {"type": "training", "name": "myvoice", "status": "failed"}})
    assert evts[0][0] == "terminal" and "failed" in evts[0][1]


def test_pause_resume():
    p = AnnouncementPolicy()
    p.events(SNAP)
    paused = {"myvoice": {"type": "training", "name": "myvoice", "status": "paused"}}
    assert p.events(paused) == [("info", "training: myvoice paused")]
    assert p.events(SNAP) == [("info", "training: myvoice resumed")]


def test_disappeared_running_announces_finished():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events({})
    assert evts == [("terminal", "training: myvoice finished")], evts


def test_disappeared_terminal_no_event():
    p = AnnouncementPolicy()
    p.events({"m": {"type": "tts", "name": "m", "status": "completed"}})
    assert p.events({}) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll applio_a11y tests passed ({len(fns)}).")
```

- [ ] **Step 2: Run to verify failure**

Run: `venv_macos/bin/python tests/test_applio_a11y.py`
Expected: `ModuleNotFoundError: No module named 'applio_a11y'`

- [ ] **Step 3: Implement** `applio_a11y.py`:

```python
# applio_a11y.py
"""Accessibility announcement engine for the Applio native app (fork-only).

Pure-Python decision logic (importable/testable with zero AppKit) plus a thin
poster that mirrors applio_launcher's _announce_for_accessibility (userInfo
key "AXAnnouncementKey" — verified against applio_launcher.py:142-151).

Phase 1 scope: job LIFECYCLE announcements only (start/pause/resume/terminal).
No per-tick chatter, no speech synthesis (must never collide with the audio
the user is evaluating). Percentage/epoch milestones are Phase 2.
"""

TERMINAL_STATUSES = {"completed", "failed", "error", "cancelled", "canceled", "interrupted"}


class AnnouncementPolicy:
    """Diffs consecutive process snapshots and decides what to announce."""

    def __init__(self):
        self._seen = {}  # key -> (status, label)

    def events(self, snapshot):
        """Return [(kind, message)] to announce.

        snapshot: dict key -> {"type": str, "name": str, "status": str}
        kind: "start" | "terminal" | "info"
        """
        out = []
        for key, info in snapshot.items():
            status = info.get("status", "running")
            label = f"{info.get('type', 'process')}: {info.get('name') or key}"
            prev = self._seen.get(key, (None, label))[0]
            if prev is None:
                if status == "running":
                    out.append(("start", f"Started {label}"))
            elif prev != status:
                if status in TERMINAL_STATUSES:
                    out.append(("terminal", f"{label} {status}"))
                elif status == "paused":
                    out.append(("info", f"{label} paused"))
                elif status == "running":
                    out.append(("info", f"{label} resumed"))
            self._seen[key] = (status, label)
        for key in [k for k in self._seen if k not in snapshot]:
            prev_status, label = self._seen.pop(key)
            if prev_status == "running":
                out.append(("terminal", f"{label} finished"))
        return out


def post_announcement(message, element):
    """Post a VoiceOver announcement. MUST be called on the main thread.

    Silently no-ops when AppKit is unavailable or posting fails (matches the
    launcher helper's defensive style — applio_launcher.py:142-151).
    """
    try:
        from AppKit import (
            NSAccessibilityPostNotification,
            NSAccessibilityAnnouncementRequestedNotification,
        )

        userInfo = {"AXAnnouncementKey": message}
        NSAccessibilityPostNotification(
            element, NSAccessibilityAnnouncementRequestedNotification, userInfo
        )
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to verify pass**

Run: `venv_macos/bin/python tests/test_applio_a11y.py`
Expected: `All applio_a11y tests passed (7).`

- [ ] **Step 5: Register in HIDDEN_IMPORTS** — in `build_macos.py`, find the `HIDDEN_IMPORTS` list (contains `"applio_update_check"`), add `"applio_a11y"` beside it.

- [ ] **Step 6: Safety check + commit**

Run: `venv_macos/bin/python build_macos.py --help && venv_macos/bin/python -m py_compile applio_a11y.py`
Expected: help text, exit 0 (never triggers the module-level build).

```bash
git add applio_a11y.py tests/test_applio_a11y.py build_macos.py
git commit -m "feat(a11y): announcement engine (pure policy + AX poster)"
```

---

### Task 2: Launcher wiring — heartbeat announcements, dock badge, attention requests

**Goal:** Drive `AnnouncementPolicy` from the always-on 2-second menu heartbeat so job start/pause/resume/completion/failure are announced to VoiceOver, reflected in a dock badge with the running-job count, and terminal events bounce the dock icon — all independent of whether the dashboard was ever opened.

**Files:**
- Modify: `applio_launcher.py` (top imports; `ApplioLauncher.__init__` ≈L4584-4599; `menuUpdateTimerFired_` L4937-4947; new methods near `_update_menu_state` L4999; data sources are the MODULE-LEVEL functions `get_active_processes()` L625, `_read_inference_progress()` L637, `_synthesize_inference_proc()` L656 — verified: none are methods)

**Acceptance Criteria:**
- [ ] `menuUpdateTimerFired_` calls a new `self._a11y_heartbeat()` after `_update_menu_state()`
- [ ] `_a11y_snapshot()` builds `{key: {type, name, status}}` from the module-level `get_active_processes()` (the same source `_update_menu_state` uses at L5022 — NOT the dashboard's `self._active_processes`, which only refreshes when the dashboard is open) plus `_synthesize_inference_proc()` for the in-app batch. Keys are `f"{type}:{name}"` (verified: proc dicts carry `model_name`, not `name`; type-keying avoids a preprocess/training/TTS of the same model silently overwriting each other). Paused state is derived per-proc via psutil `STATUS_STOPPED` — VERIFIED NECESSARY: `get_active_processes()` filters `status == "running"` in `active_processes.json`, and SIGSTOP-paused jobs keep that "running" status, so without the psutil probe the pause/resume events can never fire
- [ ] Announcements post via `AppHelper.callAfter` from the key/main window element
- [ ] Terminal events additionally call `NSApp.requestUserAttention_` (`NSCriticalRequest` for failure-ish messages, else `NSInformationalRequest`); because the policy only emits on transitions, a terminal event fires ONCE per job (no attention spam)
- [ ] Dock badge shows the running count, cleared (`None`) at idle (`NSApp.dockTile()` exists for Regular-policy dev runs too; the existing try/except covers headless); failures in the heartbeat never crash the timer (try/except with `logging.debug`)
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py` passes

**Verify:** `venv_macos/bin/python -m py_compile applio_launcher.py && grep -c "_a11y_heartbeat" applio_launcher.py` → `2`

**Steps:**

- [ ] **Step 1: Confirm the data sources** (all already exist; no new accessor needed — do NOT invent `self._get_active_processes()`, the module functions are the shared source):
  - `get_active_processes()` (module fn, L625) — subprocess jobs from `active_processes.json`, every entry has `status == "running"` (paused jobs included; the JSON status does not change on SIGSTOP).
  - `_synthesize_inference_proc()` (module fn, L656) — returns the in-app batch-inference proc dict (`_is_inference: True`, `model_name`, `status` in `running`/`cancelling`) or `None`. Disjoint from `get_active_processes()` by construction (inference never writes `active_processes.json` — CLAUDE.md), so no dedupe is needed.
  - Proc name key: `proc.get("model_name")` (verified at `_update_menu_state` L5026 and throughout the dashboard), falling back to `str(proc.get("pid"))`.

- [ ] **Step 2: Add imports and state.** Near the other fork-module imports at the top of `applio_launcher.py`:

```python
import applio_a11y
```

In `ApplioLauncher.__init__`, next to the other state attributes (e.g. near `self._dashboard_controller = None`):

```python
self._a11y_policy = applio_a11y.AnnouncementPolicy()
```

- [ ] **Step 3: Extend the heartbeat** — `menuUpdateTimerFired_` (L4937-4947), add after the dashboard block:

```python
        self._a11y_heartbeat()
```

- [ ] **Step 4: Implement the three methods** (place near `_update_menu_state`):

```python
    # ---- Accessibility heartbeat (Phase 1: lifecycle announcements + dock badge) ----

    def _a11y_snapshot(self):
        """Current tracked-job snapshot for the announcement policy.

        Sources are the module-level functions (verified scopes): subprocess
        jobs from get_active_processes(), the in-app batch from
        _synthesize_inference_proc() — disjoint, no dedupe. Keys are
        type:name so two jobs sharing a model name (e.g. preprocess vs
        training) are tracked independently. Paused is derived per-proc via
        psutil because active_processes.json keeps SIGSTOPped jobs "running".
        """
        snap = {}
        for proc in get_active_processes():
            name = (proc.get("model_name") or "").strip() or str(proc.get("pid"))
            status = "running"
            pid = proc.get("pid")
            if pid and PSUTIL_AVAILABLE:
                try:
                    if psutil.Process(pid).status() == psutil.STATUS_STOPPED:
                        status = "paused"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            snap[f"{proc.get('type', 'process')}:{name}"] = {
                "type": proc.get("type", "process"),
                "name": name,
                "status": status,
            }
        inf = _synthesize_inference_proc()
        if inf:
            name = (inf.get("model_name") or "").strip() or "batch"
            snap[f"inference:{name}"] = {
                "type": "batch inference",
                "name": name,
                "status": "running",
            }
        return snap

    def _a11y_heartbeat(self):
        """Diff job states every 2 s; announce changes; refresh the dock badge."""
        try:
            snap = self._a11y_snapshot()
            events = self._a11y_policy.events(snap)
        except Exception:
            logging.debug("[A11y] snapshot failed", exc_info=True)
            return
        for kind, msg in events:
            logging.info(f"[A11y] {kind}: {msg}")
            AppHelper.callAfter(self._a11y_post, msg, kind)
        running = sum(1 for v in snap.values() if v.get("status") == "running")
        AppHelper.callAfter(self._a11y_update_badge, running)

    def _a11y_post(self, msg, kind):
        """Runs on the main thread. Post the AX announcement + attention request."""
        try:
            from AppKit import NSApp, NSCriticalRequest, NSInformationalRequest

            element = (
                NSApp.keyWindow() or NSApp.mainWindow() or self._main_window.native
            )
            applio_a11y.post_announcement(msg, element)
            if kind == "terminal":
                bad = any(w in msg for w in ("fail", "error", "cancel", "interrupt"))
                NSApp.requestUserAttention_(
                    NSCriticalRequest if bad else NSInformationalRequest
                )
        except Exception:
            pass

    def _a11y_update_badge(self, running):
        """Runs on the main thread. Dock badge = number of running jobs."""
        try:
            from AppKit import NSApp

            NSApp.dockTile().setBadgeLabel_(str(running) if running else None)
        except Exception:
            pass
```

Notes for the implementer (all verified against the file):
- `AppHelper` and `logging` are module-level imports (L127, existing); `psutil` and `PSUTIL_AVAILABLE` are module-level (L68-70, used the same way at L3402-3407). **`NSApp` is NOT imported at module top** (the top-level `from AppKit import ...` block at L85-114 omits it) — every method that touches `NSApp` in this file imports it locally (e.g. L4909, L494); the code above follows that pattern. Do not "simplify" the local imports away.
- `self._main_window` is initialized to `None` in `__init__` (L4597) and assigned the real window in `start()` (L4685); `_a11y_post` may run before it exists on the very first ticks — the `or` chain plus try/except covers that (`self._main_window.native` is the NSWindow; pywebview `Window.native` exists on cocoa).
- `menuUpdateTimerFired_` runs on the MAIN thread (NSTimer on the main run loop), so `AppHelper.callAfter` is a next-run-loop-pass defer, not a thread marshal — kept because it coalesces with the existing `_reassert_menu_and_delegate` pattern and costs nothing.
- Second per-tick JSON read (`_update_menu_state` already calls `get_active_processes()` at L5022): accepted — it is a small locked file read that already happens every 2 s; sharing the dashboard's `self._active_processes` instead would couple announcements to the dashboard being open, which this task exists to avoid.

- [ ] **Step 5: Compile + commit**

```bash
venv_macos/bin/python -m py_compile applio_launcher.py
git add applio_launcher.py
git commit -m "feat(a11y): announce job lifecycle from menu heartbeat + dock badge/attention"
```

---

### Task 3: Webview boundary repairs — Tab traversal, downloads, AX resync

**Goal:** Enable Tab-to-all-controls in the embedded WKWebView, allow gr.File download links (trained-model export) to actually download, and post `NSAccessibilityLayoutChangedNotification` at the loading→Gradio page swap so VoiceOver's AX tree resyncs.

**Files:**
- Modify: `macos_wrapper.py` (webview.settings block ≈L1470; `monitor_transition` L1417-1424; new helper)
- Modify: `applio_launcher.py` (`_reassert_menu_and_delegate` ≈L4890-4924; `menuUpdateTimerFired_` from Task 2)

**Acceptance Criteria:**
- [ ] `webview.settings["ALLOW_DOWNLOADS"] = True` is set in `macos_wrapper.py` before `webview.start`
- [ ] New `_enable_webview_keyboard_access()` in the launcher walks `NSApp.windows()`, finds the `WKWebView` contentView, calls `configuration().preferences().setTabFocusesLinks_(True)` once (flag set only on success; retried from the heartbeat until it succeeds)
- [ ] `monitor_transition` posts `NSAccessibilityLayoutChangedNotification` on the webview contentView via `AppHelper.callAfter` after `load_url`
- [ ] All new code is exception-guarded; `py_compile` passes both files

**Verify:** `venv_macos/bin/python -m py_compile macos_wrapper.py applio_launcher.py && grep -c "ALLOW_DOWNLOADS\|setTabFocusesLinks_\|LayoutChanged" macos_wrapper.py applio_launcher.py` → each file ≥1

**Steps:**

- [ ] **Step 1: Allow downloads** — `macos_wrapper.py`, in the settings block where `SHOW_DEFAULT_MENUS` is set (L1470, inside `run_until_window_created`, which runs BEFORE `webview.start` — verified placement; cocoa.py reads `webview_settings['ALLOW_DOWNLOADS']` at navigation/download-decision time, default `False` in `webview/__init__.py:120`):

```python
    # gr.File download links (model export, F0 txt) are silently cancelled without this.
    # NOTE (intended behavior change): any non-displayable response now offers a
    # save panel instead of doing nothing — that is exactly the export journey fix.
    webview.settings["ALLOW_DOWNLOADS"] = True
```

- [ ] **Step 2: Enable Tab traversal** — `applio_launcher.py`, add the method (near `_reassert_menu_and_delegate`, L4889-4924):

```python
    def _enable_webview_keyboard_access(self):
        """Tab must reach buttons/checkboxes in the WKWebView.

        WKPreferences.tabFocusesLinks defaults to False and pywebview never
        sets it (verified against venv_macos webview/platforms/cocoa.py);
        without this, Tab moves only between text inputs. Idempotent: the
        flag is set only on success, so the heartbeat retries until the
        webview exists. Verified: pywebview's cocoa backend sets the
        WebKitHost (a WKWebView subclass) as the window's contentView at
        didFinishNavigation (cocoa.py:381), so contentView() IS the webview.
        """
        if getattr(self, "_webview_kb_done", False):
            return
        try:
            from AppKit import NSApp
            from WebKit import WKWebView
        except Exception:
            return
        for win in NSApp.windows():
            cv = win.contentView()
            if isinstance(cv, WKWebView):
                try:
                    cv.configuration().preferences().setTabFocusesLinks_(True)
                    self._webview_kb_done = True
                    logging.info("[A11y] WKWebView tab traversal enabled")
                except Exception:
                    logging.debug("[A11y] setTabFocusesLinks_ failed", exc_info=True)
                return
```

(`setTabFocusesLinks:` verified present on WKPreferences in this venv; `NSApp` must be imported locally — see Task 2 notes.)

Call it from `_reassert_menu_and_delegate` (one line at the end of the `_do()` closure, after `self._update_menu_state()`):

```python
                self._enable_webview_keyboard_access()
```

and from `menuUpdateTimerFired_` (after `self._a11y_heartbeat()`):

```python
        self._enable_webview_keyboard_access()
```

(⌘-shortcut conflict check, verified against `menu_spec.py` + WKWebView defaults: none of ⌘C/⌘V/⌘X/⌘Z/⌘A/⌘L/⌘0/⇧⌘R/⇧⌘D are bound by WKWebView or Gradio, so the menu bar intercepting them before the page is the desired behavior — it is what restores clipboard/shortcut access at all.)

- [ ] **Step 3: AX resync at page swap** — `macos_wrapper.py`, inside `monitor_transition` (L1417-1424), immediately after the `self.window.load_url(...)` call:

```python
            self._post_layout_changed()
```

and add the helpers (as methods on the same class as `monitor_transition`):

```python
    def _post_layout_changed(self):
        """Marshal to main thread — monitor_transition runs on a daemon thread."""
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._do_post_layout_changed)
        except Exception:
            pass

    def _do_post_layout_changed(self):
        """Force VoiceOver AX-tree resync after the full page swap.

        WKWebView accessibility trees can fall out of sync on async loads
        (Apple forums thread 809541 / FB21257352); LayoutChanged is the
        documented workaround.
        """
        try:
            from AppKit import (
                NSAccessibilityPostNotification,
                NSAccessibilityLayoutChangedNotification,
            )

            wv = self.window.native.contentView()
            NSAccessibilityPostNotification(wv, NSAccessibilityLayoutChangedNotification)
        except Exception:
            pass
```

- [ ] **Step 4: Compile + commit**

```bash
venv_macos/bin/python -m py_compile macos_wrapper.py applio_launcher.py
git add macos_wrapper.py applio_launcher.py
git commit -m "feat(a11y): webview boundary — tab traversal, allow downloads, AX layout-changed"
```

---

### Task 4: Accessible boot — loading screen ARIA, staged window title, reduced motion, timeout alert

**Goal:** The up-to-600 s boot becomes non-visually observable: an `aria-live` status region announcing stage transitions, a real `role=progressbar` with `aria-valuenow`, a window title that tracks the stage, `prefers-reduced-motion` support, and an NSAlert (not a silent HTML heading) on startup timeout.

**Files:**
- Modify: `assets/loading.html` (fork-owned; styles ≈L37-114, markup ≈L184-195, `pollStatus` L214-258)
- Modify: `macos_wrapper.py` (`tail_logs` heading/stage updates ≈L1238-1329; `monitor_transition` L1417-1424; timeout path L1426-1430; new `_set_window_title` + `_alert_startup_timeout` helpers)

**Acceptance Criteria:**
- [ ] `loading.html` contains a static `<div id="sr-status" role="status" aria-live="polite" aria-atomic="true">` present in the initial HTML (live regions must exist before updates), visually hidden via a `.sr-only` class
- [ ] `#progress-bar` carries `role="progressbar"` + `aria-valuemin/max/now` + `aria-label`, and `pollStatus` updates `aria-valuenow`/`aria-valuetext` wherever it sets `style.width`
- [ ] `#sr-status` text changes ONLY on heading/stage transitions (not per 200 ms poll)
- [ ] A `@media (prefers-reduced-motion: reduce)` block disables animations/transitions
- [ ] Window title tracks boot stage via `Window.set_title` (the real pywebview API, `webview/window.py:314`), resets to "Applio" on success, becomes "Applio — Startup Error" on timeout
- [ ] Timeout path shows an activating NSAlert pointing at the log location before/alongside the error page
- [ ] `grep -ci "aria-" assets/loading.html` → ≥ 4

**Verify:** `grep -c "aria-" assets/loading.html && venv_macos/bin/python -m py_compile macos_wrapper.py`

**Steps:**

- [ ] **Step 1: Add the CSS** — inside the existing `<style>` block in `assets/loading.html`:

```css
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

- [ ] **Step 2: Add the live region + progressbar semantics** — in the static markup: add right after `<body>` (or next to the main container):

```html
<div id="sr-status" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>
```

On the existing progress bar div (≈L186 `<div ... id="progress-bar">`), add attributes:

```html
role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-label="Startup progress"
```

- [ ] **Step 3: Update `pollStatus`** (L214-258; the real local variable holding the numeric percent is `displayProgress`, set at L220-221). Immediately after `progressBar.style.width = displayProgress + '%';` (L221) add:

```js
progressBar.setAttribute("aria-valuenow", String(displayProgress));
progressBar.setAttribute("aria-valuetext", data.heading + " — " + displayProgress + "%");
```

Add a transition-only announcer near the top of the script (after the `lastDetail` declarations at L210-212):

```js
var lastAnnouncedStage = "";
function announceStage(heading, sub) {
  var text = heading + (sub ? ". " + sub : "");
  if (text && text !== lastAnnouncedStage) {
    lastAnnouncedStage = text;
    document.getElementById("sr-status").textContent = text;
  }
}
```

Call it inside the two change-guarded blocks that already exist (verified at L224-231 and L233-240): add `announceStage(data.heading, data.sub_heading);` as the last statement inside `if (data.heading !== lastHeading) {...}` and inside `if (data.sub_heading !== lastSubHeading) {...}`. Its own `lastAnnouncedStage` guard makes it idempotent; do NOT add it to the unconditional 200 ms path (`data.stage` at L249-251 writes every poll and is not change-guarded — the announcer's dedupe is what protects it).

- [ ] **Step 4: Staged window title + timeout alert** — `macos_wrapper.py`. Add the helpers (methods on `ApplioApp`, the class owning `self.window`/`tail_logs`):

```python
    def _set_window_title(self, title):
        """pywebview Window.set_title (verified at webview/window.py:314).

        Thread-safe from tail_logs' daemon thread: the cocoa backend marshals
        via AppHelper.callAfter (cocoa.py:761-762). set_title is wrapped in
        @_shown_call, so before the window is shown it blocks up to 20 s then
        raises — the getattr guard + except covers the early race (threads
        start at L1441-1449, self.window is created at L452).
        """
        try:
            if getattr(self, "window", None):
                self.window.set_title(title)
        except Exception:
            logging.debug("[A11y] set_title failed", exc_info=True)

    def _sync_title_to_heading(self):
        """Set the window title to the current heading, deduped.

        ONE call site (end of tail_logs' per-line dispatch) instead of one
        per branch: the LOGIC MAPPING block at L1238-1329 has ~12 assignment
        branches — hooking each would churn. Title is heading-only (never the
        download percent: percent lines arrive many times per second).
        """
        if self.heading != getattr(self, "_last_title_heading", None):
            self._last_title_heading = self.heading
            self._set_window_title(f"Applio — {self.heading}")

    def _alert_startup_timeout(self):
        """Main-thread NSAlert for the boot-timeout path (was a silent <h1>)."""
        try:
            from AppKit import NSAlert, NSApp

            NSApp.activateIgnoringOtherApps_(True)
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Applio failed to start")
            alert.setInformativeText_(
                "The backend did not become ready in time. The log file explains "
                "why: once the window loads, use Process → Open Debug Logs…, or "
                "open ~/Library/Logs/Applio/ manually."
            )
            alert.addButtonWithTitle_("OK")
            alert.runModal()
        except Exception:
            pass
```

In `tail_logs`, add ONE call at the end of the per-line `if/elif` dispatch (after the `else:` fallback branch that assigns `self.sub_heading`, just before the loop continues — inside the `try` that wraps the mapping, at the same indent as the `if p_dl_percent.search(line):` chain):

```python
                        self._sync_title_to_heading()
```

In `monitor_transition` success path (after the Task 3 `load_url`/`_post_layout_changed`): `self._set_window_title("Applio")`.
In the timeout path (L1425-1430), before the `load_html` fallback:

```python
            self._set_window_title("Applio — Startup Error")
            try:
                from PyObjCTools import AppHelper

                AppHelper.callAfter(self._alert_startup_timeout)
            except Exception:
                pass
```

- [ ] **Step 5: Compile/verify + commit**

```bash
grep -c "aria-" assets/loading.html
venv_macos/bin/python -m py_compile macos_wrapper.py
git add assets/loading.html macos_wrapper.py
git commit -m "feat(a11y): accessible boot — live region, progressbar semantics, staged title, timeout alert"
```

---

### Task 5: First-run data-location flow — confirm instead of silent default

**Goal:** Cancelling (or mis-picking) the first-run folder picker no longer silently commits multi-GB of data to `~/Applio`: an activating NSAlert offers "Use Default" vs "Choose Again…", for both the cancel path and the non-writable path.

**Files:**
- Modify: `macos_wrapper.py` (new module-level `confirm_data_location()` next to `select_data_folder` L533-565 [verified: returns the path or `None` on cancel, and returns `default_path` unchanged when native APIs are unavailable — so the loop below is unreachable without AppKit]; first-run block L1707-1732, with `global DATA_PATH` declared at L1703 and `_prefs` bound at L1704 — both stay as-is)

**Acceptance Criteria:**
- [ ] Cancel path shows the confirm alert before falling back to the default; "Choose Again…" re-runs `select_data_folder` (loop until resolved — user-driven only, cannot infinite-loop on its own: every iteration requires a dialog/picker interaction)
- [ ] Non-writable path shows the same alert with the underlying error in the informative text
- [ ] Alert calls `NSApp.activateIgnoringOtherApps_(True)` before `runModal`; "Use Default" is the first (Return-activated) button
- [ ] `py_compile` passes; no change to the writable-path success flow

**Verify:** `venv_macos/bin/python -m py_compile macos_wrapper.py && grep -c "confirm_data_location" macos_wrapper.py` → `3`

**Steps:**

- [ ] **Step 1: Add the helper** next to `select_data_folder` (≈L533-565):

```python
def confirm_data_location(default_location, message, info):
    """First-run safety net: [Use Default] (Return) / [Choose Again…].

    Returns True when the user chose the default, False to re-run the picker.
    """
    from AppKit import NSAlert, NSApp, NSAlertFirstButtonReturn

    NSApp.activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    alert.setMessageText_(message)
    alert.setInformativeText_(info)
    alert.addButtonWithTitle_("Use Default")
    alert.addButtonWithTitle_("Choose Again…")
    return alert.runModal() == NSAlertFirstButtonReturn
```

- [ ] **Step 2: Rewire the first-run block** (L1707-1732). Replace the `if not DATA_PATH:` inner handling with a loop:

```python
    if not DATA_PATH:
        # First run - prompt for location
        default_location = os.path.expanduser("~/Applio")
        DATA_PATH = select_data_folder(default_location)

        while not DATA_PATH:
            # User cancelled - confirm the fallback instead of silently defaulting
            use_default = confirm_data_location(
                default_location,
                "No data location was chosen.",
                "Applio stores models, datasets and training results in the data "
                f"location. Use the default ({default_location}) or choose again?",
            )
            if use_default:
                DATA_PATH = default_location
                logging.info(f"User confirmed default data location: {DATA_PATH}")
            else:
                DATA_PATH = select_data_folder(default_location)

        # Validate path is writable
        path_error = None
        try:
            os.makedirs(DATA_PATH, exist_ok=True)
            test_file = os.path.join(DATA_PATH, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except (IOError, OSError) as e:
            path_error = str(e)

        while path_error is not None:
            use_default = confirm_data_location(
                default_location,
                "The selected location is not writable.",
                f"Error: {path_error}\nUse the default location "
                f"({default_location}) or choose again?",
            )
            if use_default:
                path_error = None
                DATA_PATH = default_location
                try:
                    os.makedirs(DATA_PATH, exist_ok=True)
                except (IOError, OSError) as e:
                    # Default itself unwritable (~/Applio) — hard stop with the
                    # error rather than an unhandled crash at startup.
                    logging.error(f"Default data location unwritable: {e}")
                    raise
            else:
                DATA_PATH = select_data_folder(default_location)
                path_error = None
                try:
                    os.makedirs(DATA_PATH, exist_ok=True)
                    test_file = os.path.join(DATA_PATH, ".write_test")
                    with open(test_file, "w") as f:
                        f.write("test")
                    os.remove(test_file)
                except (IOError, OSError) as e:
                    path_error = str(e)

        # Save preference
        _prefs.set_data_path(DATA_PATH)
        _prefs.mark_first_run_complete()
        logging.info(f"Data location set to: {DATA_PATH}")
```

- [ ] **Step 3: Compile + commit**

```bash
venv_macos/bin/python -m py_compile macos_wrapper.py
git add macos_wrapper.py
git commit -m "feat(a11y): first-run data location — confirm fallback instead of silent default"
```

---

### Task 6: Re-add `NSMicrophoneUsageDescription` (functional regression fix)

**Goal:** Restore the microphone usage description removed under the stale two-process rationale — realtime voice conversion now captures in-process (`rvc/realtime/audio.py` `sd.InputStream`) and macOS auto-denies mic access without the key.

**Files:**
- Modify: `build_macos.py` (POST-build Info.plist patch block L1061-1098 — verified: this block runs AFTER PyInstaller via `plistlib`, it is NOT "the plist dict passed to PyInstaller"; the stale removal comment is at L1073-1074 and `NSDesktopFolderUsageDescription` at L1078)
- Modify: `assets/entitlements.plist` (comment-only — same stale rationale sits there, fork-owned, verified not upstream)

**Acceptance Criteria:**
- [ ] The post-build plist patch block gains `plist["NSMicrophoneUsageDescription"] = "Applio uses the microphone for real-time voice conversion."` (no new entitlement needed: the app is NOT sandboxed — `com.apple.security.app-sandbox` is `false` in `assets/entitlements.plist` — so TCC needs only the usage string)
- [ ] Both stale removal comments (build_macos.py L1073-1074 and the `audio-input` note in `assets/entitlements.plist`) are updated to the in-process-capture rationale
- [ ] `venv_macos/bin/python build_macos.py --help` exits 0 (runtime plist verification happens in Task 15)

**Verify:** `venv_macos/bin/python build_macos.py --help >/dev/null && grep -c "NSMicrophoneUsageDescription" build_macos.py` → `1`

**Steps:**

- [ ] **Step 1:** In `build_macos.py`, in the post-build plist block (search `NSDesktopFolderUsageDescription`, L1078). Replace the stale comment at L1073-1074 and add the key next to the other usage descriptions:

```python
        # Realtime voice conversion captures the microphone IN-PROCESS
        # (rvc/realtime/audio.py sd.InputStream) since the single-process merge;
        # macOS auto-denies the TCC prompt without this key. (No audio-input
        # entitlement needed: the app is not sandboxed.)
        plist["NSMicrophoneUsageDescription"] = (
            "Applio uses the microphone for real-time voice conversion."
        )
```

- [ ] **Step 2:** In `assets/entitlements.plist`, replace the stale comment `<!-- Note: audio-input removed - not needed for wrapper, Gradio handles audio in browser -->` with `<!-- No audio-input entitlement needed: the app is not sandboxed; mic TCC is granted via NSMicrophoneUsageDescription in build_macos.py (in-process capture since the single-process merge) -->`. Entitlement values themselves are untouched.

- [ ] **Step 3: Safety check + commit**

```bash
venv_macos/bin/python build_macos.py --help >/dev/null && echo OK
git add build_macos.py assets/entitlements.plist
git commit -m "fix(realtime): re-add NSMicrophoneUsageDescription for in-process mic capture"
```

---

### Task 7: Edit menu — clipboard access via responder-chain selectors

**Goal:** Give keyboard/VoiceOver users a reliable clipboard path: a standard Edit menu (Undo/Redo/Cut/Copy/Paste/Select All) wired through the AppKit responder chain (`cut:`/`copy:`/`paste:`/`selectAll:` reach `WKContentView`), restoring ⌘C/⌘V/⌘X/⌘Z/⌘A menu-equivalents that pywebview's stripped context menu took away.

**Why this reverses an earlier deliberate decision** (`test_no_settings_no_edit` asserted "no Edit menu"): the no-Edit state dates from the menu-overhaul work, before the accessibility audit established that pywebview's cocoa backend strips the WKWebView context menu and WKWebView binds no ⌘-shortcuts of its own — leaving blind users NO clipboard path at all (audit kf-cluster / critic gap "clipboard"). The Edit menu is the only native remedy available in Phase 1 (a JS-injected web-level handler is Phase 2). Do not revert this; if `test_no_settings_no_edit`'s ghost resurfaces in review, point at this note.

**Files:**
- Modify: `menu_spec.py` (new `EDIT_KEYS` set; extend `STANDARD_SELECTOR_KEYS`, `TAXONOMY`, `LAUNCHER_ACTION_KEYS`, `WRAPPER_ACTION_KEYS`; insert Edit menu into `MENU` between App and File)
- Modify: `applio_launcher.py` (NO code change expected — verified: `_build_launcher_dispatch` (L5099-5132) builds dispatch wholesale from `menu_spec.STANDARD_SELECTOR_KEYS` at L5109, so the six new keys auto-wire to `setAction_(selector)` + `setTarget_(None)` via `_fill_ns_menu`'s `isinstance(handler, str)` branch at L4366-4368. Step 4 is a READ-ONLY verification)
- Modify: `macos_wrapper.py` (one real change: `render_pywebview` must skip a top-level menu whose rendered children list is empty — without this the standalone renderer shows an EMPTY "Edit" menu, because `_build_wrapper_dispatch` (L1016+) simply has no `edit.*` entries and the builder skips unknown keys at L1000-1001)
- Test: `tests/test_menu_spec.py`

**Acceptance Criteria:**
- [ ] `MENU` top level is `["Applio", "Edit", "File", "Process", "Window", "Help"]`
- [ ] All six Edit items carry `shortcut`/`mods` and their keys map to selectors in `STANDARD_SELECTOR_KEYS`
- [ ] The PyObjC renderer creates the items with `setAction_(selector)` and no target (responder chain), exactly as it already does for `app.hide` — by construction, since dispatch derives from `STANDARD_SELECTOR_KEYS`
- [ ] The standalone (pywebview) renderer renders NO empty Edit menu (top-level entries with zero renderable children are skipped)
- [ ] Note on enablement (accepted behavior): Edit items are responder-chain-validated, so Undo/Redo/Cut may appear disabled until a text field in the WKWebView has focus — this matches native macOS behavior and is correct, not a bug
- [ ] `venv_macos/bin/python tests/test_menu_spec.py` passes with updated expectations

**Verify:** `venv_macos/bin/python tests/test_menu_spec.py` → all PASS

**Steps:**

- [ ] **Step 1: Update tests first** — in `tests/test_menu_spec.py`:

```python
EXPECTED_TOP_LEVEL = ["Applio", "Edit", "File", "Process", "Window", "Help"]
```

Replace `test_no_settings_no_edit` with:

```python
def test_no_settings_menu():
    for leaf in iter_leaves(MENU):
        assert leaf.key != "app.settings", "app.settings must not exist"


def test_edit_menu_present():
    edit = next(t for t in MENU if t.title == "Edit")
    keys = [leaf.key for leaf in iter_leaves(edit.submenu)]
    assert keys == [
        "edit.undo",
        "edit.redo",
        "edit.cut",
        "edit.copy",
        "edit.paste",
        "edit.select_all",
    ], keys
    from menu_spec import STANDARD_SELECTOR_KEYS

    for k in keys:
        assert k in STANDARD_SELECTOR_KEYS, f"{k} needs a responder-chain selector"
        assert STANDARD_SELECTOR_KEYS[k].endswith(":"), f"{k} selector must be an action"
```

In `test_action_key_contracts`, update the wrapper-contract assertion:

```python
    assert (
        WRAPPER_ACTION_KEYS == LAUNCHER_ACTION_KEYS - injected - EDIT_KEYS
    ), "wrapper contract mismatch (Edit items are launcher-only)"
```

adding `EDIT_KEYS` to the imports from `menu_spec`.

- [ ] **Step 2: Run tests to verify failure**

Run: `venv_macos/bin/python tests/test_menu_spec.py`
Expected: FAIL on `test_top_level_order` / `test_edit_menu_present` (Edit not present)

- [ ] **Step 3: Implement in `menu_spec.py`:**

```python
# Edit menu: clipboard via the AppKit responder chain (WKContentView implements
# cut:/copy:/paste:/selectAll:). Launcher-only — pywebview's static renderer
# cannot bind selectors, and its stripped WKWebView context menu (cocoa.py
# willOpenMenu_withEvent_ → removeAllItems) leaves no other clipboard path.
EDIT_KEYS = {
    "edit.undo",
    "edit.redo",
    "edit.cut",
    "edit.copy",
    "edit.paste",
    "edit.select_all",
}
```

Extend the existing maps:

```python
TAXONOMY = APP_KEYS | FILE_KEYS | PROCESS_KEYS | WINDOW_KEYS | HELP_KEYS | EDIT_KEYS

STANDARD_SELECTOR_KEYS = {
    ...existing entries...,
    "edit.undo": "undo:",
    "edit.redo": "redo:",
    "edit.cut": "cut:",
    "edit.copy": "copy:",
    "edit.paste": "paste:",
    "edit.select_all": "selectAll:",
}

LAUNCHER_ACTION_KEYS = (
    APP_KEYS | FILE_KEYS | PROCESS_KEYS | WINDOW_KEYS | HELP_KEYS | EDIT_KEYS
) - set()

WRAPPER_ACTION_KEYS = LAUNCHER_ACTION_KEYS - {
    ...existing exclusions...,
    *EDIT_KEYS,  # selector-based: cannot be rendered by the static pywebview menu
}
```

Insert the menu (between the App menu item and the File item):

```python
    MenuItem(
        title="Edit",
        submenu=[
            MenuItem(key="edit.undo", title="Undo", shortcut="z", mods=("cmd",)),
            MenuItem(
                key="edit.redo",
                title="Redo",
                shortcut="z",
                mods=(
                    "cmd",
                    "shift",
                ),
            ),
            MenuItem(separator=True),
            MenuItem(key="edit.cut", title="Cut", shortcut="x", mods=("cmd",)),
            MenuItem(key="edit.copy", title="Copy", shortcut="c", mods=("cmd",)),
            MenuItem(key="edit.paste", title="Paste", shortcut="v", mods=("cmd",)),
            MenuItem(key="edit.select_all", title="Select All", shortcut="a", mods=("cmd",)),
        ],
    ),
```

(**Redo uses lowercase `"z"` + explicit shift** — do NOT use uppercase `"Z"` with ⌘-only mods: verified in this venv that `NSMenuItem` reads the mask back WITHOUT shift in that case (display would show ⌘Z while the item only fires on ⇧⌘Z). Lowercase + explicit shift is also the existing repo precedent — `process.open_dashboard` is `"p"` + `("cmd", "shift")` at menu_spec.py L170-171.)

- [ ] **Step 4: Verify the launcher renderer (read-only), fix the standalone renderer (one edit).**
  1. Read `_fill_ns_menu` in `applio_launcher.py` (L4299-4382): confirm the `isinstance(handler, str)` branch (L4366-4368) — `setAction_(selector)` + `setTarget_(None)` — reaches the new keys via `_build_launcher_dispatch` L5109-5110. Nothing to change; if the code has drifted and dispatch no longer derives from `menu_spec.STANDARD_SELECTOR_KEYS`, STOP and re-point this task.
  2. In `macos_wrapper.py` `render_pywebview` (L960-1013), the top-level loop at L1007-1012 appends `Menu(top.title, build(top.submenu))` unconditionally. Change it to skip empty results (this is what keeps the Edit menu out of the standalone renderer — its `edit.*` leaves have no wrapper dispatch entries):

```python
    out = []
    for idx, top in enumerate(MENU):
        if idx == 0:
            out.append(Menu(PYWEBVIEW_APP_KEY, build(top.submenu, is_app_payload=True)))
        else:
            children = build(top.submenu)
            if not children:
                continue  # e.g. Edit: selector-only items this renderer cannot bind
            out.append(Menu(top.title, children))
    return out
```

- [ ] **Step 5: Run tests + compile + commit**

```bash
venv_macos/bin/python tests/test_menu_spec.py
venv_macos/bin/python -m py_compile menu_spec.py applio_launcher.py macos_wrapper.py
git add menu_spec.py applio_launcher.py macos_wrapper.py tests/test_menu_spec.py
git commit -m "feat(a11y): Edit menu with responder-chain clipboard selectors"
```

---

### Task 8: Menu shortcuts for frequent blind-user actions

**Goal:** Add key equivalents to the menu-traversal-only frequent actions: Open Debug Logs (⌘L), Set Data Location (⇧⌘D), Show Main Window (⌘0), Reveal Root (⇧⌘R) — all Cmd-modified (clear of VoiceOver's Ctrl+Option keys).

**Files:**
- Modify: `menu_spec.py` (four `MenuItem`s)
- Test: `tests/test_menu_spec.py`

**Acceptance Criteria:**
- [ ] `process.open_logs` → `shortcut="l", mods=("cmd",)`; `file.set_data_location` → `shortcut="d", mods=("cmd", "shift")`; `window.show_main` → `shortcut="0", mods=("cmd",)`; `file.reveal_root` → `shortcut="r", mods=("cmd", "shift")`
- [ ] A new test asserts all four assignments
- [ ] No new shortcut uses a bare Ctrl/Option modifier (VoiceOver conflict); ⌘W/⌘R/⌘T/⌘N deliberately avoided
- [ ] Conflict check (verified against current `menu_spec.py` + WKWebView defaults): existing equivalents are ⌘H/⌥⌘H/⌘Q/⇧⌘P/⌘M only; ⌘L/⇧⌘D/⌘0/⇧⌘R collide with nothing (WKWebView binds none of them; "0" is a valid key-equivalent string — verified in this venv)
- [ ] `tests/test_menu_spec.py` passes

**Verify:** `venv_macos/bin/python tests/test_menu_spec.py` → all PASS

**Steps:**

- [ ] **Step 1: Add the test:**

```python
def test_frequent_action_shortcuts():
    by_key = {leaf.key: leaf for leaf in iter_leaves(MENU)}
    expected = {
        "process.open_logs": ("l", ("cmd",)),
        "file.set_data_location": ("d", ("cmd", "shift")),
        "window.show_main": ("0", ("cmd",)),
        "file.reveal_root": ("r", ("cmd", "shift")),
    }
    for key, (sc, mods) in expected.items():
        leaf = by_key[key]
        assert (leaf.shortcut, leaf.mods) == (sc, mods), f"{key}: {leaf.shortcut} {leaf.mods}"
```

- [ ] **Step 2: Run to verify failure**, then **Step 3: apply the four `MenuItem` edits** (add `shortcut=`/`mods=` to the four items in `MENU`).

- [ ] **Step 4: Run tests + commit**

```bash
venv_macos/bin/python tests/test_menu_spec.py
git add menu_spec.py tests/test_menu_spec.py
git commit -m "feat(a11y): keyboard shortcuts for logs/data-location/main-window/reveal-root"
```

---

### Task 9: Process menu — live jobs submenu instead of a disabled status line

**Goal:** Replace the permanently-disabled, symbol-prefixed `process.status` line with an "active jobs" submenu rebuilt every 2 s: each job item ("training: myvoice") opens the dashboard; empty state shows one disabled "No active processes" item. VoiceOver reads actual state from the menu bar without opening anything.

**Files:**
- Modify: `menu_spec.py` (`process.status` item gains an empty `submenu=[]` and title "Active Processes"; comment update)
- Modify: `applio_launcher.py` (`_update_menu_state` L5016-5029 — replace title-mutation with submenu rebuild; the NSMenuItem ref is ALREADY retained in `self._dynamic_items["process.status"]` as `(item, hint)` — verified: `_fill_ns_menu` L4380-4381 records dynamic items there, and `_build_native_menu` L4869+ resets it per build. No new `_menu_item_refs` dict is needed)

**Acceptance Criteria:**
- [ ] The `● ` prefix mutation is gone; menu text is human words only
- [ ] With N active jobs the submenu has N enabled items that fire the SAME handler as `process.open_dashboard` (verified mechanism: action `"runDispatch:"` + target `self._menu_handler` + the tag recorded in `self._key_to_tag["process.open_dashboard"]` — one FIXED tag reused for all job items so the handler table never grows)
- [ ] With 0 jobs the submenu has one disabled "No active processes" item
- [ ] The parent menu item is ENABLED (a disabled item's submenu may not open; `_fill_ns_menu` builds display-only items disabled at L4379, so the rebuild must `setEnabled_(True)`); rebuild is exception-guarded so the timer never dies
- [ ] `tests/test_menu_spec.py` still passes (display-key contract unchanged — `process.status` remains in `DISPLAY_KEYS` and `dynamic="status"`; verified: `iter_leaves` yields items with an EMPTY `submenu=[]` as leaves, and no test asserts the status item's title)

**Verify:** `venv_macos/bin/python -m py_compile applio_launcher.py menu_spec.py && venv_macos/bin/python tests/test_menu_spec.py`

**Steps:**

- [ ] **Step 1: Spec change** — replace the `process.status` item:

```python
            MenuItem(
                key="process.status",
                title="Active Processes",
                dynamic="status",  # launcher rebuilds the submenu every 2 s
                submenu=[],  # populated at runtime; empty spec submenu is valid
            ),
```

- [ ] **Step 2: Launcher rebuild** — in `_update_menu_state`, replace the title-mutation block (L5016-5029) with `self._refresh_status_submenu(get_active_processes())`, implemented next to it:

```python
    def _refresh_status_submenu(self, procs):
        """Rebuild the Process→Active Processes submenu from tracked jobs."""
        entry = getattr(self, "_dynamic_items", {}).get("process.status")
        if not entry:
            return
        item, _hint = entry
        try:
            from AppKit import NSMenu, NSMenuItem

            sub = NSMenu.alloc().init()
            tag = getattr(self, "_key_to_tag", {}).get("process.open_dashboard")
            handler = self._menu_handler  # MenuActionHandler (NSObject proxy)
            if not procs:
                ni = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "No active processes", None, ""
                )
                ni.setEnabled_(False)
                sub.addItem_(ni)
            else:
                for proc in procs:
                    title = (
                        f"{(proc.get('type') or 'process').capitalize()}: "
                        f"{proc.get('model_name') or 'active job'}"
                    ).strip()
                    ni = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        title, "runDispatch:" if handler and tag is not None else None, ""
                    )
                    if handler and tag is not None:
                        ni.setTarget_(handler)
                        ni.setTag_(tag)  # same tag as Open Progress Dashboard
                    sub.addItem_(ni)
            item.setSubmenu_(sub)
            item.setEnabled_(True)  # display-only items are built disabled (L4379)
        except Exception:
            logging.debug("[Menu] status submenu rebuild failed", exc_info=True)
```

**Implementer notes (all verified):** `self._menu_handler` (init L4590, created L4836-4837) is the MenuActionHandler; `runDispatch_` (L4432-4439) looks the handler up by `sender.tag()` in `_dispatch_table` — reusing `process.open_dashboard`'s recorded tag fires exactly its handler (`showProgressMonitor_`), satisfying "same handler as the dashboard item" with zero new dispatch entries per rebuild. Allocating a fresh NSMenu every 2 s is autoreleased pool garbage, not a leak (AppKit-typical for menu rebuilds); do NOT try to diff the old submenu — the item count is tiny and VoiceOver reads the submenu on open, not on rebuild.

- [ ] **Step 3: Compile + tests + commit**

```bash
venv_macos/bin/python -m py_compile applio_launcher.py menu_spec.py
venv_macos/bin/python tests/test_menu_spec.py
git add applio_launcher.py menu_spec.py
git commit -m "feat(a11y): Process menu shows live jobs submenu (was disabled status line)"
```

---

### Task 10: Dashboard truth I — dynamic labels and status badge

**Goal:** Stop the dashboard's accessibility tree from lying: the Pause/Resume button keeps its AX label in sync; inference rows get inference-specific labels and training rows re-assert theirs; the "Running" status badge reflects actual state.

**Files:**
- Modify: `applio_launcher.py` (all cites verified: `_update_action_bar` L3374 with `setTitle_` at L3393+L3413; `togglePauseProcess_` L3469 with `sender.setTitle_` at L3484; `_render_inference_detail` L3248 with value writes at L3315-3326; `_update_detail_panel` L2956 training branch L3114-3153; `status_badge` created L1183-1204 — its string value is set exactly ONCE, to the literal "Running", at L1188, so it lies both at idle and after pause/stop/complete; `detail_status` write sites L2797/L3069/L3276/L3439/L3465/L3489-3491)

**Acceptance Criteria:**
- [ ] Every `setTitle_` on the pause button (≈L3393, L3413, L3484) is immediately paired with `setAccessibilityLabel_` of the same string
- [ ] `_render_inference_detail` sets `detail_best_label`→"Conversion speed" and `detail_current_label`→"Converted, skipped and current file" before writing inference values
- [ ] The training render path re-asserts "Best epoch and its loss" / "Current epoch, step and training speed" each time it writes those outlets
- [ ] The status badge's string value updates wherever detail status changes (running/paused/completed/failed/stopping), not just at creation
- [ ] `py_compile` passes

**Verify:** `venv_macos/bin/python -m py_compile applio_launcher.py && grep -c "setAccessibilityLabel_" applio_launcher.py` → count strictly greater than before the task

**Steps:**

- [ ] **Step 1: Pause/Resume pairing.** At each of the three verified sites — L3393 (`self.pause_btn.setTitle_("Pause")`, the inference branch where pause is disabled), L3413 (`self.pause_btn.setTitle_("Resume" if is_stopped else "Pause")`), and L3484 (`sender.setTitle_` inside `togglePauseProcess_`) — transform patterns like:

```python
        self.pause_btn.setTitle_("Resume" if is_stopped else "Pause")
```

into:

```python
        new_title = "Resume" if is_stopped else "Pause"
        self.pause_btn.setTitle_(new_title)
        self.pause_btn.setAccessibilityLabel_(new_title)
```

(use `sender` instead of `self.pause_btn` at the L3484 site; mirror the already-correct `setTitle_`+`setAccessibilityLabel_` pairing in `ProgressWindowController` at L2153-2175).

- [ ] **Step 2: Inference/training label swap.** At the top of `_render_inference_detail`'s value-writing block (≈L3315):

```python
        self.detail_best_label.setAccessibilityLabel_("Conversion speed")
        self.detail_current_label.setAccessibilityLabel_(
            "Converted, skipped and current file"
        )
```

In `_update_detail_panel`'s training branch, where it writes `detail_best_label`/`detail_current_label` (≈L3114-3153), add the re-assertion:

```python
        self.detail_best_label.setAccessibilityLabel_("Best epoch and its loss")
        self.detail_current_label.setAccessibilityLabel_(
            "Current epoch, step and training speed"
        )
```

- [ ] **Step 3: Status badge.** Both outlets are real and verified (`self.detail_status`, AX label "Process status" L2798; `self.status_badge`, AX label "Process status badge" L1202). Introduce ONE helper and route EVERY status write through it — the six verified sites are L2797 (creation default "No process selected"), L3069 (active branch, `status_text` incl. phase), L3276 (inference branch, `label`), L3439 + L3465 (both "Stopping…"), and L3489-3491 (pause toggle "Paused"/"Running"):

```python
    def _set_detail_status(self, display, badge_text=None):
        """Write the detail status line and the status badge together."""
        if hasattr(self, "detail_status") and self.detail_status:
            self.detail_status.setStringValue_(display)
        if hasattr(self, "status_badge") and self.status_badge:
            self.status_badge.setStringValue_(
                badge_text if badge_text is not None else display
            )
```

Call-site conversions (replace each existing `self.detail_status.setStringValue_(X)` guarded block with `self._set_detail_status(X)`):

| Site | Call |
|------|------|
| L3069 | `self._set_detail_status(status_text)` |
| L3276 | `self._set_detail_status(label)` |
| L3439, L3465 | `self._set_detail_status("Stopping…")` |
| L3489-3491 | `self._set_detail_status("Paused" if now_stopped else "Running")` |
| L2797 | `self._set_detail_status("No process selected", badge_text="Idle")` |

Additionally change the badge's creation-time literal at L1188 from `"Running"` to `"Idle"` — the dashboard is built before any process is known, so "Running" is false at launch. (Badge COLOR mapping per state — green/orange/blue/red — is visual polish, NOT accessibility, and is deliberately out of scope here; the string value is what VoiceOver reads.)

- [ ] **Step 4: Compile + commit**

```bash
venv_macos/bin/python -m py_compile applio_launcher.py
git add applio_launcher.py
git commit -m "fix(a11y): dashboard labels track Pause/Resume, inference mode, real status"
```

---

### Task 11: Dashboard truth II — row states, loss-chart summary, progress values

**Goal:** Sidebar rows spell out state in words; the custom-drawn loss chart exposes a textual summary via `setAccessibilityValue_`; the progress indicator publishes its value accessibly.

**Files:**
- Modify: `applio_launcher.py` (all cites verified: `tableView_objectValueForTableColumn_row_` L3689-3707 — active rows use `●`/`⏸` from the JSON `status` (the `⏸` branch is DEAD: a SIGSTOP-paused process keeps `status == "running"` in the JSON, so the symbol never shows) and history rows use an unconditional `✓`; both branches already read the `model_name` key, NOT `name`; the working paused probe lives at L3402-3407 — `PSUTIL_AVAILABLE` + `psutil.Process(pid).status() == psutil.STATUS_STOPPED` with pid from `_current_pid` L3362; `LossChartView.set_points` L2360-2368 — verified tuple order `(epoch, loss)` (`cleaned.append((int(p[0]), float(p[1])))`, docstring "list of (epoch, loss) tuples"); progress `setDoubleValue_` sites L3095 (training, var `frac`, already 0-100 via `frac * 100.0`) and L3310 (inference, `stats["pct"]` already 0-100); list rebuilds in `refresh_process_list` L3741-3744 and `update_process_list` L4238-4244)

**Acceptance Criteria:**
- [ ] Active rows read "Running — {Type}: {model_name}" / "Paused — …" (no `●`/`⏸` symbols), with Paused derived from a psutil `STATUS_STOPPED` probe taken at list-refresh time (the JSON status alone cannot detect it); history rows read "Completed/Failed/Cancelled/Interrupted — {Type}: {model_name}" derived from the stored status (never an unconditional `✓`)
- [ ] `LossChartView.set_points` builds and posts a text summary ("Best loss X at epoch N; latest …") via `setAccessibilityValue_`, exception-guarded
- [ ] BOTH determinate progress sites (training L3095, inference L3310) also set `setAccessibilityValue_` with the percent
- [ ] `py_compile` passes

**Verify:** `venv_macos/bin/python -m py_compile applio_launcher.py && ! grep -n '"✓ {\|"●" if\|"⏸"' applio_launcher.py` (no symbol-prefix row strings remain)

**Steps:**

- [ ] **Step 1: Row strings + pause annotation.** The dead `⏸` branch means the data source has NO working paused signal — add one. First add a tiny helper (next to `_current_pid`, L3362) and call it at the end of BOTH list rebuilds (in `refresh_process_list` after the inference-proc append at L3744, and in `update_process_list` after the append at L4244) so the probe runs once per refresh, not once per visible cell per repaint:

```python
    def _annotate_pause_state(self, procs):
        """Stamp live SIGSTOP state on each proc (JSON status stays 'running')."""
        for proc in procs:
            proc["_ps_stopped"] = False
            pid = self._current_pid(proc)
            if pid and PSUTIL_AVAILABLE:
                try:
                    proc["_ps_stopped"] = (
                        psutil.Process(pid).status() == psutil.STATUS_STOPPED
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
```

(The synthesized inference proc has no pid, so `_current_pid` returns None and it stays "Running" — correct, in-process batches cannot SIGSTOP.) Then replace the two branches in `tableView_objectValueForTableColumn_row_` (L3689-3707):

```python
        if row < len(self._active_processes):
            proc = self._active_processes[row]
            word = "Paused" if proc.get("_ps_stopped") else "Running"
            proc_type = proc.get("type", "Unknown").capitalize()
            model_name = proc.get("model_name", "")
            return f"{word} — {proc_type}: {model_name}"
        else:
            recent_idx = row - len(self._active_processes)
            if recent_idx < len(self._recent_processes):
                proc = self._recent_processes[recent_idx]
                status = (proc.get("status") or "completed").lower()
                word = {
                    "completed": "Completed",
                    "failed": "Failed",
                    "error": "Failed",
                    "cancelled": "Cancelled",
                    "canceled": "Cancelled",
                    "interrupted": "Interrupted",
                }.get(status, status.capitalize() or "Completed")
                proc_type = proc.get("type", "Unknown").capitalize()
                model_name = proc.get("model_name", "")
                return f"{word} — {proc_type}: {model_name}"
        return ""
```

- [ ] **Step 2: Loss-chart summary.** Append to `LossChartView.set_points` (L2360-2368), after the existing `self._points = cleaned` + `setNeedsDisplay_`:

```python
        try:
            pts = self._points or []
            if pts:
                best = min(pts, key=lambda t: t[1])
                summary = (
                    f"Loss chart: {len(pts)} epochs plotted. Best loss "
                    f"{best[1]:.4g} at epoch {best[0]}. Latest: loss "
                    f"{pts[-1][1]:.4g} at epoch {pts[-1][0]}."
                )
            else:
                summary = "Loss chart: no data yet."
            self.setAccessibilityValue_(summary)
        except Exception:
            pass
```

(Tuple order is verified `(epoch, loss)` — `set_points` itself builds `cleaned` as `(int(p[0]), float(p[1]))`; epochs stay ints so no `int()` cast is needed in the summary.)

- [ ] **Step 3: Progress value.** At BOTH determinate sites in the dashboard detail panel add an AX value right after the `setDoubleValue_`:

```python
            # training branch, after L3095 (frac is 0..1):
            self.detail_progress.setAccessibilityValue_(f"{int(frac * 100)} percent")
            # inference branch, after L3310 (stats["pct"] is already 0..100):
            self.detail_progress.setAccessibilityValue_(f"{int(stats['pct'])} percent")
```

(The adjacent textual lines — `pct_txt` at L3096 and `detail_progress_text` at L3312-3314 — are NSTextField values VoiceOver reads as static text; the AX value on the indicator itself is what makes the CONTROL announce.)

- [ ] **Step 4: Compile + commit**

```bash
venv_macos/bin/python -m py_compile applio_launcher.py
git add applio_launcher.py
git commit -m "fix(a11y): dashboard rows/chart/progress expose truthful accessible values"
```

---

### Task 12: Progress-window live zone — readable by ear

**Goal:** The ProgressWindowController's live status (shown on relaunch-with-running-jobs) reads as words, not glyph noise: the Unicode block bar is hidden from the AX tree, the phase line carries an emoji-free accessible value, and every stats field is labeled.

**Files:**
- Modify: `applio_launcher.py` (cites verified: `_create_ui` L1147+ with `phase_label` L1357-1362, `visual_progress` L1373, `progress_percent` L1389-1392, `stats_values` built L1406-1435; live-zone update ≈L1859-1930 with the phase string at L1888-1890 and block bar at L1892-1898; timeout reset path L2048-2056)

**Acceptance Criteria:**
- [ ] `visual_progress` (block bar) is hidden from the accessibility tree (`setAccessibilityHidden_(True)` — verified available in this PyObjC)
- [ ] `phase_label` has AX label "Current phase"; its update site sets `setAccessibilityValue_(f"{phase} — {current} of {total} {total_label}")` (no emoji) AND the timeout reset path (L2048-2056) clears the AX value back to "Waiting for progress..."
- [ ] `progress_percent` has AX label "Phase progress"
- [ ] The four stats value fields are labeled "Speed", "Estimated time remaining", "Phase time", "Items"
- [ ] `py_compile` passes

**Verify:** `venv_macos/bin/python -m py_compile applio_launcher.py && grep -c "setAccessibilityHidden_\|Phase progress" applio_launcher.py` → ≥ 2

**Steps:**

- [ ] **Step 1: Labels at creation** — in `_create_ui` (elements at L1357-1435, all attribute names verified), after each element is built:

```python
        self.phase_label.setAccessibilityLabel_("Current phase")
        self.progress_percent.setAccessibilityLabel_("Phase progress")
        self.visual_progress.setAccessibilityHidden_(True)  # '█░░█…' is SR noise
        for field, ax_label in zip(
            self.stats_values,
            ("Speed", "Estimated time remaining", "Phase time", "Items"),
        ):
            field.setAccessibilityLabel_(ax_label)
```

(`self.stats_values` is the verified collection: built at L1406-1435, and its four slots are written in order Speed (L1906) / ETA (L1910) / Phase time (L1924) / Items (L1927) — the zip label order matches the real slot order.)

- [ ] **Step 2: Accessible phase value** — at the live-zone update site (L1888-1890, where the display string is `f"{icon}  {phase.upper()}  •  {current} of {total} {total_label}"`), keep the visual string and add right after it, reusing the SAME in-scope variables minus the icon:

```python
            self.phase_label.setAccessibilityValue_(
                f"{phase} — {current} of {total} {total_label}"
            )
```

ALSO clear the AX value in the reset path (L2048-2056, the 2-second-timeout branch that restores "Waiting for progress..." and `"--"` stats) — without this, a stale "PREPROCESS — 41 of 120 items" value outlives the visual reset:

```python
                    self.phase_label.setAccessibilityValue_("Waiting for progress...")
                    for val in self.stats_values:
                        val.setStringValue_("--")
```

- [ ] **Step 3: Compile + commit**

```bash
venv_macos/bin/python -m py_compile applio_launcher.py
git add applio_launcher.py
git commit -m "fix(a11y): progress window live zone reads as words, not glyph noise"
```

---

### Task 13: Dialog safety — non-destructive defaults, activated alerts, first responders

**Goal:** Reflexive Enter can no longer kill a training run; update alerts activate the app and offer an Escape-bound dismiss button with honest labeling; the dashboard and progress windows hand keyboard focus somewhere useful on open.

**Files:**
- Modify: `macos_wrapper.py` (`show_close_confirmation` L365-419 — buttons at L401-406, return-code mapping INSIDE the function at L414-419; the caller `on_window_closing` L422+ compares only the `CLOSE_*` module constants and needs NO changes — verified at L442/L447)
- Modify: `applio_launcher.py` (quit confirm L4525-4542 — AppKit import L4526-4530, buttons L4540-4541, check L4542; `ProcessDashboardController.show` L3953-3977; `ProgressWindowController` buttons `terminate_btn` L1487 / `pause_btn` L1502 / `logs_btn` L1521, with `terminate_btn`+`pause_btn` disabled after a user terminate at L2136-2138)
- Modify: `applio_update_check.py` (runModal sites L205 / L218 / L227 / L260; button pairs "Open GitHub Releases"/"OK" L202-203, "Download Update"/"Later" L215-216, single "OK" L225, "Open GitHub Releases"/"Later" L257-258 — all inside `_on_main`, which already runs on the main thread)

**Acceptance Criteria:**
- [ ] In both quit/close confirms the first (Return) button is the safe action; terminate requires an explicit non-default press; every `NSAlertFirstButtonReturn`/`NSAlertSecondButtonReturn` comparison matches the new order
- [ ] All four `applio_update_check.py` runModal sites call `NSApp.activateIgnoringOtherApps_(True)` first; the dismissive button (titled "OK"/"Later" — NOT "Cancel", so it gets no auto-Escape) has `setKeyEquivalent_("\x1b")`; the misleading "Download Update" title is renamed "Open Releases Page…"
- [ ] Dashboard `show()` sets `setInitialFirstResponder_(self.process_table)` and selects row 0 when rows exist; the progress window's initial responder is `pause_btn`, falling back to `logs_btn` when pause is disabled (post-terminate) — NEVER `terminate_btn`, which would put Return one keystroke from killing the run
- [ ] `py_compile` passes all three files

**Verify:** `venv_macos/bin/python -m py_compile macos_wrapper.py applio_launcher.py applio_update_check.py && grep -c "setKeyEquivalent_\|setInitialFirstResponder_" applio_update_check.py applio_launcher.py` → present in both

**Steps:**

- [ ] **Step 1: Close-confirm reorder** (`macos_wrapper.py` L365-419). EMPIRICAL FACT (verified in this venv): NSAlert auto-assigns Return (`\r`) to the FIRST button, and auto-assigns Escape (`\x1b`) to a button titled "Cancel" REGARDLESS of position; every other button gets `""`. So no explicit key-equivalent code is needed here — only the ORDER changes. Inside `show_close_confirmation`, reorder the three `addButtonWithTitle_` calls (L401-406) and swap the return mapping (L414-419):

```python
    alert.addButtonWithTitle_(
        "Keep Running"
    )  # First: safe default — auto Return; SIGSTOP'd jobs keep running
    alert.addButtonWithTitle_(
        "Terminate & Quit"
    )  # Second: no key equivalent — explicit click only
    alert.addButtonWithTitle_("Cancel")  # Third: auto Escape (title-based)
```

```python
    if response == NSAlertFirstButtonReturn:
        return CLOSE_KEEP_RUNNING
    elif response == NSAlertSecondButtonReturn:
        return CLOSE_QUIT
    else:
        return CLOSE_CANCEL
```

The CALLER (`on_window_closing`) needs NO changes — it compares `choice` only against the `CLOSE_*` module constants; the NSAlert return codes never escape this function (this corrects an earlier draft of this step that proposed editing the caller). Update the inline `# First button (NSAlertFirstButtonReturn)` comments and the docstring's option order (L369-373) to match.

- [ ] **Step 2: Quit-confirm reorder** (`applio_launcher.py` L4525-4542). Reorder to `"Cancel"` first / `"Terminate & Quit"` second, add `NSAlertSecondButtonReturn` to the AppKit import at L4526-4530, and swap the comparison at L4542:

```python
                alert.addButtonWithTitle_("Cancel")  # First: auto Escape; NO Return default
                alert.addButtonWithTitle_(
                    "Terminate & Quit"
                )  # Second: no key equivalent — explicit click only
                if alert.runModal() != NSAlertSecondButtonReturn:
                    return 0  # NSTerminateCancel
```

(Verified: when the first button is titled "Cancel", it takes Escape and NO button receives Return — Enter is inert, which is exactly the desired non-destructive behavior for a quit-with-running-jobs prompt. "Terminate & Quit" keeps `""`.)

- [ ] **Step 3: Update alerts** (`applio_update_check.py`, sites L205/L218/L227/L260): before each `runModal()`:

```python
            from AppKit import NSApp

            NSApp.activateIgnoringOtherApps_(True)
```

After building each alert's buttons, bind Escape to the dismissive one:

```python
            buttons = alert.buttons()
            if buttons:
                buttons[-1].setKeyEquivalent_("\x1b")
```

(Verified: `alert.buttons()` works in this PyObjC and returns the buttons in add order; `addButtonWithTitle_` also returns the button directly if you prefer to keep the reference. None of the dismissive titles here is "Cancel", so the explicit `\x1b` cannot collide with the title-based auto-Escape — do NOT set `\x1b` on two buttons of one alert.) Rename the primary button string `"Download Update"` → `"Open Releases Page…"` (L215; it runs `subprocess.Popen(["open", release_url])` — it opens a page, it does not download; audit gap). The first-position action buttons ("Open GitHub Releases"/"Open Releases Page…") keep the auto Return — opening a URL is non-destructive.

- [ ] **Step 4: Initial first responders.** Dashboard `show()` (L3953-3977), after `makeKeyAndOrderFront_`:

```python
        try:
            self.window.setInitialFirstResponder_(self.process_table)
            if self.process_table.numberOfRows() > 0:
                from Foundation import NSIndexSet

                self.process_table.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(0), False
                )
        except Exception:
            logging.debug("[Dashboard] first-responder setup failed", exc_info=True)
```

Progress window (in `show()`, L2092+, after the window is ordered front):

```python
        try:
            target = (
                self.pause_btn
                if hasattr(self, "pause_btn")
                and self.pause_btn
                and self.pause_btn.isEnabled()
                else self.logs_btn
            )
            self.window.setInitialFirstResponder_(target)
        except Exception:
            logging.debug("[ProgressWindow] first-responder setup failed", exc_info=True)
```

(`pause_btn` L1502 is the primary RECOVERABLE action; `logs_btn` L1521 is always enabled and fully non-destructive. `terminate_btn` L1487 must NOT be the initial responder — a reflexive Return there would kill the run, the exact failure this task exists to prevent. Both `pause_btn` and `terminate_btn` are disabled after a user terminate at L2136-2138, hence the `isEnabled()` fallback.)

- [ ] **Step 5: Compile + commit**

```bash
venv_macos/bin/python -m py_compile macos_wrapper.py applio_launcher.py applio_update_check.py
git add macos_wrapper.py applio_launcher.py applio_update_check.py
git commit -m "fix(a11y): safe dialog defaults, activated update alerts, window first responders"
```

---

### Task 14: Build-time patch — announced Stop/upload feedback in upstream files

**Goal:** Upstream handlers stop lying by silence: Stop Training / Stop Convert confirm via announced `gr.Info`/`gr.Warning` toasts; a completed audio upload announces where the file landed. Implemented as one new patcher plus an edit to the existing fork-owned `patch_stop_infer.py`.

**Files:**
- Create: `patches/patch_stop_feedback.py`
- Modify: `patches/patch_stop_infer.py` (fork-owned — add `gr.Info` inside `STOP_INFER_REPLACEMENT`)
- Modify: `build_macos.py` (`patches_to_apply` list in `pre_build_patch()` L713-847; the entry shape is a 4-TUPLE `(patcher_path, source_file, description, patcher_type)` — verified at L716 and in the loop at L875)
- Targets patched at build time (never edited directly): `tabs/settings/sections/restart.py` (commented `gr.Info` block in `stop_train` at L43-46, 8-SPACE indent, inside the outer `try:`; count variable is `killed`, incremented at L32/L40; `gradio as gr` already imported at L5; `stop_infer` L52-74 has NO commented block — its feedback comes from Step 3), `tabs/inference/inference.py` (`save_to_wav2` L286-297, single `return` at L297, 4-space indent; `gradio as gr` already imported at L8)

**Acceptance Criteria:**
- [ ] Running the patcher from the repo root transforms `restart.py` (`stop_train`: live `if killed > 0:` / `gr.Info(f"Stopped training ({killed} process(es) terminated).")` / `else: gr.Warning("No active training processes were found.")` replacing the commented block at try-body indent) and `inference.py` (`save_to_wav2` calls `gr.Info("Audio uploaded. It is now selected in the 'Select Audio' dropdown.")` just before its single `return`)
- [ ] Patcher resolves targets per-invocation base: with `tabs/settings/sections` as argv[1] it patches ONLY restart.py; with `tabs/inference` ONLY inference.py; with the repo root, both. Idempotent via its OWN per-file markers; exits 0 = patched/already-patched, 1 = anchor miss (matching `patch_stop_infer.py`'s convention at its L99)
- [ ] Registered as TWO 4-tuple entries in `patches_to_apply` (one per source file — a single entry would leave `inference.py` out of the `patched_files` snapshot/restore bookkeeping at L871-874 and it would stay patched after the build), placed right after the `patch_stop_infer` entry
- [ ] Indent rules followed: horizontal-only indent capture `\n([ \t]+)` (NOT `(\n\s+)` — see CLAUDE.md patcher indent-capture gotcha), replacement reproduces exactly one leading newline, per-file markers
- [ ] Patched targets `py_compile` cleanly; sources restored with `git checkout -- tabs/` afterward; `git status --porcelain tabs/` empty
- [ ] `patch_stop_infer.py` replacement body fires `gr.Info("Stopping batch conversion - finishing current file…")` before writing the cancel flag

**Verify:** `venv_macos/bin/python patches/patch_stop_feedback.py && venv_macos/bin/python -m py_compile tabs/settings/sections/restart.py tabs/inference/inference.py && git checkout -- tabs/ && git status --porcelain tabs/` → empty

**Steps:**

- [ ] **Step 1: Re-read the anchors** — `tabs/settings/sections/restart.py` L11-49 (`stop_train`: `killed = 0` at L16, the commented block at L43-46 at 8-space try-body indent, blank line before it and after it, bare `except:` at L48-49) and `tabs/inference/inference.py` L286-297 (`save_to_wav2`, single return). If upstream has changed since this plan was written (the merge notes in CLAUDE.md warn about anchor drift), re-point before continuing.

- [ ] **Step 2: Write the patcher** — `patches/patch_stop_feedback.py`. Key design point: the SAME patcher is registered TWICE with different `"dir"` bases (`build_macos` invokes it once per entry, argv[1] = `os.path.dirname(source_file)`, L890-893), so `apply()` must resolve each target relative to whatever base it is given — basename under a dir-type base, repo-relative path under the repo root (standalone dev runs):

```python
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
STOP_TRAIN_RE = re.compile(
    r"\n([ \t]+)# if killed > 0:\n(?:[ \t]+#[^\n]*\n)+"
)
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
    ret = content.find("\n    return", idx)
    if ret == -1:
        return content, "miss"
    insert_at = ret + 1
    inject = (
        f"    {UPLOAD_MARKER}\n"
        "    gr.Info(\"Audio uploaded. It is now selected in the "
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
```

(Exit convention matches `patches/patch_stop_infer.py` L99: 0 = patched or already patched, 1 = anchor miss — build_macos accepts both without warning, L908.)

- [ ] **Step 3: Edit `patches/patch_stop_infer.py`** (fork-owned) — inside the `STOP_INFER_REPLACEMENT` function body, before the cancel-flag write, add:

```python
    try:
        import gradio as gr

        gr.Info("Stopping batch conversion - finishing current file…")
    except Exception:
        pass
```

(This is the ONLY change stop_infer needs — upstream's `stop_infer` has no commented block to revive.)

- [ ] **Step 4: Register** — in `build_macos.py` `pre_build_patch()`'s `patches_to_apply` list, append TWO entries right after the `patch_stop_infer` tuple (L841-846), matching the list's 4-tuple shape exactly:

```python
        (
            "patches/patch_stop_feedback.py",
            "tabs/settings/sections/restart.py",
            "restart.py - announced Stop Training feedback",
            "dir",
        ),
        (
            "patches/patch_stop_feedback.py",
            "tabs/inference/inference.py",
            "inference.py - announced audio-upload feedback",
            "dir",
        ),
```

(TWO entries are required, not one: `patched_files` snapshots/restores per `source_file` — a single entry would restore `restart.py` but leave `inference.py` permanently patched on disk after every build. No PATCH_DEPENDENCIES entry is needed: this patcher's anchors — the commented block and `save_to_wav2`'s return — are untouched by every other patcher, including `patch_stop_infer`, which rewrites only the `stop_infer` function.)

- [ ] **Step 5: Test + restore + commit**

```bash
venv_macos/bin/python patches/patch_stop_feedback.py
venv_macos/bin/python -m py_compile tabs/settings/sections/restart.py tabs/inference/inference.py
grep -n "_APPLIO_A11Y" tabs/settings/sections/restart.py tabs/inference/inference.py
venv_macos/bin/python patches/patch_stop_feedback.py   # second run: already patched
git checkout -- tabs/
git status --porcelain tabs/   # must be empty
git add patches/patch_stop_feedback.py patches/patch_stop_infer.py build_macos.py
git commit -m "feat(a11y): announced Stop/upload feedback via build-time patch"
```

---

### Task 15: Build, frozen verification, live VoiceOver session

**Goal:** Produce a cert-free smoke build validating all Phase 1 changes frozen, verify the mechanical outcomes programmatically, and hand the user the live VoiceOver checklist that feeds the Phase 2 plan.

**Files:**
- No source changes (fix-forward only if verification exposes a defect)

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python build_macos.py` (no flags) completes with `BUILD COMPLETE`; build timestamp newer than the last commit
- [ ] `PlistBuddy` confirms `NSMicrophoneUsageDescription` in the built Info.plist
- [ ] Frozen app launches (`open dist/Applio.app`) and: Edit menu present with ⌘C/⌘V/⌘A; Process menu shows the jobs submenu; ⌘L/⇧⌘D/⌘0/⇧⌘R shortcuts fire; window title tracks boot stages; loading page has `aria-live` (verify via `curl` of the loading server or Safari Web Inspector if practical)
- [ ] During a short tracked job (batch-convert 2 audio files — training scripts are frozen-only but need a dataset; batch inference is the cheapest end-to-end job), the dock badge shows the count and `~/Library/Logs/Applio/applio_launcher.log` contains `[A11y] start:` and `[A11y] terminal:` lines
- [ ] The live VoiceOver checklist (below) has been handed to the user and its results recorded for the Phase 2 plan

**Verify:** `tail -20 ~/Library/Logs/Applio/applio_launcher.log | grep "\[A11y\]"` → at least one start/terminal pair after a job run

**Steps:**

- [ ] **Step 1: Pre-build hygiene**

```bash
osascript -e 'tell application "Applio" to quit' 2>/dev/null; sleep 3
git status --porcelain   # confirm no patched upstream files
```

- [ ] **Step 2: Cert-free smoke build** (per CLAUDE.md this is the functional gate; make it the LAST command of the invocation so its exit code is real):

```bash
venv_macos/bin/python build_macos.py
stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio
/usr/libexec/PlistBuddy -c 'Print :NSMicrophoneUsageDescription' dist/Applio.app/Contents/Info.plist
```

Expected: `BUILD COMPLETE`, a fresh timestamp, and the mic string printed.

- [ ] **Step 3: Frozen functional checks**

```bash
open dist/Applio.app
# after boot completes, in the Gradio UI: run a 2-file batch conversion
tail -f ~/Library/Logs/Applio/applio_launcher.log   # watch for [A11y] lines + badge
```

Manually confirm: Edit menu + shortcuts; Process → Active Processes submenu; export/model download link now opens a save panel (ALLOW_DOWNLOADS); quit confirm has "Cancel" first (Enter inert, Escape cancels — per Task 2's verified NSAlert behavior) and close confirm defaults to "Keep Running".

- [ ] **Step 4: Live VoiceOver checklist (user-run, results recorded for Phase 2):**
1. Clipboard: ⌘A/⌘C/⌘V inside a Gradio Textbox; VO+Shift+M on a text field and on the terms link (context menu still empty — expected; Edit menu is the remedy — confirm it covers the need)
2. Boot with VoiceOver on: does the live region announce stages? Does the window-title change appear in the VO window chooser?
3. Tab traversal: Tab from the URL-less main window reaches buttons/checkboxes now
4. Train→finish→export round trip (with a real dataset): announcements at start/finish, badge behavior, dashboard reading (Pause label, loss-chart summary, row words)
5. Toast catching: start a long job, keep navigating — are completion announcements audible? Is 10 s toast transience still a problem? (feeds Phase 2 "Last result" region)
6. Dialogs: Enter on quit confirm must NOT terminate; Escape dismisses update alert
7. If available: repeat 1+4 with a braille display; note churn/panning problems

- [ ] **Step 5: Record results, CHANGELOG entry, commit any fix-forwards**

```bash
git status --porcelain && git log --oneline -1
```

Add an entry under the top-most section of `CHANGELOG.md` (fork-owned; convention: one bullet per user-visible change) summarizing Phase 1: announced job lifecycle + dock badge, Edit menu + keyboard shortcuts, enabled downloads, accessible boot/loading screen, mic TCC string, dashboard/progress-window truthful AX labels and values, safe dialog defaults, Stop/upload toasts. Document checklist outcomes in `ACCESSIBILITY_AUDIT.md` §7 ("Phase 1 results") or a follow-up notes file; commit.

---

## Self-review notes

- **Pre-implementation review pass (2026-08-21):** every load-bearing code claim in this plan was verified against the working tree at main HEAD `df9ff52b` (`applio_launcher.py`, `macos_wrapper.py`, `menu_spec.py`, `applio_update_check.py`, `build_macos.py`, `patches/`, `tabs/`, `assets/`, and the frozen `venv_macos` pywebview source), and NSAlert key-equivalent behavior was verified EMPIRICALLY in `venv_macos` (first button auto-receives Return; a button titled "Cancel" auto-receives Escape in ANY position; other buttons get `""`; `alert.buttons()` and the `addButtonWithTitle_` return value both work). Corrections folded in during review: Task 2 uses module-level process fns + `model_name` keys + a psutil pause probe (JSON status cannot see SIGSTOP); Task 9 uses the real submenu plumbing (`_dynamic_items`, `runDispatch:` + one fixed tag from `_key_to_tag` — no invented refs); Task 11 annotates pause state at list-refresh time (the `⏸` branch is dead) and names BOTH progress sites; Task 12 clears the AX value in the reset path; Task 13 reorders buttons only where the caller needs no change, maps return codes inside `show_close_confirmation`, and targets `pause_btn`/`logs_btn` as initial responder (never `terminate_btn`); Task 14 registers TWO 4-tuple entries with per-base target resolution and the real 8-space-indent anchor regex; Task 15 adds the CHANGELOG entry. Line cites are as-of that HEAD; tasks that anchor on upstream-owned files (Tasks 1-3, 14) tell the implementer to re-read anchors first.
- **Spec coverage vs. the audit:** blockers ps-1..4 → Tasks 2/3/4 (+ patch Task 14 for stop feedback); fs-1 partially (browse buttons are Phase 2; this plan fixes the native-side enablers: ALLOW_DOWNLOADS + Edit menu + shortcuts); ws-1 partially (Task 14 toasts the dropped feedback; full error-routing is Phase 2/3); kf-1 → Task 3. Majors covered: na-2/3/4/5/6/7 → Tasks 2/10/11/12; na-8/9 → Tasks 9/4; ir-2/3(partial)/5/6/8/10/11 → Tasks 3/4/13/2; kf-2/5/9 + ws-3 are web-UI-side → Phase 2 (JS payload) / Phase 3 (gradio PRs); ps-5 → Task 12; ps-9 → Tasks 10/11. Critic gaps covered: clipboard (Task 7), downloads (Task 3), mic (Task 6); toast-transience/i18n/braille/export-journey/restart-confirm → Phase 2 plan.
- **Deliberately out of scope (Phase 2/3 plans):** `/api/progress` route + injected JS live region (web-UI announcements), `js_api` FileBridge + per-field Browse buttons, Accessibility settings submenu (verbosity/sound), native-string i18n, persistent "Last result" region, gr.Error routing with log tails, upstream Applio/gradio PRs, announcement milestones (epoch/percent).
- **Type consistency:** `AnnouncementPolicy.events(snapshot)` shape `{key: {"type","name","status"}}` is produced by `_a11y_snapshot` (Task 2) and consumed unchanged; `post_announcement(message, element)` matches the launcher's call; menu-spec keys `edit.*` are introduced once (Task 7) and referenced by the test updates in Tasks 7/8.
