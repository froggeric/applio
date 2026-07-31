# Single-Process-Only + Inference Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v3.6.3.7 with (A) single-process as the only code path (two-process machinery + flags deleted) and (B) batch-inference progress on the Process Dashboard, plus two bug fixes carried by Part B.

**Architecture:** Part A is a deletion refactor — every two-process branch is inert under the default flag (`APPLIO_SINGLE_PROCESS` defaults to `"1"` at `applio_launcher.py:287`; `APPLIO_LAUNCHED_BY_LAUNCHER` is only ever set by the dead `_spawn_wrapper`), so removing branches is behavior-preserving for the shipped path. Part B instruments the upstream `convert_audio_batch` (`rvc/infer/infer.py:345`) via a new build-time patcher to write `~/Applio/.applio/inference_progress.json` (atomic temp+`os.replace`, single writer, no lock), which the dashboard polls on its existing heartbeat (`menuUpdateTimerFired_` `applio_launcher.py:4613` → `update_process_list` `:3711`) and synthesizes into `_active_processes`. Stop is cooperative cancellation via `inference_cancel.flag` (replaces the PID-kill at `tabs/settings/sections/restart.py:52-74` that killed the whole app in single-process, and the frozen-CWD `infer_pid.txt` write at `rvc/infer/infer.py:364`). No subprocess, no PID kill — inference stays the synchronous in-process call that returns converted audio to the Gradio UI.

**Tech Stack:** Python 3.10, PyObjC/AppKit (dashboard NSView), PyInstaller build-time patchers (`patches/`), file-based inter-thread signaling (`~/Applio/.applio/`).

**User decisions (already made, do not re-litigate):**
- Inference scope: **batch only**. Single-file / TTS / realtime deferred (reasons in spec "Out of scope").
- Tracking mechanism: **in-process progress file** (NOT a subprocess — the synchronous return-the-output contract is load-bearing; `core.py:314` calls `convert_audio_batch(**kwargs)` synchronously and returns a string).
- Two-process code: **rip out entirely**, drop the flag. No opt-out remains.
- `python macos_wrapper.py` stays a **single-process-only** dev entry (`start_gui(launcher=None)` + `webview.start`).
- One release (v3.6.3.7) carries both parts; Part A code lands before Part B code.

**Spec of record:** `docs/superpowers/specs/2026-07-31-single-process-only-and-inference-dashboard-design.md`. This plan is self-contained, but the spec is the design authority if a detail is ambiguous.

**Branch:** `feat/single-process-and-inference-dashboard`.

---

## Verified facts (re-confirmed against source at plan-review time — trust these)

- `rvc/infer/infer.py:345-406` `convert_audio_batch(self, audio_input_paths, audio_output_path, **kwargs)`. Body L361-406: `pid = os.getpid()` → `try:` → writes `os.path.join(now_dir,"assets","infer_pid.txt")` (L364, `now_dir=os.getcwd()` L25) → builds `audio_files` via `os.listdir`+extension-tuple filter → loops `for a in audio_files:` calling `self.convert_audio(audio_input_path=, audio_output_path=, **kwargs)` (L397-401), skipping files whose `_output.wav` already exists (L395-396) → `finally: os.remove(...infer_pid.txt)` (L406). **Only one** `os.remove(os.path.join(now_dir, "assets", "infer_pid.txt"))` in the file.
- **Model name source:** `core.py:255` passes `"model_path": pth_path` in the kwargs dict, then `core.py:314 infer_pipeline.convert_audio_batch(**kwargs)`. So inside `convert_audio_batch` the model path is `kwargs.get("model_path")` (a `.pth` path). It is NOT `cpt_name` and `weight_root` is NOT in scope there. The instance attr `self.loaded_model` (`rvc/infer/infer.py:61,426`) holds the same path after `get_vc`. **Use `kwargs.get("model_path")`.**
- `tabs/settings/sections/restart.py:52-74` `stop_infer()`; `now_dir=os.getcwd()` L8; `import psutil` L6 (shared with `stop_train` L11 — KEEP it); next function is `def restart_applio()` L77. The only caller of `stop_infer` is the inference-tab Stop button (`tabs/inference/inference.py` imports it + `stop_button.click(fn=stop_infer)`). Nothing else reads `infer_pid.txt`.
- `patches/patch_process_tracking.py:29-34` `_get_process_state_path()` uses `os.environ.get("APPLIO_DATA_PATH", os.path.expanduser("~/Applio"))` → `<data>/.applio/active_processes.json` (2-tier). History writer `:175-194` `_add_to_history`: required fields `type, started_at, completed_at`; cap `_HISTORY_MAX_ENTRIES=50`; fcntl `LOCK_EX` on `<hist>.lock`; `process_id = f"{type}-{started_at}"`. Injected into `core.py` (NOT importable from `rvc/infer/infer.py`).
- `applio_launcher.py` history paths: `get_history_file_path()` (L805) = `os.path.join(os.path.dirname(get_process_state_path()), "process_history.json")`; lock = `get_history_file_path() + ".lock"` (L598). `get_process_state_path()` (L363) is **3-tier** (env → `runtime_paths.json` → `~/Applio`), but checks env FIRST. `load_process_history()` (L601) / `add_to_history()` (L737) generate `process_id` the same way. So an injected entry with `type, started_at, completed_at` renders natively.
- **`APPLIO_DATA_PATH` is set in-process for the frozen path:** `macos_wrapper.py:1765-1776` (inside `start_gui`, called by both the single-process launcher and standalone `__main__`) sets `os.environ["APPLIO_DATA_PATH"] = _early_prefs.get_data_path() or ~/Applio` **when `sys.frozen`**. Inference runs in the Gradio thread of that same process, so the injected 2-tier resolver (env → `~/Applio`) lands in the SAME `.applio` dir the launcher reads. (Dev, non-frozen: env unset → both fall back to `~/Applio`; consistent.)
- Dashboard refresh model: `_menu_update_timer` (`applio_launcher.py:4605`, 2 s) → `menuUpdateTimerFired_` (L4613) → `update_process_list` (L3711) rebuilds `_active_processes` + state transitions + auto-show. Separately `_timer` (`_start_update_timer` L3315, `DETAIL_UPDATE_INTERVAL`) → `coordinatedUpdate_` (L3344) → `_update_detail_panel()` (L3379) every tick + `refresh_process_list()` (L3208, throttled ~3 s). **Two `_active_processes` rebuild sites: `update_process_list` L3723 and `refresh_process_list` L3214** — the inference synthesis must be applied at BOTH.
- Detail-panel outlets (`applio_launcher.py:2299-2564`): `detail_panel, detail_name, detail_status, detail_progress, detail_progress_text, detail_best_label, detail_current_label, detail_eta, detail_chart (LossChartView), detail_log_view, detail_log_scroll`. Training path (L2670-2800) maps metrics into these; `_update_detail_panel` calls `_update_action_bar(proc)` at L2797 and `_update_log_display(proc)` at L2800.
- `_current_pid` (L2881) returns a pid only if `verify_process_identity` confirms it alive → **None for an inference proc** (no pid key). `_update_action_bar` (L2893) sets `stop_btn.setEnabled_(bool(pid))` → would DISABLE Stop for inference unless branched. `_resolve_log_path` (L2875) returns `log_file`/`log_path` → None for inference. `stopProcess_` (L2922) early-returns on `if not pid` (L2926) before any cancel logic.
- `applio_launcher.py` imports `from AppKit import (...)` at module top (L73-85) → **NOT importable headless for pytest**. The stats math must live in a separate AppKit-free module.
- `patches/patch_refinegan_legacy_infer.py` (registered `build_macos.py:698`) ALSO patches `rvc/infer/infer.py`: injects `_detect_refinegan_legacy_from_weights` after the `logging.getLogger("faiss.loader")...` line (L37) and rewrites `setup_network`; appends its marker at EOF. **No collision** with the new patcher (different injection point — before `class VoiceConverter` vs after the logging line; different method — `convert_audio_batch` vs `setup_network`). `refinegan` is registered FIRST so it runs first; the new patcher sees its edits but its own anchors (`pid = os.getpid()`, `class VoiceConverter`) are untouched.
- `build_macos.py:717-736` runs patchers in `patches_to_apply` order; for `"dir"` patchers, `patcher_arg = os.path.dirname(source_file)` (so `rvc/infer` → patcher opens `os.path.join(base_path,"infer.py")`).

