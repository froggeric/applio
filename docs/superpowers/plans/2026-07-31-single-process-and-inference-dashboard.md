# Single-Process-Only + Inference Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v3.6.3.7 with (A) single-process as the only code path (two-process machinery + flags deleted) and (B) batch-inference progress on the Process Dashboard, plus two bug fixes carried by Part B.

**Architecture:** Part A is a deletion refactor — every two-process branch is inert under the default flag, so removing branches is behavior-preserving. Part B instruments the upstream `convert_audio_batch` via a new build-time patcher to write `~/Applio/.applio/inference_progress.json` (atomic, single-writer, no lock), which the dashboard polls on its existing 2 s heartbeat and synthesizes into `_active_processes`. Stop is cooperative cancellation via `inference_cancel.flag` (replaces the PID-kill that killed the whole app in single-process). No subprocess, no PID kill — inference stays the synchronous in-process call that returns converted audio to the Gradio UI.

**Tech Stack:** Python 3.10, PyObjC/AppKit (dashboard NSView), PyInstaller build-time patchers (`patches/`), file-based inter-thread signaling (`~/Applio/.applio/`).

**User decisions (already made, do not re-litigate):**
- Inference scope: **batch only**. Single-file / TTS / realtime deferred (reasons in spec "Out of scope").
- Tracking mechanism: **in-process progress file** (NOT a subprocess — the synchronous return-the-output contract is load-bearing).
- Two-process code: **rip out entirely**, drop the flag. No opt-out remains.
- `python macos_wrapper.py` stays a **single-process-only** dev entry.
- One release (v3.6.3.7) carries both parts; Part A code lands before Part B code.

**Spec of record:** `docs/superpowers/specs/2026-07-31-single-process-only-and-inference-dashboard-design.md` (verified file:line facts, full injected code, edge cases, security). This plan is self-contained, but the spec is the design authority if a detail is ambiguous.

**Branch:** `feat/single-process-and-inference-dashboard` (already created; spec committed at a4b89de4).

---

## File Structure

| File | Responsibility | Touched by |
|---|---|---|
| `macos_wrapper.py` (fork-owned) | Strip `_SINGLE_PROCESS` + `APPLIO_LAUNCHED_BY_LAUNCHER` gates, `_ipc_signal_checker`; collapse to single-process-only | A1 |
| `applio_launcher.py` (fork-owned) | Strip `APPLIO_SINGLE_PROCESS` gates + dead methods (A2); add inference reader/synth/detail-panel/stop/sweep (B3, B4) | A2, B3, B4 |
| `patches/patch_inference_progress.py` (NEW, fork-owned) | Inject progress helpers + rewrite `convert_audio_batch` in `rvc/infer/infer.py` | B1 |
| `patches/patch_stop_infer.py` (NEW, fork-owned) | Rewrite `stop_infer` in `tabs/settings/sections/restart.py` to cooperative cancel | B2 |
| `build_macos.py` (fork-owned) | Register the two new patchers in `patches_to_apply` | B1, B2 |
| `tests/test_inference_progress.py` (NEW) | Pure-Python unit test for the dashboard ETA/speed math + progress-file schema | B3 |
| `CLAUDE.md`, `README_MACOS.md`, `FORK_DIFFERENCES.md`, `CHANGELOG.md` | Reflect single-process-only; Part B changelog | A3 |
| `dist/Applio.app` (build output) | One frozen build validates both parts | F1 |
| GitHub release `v3.6.3.7` | Signed+notarized DMG + description | R1 |

**Discipline (from CLAUDE.md):** `rvc/infer/infer.py`, `tabs/**`, `core.py` are UPSTREAM — patch only via `patches/`, never direct-edit; after any build, `git status` must show no upstream files dirty. **Never `import build_macos`** (runs the whole build at import). Test a patcher by running it directly, then `git checkout -- <source>`.

---

## Part A — Remove the two-process code

### Task A1: Strip two-process gates in `macos_wrapper.py`

**Goal:** Remove `_SINGLE_PROCESS`, all `APPLIO_LAUNCHED_BY_LAUNCHER` gates, and `_ipc_signal_checker`; leave `macos_wrapper.py` single-process-only with `start_gui(launcher=None)` still callable.

**Files:**
- Modify: `macos_wrapper.py` — L39 (`_SINGLE_PROCESS` def), L65/108/128/287/1694/1726/1963 (`APPLIO_LAUNCHED_BY_LAUNCHER` gates), L951/1575/1595/1615/1661 (`_SINGLE_PROCESS` branches), L1637 (`_ipc_signal_checker` def), L1671 (its daemon-thread start).

**Acceptance Criteria:**
- [ ] `rg -n "_SINGLE_PROCESS|APPLIO_LAUNCHED_BY_LAUNCHER|_ipc_signal_checker" macos_wrapper.py` → zero hits.
- [ ] `venv_macos/bin/python -m py_compile macos_wrapper.py` exits 0.
- [ ] `start_gui(launcher=None)` is still defined and callable (the standalone dev entry path).
- [ ] No references to the removed `_ipc_signal_checker` remain anywhere in the file.

**Verify:**
```bash
rg -n "_SINGLE_PROCESS|APPLIO_LAUNCHED_BY_LAUNCHER|_ipc_signal_checker" macos_wrapper.py   # expect: no output
venv_macos/bin/python -m py_compile macos_wrapper.py && echo OK
```