---

## File Structure

| File | Responsibility | Touched by |
|---|---|---|
| `macos_wrapper.py` (fork-owned) | Strip `_SINGLE_PROCESS` + `APPLIO_LAUNCHED_BY_LAUNCHER` gates, `_ipc_signal_checker`; collapse to single-process-only | A1 |
| `applio_launcher.py` (fork-owned) | Strip `APPLIO_SINGLE_PROCESS` gates + dead methods (A2); add inference reader/synth/detail-panel/action-bar/stop/sweep (B3, B4) | A2, B3, B4 |
| `applio_inference_stats.py` (NEW, fork-owned) | AppKit-free pure function `_compute_inference_stats(record, now)` (import-safe for pytest) | B3 |
| `patches/patch_inference_progress.py` (NEW, fork-owned) | Inject progress helpers + rewrite `convert_audio_batch` in `rvc/infer/infer.py` | B1 |
| `patches/patch_stop_infer.py` (NEW, fork-owned) | Rewrite `stop_infer` in `tabs/settings/sections/restart.py` to cooperative cancel | B2 |
| `build_macos.py` (fork-owned) | Register the two new patchers in `patches_to_apply` | B1, B2 |
| `tests/test_inference_progress.py` (NEW) | Pure-Python unit test for `_compute_inference_stats` (no AppKit import) | B3 |
| `CLAUDE.md`, `README_MACOS.md`, `FORK_DIFFERENCES.md`, `CHANGELOG.md` | Reflect single-process-only; Part B changelog | A3 |
| `dist/Applio.app` (build output) | One frozen build validates both parts | F1 |
| GitHub release `v3.6.3.7` | Signed+notarized DMG + description | R1 |

**Discipline (from CLAUDE.md):** `rvc/infer/infer.py`, `tabs/**`, `core.py` are UPSTREAM — patch only via `patches/`, never direct-edit; after any build, `git status` must show no upstream files dirty. **Never `import build_macos`** (runs the whole build at module import). Test a patcher by running it directly, then `git checkout -- <source>`.

---

## Part A — Remove the two-process code

### Task A1: Strip two-process gates in `macos_wrapper.py`

**Goal:** Remove `_SINGLE_PROCESS`, all `APPLIO_LAUNCHED_BY_LAUNCHER` gates, and `_ipc_signal_checker`; leave `macos_wrapper.py` single-process-only with `start_gui(launcher=None)` still callable.

**Approach (grep-driven — line numbers drift as you edit, so resolve EVERY grep hit):** For each `if _SINGLE_PROCESS:` keep the True (single-process) body, delete the `if`/`else` wrapper + the two-process `else` body. For each `if os.environ.get("APPLIO_LAUNCHED_BY_LAUNCHER"):` keep the standalone (False/else) body, delete the True branch + wrapper. Then delete methods/helpers that become unreferenced.

**Sites (confirmed by grep `rg -n "_SINGLE_PROCESS|APPLIO_LAUNCHED_BY_LAUNCHER|_ipc_signal_checker|_request_launcher_quit|_check_and_handle_show_main_window" macos_wrapper.py`):** L39 (`_SINGLE_PROCESS` def); `_SINGLE_PROCESS` branches at L951, L1575, L1595, L1615, L1661; `APPLIO_LAUNCHED_BY_LAUNCHER` gates at L65, L108, L128, L287, L1694, L1963 (L1726 is a docstring mention, delete the mention); `_ipc_signal_checker` def L1637 + its daemon-thread start L1671; `_request_launcher_quit` def L264 (callers L632 in `on_window_closing` two-process branch, L1610/L1622 in `_report_fatal_error`); `_check_and_handle_show_main_window` def L862 (only caller L1643 inside `_ipc_signal_checker`); `_report_fatal_error` def L1583.

**Notable callouts:**
- `on_window_closing` (~L619-633): the single-process branch quits via `AppHelper.callAfter(_deferred_terminate)` (KEEP — this is the deferred-terminate path); the two-process tail (`logging.info("[Window] Forwarding quit to launcher"); _request_launcher_quit(); return False`) is DELETED. After this, `_request_launcher_quit` has only the `_report_fatal_error` callers left.
- `_report_fatal_error` (L1583): collapse to the single-process body only (the `if _SINGLE_PROCESS:` branches become unconditional; drop the `_request_launcher_quit()` calls at L1610/L1622). After collapse, `_request_launcher_quit` has no callers → delete it (L264).
- `run_until_window_created` (L1647-1698): keep the `if _SINGLE_PROCESS:` supervised-backend branch (`_supervised_backend(self)`, L1665), delete the `else: start_backend` branch (L1667); delete the `_ipc_signal_checker` thread start (L1671); collapse the L1694 `if APPLIO_LAUNCHED_BY_LAUNCHER` logging block to the standalone log line (or delete the if/else, keep one log). `webview.settings['SHOW_DEFAULT_MENUS'] = False` (L1698) stays.
- `_check_and_handle_show_main_window` (L862): after deleting `_ipc_signal_checker` (its only caller), it is unreferenced → delete. (In single-process the launcher shows windows directly via `bring_to_front`/`_surface_window`; this IPC handler is dead.)

**Removing `_ipc_signal_checker` is safe for single-process:** it only polled `_check_and_handle_show_main_window()` every 2 s (two-process file-IPC: dashboard→wrapper "show window"). In single-process the dashboard and Gradio share one process, so the launcher handles window-show directly. No regression.

**Acceptance Criteria:**
- [ ] `rg -n "_SINGLE_PROCESS|APPLIO_LAUNCHED_BY_LAUNCHER|_ipc_signal_checker|_request_launcher_quit|_check_and_handle_show_main_window" macos_wrapper.py` → zero hits.
- [ ] `venv_macos/bin/python -m py_compile macos_wrapper.py` exits 0.
- [ ] `start_gui(launcher=None)` is still defined (the standalone dev entry path).
- [ ] Deferred-terminate quit path (`AppHelper.callAfter(...)` in `on_window_closing`) is intact.

**Verify:**
```bash
rg -n "_SINGLE_PROCESS|APPLIO_LAUNCHED_BY_LAUNCHER|_ipc_signal_checker|_request_launcher_quit|_check_and_handle_show_main_window" macos_wrapper.py   # expect: no output
venv_macos/bin/python -m py_compile macos_wrapper.py && echo OK
```

**Steps:**
- [ ] **Step 1:** Read each gate site to see exact branch text before editing (L39, L65, L951, L108, L128, L287, L1575, L1595, L1615, L1637, L1661, L1671, L1694, L1726, L1963, plus L264, L619-633, L862, L1583).
- [ ] **Step 2:** Delete `_SINGLE_PROCESS = ...` (L39) and the Phase-2 comment block above it. Resolve every `if _SINGLE_PROCESS:` branch (keep True body).
- [ ] **Step 3:** Resolve every `if os.environ.get("APPLIO_LAUNCHED_BY_LAUNCHER"):` gate (keep standalone body); delete the docstring mention at L1726.
- [ ] **Step 4:** Delete `_ipc_signal_checker` (L1637) + the daemon-thread start (L1671). Delete `_check_and_handle_show_main_window` (L862 — now unreferenced).
- [ ] **Step 5:** Collapse `on_window_closing` to its deferred-terminate branch; collapse `_report_fatal_error` to single-process-only; delete `_request_launcher_quit` (L264, now unreferenced).
- [ ] **Step 6:** Run Verify (all greps empty, `py_compile` passes).
- [ ] **Step 7:** Commit: `git add macos_wrapper.py && git commit -m "refactor: remove two-process code from macos_wrapper (single-process only)"`.

---

### Task A2: Strip two-process gates in `applio_launcher.py`

**Goal:** Remove `APPLIO_SINGLE_PROCESS`, `_spawn_wrapper`, `_setup_ipc_observer`, and all gate sites; leave single-process as the only path. (Edits the same file B3/B4 will later touch — must complete before them.)

**Sites (grep `rg -n "APPLIO_SINGLE_PROCESS|_spawn_wrapper|_setup_ipc_observer|APPLIO_LAUNCHED_BY_LAUNCHER" applio_launcher.py`):** L287 (flag def + the stale "OFF default == two-process" comment L282-286); gate sites L3410, L3746, L3939, L3942, L3970, L4017, L4105, L4145, L4254, L4343, L4618, L4621, L4627, L4723, L5036; `_setup_ipc_observer` L4190 + its call L4065; `_spawn_wrapper` L4460 + call sites L4166, L4304 (+ the `APPLIO_LAUNCHED_BY_LAUNCHER=1` env it sets L4471); `wrapper_pid` docstring L4421; "None in two-process" annotations on `_main_window` (~L4058).

**Behavior-preservation targets (grep-verify each after edit):**
- The auto-show hook (~L3745-3752 in `update_process_list`): now unconditional but STILL guarded by `_opened_this_session` (L3749). Keep the `not was_active and self._current_state == "active"` conditions.
- Quit path: `applicationShouldTerminate_` / `_handle_terminate` still quits via deferred `AppHelper.callAfter(... NSApp.terminate_(None))` with `_user_confirmed_quit`; SIGTERM suppression (`_handle_terminate` ignoring SIGTERM in single-process) is preserved (the `if APPLIO_SINGLE_PROCESS:` gate there just becomes unconditional).
- `menuUpdateTimerFired_` (L4613-4628): keep the single-process dashboard-heartbeat branch (L4621-4625); delete the two-process `_check_wrapper_died()` branch (L4627-4628).

**Acceptance Criteria:**
- [ ] `rg -n "APPLIO_SINGLE_PROCESS|_spawn_wrapper|_setup_ipc_observer|APPLIO_LAUNCHED_BY_LAUNCHER" applio_launcher.py` → zero hits.
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py` exits 0.
- [ ] Auto-show hook unconditional but still gated on `_opened_this_session`.
- [ ] Deferred-terminate quit + SIGTERM suppression intact.

**Verify:**
```bash
rg -n "APPLIO_SINGLE_PROCESS|_spawn_wrapper|_setup_ipc_observer|APPLIO_LAUNCHED_BY_LAUNCHER" applio_launcher.py   # expect: no output
venv_macos/bin/python -m py_compile applio_launcher.py && echo OK
```

**Steps:**
- [ ] **Step 1:** Delete `APPLIO_SINGLE_PROCESS = ...` (L287) + the stale comment (L282-286).
- [ ] **Step 2:** Resolve every `if APPLIO_SINGLE_PROCESS:` gate (keep True body). Notable: reopen paths (L3942, L4254 — keep `window.show()`); auto-show hook (keep, gated `_opened_this_session`); terminate/SIGTERM handler (L4017, L4105, L4145, L4343 — keep ignore-SIGTERM + deferred-terminate).
- [ ] **Step 3:** Delete `_spawn_wrapper` (L4460) + call sites (L4166, L4304). Grep-verify no callers remain.
- [ ] **Step 4:** Delete `_setup_ipc_observer` (L4190) + its setup call (L4065).
- [ ] **Step 5:** Remove the `wrapper_pid` docstring (L4421) + "None in two-process" annotations.
- [ ] **Step 6:** Run Verify.
- [ ] **Step 7:** Commit: `git add applio_launcher.py && git commit -m "refactor: remove two-process code from applio_launcher (single-process only)"`.

---

### Task A3: Update docs to single-process-only

**Goal:** Repo docs reflect that single-process is the only architecture.

**Files:** `CLAUDE.md` (Phase 2 section; the `APPLIO_SINGLE_PROCESS=0` opt-back-in line; two-process gotchas that no longer apply — KEEP load-bearing gotchas: NSApp.delegate weak ref, deferred terminate via `callAfter`, supervisor `_supervised_backend`, `setup_logging` additive, frozen-CWD invariant, post-training SIGTERM suppression); `README_MACOS.md`; `FORK_DIFFERENCES.md`; `CHANGELOG.md` (add `[3.6.3.7]` entry).

**Acceptance Criteria:**
- [ ] `rg -n "APPLIO_SINGLE_PROCESS=0|opt back into two-process|two-process fallback" CLAUDE.md README_MACOS.md` → no output.
- [ ] `CHANGELOG.md` has a `[3.6.3.7]` section: single-process-only, inference dashboard, Stop-kills-app fix, frozen-CWD `infer_pid.txt` fix.
- [ ] No em dashes, no AI-tell phrasing.

**Verify:**
```bash
rg -n "APPLIO_SINGLE_PROCESS=0|opt back into two-process|two-process fallback" CLAUDE.md README_MACOS.md   # expect: no output
rg -n "\[3.6.3.7\]" CHANGELOG.md   # expect: 1 hit
```

**Steps:**
- [ ] **Step 1:** `CLAUDE.md`: rewrite the Phase 2 section to past tense ("single-process is the only architecture; the two-process code and `APPLIO_SINGLE_PROCESS` flag were removed in 3.6.3.7"). Delete the `APPLIO_SINGLE_PROCESS=0` opt-back-in instructions + standalone-run/legacy-fallback notes. Delete gotchas that only mattered for two-process (the `APPLIO_LAUNCHED_BY_LAUNCHER` spawn note; the "2 icons in dock" launcher limitation). KEEP the load-bearing gotchas listed above.
- [ ] **Step 2:** `README_MACOS.md`: replace any "two-process fallback" paragraph with a one-line statement that the app runs as a single native process.
- [ ] **Step 3:** `FORK_DIFFERENCES.md`: add a bullet — single-process native app; two-process removed in 3.6.3.7.
- [ ] **Step 4:** Add the `[3.6.3.7]` CHANGELOG entry (Added: inference dashboard; Changed: single-process-only; Fixed: Stop-kills-app, frozen-CWD infer_pid write). No em dashes.
- [ ] **Step 5:** Run Verify.
- [ ] **Step 6:** Commit: `git add CLAUDE.md README_MACOS.md FORK_DIFFERENCES.md CHANGELOG.md && git commit -m "docs: single-process-only + inference dashboard (3.6.3.7)"`.

---

## Part B — Batch-inference progress on the Process Dashboard

### Task B1: `patches/patch_inference_progress.py` + register

**Goal:** New build-time patcher that injects progress helpers and rewrites `convert_audio_batch` in `rvc/infer/infer.py` to emit `inference_progress.json`, support cooperative cancel, reject concurrent batches, append history, and remove the broken `infer_pid.txt` logic.

**Files:**
- Create: `patches/patch_inference_progress.py`
- Modify: `build_macos.py:699` (after the existing `patch_refinegan_legacy_infer.py` entry).

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python patches/patch_inference_progress.py rvc/infer` exits 0 and prints patched-success.
- [ ] `venv_macos/bin/python -m py_compile rvc/infer/infer.py` exits 0 after patching.
- [ ] `rg -n "_infer_cancel_requested|_write_infer_progress|_infer_progress_path" rvc/infer/infer.py` → hits.
- [ ] `rg -n "infer_pid" rvc/infer/infer.py` → zero hits.
- [ ] Idempotent: running twice on a patched file makes no change.
- [ ] After testing, `git checkout -- rvc/infer/infer.py` restores upstream (clean tree).
- [ ] Registered in `build_macos.py:patches_to_apply` as `("patches/patch_inference_progress.py", "rvc/infer/infer.py", "infer.py - batch inference progress tracking", "dir")`.