**Steps:**
- [ ] **Step 1:** Read `macos_wrapper.py` around each gate site (L39, L65, L951, L108, L128, L1575, L1595, L1615, L1637, L1661, L1671, L1694, L1726, L1963, L287) to see the exact branch text before editing.
- [ ] **Step 2:** Delete `_SINGLE_PROCESS = os.environ.get(...)` (L39). For each `if _SINGLE_PROCESS:` branch, keep the single-process body and delete the `if`/`else` wrapper and the two-process `else` body.
- [ ] **Step 3:** For each `if os.environ.get("APPLIO_LAUNCHED_BY_LAUNCHER"):` gate, keep the standalone (else/False) branch as the unconditional body and delete the launcher-spawned (True) branch + the `if` wrapper. (In the shipped default these were already False, so this is behavior-preserving.)
- [ ] **Step 4:** Delete the `_ipc_signal_checker` method (L1637) and the `threading.Thread(target=self._ipc_signal_checker, daemon=True).start()` call (L1671). Grep to confirm no remaining references.
- [ ] **Step 5:** Collapse `_report_fatal_error` to its single-process body (unconditional `raise` upstream; remove the `_request_launcher_quit()` two-process calls). Confirm any helper that becomes unreferenced (`_request_launcher_quit`, `_check_and_handle_show_main_window`) is also removed — grep each before deleting.
- [ ] **Step 6:** Run Verify. `py_compile` must pass and all three greps must be empty.
- [ ] **Step 7:** Commit: `git add macos_wrapper.py && git commit -m "refactor: remove two-process code from macos_wrapper (single-process only)"`.

---

### Task A2: Strip two-process gates in `applio_launcher.py`

**Goal:** Remove `APPLIO_SINGLE_PROCESS`, `_spawn_wrapper`, `_setup_ipc_observer`, and all gate sites; leave single-process as the only path. (Edits the same file B3/B4 will later touch — must complete before them.)

**Files:**
- Modify: `applio_launcher.py` — L287 (flag def); gate sites L3410, L3746, L3939, L3942, L3970, L4017, L4105, L4145, L4254, L4343, L4618, L4621, L4627, L4723, L5036; `_setup_ipc_observer` (L4190) + its call (L4065); `_spawn_wrapper` (L4460) + call sites (L4166, L4304); `APPLIO_LAUNCHED_BY_LAUNCHER=1` env (L4471); `wrapper_pid` docstring (L4421); "None in two-process" annotations (L4058 et al.); stale comment ~L283.