**Verify:**
```bash
venv_macos/bin/python patches/patch_inference_progress.py rvc/infer
venv_macos/bin/python -m py_compile rvc/infer/infer.py && echo COMPILE_OK
rg -c "_infer_cancel_requested|_write_infer_progress" rvc/infer/infer.py   # expect: >=1
rg -c "infer_pid" rvc/infer/infer.py                                       # expect: 0
venv_macos/bin/python patches/patch_inference_progress.py rvc/infer        # idempotency: no-op
git checkout -- rvc/infer/infer.py
git status --short                                                          # expect: clean
```

**Steps:**

- [ ] **Step 1:** Create `patches/patch_inference_progress.py` modeled on `patches/patch_refinegan_legacy_infer.py` (same `base_path` arg contract: opens `os.path.join(base_path, "infer.py")`; `__main__` takes `base_path = sys.argv[1]`).

- [ ] **Step 2 — Injected helper block** (inject BEFORE `class VoiceConverter`, idempotency marker `# === Inference Progress Tracking (injected by patch) ===`). This is the verbatim block; it uses `_infer_*` aliases exclusively so the injection is self-contained and survives upstream import changes:

```python
INFER_PROGRESS_HELPERS = r'''
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
'''
```

- [ ] **Step 3 — `convert_audio_batch` replacement.** Anchor with a regex (NOT a literal — the body contains a 13-element tuple that would make a literal match fragile). Match from `pid = os.getpid()` non-greededly to the single `os.remove(os.path.join(now_dir, "assets", "infer_pid.txt"))` line:

```python
# Anchor regex: spans the method BODY only (the def + docstring L345-360 are preserved).
INFER_BATCH_ANCHOR = re.compile(
    r'        pid = os\.getpid\(\)\n        try:.*?'
    r'os\.remove\(os\.path\.join\(now_dir, "assets", "infer_pid\.txt"\)\)\n',
    re.DOTALL,
)
```

The replacement (8-space method-body indent; correct `try/except/finally` structure — terminal write + history for completed/cancelled live INSIDE the try body; `finally` ONLY cleans the cancel flag; `except` writes the error record + history then re-raises). Verbatim:

```python
INFER_BATCH_REPLACEMENT = r'''        # Inference progress tracking (3.6.3.7): cooperative cancel + progress file.
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
'''
```

  **Why this is correct (the original plan had bugs here — all fixed):**
  - **`try/except/finally` is syntactically valid:** the terminal-record write + history append for the completed/cancelled path are INSIDE the `try` body (after the loop), not between `except` and `finally`. `finally` only removes the cancel flag. (The original plan put `print`/write/history between `except` and `finally`, which is a `SyntaxError` — Python requires `finally` to immediately follow the last `except`.)
  - **Model name:** `kwargs.get("model_path")` (confirmed `core.py:255` passes `model_path`). The original plan used `weight_root`/`cpt_name`, neither of which is in scope (`NameError`).
  - **`enumerate`** instead of `audio_files.index(a)` — O(1) and immune to any duplicate-basename concern (listdir names are unique, but enumerate is clearer and avoids O(n²)).
  - **Terminal status normalised:** `cancelling` (set on the break) becomes `cancelled` in the terminal record; `running` becomes `completed`. (Original wrote the literal `"cancelling"` as a terminal status.)
  - **Stale-flag clear at start:** a Stop click after a batch already finished would otherwise leave a flag that cancels the NEXT batch on its first file.

  **`self.convert_audio(**kwargs)` is unchanged** — `kwargs` still carries `model_path`, so single-file conversion per batch item works exactly as before. One bad file raises (caught → error record → re-raised) so the batch aborts on first error, matching original behavior.

- [ ] **Step 4 — Patcher functions:** `patch_infer_py(base_path)`:
  - (a) Inject `INFER_PROGRESS_HELPERS` before `class VoiceConverter` (use `content.replace("class VoiceConverter:", INFER_PROGRESS_HELPERS + "\n\nclass VoiceConverter:", 1)` or insert before the first `\nclass ` — but `class VoiceConverter` is unique and stable; prefer the explicit replace) IF `# === Inference Progress Tracking (injected by patch) ===` not already in content.
  - (b) Replace the batch body: if `"_infer_cancel_requested()"` NOT already in content, `INFER_BATCH_ANCHOR.sub(INFER_BATCH_REPLACEMENT, content, count=1)`. If the anchor doesn't match, print `"Could not find convert_audio_batch anchor"` and return False.
  - Write back only if changed.
- [ ] **Step 5:** `__main__`: `base_path = sys.argv[1] if len(sys.argv) > 1 else "."`; call `patch_infer_py`; print `"[infer.py inference-progress] Patched successfully"` / `"Already patched, skipping"` / `"Could not find convert_audio_batch anchor"`.
- [ ] **Step 6:** Register in `build_macos.py:patches_to_apply` AFTER the `patch_refinegan_legacy_infer.py` line (L698) — same source file, different method, no collision:
```python
("patches/patch_inference_progress.py", "rvc/infer/infer.py", "infer.py - batch inference progress tracking", "dir"),
```
- [ ] **Step 7:** Run Verify.
- [ ] **Step 8:** Commit: `git add patches/patch_inference_progress.py build_macos.py && git commit -m "feat: patcher for batch-inference progress tracking + cancel + history"`.

---

### Task B2: `patches/patch_stop_infer.py` + register

**Goal:** Rewrite `stop_infer` in `tabs/settings/sections/restart.py` to write the cancel flag cooperatively (no PID kill, no `now_dir`).

**Files:** Create `patches/patch_stop_infer.py`; register in `build_macos.py:patches_to_apply`.

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python patches/patch_stop_infer.py tabs/settings/sections` exits 0.
- [ ] `venv_macos/bin/python -m py_compile tabs/settings/sections/restart.py` exits 0.
- [ ] `rg -n "inference_cancel.flag" tabs/settings/sections/restart.py` → 1 hit (inside `stop_infer`).
- [ ] `rg -n "infer_pid" tabs/settings/sections/restart.py` → 0 hits. (`import psutil` stays — `stop_train` L11 still uses it.)
- [ ] Idempotent; restore upstream after testing.

**Verify:**
```bash
venv_macos/bin/python patches/patch_stop_infer.py tabs/settings/sections
venv_macos/bin/python -m py_compile tabs/settings/sections/restart.py && echo OK
rg -n "inference_cancel.flag" tabs/settings/sections/restart.py    # expect: 1 hit
rg -n "infer_pid" tabs/settings/sections/restart.py                # expect: 0 hits
git checkout -- tabs/settings/sections/restart.py
git status --short                                                  # expect: clean
```

**Steps:**
- [ ] **Step 1:** Create `patches/patch_stop_infer.py` (opens `os.path.join(base_path, "restart.py")`; `__main__` takes `base_path = sys.argv[1]`).
- [ ] **Step 2:** Replacement (regex from `def stop_infer():` up to (but not including) `def restart_applio():`, `re.DOTALL`). Idempotency marker = the string `inference_cancel.flag` (skip if present):

```python
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
```

- [ ] **Step 3:** `patch_restart_py(base_path)`: read, skip if `"inference_cancel.flag" in content`, else `re.sub(r'def stop_infer\(\):.*?(?=\ndef restart_applio\(\))', STOP_INFER_REPLACEMENT, content, count=1, flags=re.DOTALL)`, write back.
- [ ] **Step 4:** Register in `build_macos.py:patches_to_apply`:
```python
("patches/patch_stop_infer.py", "tabs/settings/sections/restart.py", "restart.py - cooperative inference cancel", "dir"),
```
- [ ] **Step 5:** Run Verify.
- [ ] **Step 6:** Commit: `git add patches/patch_stop_infer.py build_macos.py && git commit -m "fix: cooperative inference Stop (no longer kills the app in single-process)"`.

---

### Task B3: Dashboard integration in `applio_launcher.py`

**Goal:** The dashboard reads `inference_progress.json`, synthesizes an inference proc into `_active_processes` (at BOTH rebuild sites), renders an inference card (progress = processed/total, ETA/speed stats, Stop writes the cancel flag, Reveal targets output_folder). Includes a pure-Python unit test for the stats math in an AppKit-free module.

**Files:** Create `applio_inference_stats.py`; create `tests/test_inference_progress.py`; modify `applio_launcher.py` (reader + synthesis helper + 5 branch points).

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py applio_inference_stats.py` exits 0.
- [ ] `venv_macos/bin/python -m pytest tests/test_inference_progress.py -v` passes (no AppKit import).
- [ ] `rg -n "_read_inference_progress|_augment_processes_with_inference|_render_inference_detail|_is_inference" applio_launcher.py` → hits.
- [ ] Synthesized proc carries `_is_inference: True`; `stopProcess_`/`_update_action_bar`/`_resolve_log_path`/`_update_detail_panel` all branch on it (no pid access on the inference path).

**Verify:**
```bash
venv_macos/bin/python -m py_compile applio_launcher.py applio_inference_stats.py && echo OK
venv_macos/bin/python -m pytest tests/test_inference_progress.py -v
rg -n "_augment_processes_with_inference|_render_inference_detail|_is_inference" applio_launcher.py
```

**Steps:**

- [ ] **Step 1 (TDD — failing test first):** Create `applio_inference_stats.py` (pure stdlib, NO AppKit import — this is the import-safe module; the launcher imports from it, the test imports from it directly):

```python
# applio_inference_stats.py - pure-Python inference-progress stats (no AppKit).
def compute_inference_stats(record, now):
    """Return {pct, elapsed, eta, speed} for an inference progress record.

    pct = processed/total*100. eta = remaining_files * avg_per_file (avg uses
    converted files only; skips don't cost convert time). speed = files/min.
    All divide-by-zeros guarded to 0.0. On a terminal record, ended_at drives
    elapsed (so `now` is ignored) and eta is 0 once processed >= total.
    """
    total = record.get("total", 0) or 0
    processed = record.get("processed", 0) or 0
    converted = record.get("converted", 0) or 0
    started = record.get("started_at") or now
    pct = (100.0 * processed / total) if total else 0.0
    elapsed = max(0.0, (record.get("ended_at") or now) - started)
    avg = (elapsed / converted) if converted else 0.0
    remaining = max(0, total - processed)
    eta = (remaining * avg) if converted else 0.0
    speed = (converted / (elapsed / 60.0)) if (elapsed > 0 and converted) else 0.0
    return {"pct": round(pct, 1), "elapsed": round(elapsed, 1),
            "eta": round(eta, 1), "speed": round(speed, 1)}
```

  Test (`tests/test_inference_progress.py`):
```python
from applio_inference_stats import compute_inference_stats

def test_progress_pct_and_eta():
    r = {"total": 10, "processed": 4, "converted": 4, "skipped": 0, "started_at": 1000.0}
    s = compute_inference_stats(r, now=1010.0)
    assert s["pct"] == 40.0 and s["elapsed"] == 10.0
    assert s["eta"] == 15.0          # (10-4)*(10/4)
    assert s["speed"] == 24.0        # 4/(10/60)

def test_zero_converted_no_divzero():
    r = {"total": 5, "processed": 0, "converted": 0, "skipped": 0, "started_at": 1000.0}
    s = compute_inference_stats(r, now=1003.0)
    assert s["eta"] == 0.0 and s["speed"] == 0.0 and s["pct"] == 0.0

def test_completed_uses_ended_at_eta_zero():
    r = {"total": 3, "processed": 3, "converted": 2, "skipped": 1,
         "started_at": 1000.0, "ended_at": 1010.0}
    s = compute_inference_stats(r, now=9999.0)
    assert s["pct"] == 100.0 and s["eta"] == 0.0 and s["elapsed"] == 10.0

def test_zero_total():
    r = {"total": 0, "processed": 0, "converted": 0, "skipped": 0, "started_at": 1000.0}
    s = compute_inference_stats(r, now=1001.0)
    assert s["pct"] == 0.0 and s["eta"] == 0.0
```