**Acceptance Criteria:**
- [ ] `rg -n "APPLIO_SINGLE_PROCESS|_spawn_wrapper|_setup_ipc_observer|APPLIO_LAUNCHED_BY_LAUNCHER" applio_launcher.py` → zero hits.
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py` exits 0.
- [ ] The auto-show hook (formerly gated on `APPLIO_SINGLE_PROCESS` ~L3745-3752) is now unconditional but still guarded by `_opened_this_session`.
- [ ] Quit path (`applicationShouldTerminate_` / `_handle_terminate`) still quits via deferred `AppHelper.callAfter(NSApp.terminate_(None))` with `_user_confirmed_quit` (the SIGTERM-suppression behavior is preserved).

**Verify:**
```bash
rg -n "APPLIO_SINGLE_PROCESS|_spawn_wrapper|_setup_ipc_observer|APPLIO_LAUNCHED_BY_LAUNCHER" applio_launcher.py   # expect: no output
venv_macos/bin/python -m py_compile applio_launcher.py && echo OK
```

**Steps:**
- [ ] **Step 1:** Delete `APPLIO_SINGLE_PROCESS = os.environ.get(...)` (L287) and the stale "OFF default == two-process" comment (~L283).
- [ ] **Step 2:** For each `if APPLIO_SINGLE_PROCESS:` gate (15 sites), keep the single-process (True) body as the unconditional code and delete the two-process `else` branch + the `if` wrapper. Pay special attention to: the reopen path (~L3942, L4254 — keep `window.show()`); the auto-show hook (~L4618-4627 — keep, still gated on `_opened_this_session`); the terminate/SIGTERM handler (~L4017, L4105, L4145, L4343 — keep the single-process ignore-SIGTERM + deferred-terminate behavior).
- [ ] **Step 3:** Delete `_spawn_wrapper` (L4460) and its two call sites (L4166, L4304). Grep confirms no callers remain.
- [ ] **Step 4:** Delete `_setup_ipc_observer` (L4190) and its setup call (L4065).
- [ ] **Step 5:** Remove the `wrapper_pid` docstring (L4421) and all "None in two-process" annotations on `_main_window`.
- [ ] **Step 6:** Run Verify (both greps empty, `py_compile` passes).
- [ ] **Step 7:** Commit: `git add applio_launcher.py && git commit -m "refactor: remove two-process code from applio_launcher (single-process only)"`.

---

### Task A3: Update docs to single-process-only

**Goal:** Repo docs reflect that single-process is the only architecture (past-tense the migration, drop the opt-back-in instructions).

**Files:**
- Modify: `CLAUDE.md` — Phase 2 section; the `APPLIO_SINGLE_PROCESS=0` opt-back-in line; two-process gotchas that no longer apply. Keep load-bearing gotchas (NSApp.delegate weak ref, deferred terminate, supervisor, `setup_logging` additive, frozen-CWD, SIGTERM suppression).
- Modify: `README_MACOS.md` — any "two-process fallback / `APPLIO_SINGLE_PROCESS=0`" paragraph.
- Modify: `FORK_DIFFERENCES.md` — note single-process-only as a fork characteristic.
- Modify: `CHANGELOG.md` — add `[3.6.3.7]` entry (Unreleased → 3.6.3.7 at release time): two-process removal + inference dashboard + the two bug fixes.

**Acceptance Criteria:**
- [ ] `rg -n "APPLIO_SINGLE_PROCESS|two-process|_SINGLE_PROCESS" CLAUDE.md README_MACOS.md` returns only intentional historical/migration mentions (no live "set this flag" instructions).
- [ ] `CHANGELOG.md` has a `[3.6.3.7]` section listing: single-process-only, inference dashboard, Stop-kills-app fix, frozen-CWD `infer_pid.txt` fix.
- [ ] No em dashes and no AI-tell phrasing (per the user's standing requirement).

**Verify:**
```bash
rg -n "APPLIO_SINGLE_PROCESS=0|opt back into two-process|two-process fallback" CLAUDE.md README_MACOS.md   # expect: no output
rg -n "\[3.6.3.7\]" CHANGELOG.md   # expect: 1 hit
```

**Steps:**
- [ ] **Step 1:** In `CLAUDE.md`, rewrite the Phase 2 section to past tense ("single-process is the only architecture; the two-process code and `APPLIO_SINGLE_PROCESS` flag were removed in 3.6.3.7"). Delete the `APPLIO_SINGLE_PROCESS=0` opt-back-in instructions + the standalone-run/legacy-fallback notes. Delete gotchas that only mattered for two-process (the `APPLIO_LAUNCHED_BY_LAUNCHER` spawn note; the "2 icons in dock" launcher limitation). KEEP: NSApp.delegate weak ref, deferred terminate via `callAfter`, supervisor `_supervised_backend`, `setup_logging` additive, frozen-CWD invariant, post-training SIGTERM suppression.
- [ ] **Step 2:** In `README_MACOS.md`, replace any "two-process fallback" paragraph with a one-line statement that the app runs as a single native process.
- [ ] **Step 3:** In `FORK_DIFFERENCES.md`, add a bullet: single-process native app (launcher+Gradio+dashboard in one process), two-process removed in 3.6.3.7.
- [ ] **Step 4:** Add the `[3.6.3.7]` CHANGELOG entry (Added: inference dashboard; Changed: single-process-only; Fixed: Stop-kills-app, frozen-CWD infer_pid write). No em dashes.
- [ ] **Step 5:** Run Verify.
- [ ] **Step 6:** Commit: `git add CLAUDE.md README_MACOS.md FORK_DIFFERENCES.md CHANGELOG.md && git commit -m "docs: single-process-only + inference dashboard (3.6.3.7)"`.

---

## Part B — Batch-inference progress on the Process Dashboard

### Task B1: `patches/patch_inference_progress.py` + register

**Goal:** New build-time patcher that injects progress helpers and rewrites `convert_audio_batch` in `rvc/infer/infer.py` to emit `inference_progress.json`, support cooperative cancel, reject concurrent batches, append history, and remove the broken `infer_pid.txt` logic.

**Files:**
- Create: `patches/patch_inference_progress.py`
- Modify: `build_macos.py:698` — add registration tuple after `patch_refinegan_legacy_infer.py`.

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python patches/patch_inference_progress.py rvc/infer` exits 0 and prints "Patched successfully".
- [ ] `venv_macos/bin/python -m py_compile rvc/infer/infer.py` exits 0 after patching.
- [ ] `rg -n "_infer_cancel_requested|_write_infer_progress|_infer_progress_path" rvc/infer/infer.py` → hits (helpers injected).
- [ ] `rg -n "infer_pid" rvc/infer/infer.py` → zero hits (PID logic removed).
- [ ] Idempotent: running the patcher twice on an already-patched file makes no change (specific-marker early-return).
- [ ] After testing, `git checkout -- rvc/infer/infer.py` restores upstream (working tree clean).
- [ ] Registered in `build_macos.py:patches_to_apply` as `("patches/patch_inference_progress.py", "rvc/infer/infer.py", "infer.py - batch inference progress tracking", "dir")`.

**Verify:**
```bash
venv_macos/bin/python patches/patch_inference_progress.py rvc/infer
venv_macos/bin/python -m py_compile rvc/infer/infer.py && echo COMPILE_OK
rg -c "_infer_cancel_requested|_write_infer_progress" rvc/infer/infer.py   # expect: >=1
rg -c "infer_pid" rvc/infer/infer.py                                       # expect: 0
# idempotency
venv_macos/bin/python patches/patch_inference_progress.py rvc/infer
git checkout -- rvc/infer/infer.py
git status --short                                                          # expect: clean
```

**Steps:**
- [ ] **Step 1:** Create `patches/patch_inference_progress.py` modeled on `patches/patch_refinegan_legacy_infer.py` (same `base_path` arg contract: `os.path.join(base_path, "infer.py")`).

- [ ] **Step 2:** Define the injected helper block (inject after the existing imports, before `class VoiceConverter`). This is the verbatim block:

```python
INFER_PROGRESS_HELPERS = r'''
# === Inference Progress Tracking (injected by patch) ===
import json as _infer_json
import time as _infer_time
import os as _infer_os
import datetime as _infer_dt

_INFER_PROGRESS_FILE = None
_INFER_CANCEL_FLAG = None
_INFER_HIST_MAX = 50

def _infer_progress_path():
    global _INFER_PROGRESS_FILE
    if _INFER_PROGRESS_FILE is None:
        data_path = _infer_os.environ.get("APPLIO_DATA_PATH") or _infer_os.path.expanduser("~/Applio")
        _INFER_PROGRESS_FILE = _infer_os.path.join(data_path, ".applio", "inference_progress.json")
    return _INFER_PROGRESS_FILE

def _infer_cancel_path():
    global _INFER_CANCEL_FLAG
    if _INFER_CANCEL_FLAG is None:
        data_path = _infer_os.environ.get("APPLIO_DATA_PATH") or _infer_os.path.expanduser("~/Applio")
        _INFER_CANCEL_FLAG = _infer_os.path.join(data_path, ".applio", "inference_cancel.flag")
    return _INFER_CANCEL_FLAG

def _read_infer_progress():
    try:
        with open(_infer_progress_path(), "r", encoding="utf-8") as f:
            return _infer_json.load(f)
    except (IOError, _infer_json.JSONDecodeError):
        return None

def _write_infer_progress(record):
    # Best-effort: tracking must NEVER block inference. Single writer + atomic replace => no lock.
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
    # Schema-compatible with applio_launcher.load_process_history. fcntl lock = matches the launcher writer.
    try:
        import fcntl as _infer_fcntl
        hist_path = _infer_os.path.join(_infer_os.path.dirname(_infer_progress_path()), "process_history.json")
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

- [ ] **Step 3:** Define the `convert_audio_batch` replacement. Anchor on the existing body from `pid = os.getpid()` (L361) through the `finally: os.remove(os.path.join(now_dir, "assets", "infer_pid.txt"))` (L406). Replacement (preserves the `audio_files` extension filter and the per-file `convert_audio` call; adds tracking + cancel + history; removes PID file):

```python
INFER_BATCH_REPLACEMENT = r'''        existing = _read_infer_progress()
        if existing and existing.get("status") == "running":
            raise RuntimeError("Another batch inference is already running. Stop it first from the Process Dashboard.")
        _model_name = _infer_os.path.basename(os.path.join(weight_root, kwargs.get("cpt_name", ""))) if kwargs.get("cpt_name") else ""
        start_time = _infer_time.time()
        print(f"Converting audio batch '{audio_input_paths}'...")
        audio_files = [f for f in _infer_os.listdir(audio_input_paths) if f.lower().endswith(("wav","mp3","flac","ogg","opus","m4a","mp4","aac","alac","wma","aiff","webm","ac3"))]
        print(f"Detected {len(audio_files)} audio files for inference.")
        total = len(audio_files)
        processed = converted = skipped = 0
        status = "running"
        _write_infer_progress({"version":1,"type":"inference","status":status,"model_name":_model_name,
            "input_folder":audio_input_paths,"output_folder":audio_output_path,"total":total,
            "processed":0,"converted":0,"skipped":0,"current_file":audio_files[0] if audio_files else "",
            "started_at":start_time,"ended_at":None,"elapsed":None,"error":None})
        if total == 0:
            status = "completed"
        try:
            for a in audio_files:
                if _infer_cancel_requested():
                    status = "cancelling"
                    _write_infer_progress({"version":1,"type":"inference","status":status,"model_name":_model_name,
                        "input_folder":audio_input_paths,"output_folder":audio_output_path,"total":total,
                        "processed":processed,"converted":converted,"skipped":skipped,"current_file":a,
                        "started_at":start_time,"ended_at":None,"elapsed":None,"error":None})
                    break
                new_input = _infer_os.path.join(audio_input_paths, a)
                new_output = _infer_os.path.splitext(a)[0] + "_output.wav"
                new_output = _infer_os.path.join(audio_output_path, new_output)
                if _infer_os.path.exists(new_output):
                    skipped += 1
                    processed += 1
                else:
                    self.convert_audio(audio_input_path=new_input, audio_output_path=new_output, **kwargs)
                    converted += 1
                    processed += 1
                idx = audio_files.index(a) + 1
                nxt = audio_files[idx] if idx < total else ""
                _write_infer_progress({"version":1,"type":"inference","status":status,"model_name":_model_name,
                    "input_folder":audio_input_paths,"output_folder":audio_output_path,"total":total,
                    "processed":processed,"converted":converted,"skipped":skipped,"current_file":nxt,
                    "started_at":start_time,"ended_at":None,"elapsed":None,"error":None})
            if status == "running":
                status = "completed"
        except Exception as _infer_exc:
            status = "error"
            _write_infer_progress({"version":1,"type":"inference","status":status,"model_name":_model_name,
                "input_folder":audio_input_paths,"output_folder":audio_output_path,"total":total,
                "processed":processed,"converted":converted,"skipped":skipped,"current_file":"",
                "started_at":start_time,"ended_at":_infer_time.time(),"elapsed":_infer_time.time()-start_time,
                "error":str(_infer_exc)})
            _infer_add_to_history({"type":"inference","model_name":_model_name,
                "started_at":_infer_dt.datetime.fromtimestamp(start_time).isoformat(),
                "completed_at":_infer_dt.datetime.fromtimestamp(_infer_time.time()).isoformat(),
                "status":status,"total":total,"converted":converted,"skipped":skipped})
            raise
        print(f"Conversion completed at '{audio_input_paths}'.")
        elapsed_time = _infer_time.time() - start_time
        print(f"Batch conversion completed in {elapsed_time:.2f} seconds.")
        _write_infer_progress({"version":1,"type":"inference","status":status,"model_name":_model_name,
            "input_folder":audio_input_paths,"output_folder":audio_output_path,"total":total,
            "processed":processed,"converted":converted,"skipped":skipped,"current_file":"",
            "started_at":start_time,"ended_at":_infer_time.time(),"elapsed":elapsed_time,"error":None})
        _infer_add_to_history({"type":"inference","model_name":_model_name,
            "started_at":_infer_dt.datetime.fromtimestamp(start_time).isoformat(),
            "completed_at":_infer_dt.datetime.fromtimestamp(_infer_time.time()).isoformat(),
            "status":status,"total":total,"converted":converted,"skipped":skipped})
        finally:
            try:
                _infer_os.remove(_infer_cancel_path())
            except OSError:
                pass
'''
```

  **Note on `weight_root`/`cpt_name`:** confirm the actual kwargs the method receives for the model path at plan-read time (`convert_audio_batch` signature is `(self, audio_input_paths, audio_output_path, **kwargs)`); the model name comes from `kwargs` (e.g. `cpt_name`) or the instance's loaded model. If neither is reliably present, set `_model_name = ""` (the dashboard still works; the model name is display-only). Verify against `rvc/infer/infer.py` before finalizing the anchor.

- [ ] **Step 4:** Implement the patcher functions: `patch_infer_py(base_path)` that (a) injects `INFER_PROGRESS_HELPERS` before `class VoiceConverter` if the marker `# === Inference Progress Tracking (injected by patch) ===` is absent; (b) replaces the `convert_audio_batch` body (anchor: the substring from `pid = os.getpid()` through `os.remove(os.path.join(now_dir, "assets", "infer_pid.txt"))`) with `INFER_BATCH_REPLACEMENT` if `_infer_cancel_requested` is not already present. Use the same `read → transform → write` + idempotency-marker pattern as `patch_refinegan_legacy_infer.py`.