- [ ] **Step 2:** Run the test → expect PASS (the module has no AppKit import). (`applio_launcher` is NOT imported by the test — it pulls AppKit at module top L73, so it is not headless-importable; that is exactly why the math lives in `applio_inference_stats.py`.)

- [ ] **Step 3:** In `applio_launcher.py`, near `get_active_processes` (L575), add the reader:
```python
def _read_inference_progress():
    """Read ~/Applio/.applio/inference_progress.json, or None if missing/corrupt."""
    path = os.path.join(os.path.dirname(get_process_state_path()), "inference_progress.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
```
  (Reuses the launcher's own `get_process_state_path` 3-tier resolver → guaranteed same `.applio` dir the launcher reads history/active from.)

- [ ] **Step 4:** Add the synthesis helper (module-level) and call it at BOTH rebuild sites:
```python
def _synthesize_inference_proc():
    inf = _read_inference_progress()
    if not inf or inf.get("status") not in ("running", "cancelling"):
        return None
    return {
        "type": "inference", "status": inf["status"],
        "model_name": inf.get("model_name", ""),
        "total": inf.get("total", 0), "processed": inf.get("processed", 0),
        "converted": inf.get("converted", 0), "skipped": inf.get("skipped", 0),
        "current_file": inf.get("current_file", ""),
        "started_at": inf.get("started_at"),
        "started_at_epoch": inf.get("started_at"),
        "output_folder": inf.get("output_folder"),
        "_is_inference": True,
    }
```
  Apply at L3723 (`update_process_list`) and L3214 (`refresh_process_list`): after `self._active_processes = get_active_processes()`, insert:
```python
_inf_proc = _synthesize_inference_proc()
if _inf_proc:
    self._active_processes.append(_inf_proc)
```
  (Two sites — confirmed by grep. This makes the sidebar row, idle→active transition, and auto-show hook all fire for inference with no new UI primitives. The auto-show now surfaces the dashboard when a batch starts.)

- [ ] **Step 5:** In `_update_detail_panel`, immediately after `self._current_proc = proc` (L2668), add the inference branch — it reads the LIVE record so the bar climbs every timer tick (the table rebuild refreshes the row every ~3 s; the detail timer refreshes the panel every ~1 s):
```python
if proc.get("_is_inference"):
    live = _read_inference_progress()
    if live and live.get("status") in ("running", "cancelling"):
        proc = dict(proc)
        proc.update(live)
        proc["_is_inference"] = True
        proc["started_at_epoch"] = live.get("started_at")
        self._current_proc = proc
    self._render_inference_detail(proc)
    return
```
  Then add `_render_inference_detail(self, proc)` (maps inference values onto the SAME outlets the training path uses — confirmed names L2299-2564):
```python
def _render_inference_detail(self, proc):
    from applio_inference_stats import compute_inference_stats
    try:
        self.detail_panel.setHidden_(False)
        if hasattr(self, "placeholder_view") and self.placeholder_view:
            self.placeholder_view.setHidden_(True)
        model_name = proc.get("model_name", "")
        if hasattr(self, "detail_name") and self.detail_name:
            self.detail_name.setStringValue_(
                f"Inference: {model_name}" if model_name else "Inference")
        status = proc.get("status", "running")
        label = {"running": "Running", "cancelling": "Stopping…"}.get(status, status.title())
        if hasattr(self, "detail_status") and self.detail_status:
            self.detail_status.setStringValue_(label)
        stats = compute_inference_stats(proc, now=time.time())
        total = proc.get("total", 0) or 0
        processed = proc.get("processed", 0) or 0
        converted = proc.get("converted", 0) or 0
        skipped = proc.get("skipped", 0) or 0
        if hasattr(self, "detail_progress") and self.detail_progress:
            self.detail_progress.stopAnimation_(None)
            self.detail_progress.setIndeterminate_(False)
            self.detail_progress.setDoubleValue_(stats["pct"])
        if hasattr(self, "detail_progress_text") and self.detail_progress_text:
            self.detail_progress_text.setStringValue_(
                f"{processed}/{total} files ({stats['pct']}%)")
        if hasattr(self, "detail_current_label") and self.detail_current_label:
            cur = proc.get("current_file", "")
            self.detail_current_label.setStringValue_(
                f"Converted {converted}  |  Skipped {skipped}" +
                (f"  |  File: {cur}" if cur else ""))
            self.detail_current_label.setHidden_(False)
        if hasattr(self, "detail_best_label") and self.detail_best_label:
            self.detail_best_label.setStringValue_(
                f"Speed {stats['speed']} files/min")
            self.detail_best_label.setHidden_(False)
        if hasattr(self, "detail_eta") and self.detail_eta:
            self.detail_eta.setStringValue_(f"Estimated time: {stats['eta']}s")
        if hasattr(self, "detail_chart") and self.detail_chart:
            self.detail_chart.setHidden_(True)   # no loss curve for inference
        if hasattr(self, "detail_log_view") and self.detail_log_view:
            self.detail_log_view.setString_(
                f"Status: {label}\n{converted} converted, {skipped} skipped of {total}.\n"
                f"Speed {stats['speed']} files/min, elapsed {stats['elapsed']}s.")
        self._update_action_bar(proc)
    except Exception as e:
        logging.warning(f"[Dashboard] inference detail render failed: {e}")
```
  (For a HISTORICAL inference row selected from the sidebar, `live` is terminal/None so `proc` keeps the history entry's terminal stats; `compute_inference_stats` uses its `ended_at`.)

- [ ] **Step 6 — `_update_action_bar` (REGRESSION FIX):** it currently does `stop_btn.setEnabled_(bool(pid))`, which DISABLES Stop for inference (no pid). Add an inference branch at the TOP (before the pid logic):
```python
def _update_action_bar(self, proc):
    if proc is not None and proc.get("_is_inference"):
        is_running = proc.get("status") in ("running", "cancelling")
        has_output = bool(proc.get("output_folder"))
        if hasattr(self, "stop_btn") and self.stop_btn:
            self.stop_btn.setEnabled_(is_running)
        if hasattr(self, "pause_btn") and self.pause_btn:
            self.pause_btn.setEnabled_(False)          # pause meaningless in-process
            self.pause_btn.setTitle_("Pause")
        if hasattr(self, "reveal_btn") and self.reveal_btn:
            self.reveal_btn.setEnabled_(has_output)
        if hasattr(self, "open_btn") and self.open_btn:
            self.open_btn.setEnabled_(has_output)
        return
    # ... existing pid-based logic unchanged ...
```

- [ ] **Step 7 — `stopProcess_` (branch BEFORE the pid early-return at L2926):**
```python
def stopProcess_(self, sender):
    proc = getattr(self, "_current_proc", None) or self._selected_process
    if proc is not None and proc.get("_is_inference"):
        if proc.get("status") not in ("running", "cancelling"):
            return
        try:
            data_path = os.environ.get("APPLIO_DATA_PATH") or os.path.expanduser("~/Applio")
            flag = os.path.join(data_path, ".applio", "inference_cancel.flag")
            os.makedirs(os.path.dirname(flag), exist_ok=True)
            open(flag, "w").close()
            if hasattr(self, "detail_status") and self.detail_status:
                self.detail_status.setStringValue_("Stopping…")
            if hasattr(self, "stop_btn") and self.stop_btn:
                self.stop_btn.setEnabled_(False)
            logging.info("[Dashboard] Wrote inference cancel flag")
        except OSError as e:
            logging.warning(f"[Dashboard] Could not write inference cancel flag: {e}")
        return
    # ... existing pid-based terminate() logic unchanged ...
```
  (`togglePauseProcess_` already early-returns on `if not pid` (L2952); with Pause disabled for inference it is never invoked. No change needed, but verify the button is disabled per Step 6.)

- [ ] **Step 8 — `_resolve_log_path` (so Reveal/Open target output_folder unchanged):**
```python
def _resolve_log_path(self, proc):
    if not proc:
        return None
    if proc.get("_is_inference"):
        out = proc.get("output_folder")
        if out:
            real = os.path.realpath(out)
            if os.path.isdir(real):     # realpath + isdir guard (no exec, Finder only)
                return real
        return None
    return proc.get("log_file") or proc.get("log_path")
```
  `revealLog_`/`openLog_` (L2970/L2982) need NO change — they call `_resolve_log_path` and `os.path.exists`/`NSWorkspace`; for a folder, `activateFileViewerSelecting_` reveals it and `openURL_` opens it in Finder.

- [ ] **Step 9:** Run Verify. Manual dev spot-check optional (the frozen smoke in F1 is the real gate).
- [ ] **Step 10:** Commit: `git add applio_launcher.py applio_inference_stats.py tests/test_inference_progress.py && git commit -m "feat: dashboard shows batch-inference progress (card, ETA, cooperative Stop)"`.

---

### Task B4: Startup sweep for stale inference progress

**Goal:** On launcher startup, mark a stale `running` inference record as `interrupted` (crash/quit recovery) so the dashboard never shows a phantom running job, and append the interrupted run to history.

**Files:** Modify `applio_launcher.py` — add `_sweep_stale_inference_progress()` and call it once at launcher init.

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py` exits 0.
- [ ] `rg -n "_sweep_stale_inference_progress" applio_launcher.py` → ≥2 hits (def + call site).
- [ ] A stale `running` record is rewritten to `interrupted` with `ended_at`/`elapsed` set, a matching history entry appended (schema-compatible), and any stale `inference_cancel.flag` removed.

**Verify:**
```bash
venv_macos/bin/python -m py_compile applio_launcher.py && echo OK
rg -n "_sweep_stale_inference_progress" applio_launcher.py
```

**Steps:**
- [ ] **Step 1:** Add module-level `_sweep_stale_inference_progress()` (reuses the launcher's own resolution + the same history schema/lock the injected writer uses):
```python
def _sweep_stale_inference_progress():
    """Mark a stale 'running' inference record (app crashed/quit mid-batch) as
    'interrupted' so the dashboard never shows a phantom running job. Appends a
    history entry and removes any stale cancel flag. Safe to call multiple times."""
    inf = _read_inference_progress()
    if not inf or inf.get("status") != "running":
        return
    import time as _t, datetime as _dt
    started = inf.get("started_at") or _t.time()
    ended = _t.time()
    inf["status"] = "interrupted"
    inf["error"] = "interrupted by app restart"
    inf["ended_at"] = ended
    inf["elapsed"] = ended - started
    inf["current_file"] = ""
    data_path = os.path.dirname(_read_inference_progress.__code__.co_filename)  # placeholder
    # Write the progress file atomically (0o600) — reuse the launcher's resolver:
    prog_path = os.path.join(os.path.dirname(get_process_state_path()), "inference_progress.json")
    try:
        os.makedirs(os.path.dirname(prog_path), exist_ok=True)
        tmp = prog_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(inf, f)
        os.replace(tmp, prog_path)
    except OSError as e:
        logging.warning(f"[Launcher] inference sweep write failed: {e}")
    # Append interrupted history entry (fcntl LOCK_EX, schema-compatible).
    hist_path = get_history_file_path()
    try:
        os.makedirs(os.path.dirname(hist_path), exist_ok=True)
        with open(hist_path + ".lock", "a") as _lf:
            fcntl.flock(_lf.fileno(), fcntl.LOCK_EX)
            try:
                hist = {"version": 1, "history": []}
                if os.path.exists(hist_path):
                    try:
                        with open(hist_path, "r", encoding="utf-8") as f:
                            hist = json.load(f) or hist
                    except json.JSONDecodeError:
                        pass
                hist.setdefault("history", []).insert(0, {
                    "type": "inference",
                    "model_name": inf.get("model_name", ""),
                    "started_at": _dt.datetime.fromtimestamp(started).isoformat(),
                    "completed_at": _dt.datetime.fromtimestamp(ended).isoformat(),
                    "status": "interrupted",
                    "total": inf.get("total", 0),
                    "converted": inf.get("converted", 0),
                    "skipped": inf.get("skipped", 0),
                    "process_id": "inference-%s" % started,
                })
                hist["history"] = hist["history"][:HISTORY_MAX_ENTRIES]
                tmp = hist_path + ".tmp"
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(hist, f, indent=2)
                os.replace(tmp, hist_path)
            finally:
                fcntl.flock(_lf.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        logging.warning(f"[Launcher] inference history append failed: {e}")
    # Clear a stale cancel flag.
    try:
        os.remove(os.path.join(os.path.dirname(get_process_state_path()), "inference_cancel.flag"))
    except OSError:
        pass
```
  **(Drop the placeholder line `data_path = ...co_filename...` — it is a leftover; the function uses `get_process_state_path()` directly for both paths.)**
- [ ] **Step 2:** Call `_sweep_stale_inference_progress()` once at launcher init, AFTER `~/Applio/.applio/` is known to exist (in `ApplioLauncher.__init__` or the existing startup sequence, near where history cleanup runs). Place it before the menu/NSApplication loop starts.
- [ ] **Step 3:** Run Verify.
- [ ] **Step 4:** Commit: `git add applio_launcher.py && git commit -m "feat: recover stale inference progress on startup (no phantom running card)"`.

---

## Validation + Release

### Task F1: Frozen validation (Part A + Part B)

> **USER-ORDERED GATE — NON-SKIPPABLE.** This validates the shipped, frozen app (the user has consistently required testing the built path, not dev). It MUST NOT be closed by declaring it "verified inline" or substituting a dev run. Close only after every acceptance item is re-validated against `dist/Applio.app` with output captured.

**Goal:** One frozen build; smoke-test both Part A (single-process-only launch/quit) and Part B (inference card, cooperative Stop that leaves the app alive, completion+history, concurrent-batch rejection, empty/skip-all, interrupted recovery).

**Files:** Build outputs only. No source edits.

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python build_macos.py` (no `--sign`) completes; after build `git status` shows NO upstream files dirty.
- [ ] `stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio` timestamp is after the last commit.
- [ ] **Part A:** `open dist/Applio.app` → Window → Process Monitor opens the dashboard (one window); Cmd+Q quits; `pgrep -f Applio` → no orphan.
- [ ] **Part B (Stop no longer kills app — load-bearing):** batch of ≥3 files → dashboard auto-shows an inference card with `processed/total` climbing → capture `pgrep -f Applio` (pid P1) → click Stop (dashboard OR inference-tab "Stop convert") → within one file's conversion the loop halts, status `cancelled`, and `pgrep -f Applio` shows the SAME pid P1 (app alive) → history sidebar shows `cancelled`.
- [ ] **Part B (completion + history):** a small batch to completion → card reaches total → `completed` → history shows the run with correct counts; selecting it renders the inference summary.
- [ ] **Part B (concurrent-batch rejection):** start a batch, start a second from another tab → second surfaces the "Another batch inference is already running" error; first's progress file unclobbered.
- [ ] **Part B (empty + skip-all):** empty folder → no running card, a 0-file completed history entry; all-outputs-exist folder → "0 converted, N skipped" then completes.
- [ ] **Part B (interrupted recovery):** start a batch, force-quit mid-batch (`kill -9`) → relaunch → no phantom running card → history shows `interrupted`.

**Verify:** the acceptance items above, each with captured output. The `pgrep -f Applio` pid before/after Stop is the load-bearing proof that Stop no longer kills the app.

**Steps:**
- [ ] **Step 1:** `git status --short` (clean), then `venv_macos/bin/python build_macos.py` (cert-free). Capture tail; confirm `BUILD COMPLETE`.
- [ ] **Step 2:** `git status --short` → expect no upstream dirty. `stat` the binary timestamp.
- [ ] **Step 3:** Run the Part A smoke (open, dashboard, Cmd+Q, pgrep).
- [ ] **Step 4:** Run each Part B smoke (B-AC5 through B-AC9), capturing the `pgrep -f Applio` pid before AND after Stop for B-AC5 (the pid must be unchanged).
- [ ] **Step 5:** If any item fails, file the failure with output and stop (do not mark complete; do not proceed to R1).
- [ ] **Step 6:** No commit (validation only). Report results.

---

### Task R1: Cut v3.6.3.7 release

> **USER-ORDERED GATE — NON-SKIPPABLE.** Releasing publishes to GitHub (hard to reverse, outward-facing). Close only after the signed+notarized DMG is verified and the release description is published with the user's sign-off.

**Goal:** Version bump, signed+notarized DMG, GitHub release `v3.6.3.7` with a clean description.

**Files:** Modify `build_macos.py` (`BUILD_NUMBER = 7`); modify `CHANGELOG.md` (date `[3.6.3.7]`).

**Acceptance Criteria:**
- [ ] `BUILD_NUMBER = 7` in `build_macos.py`; `CHANGELOG.md` `[3.6.3.7]` dated.
- [ ] `venv_macos/bin/python build_macos.py --sign --notarize --dmg` completes; `xcrun stapler validate "dist/Applio-3.6.3.7.dmg"` → "The validate action worked!"; `spctl -vvv --assess --type execute dist/Applio.app` → `source=Notarized Developer ID`.
- [ ] Tag `v3.6.3.7` on the merged commit; GitHub release created (DMG attached) with the clean description (from spec "Release notes draft"). No em dashes, no AI tells.

**Verify:**
```bash
xcrun stapler validate "dist/Applio-3.6.3.7.dmg"        # "The validate action worked!"
spctl -vvv --assess --type execute dist/Applio.app      # source=Notarized Developer ID
gh api repos/froggeric/applio-macOS-native-app/releases/tags/v3.6.3.7 --jq '{tag_name, name, assets:[.assets[].name]}'
```

**Steps:**
- [ ] **Step 1:** `BUILD_NUMBER = 7` in `build_macos.py`; date `[3.6.3.7]` in CHANGELOG. Commit.
- [ ] **Step 2:** `venv_macos/bin/python build_macos.py --sign --notarize --dmg` (background; ~15 min). Verify staple + spctl + stapler.
- [ ] **Step 3:** Merge `feat/single-process-and-inference-dashboard` → `main` (FF if possible); tag `v3.6.3.7`; push.
- [ ] **Step 4:** Create the GitHub release (`gh api` + curl upload if `gh release` lacks scope) with the spec's release-notes draft (single-process-only, inference dashboard, Stop fix, frozen-CWD fix). Attach the DMG.
- [ ] **Step 5:** Verify the release (assets + description). Capture output. Confirm with the user before considering it done.

---

## Self-Review (completed)

**1. Spec coverage:** Part A removal → A1 (macos_wrapper) + A2 (applio_launcher); docs → A3. Part B patcher → B1; stop fix → B2; dashboard → B3; stale recovery → B4; frozen validation → F1; release → R1. Both bug fixes (Stop-kills-app, frozen-CWD infer_pid) are covered by B1 (removes PID logic) + B2 (cooperative stop). Edge cases (empty, skip-all, cancel-mid-file, concurrent, interrupted, stale-flag) → F1 acceptance items + B1/B4 code. History schema → B1 `_infer_add_to_history` + B4 sweep (fcntl-matched, schema-compatible). Security (display-only fields, realpath+isdir guard) → B3 Step 8. ✅
**2. Placeholder scan:** No TBD/TODO. The model-name source is concrete (`kwargs.get("model_path")`, verified `core.py:255`). The stats module is concrete (`applio_inference_stats.py`, AppKit-free). All anchors are exact (regex for the tuple-laden batch body; literal for `stop_infer`). ✅
**3. Bugs fixed vs. the prior draft:** (a) `try/except/finally` syntax error — terminal write moved inside the try body; (b) `NameError` on `weight_root`/`cpt_name` — now `kwargs.get("model_path")`; (c) `audio_files.index(a)` O(n²) — now `enumerate`; (d) terminal status left as `"cancelling"` — now normalized to `"cancelled"`; (e) `_update_action_bar` would disable Stop for inference — now branched; (f) stale cancel flag from a post-completion Stop click would cancel the next batch — now cleared at start; (g) headless test import — now in an AppKit-free module; (h) inference synthesis applied at only one rebuild site — now at both (`update_process_list` + `refresh_process_list`); (i) detail panel reading stale `_selected_process` — now reads the live record. ✅
**4. Type/key consistency:** `compute_inference_stats` returns `{pct, elapsed, eta, speed}`; `_render_inference_detail` uses those keys. Synthesized proc keys (`_is_inference`, `started_at_epoch`, `output_folder`) match the branch logic. Progress file schema keys are consistent across B1 (writer), B3 (reader), B4 (sweep). History entry required fields (`type, started_at, completed_at`) present in every write path (completed, cancelled, error, interrupted). ✅
**5. Known limitations (accepted, out of scope):** the quit-confirmation active-process check (`applio_launcher.py:3984,4135,4239,4724,4741`) does NOT include inference (those call `get_active_processes()` directly, not the augmented list) — quitting mid-batch is recovered by the B4 startup sweep, so this is non-blocking; aligning those sites is a future hardening pass. Pause is disabled for inference (cooperative pause isn't possible mid-file).