- [ ] **Step 5:** Add `if __name__ == "__main__":` taking `base_path = sys.argv[1]` (default `.`), calling `patch_infer_py(base_path)`, printing `"[infer.py inference-progress] Patched successfully"` / `"Already patched, skipping"` / `"Could not find convert_audio_batch anchor"`.

- [ ] **Step 6:** Register in `build_macos.py:patches_to_apply` (after L698, the existing `patch_refinegan_legacy_infer.py` entry — same source file, different function, no conflict):
```python
("patches/patch_inference_progress.py", "rvc/infer/infer.py", "infer.py - batch inference progress tracking", "dir"),
```

- [ ] **Step 7:** Run Verify (patcher exits 0, `py_compile` passes, helper greps hit, `infer_pid` grep is 0, idempotent, restore upstream).

- [ ] **Step 8:** Commit: `git add patches/patch_inference_progress.py build_macos.py && git commit -m "feat: patcher for batch-inference progress tracking + cancel + history"`.

---

### Task B2: `patches/patch_stop_infer.py` + register

**Goal:** Rewrite `stop_infer` in `tabs/settings/sections/restart.py` to write the cancel flag cooperatively (no PID kill, no `now_dir`).

**Files:**
- Create: `patches/patch_stop_infer.py`
- Modify: `build_macos.py:patches_to_apply` — add registration.

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python patches/patch_stop_infer.py tabs/settings/sections` exits 0.
- [ ] `venv_macos/bin/python -m py_compile tabs/settings/sections/restart.py` exits 0.
- [ ] `rg -n "inference_cancel.flag" tabs/settings/sections/restart.py` → 1 hit (inside `stop_infer`).
- [ ] `stop_infer` no longer references `infer_pid.txt` or `psutil.Process(...).kill()` (the `psutil` import stays for `stop_train`).
- [ ] Idempotent (specific-marker early-return); restore upstream after testing.

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
- [ ] **Step 1:** Create `patches/patch_stop_infer.py` (same `base_path` arg contract: `os.path.join(base_path, "restart.py")`).

- [ ] **Step 2:** The replacement for the entire `stop_infer` function body (anchor on `def stop_infer():` through its end, before `def restart_applio`):

```python
STOP_INFER_REPLACEMENT = '''def stop_infer():
    # Cooperative cancellation (3.6.3.7): write the cancel flag; the inference loop
    # checks it per file and exits. Does NOT kill a PID (single-process: the PID is
    # the whole app). Best-effort; silent no-op if no job is running.
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

- [ ] **Step 3:** `patch_restart_py(base_path)`: read `restart.py`, find the `def stop_infer():` block (up to the next `def ` at column 0 — `def restart_applio`), replace it with `STOP_INFER_REPLACEMENT` if `inference_cancel.flag` not already present. Idempotency marker = the string `inference_cancel.flag`. Write back.

- [ ] **Step 4:** Add `__main__` taking `base_path = sys.argv[1]`.

- [ ] **Step 5:** Register in `build_macos.py:patches_to_apply`:
```python
("patches/patch_stop_infer.py", "tabs/settings/sections/restart.py", "restart.py - cooperative inference cancel", "dir"),
```

- [ ] **Step 6:** Run Verify (exits 0, `py_compile` passes, 1 cancel-flag hit, 0 `infer_pid` hits, idempotent, restore).

- [ ] **Step 7:** Commit: `git add patches/patch_stop_infer.py build_macos.py && git commit -m "fix: cooperative inference Stop (no longer kills the app in single-process)"`.

---

### Task B3: Dashboard integration in `applio_launcher.py`

**Goal:** The dashboard reads `inference_progress.json`, synthesizes an inference proc into `_active_processes`, and renders an inference card (progress bar = processed/total, ETA/speed stats, Stop writes the cancel flag, Reveal targets output_folder). Includes a pure-Python unit test for the stats math.

**Files:**
- Modify: `applio_launcher.py` — add `_read_inference_progress()` (~near `get_active_processes` L575); modify `update_process_list` (L3711) to synthesize; modify `_update_detail_panel` (~L2609) to branch on `_is_inference`; modify `stopProcess_` (L2922); modify `revealLog_`/`openLog_` (~L2970/L2982).
- Create: `tests/test_inference_progress.py`.

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py` exits 0.
- [ ] `venv_macos/bin/python -m pytest tests/test_inference_progress.py -v` passes (pure-Python stats math: ETA, speed, pct, divide-by-zero guards, empty/cancelled states).
- [ ] `rg -n "_read_inference_progress|_is_inference|_compute_inference_stats" applio_launcher.py` → hits.
- [ ] The synthesized proc has `_is_inference: True` so the existing sidebar/autoshow/action-bar code paths handle it; `stopProcess_` branches on it to write the cancel flag (no PID kill).

**Verify:**
```bash
venv_macos/bin/python -m py_compile applio_launcher.py && echo OK
venv_macos/bin/python -m pytest tests/test_inference_progress.py -v
rg -n "_compute_inference_stats|_is_inference" applio_launcher.py
```

**Steps:**
- [ ] **Step 1 (TDD — failing test first):** Create `tests/test_inference_progress.py` with a pure function extracted to the launcher (module-level so it's importable without running the app). Test the math:

```python
# tests/test_inference_progress.py
from applio_launcher import _compute_inference_stats

def test_progress_pct():
    r = {"status": "running", "total": 10, "processed": 4, "converted": 4, "skipped": 0, "started_at": 1000.0}
    s = _compute_inference_stats(r, now=1010.0)
    assert s["pct"] == 40.0
    assert s["elapsed"] == 10.0
    assert s["eta"] == 15.0            # (10-4) * (10/4) = 15
    assert s["speed"] == 24.0          # 4 files / (10/60) min = 24

def test_zero_converted_no_divzero():
    r = {"status": "running", "total": 5, "processed": 0, "converted": 0, "skipped": 0, "started_at": 1000.0}
    s = _compute_inference_stats(r, now=1003.0)
    assert s["eta"] == 0 and s["speed"] == 0   # guarded

def test_completed_status():
    r = {"status": "completed", "total": 3, "processed": 3, "converted": 2, "skipped": 1, "started_at": 1000.0, "ended_at": 1010.0, "elapsed": 10.0}
    s = _compute_inference_stats(r, now=9999.0)
    assert s["pct"] == 100.0 and s["eta"] == 0
```

- [ ] **Step 2:** Run the test → expect FAIL (`_compute_inference_stats` not defined / applio_launcher not importable in isolation). If `applio_launcher` isn't importable headless (PyObjC at import time), move `_compute_inference_stats` into a tiny import-safe helper module `applio_inference_stats.py` and import it from both the launcher and the test. (Decide at task time; prefer the import-safe module to keep the test green in CI.)

- [ ] **Step 3:** Implement `_compute_inference_stats(record, now)` (module-level, pure):
```python
def _compute_inference_stats(record, now):
    total = record.get("total", 0) or 0
    processed = record.get("processed", 0) or 0
    converted = record.get("converted", 0) or 0
    started = record.get("started_at") or now
    pct = (100.0 * processed / total) if total else 0.0
    elapsed = max(0.0, (record.get("ended_at") or now) - started)
    avg = (elapsed / converted) if converted else 0.0
    remaining = max(0, total - processed)
    eta = remaining * avg if converted else 0.0
    speed = (converted / (elapsed / 60.0)) if (elapsed > 0 and converted) else 0.0
    return {"pct": round(pct, 1), "elapsed": round(elapsed, 1),
            "eta": round(eta, 1), "speed": round(speed, 1)}
```

- [ ] **Step 4:** Run the test → expect PASS.

- [ ] **Step 5:** Add `_read_inference_progress()` (module-level, near `get_active_processes`). Resolve `~/Applio/.applio/inference_progress.json` via the same env precedence (`APPLIO_DATA_PATH` → `~/Applio`). Return the dict or `None`; tolerate missing/corrupt.

- [ ] **Step 6:** In `update_process_list` (L3711), after building `_active_processes` from `get_active_processes()`, read the inference record; if `status` in `("running","cancelling")`, append a synthesized proc:
```python
inf = _read_inference_progress()
if inf and inf.get("status") in ("running", "cancelling"):
    _active_processes.append({
        "type": "inference", "status": inf["status"], "model_name": inf.get("model_name",""),
        "total": inf.get("total",0), "processed": inf.get("processed",0),
        "converted": inf.get("converted",0), "skipped": inf.get("skipped",0),
        "current_file": inf.get("current_file",""), "started_at_epoch": inf.get("started_at"),
        "output_folder": inf.get("output_folder"), "_is_inference": True,
    })
```
This makes the idle→active transition + auto-show hook fire for inference automatically.

- [ ] **Step 7:** In `_update_detail_panel`, branch on `proc.get("_is_inference")`: skip `_parse_training_metrics`; render progress bar = `processed/total` with label `f"{processed}/{total} files ({pct}%)"`; stats grid = Current file (basename, truncated), Elapsed, ETA, Speed (from `_compute_inference_stats`); status text maps `cancelling`→"Stopping…", `running`→"Running".

- [ ] **Step 8:** In `stopProcess_`, branch on `_is_inference`: write the cancel flag (resolve `~/Applio/.applio/inference_cancel.flag`, `open(...,"w").close()`), set detail status "Stopping…", disable Stop + Pause. (Pause is a no-op for inference — disable the button + tooltip "Not available for inference".)

- [ ] **Step 9:** In `revealLog_`/`openLog_`, branch on `_is_inference`: target `output_folder` instead of a log file; `os.path.realpath()` + `os.path.isdir()` guard before `NSWorkspace`; missing → log + no-op.

- [ ] **Step 10:** `py_compile` + run the unit test (PASS). Manual dev spot-check optional.

- [ ] **Step 11:** Commit: `git add applio_launcher.py applio_inference_stats.py tests/test_inference_progress.py && git commit -m "feat: dashboard shows batch-inference progress (card, ETA, cooperative Stop)"`.

---

### Task B4: Startup sweep for stale inference progress

**Goal:** On launcher startup, mark a stale `running` inference record as `interrupted` (crash/quit recovery) so the dashboard never shows a phantom running job, and append the interrupted run to history.

**Files:**
- Modify: `applio_launcher.py` — add `_sweep_stale_inference_progress()` and call it once at launcher init.

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py` exits 0.
- [ ] `rg -n "_sweep_stale_inference_progress" applio_launcher.py` → ≥2 hits (def + call site).
- [ ] A stale `running` record is rewritten to `interrupted` with `ended_at`/`elapsed` set, a matching history entry appended, and any stale `inference_cancel.flag` removed.

**Verify:**
```bash
venv_macos/bin/python -m py_compile applio_launcher.py && echo OK
rg -n "_sweep_stale_inference_progress" applio_launcher.py
```

**Steps:**
- [ ] **Step 1:** Add module-level `_sweep_stale_inference_progress()`:
```python
def _sweep_stale_inference_progress():
    inf = _read_inference_progress()
    if not inf or inf.get("status") != "running":
        return
    import time as _t, datetime as _dt, os as _os, json as _j
    started = inf.get("started_at") or _t.time()
    ended = _t.time()
    inf["status"] = "interrupted"
    inf["error"] = "interrupted by app restart"
    inf["ended_at"] = ended
    inf["elapsed"] = ended - started
    # reuse the injected writer's path by writing the same file the patcher writes
    data_path = _os.environ.get("APPLIO_DATA_PATH") or _os.path.expanduser("~/Applio")
    path = _os.path.join(data_path, ".applio", "inference_progress.json")
    try:
        tmp = path + ".tmp"
        fd = _os.open(tmp, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
        with _os.fdopen(fd, "w") as f:
            _j.dump(inf, f)
        _os.replace(tmp, path)
    except OSError:
        pass
    # append interrupted history entry (schema-compatible)
    try:
        import fcntl as _fl
        hist_path = _os.path.join(data_path, ".applio", "process_history.json")
        _os.makedirs(_os.path.dirname(hist_path), exist_ok=True)
        with open(hist_path + ".lock", "a") as _lf:
            _fl.flock(_lf.fileno(), _fl.LOCK_EX)
            try:
                hist = {"version":1,"history":[]}
                if _os.path.exists(hist_path):
                    try:
                        with open(hist_path) as f: hist = _j.load(f) or hist
                    except _j.JSONDecodeError: pass
                hist.setdefault("history", []).insert(0, {
                    "type":"inference","model_name":inf.get("model_name",""),
                    "started_at":_dt.datetime.fromtimestamp(started).isoformat(),
                    "completed_at":_dt.datetime.fromtimestamp(ended).isoformat(),
                    "status":"interrupted","total":inf.get("total",0),
                    "converted":inf.get("converted",0),"skipped":inf.get("skipped",0)})
                hist["history"] = hist["history"][:50]
                with open(hist_path, "w") as f: _j.dump(hist, f, indent=2)
            finally:
                _fl.flock(_lf.fileno(), _fl.LOCK_UN)
    except OSError:
        pass
    # clear a stale cancel flag
    try: _os.remove(_os.path.join(data_path, ".applio", "inference_cancel.flag"))
    except OSError: pass
```
- [ ] **Step 2:** Call `_sweep_stale_inference_progress()` once at launcher init (in `ApplioLauncher.__init__` or the existing startup sequence, after `~/Applio/.applio/` is known to exist).
- [ ] **Step 3:** `py_compile` + Verify.
- [ ] **Step 4:** Commit: `git add applio_launcher.py && git commit -m "feat: recover stale inference progress on startup (no phantom running card)"`.

---

## Validation + Release

### Task F1: Frozen validation (Part A + Part B)

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task validates the shipped, frozen app (the user has consistently required testing the built path, not dev). It MUST NOT be closed by declaring it "verified inline" or substituting a dev run. Close only after every acceptance item is re-validated against `dist/Applio.app` with output captured.

**Goal:** One frozen build; smoke-test both Part A (single-process-only launch/quit) and Part B (inference card, cooperative Stop that leaves the app alive, completion+history, concurrent-batch rejection, empty/skip-all, interrupted recovery).

**Files:** Build outputs only (`dist/Applio.app`, `dist/Applio-3.6.3.7.dmg` is R1). No source edits.

**Acceptance Criteria:**
- [ ] `venv_macos/bin/python build_macos.py` (no `--sign`) completes; after build `git status` shows NO upstream files dirty (`rvc/infer/infer.py`, `tabs/settings/sections/restart.py` restored).
- [ ] `stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio` timestamp is after the last commit.
- [ ] **Part A:** `open dist/Applio.app` → Window → Process Monitor opens the dashboard (one window); Cmd+Q quits; `pgrep -f Applio` → no orphan.
- [ ] **Part B (B-AC5):** Batch of ≥3 files → dashboard auto-shows an inference card with `processed/total` climbing → click Stop (dashboard OR inference-tab "Stop convert") → within one file's conversion the loop halts, status `cancelled`, and `pgrep -f Applio` shows the SAME pid (app alive) → history sidebar shows `cancelled`.
- [ ] **Part B (B-AC6):** A small batch to completion → card reaches total → `completed` → history shows the run with correct counts.
- [ ] **Part B (B-AC7):** Start a batch, start a second from another tab → second surfaces the "Another batch inference is already running" error; first's progress file unclobbered.
- [ ] **Part B (B-AC8):** Empty folder → no running card, a 0-file completed history entry; all-outputs-exist folder → "0 converted, N skipped" then completes.
- [ ] **Part B (B-AC9):** Start a batch, force-quit mid-batch (`kill -9`) → relaunch → no phantom running card → history shows `interrupted`.

**Verify:** the acceptance items above, each with captured output (the `pgrep -f Applio` pid before/after Stop is the load-bearing proof that Stop no longer kills the app).

**Steps:**
- [ ] **Step 1:** `git status --short` (clean), then `venv_macos/bin/python build_macos.py` (cert-free). Capture tail; confirm `BUILD COMPLETE`.
- [ ] **Step 2:** `git status --short` → expect no upstream dirty (restore ran). `stat` the binary timestamp.
- [ ] **Step 3:** Run the Part A smoke (open, dashboard, Cmd+Q, pgrep).
- [ ] **Step 4:** Run each Part B smoke (B-AC5 through B-AC9), capturing the pgrep before/after Stop for B-AC5.
- [ ] **Step 5:** If any item fails, file the failure with output and stop (do not mark complete; do not proceed to R1).
- [ ] **Step 6:** No commit (validation only). Report results.

---

### Task R1: Cut v3.6.3.7 release

> **USER-ORDERED GATE — NON-SKIPPABLE.** Releasing publishes to GitHub (hard to reverse, outward-facing). Close only after the signed+notarized DMG is verified and the release description is published with the user's sign-off.

**Goal:** Version bump, signed+notarized DMG, GitHub release `v3.6.3.7` with a clean description (single-process-only, inference dashboard, the two bug fixes; no em dashes, no AI tells).

**Files:**
- Modify: `build_macos.py` — `BUILD_NUMBER = 7`.
- Modify: `CHANGELOG.md` — promote `[3.6.3.7]` from Unreleased to dated.

**Acceptance Criteria:**
- [ ] `BUILD_NUMBER = 7` in `build_macos.py`; `CHANGELOG.md` `[3.6.3.7]` dated.
- [ ] `venv_macos/bin/python build_macos.py --sign --notarize --dmg` completes; `xcrun stapler validate "dist/Applio-3.6.3.7.dmg"` → "The validate action worked!"; `spctl -vvv --assess --type execute dist/Applio.app` → `source=Notarized Developer ID`.
- [ ] Tag `v3.6.3.7` on the merged commit; GitHub release created (DMG attached) with the clean description (from spec "Release notes draft").
- [ ] No em dashes, no AI-tell phrasing in the release description.

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

**1. Spec coverage:** Part A removal → A1 (macos_wrapper) + A2 (applio_launcher); docs → A3. Part B patcher → B1; stop fix → B2; dashboard → B3; stale recovery → B4; frozen validation → F1; release → R1. Every spec section maps to a task. Both bug fixes (Stop-kills-app, frozen-CWD infer_pid) are covered by B1 (removes PID logic) + B2 (cooperative stop). Edge cases (empty, skip-all, cancel-mid-file, concurrent, interrupted) → F1 acceptance items + B1 code. History schema → B1 `_infer_add_to_history` + B4 sweep. Security (display-only fields, realpath guard) → B3 Step 9. ✅
**2. Placeholder scan:** No TBD/TODO. The one open detail (the exact kwarg for the model name in `convert_audio_batch`) is called out in B1 Step 3 with a safe fallback (`_model_name=""`). ✅
**3. Type consistency:** `_compute_inference_stats` (B3) returns `{pct, elapsed, eta, speed}`; the detail panel uses those keys. Synthesized proc keys (`_is_inference`, `started_at_epoch`, `output_folder`) match B3's branch logic. Progress file schema keys (`total, processed, converted, skipped, current_file, started_at, ended_at, elapsed, status`) are consistent across B1 (writer), B3 (reader), B4 (sweep). ✅
