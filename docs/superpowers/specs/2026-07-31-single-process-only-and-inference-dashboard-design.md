# Single-Process-Only + Inference Dashboard — Design Spec

> **For agentic workers:** This spec feeds `superpowers-extended-cc:writing-plans`. It covers two
> changes that both ship in the next release (**v3.6.3.7**): **Part A** removes the dead
> two-process code; **Part B** adds batch-inference progress to the Process Dashboard and fixes a
> latent single-process "Stop kills the app" bug **plus** a frozen-CWD bug in the same path.

**Goal:**
- **(A)** Make single-process the only code path — delete the two-process machinery and the
  `APPLIO_SINGLE_PROCESS` / `_SINGLE_PROCESS` / `APPLIO_LAUNCHED_BY_LAUNCHER` flags everywhere.
- **(B)** Surface **batch** voice-conversion progress on the Process Dashboard, and replace the
  PID-kill Stop with **cooperative cancellation** (a sentinel file). This fixes two real bugs:
  the single-process "Stop kills the whole app" hazard AND the frozen-build
  `infer_pid.txt` write failure (both stem from the same code path).

**Architecture (one paragraph):**
- Part A is a deletion refactor — every two-process branch is already inert under the default
  flag (single-process is frozen-validated), so removing the branches is behavior-preserving for
  the default path.
- Part B instruments upstream `convert_audio_batch` via a new build-time patcher to write a
  structured progress file the dashboard polls. No subprocess, no PID kill — inference stays the
  synchronous in-process call that returns converted audio to the Gradio UI. Cancellation is a
  sentinel file checked per-file. The dashboard reads the file on its existing 2 s heartbeat and
  synthesizes an inference row into the same data path that today renders training/preprocess/extract/tts.

**Tech stack:** Python 3.10, PyObjC/AppKit (dashboard NSView), PyInstaller build-time patchers
(`patches/`), file-based inter-thread signaling (`~/Applio/.applio/`).

**In-scope user decisions (already made, do not re-litigate):**
- Scope of inference tracking: **batch conversion only** this release. Single-file, TTS-enrichment,
  and realtime are deferred (each with a recorded reason in "Out of scope").
- Tracking mechanism: **in-process progress file** (NOT spawning inference as a subprocess — the
  synchronous return-the-output contract is load-bearing and must not change).
- Two-process code: **rip it out entirely**, drop the flag. No opt-out remains.
- `python macos_wrapper.py` stays a valid **single-process-only** dev entry.

**Hard project constraints honored (from `CLAUDE.md`):**
- `rvc/infer/infer.py`, `tabs/**`, `core.py`, `tabs/settings/sections/restart.py` are UPSTREAM —
  patch only via `patches/`, NEVER direct-edit. After patching, `git status` must show no upstream
  files dirty (restore via `post_build_restore`).
- Patcher idempotency: each patcher checks for its OWN specific marker before injecting; NO shared
  early-return marker.
- Frozen-CWD invariant: `os.getcwd()` in a frozen app is the read-only bundle — all paths in
  injected code must resolve absolutely via `APPLIO_DATA_PATH` env → `runtime_paths.json`
  `data_path` → `~/Applio`.
- `core.py`'s `from datetime import datetime` rebinds `datetime` to the class — in injected code
  use `import datetime as <alias>` + `<alias>.datetime.now()`, OR use `time.time()` (preferred for
  epoch floats). Mirrors `patch_process_tracking.py`'s `import datetime as _applio_dt`.
- **NEVER `import build_macos`** — it runs the entire build at module level (`pre_build_patch()`
  at L786 → PyInstaller). Test patchers by running them directly:
  `venv_macos/bin/python patches/patch_X.py <arg>` then `git checkout -- <source>`.

---

## Verified facts (re-confirmed against source at review time)

| Claim | Source (file:line) | Status |
|---|---|---|
| Inference is in-process, synchronous, returns audio | `tabs/inference/inference.py:1172` `run_infer_script(*args)` → `core.py:61` → `rvc/infer/infer.py:192` `convert_audio` (returns nothing; writes file + returns path via `core.py:185`) | ✅ confirmed |
| Batch loop | `rvc/infer/infer.py:345-406` `convert_audio_batch`; loops `for a in audio_files` (L391); skips existing outputs (L395-396); `finally` removes `infer_pid.txt` (L406) | ✅ confirmed |
| `infer_pid.txt` write path | `rvc/infer/infer.py:364` `os.path.join(now_dir, "assets", "infer_pid.txt")` where `now_dir = os.getcwd()` (L25) | ✅ confirmed — **frozen-CWD hazard** |
| `stop_infer` PID-kill | `tabs/settings/sections/restart.py:52-74`; reads `now_dir/assets/infer_pid.txt` (L53, `now_dir = os.getcwd()` L8); `psutil.Process(pid).kill()` + children (L60-63) | ✅ confirmed — **single-process kills the app; frozen-CWD read broken** |
| Stop button wiring | `tabs/inference/inference.py:1821` `stop_button.click(fn=stop_infer, ...)`; button label "Stop convert" (L1819) | ✅ confirmed |
| Path-resolution pattern to reuse | `patches/patch_process_tracking.py:29-34` `_get_process_state_path()` — `APPLIO_DATA_PATH` env → `~/Applio/.applio/active_processes.json`; `fcntl.flock` lock file at `*.lock`; alias `import datetime as _applio_dt` | ✅ confirmed |
| History writer (injected into core.py) | `patch_process_tracking.py:175-194` `_add_to_history`; required fields `type, started_at, completed_at`; cap `_HISTORY_MAX_ENTRIES = 50` | ✅ confirmed |
| History reader (launcher) | `applio_launcher.py:601-678` `load_process_history`; writer `applio_launcher.py:681-734` `save_process_history`; launcher-side `add_to_history` L737-777 | ✅ confirmed |
| Dashboard controller | `applio_launcher.py:2239` `class ProcessDashboardController(NSObject)`; heartbeat `menuUpdateTimerFired_` (L4613, 2 s) → `update_process_list` (L3711); idle↔active transition keys on `get_active_processes()` (L575, L3723) | ✅ confirmed |
| Auto-show hook | `update_process_list` L3745-3752 — fires on idle→active, gated `APPLIO_SINGLE_PROCESS` + `_opened_this_session` | ✅ confirmed |
| Dashboard Stop action | `stopProcess_` L2922 — `psutil.Process(pid).terminate()` (PID-based) | ✅ confirmed |
| `_SINGLE_PROCESS` gates | `macos_wrapper.py:39` (def) + L951, L1575, L1595, L1615, L1661; `_ipc_signal_checker` def L1637 + **unconditional** daemon thread L1671 | ✅ confirmed |
| `APPLIO_LAUNCHED_BY_LAUNCHER` gates | `macos_wrapper.py:65, 108, 128, 287, 1694, 1726(comment), 1963`; only ever SET by `applio_launcher.py:4471` inside dead `_spawn_wrapper` | ✅ confirmed — already False in default single-process |
| `APPLIO_SINGLE_PROCESS` gates | `applio_launcher.py:287` (def) + L3410, L3746, L3939, L3942, L3970, L4017, L4105, L4145, L4254, L4343, L4618, L4621, L4627, L4723, L5036 | ✅ confirmed |
| Two-process-only methods | `applio_launcher.py:4190` `_setup_ipc_observer`, `4460` `_spawn_wrapper` (+ call sites L4166, L4304), `4065` setup call | ✅ confirmed |
| Build runs at module import | `build_macos.py:786` `patched_files = pre_build_patch()` (module level) | ✅ confirmed — never `import build_macos` |
| Patcher registration | `build_macos.py:674-699` `patches_to_apply` in `pre_build_patch()`; order matters (`PATCH_DEPENDENCIES` L666) | ✅ confirmed |

---

## Part A — Remove the two-process code

### Surface (all fork-owned; re-confirmed by grep)

**`macos_wrapper.py`**
- `_SINGLE_PROCESS` flag (L39) + branch points L951, L1575, L1595, L1615, L1661.
- `APPLIO_LAUNCHED_BY_LAUNCHER` env gates L65, L108, L128, L287, L1694, L1726(comment), L1963.
- `_ipc_signal_checker` (L1637) + its **unconditional** daemon thread (L1671) — two-process file-IPC
  that runs in both paths today; remove entirely.
- The two-process `_report_fatal_error` branch (the `else: self._report_fatal_error(msg)` at L1575
  and the `_request_launcher_quit()` calls inside `_report_fatal_error` at L1595). After removal,
  `_report_fatal_error` becomes single-process-only: the `if _SINGLE_PROCESS:` branches inside it
  become unconditional (single `raise` upstream already handles the supervisor path).

**`applio_launcher.py`**
- `APPLIO_SINGLE_PROCESS` flag (L287) + ~16 gate sites: L3410, L3746, L3939, L3942, L3970, L4017,
  L4105, L4145, L4254, L4343, L4618, L4621, L4627, L4723, L5036.
- `_spawn_wrapper()` (L4460) + its call sites (L4166, L4304) + the `APPLIO_LAUNCHED_BY_LAUNCHER=1`
  env it sets (L4471) + the `wrapper_pid` docstring at L4421.
- `_setup_ipc_observer()` (L4190) + its setup call (L4065) — distributed-notification listener.
- Stale "OFF default == two-process" comment (L283 area); `_main_window` "None in two-process"
  annotations (L4058 et al.).

**Docs/release** — `CLAUDE.md` (the Phase 2 section + every gotcha gated on the flag, including
the "Opt back into two-process" line and the `_SINGLE_PROCESS`/`APPLIO_SINGLE_PROCESS` references),
`README_MACOS.md` (any "two-process fallback / `APPLIO_SINGLE_PROCESS=0`" paragraph),
`FORK_DIFFERENCES.md`, `CHANGELOG.md`, and the **v3.6.3.6 release description** (its "old
two-process layout is still around as a fallback" paragraph becomes false and must be rewritten —
see "Release notes draft").

### Approach (per gate site)
For each `if FLAG:` gate: keep the single-process branch as the unconditional body, delete the
`else`/two-process branch and the `if FLAG:` wrapper. Delete the methods that exist ONLY for
two-process: `_spawn_wrapper`, `_setup_ipc_observer`, `_ipc_signal_checker` (and the
`_check_and_handle_show_main_window` / `_request_launcher_quit` helpers if they become unreferenced
after removal — verify with grep before deleting each). Collapse `macos_wrapper.py`'s standalone
`__main__` entry to single-process-only (`start_gui(launcher=None)` + `webview.start(...)`).

**Behavior-preservation proof:** in the default path TODAY, `APPLIO_SINGLE_PROCESS` defaults to
`"1"` (L287) and `APPLIO_LAUNCHED_BY_LAUNCHER` is never set (only `_spawn_wrapper` sets it, and
that path is dead). Therefore every `if APPLIO_SINGLE_PROCESS:` evaluates True and every
`if os.environ.get("APPLIO_LAUNCHED_BY_LAUNCHER"):` evaluates False in the shipped default.
Removing the gates and keeping the True/False branch respectively is byte-equivalent in behavior.

### Decision (locked)
**`python macos_wrapper.py` stays a valid dev entry** — it runs the single-process path
(`start_gui(launcher=None)` + `webview.start`). No two-process path remains anywhere in the repo.
The standalone renderer's `__app__`-titled static-menu subset (per the pywebview gotcha in
CLAUDE.md — pywebview `Menu`/`MenuAction` are immutable and cannot bind shortcuts) stays as the
menu source for that dev entry.

### Part A — Acceptance criteria (observable, testable)
- **A-AC1:** `grep -rn "APPLIO_SINGLE_PROCESS\|_SINGLE_PROCESS\|APPLIO_LAUNCHED_BY_LAUNCHER\|_spawn_wrapper\|_setup_ipc_observer\|_ipc_signal_checker" applio_launcher.py macos_wrapper.py build_macos.py` → **zero hits** (comments/docstrings that *mention* the migration history are allowed only in `CHANGELOG.md` / release notes, not in source).
- **A-AC2:** `venv_macos/bin/python -m py_compile applio_launcher.py macos_wrapper.py` exits 0.
- **A-AC3:** `venv_macos/bin/python macos_wrapper.py` launches the single-process GUI dev window without setting any env var (manual: window appears, one dock icon, menu renders, Quit works). Note: full app start needs models present; smoke-test may stop at the model-download step — that's fine, the launch+menu+quit path is what's verified.
- **A-AC4:** Frozen smoke: `open dist/Applio.app` → app launches single-process-only; Window → Process Monitor opens the dashboard; Cmd+Q quits cleanly (one process gone, no orphan). See "Frozen smoke test (both parts)".

### Part A — Task decomposition

**Task A1 — Strip gates in `macos_wrapper.py`.** Files: `macos_wrapper.py`. Delete `_SINGLE_PROCESS`
(L39) + all 5 branch sites; remove `_ipc_signal_checker` (L1637) + its daemon thread (L1671);
collapse the 7 `APPLIO_LAUNCHED_BY_LAUNCHER` gates to their standalone (else) bodies; collapse
`_report_fatal_error` to single-process-only (unconditional `raise` upstream + in-place terminate).
Keep `start_gui(launcher=None)` callable. Verify: `py_compile macos_wrapper.py`; grep zero hits.
**Task A2 — Strip gates in `applio_launcher.py`.** Files: `applio_launcher.py`. Delete
`APPLIO_SINGLE_PROCESS` (L287) + all 16 gate sites (keep single-process body); delete `_spawn_wrapper`
(L4460), `_setup_ipc_observer` (L4190), the L4065 setup call, and the L4166/L4304 call sites;
remove the `wrapper_pid` docstring (L4421) and "None in two-process" annotations. Grep-verify no
remaining references to the removed methods before deleting each. Verify: `py_compile applio_launcher.py`; grep zero hits.
**Task A3 — Update docs.** Files: `CLAUDE.md`, `README_MACOS.md`, `FORK_DIFFERENCES.md`,
`CHANGELOG.md`. Rewrite the Phase 2 section to past-tense ("single-process is the only
architecture"); delete the `APPLIO_SINGLE_PROCESS=0` opt-back-in instructions and the two-process
gotchas that no longer apply (e.g. the `APPLIO_LAUNCHED_BY_LAUNCHER` spawn note); keep gotchas
that are still load-bearing (NSApp.delegate weak ref, deferred terminate, supervisor,
`setup_logging` additive, frozen-CWD, SIGTERM suppression). Verify: `grep -rn "two-process\|APPLIO_SINGLE_PROCESS" CLAUDE.md README_MACOS.md` returns only intentional historical/migration mentions.
**Task A4 — Rewrite the v3.6.3.6 release description + draft v3.6.3.7 notes.** See "Release notes draft".
**Task A5 — Frozen validation.** Build + smoke (A-AC4).

---

## Part B — Batch-inference progress on the Process Dashboard

### Background (verified)
Voice-conversion inference is an **in-process, synchronous** call: Gradio handler `enforce_terms`
/ `enforce_terms_batch` (`tabs/inference/inference.py:1166` / `:1180`) → `run_infer_script` /
`run_batch_infer_script` (`core.py:61` / `:191`) → `VoiceConverter.convert_audio` /
`convert_audio_batch` (`rvc/infer/infer.py:192` / `:345`). It is **not** a subprocess and is **not**
in `active_processes.json`. Progress today is bare `print()` to stdout — no tqdm, no yields, no log file.

`convert_audio_batch` (`rvc/infer/infer.py:345-406`) loops `for a in audio_files:` (L391) calling
`convert_audio` per file, skipping files whose output already exists (L395-396). `len(audio_files)`
(L390, the `print(f"Detected {len(audio_files)}...")`) is the natural progress denominator.

### Two real bugs in the same path (both fixed by Part B)

**Bug 1 — Stop kills the app (single-process).** `convert_audio_batch` writes `os.getpid()` to
`assets/infer_pid.txt` (L361-366); `stop_infer` (`restart.py:52-74`) reads it and does
`psutil.Process(pid).kill()` + kills children. **In single-process, `os.getpid()` is the whole
app** — the inference-tab Stop button (`inference.py:1821`) and any PID-based stop **kill the
entire app**. Two-process masked this (the PID was the separate wrapper); flipping the default
exposed it.

**Bug 2 — `infer_pid.txt` write fails in the frozen build.** Both `rvc/infer/infer.py:25`
(`now_dir = os.getcwd()`) and `restart.py:8` resolve `now_dir` to the frozen CWD, which is the
read-only code-signed bundle. `open(os.path.join(now_dir, "assets", "infer_pid.txt"), "w")` (L364)
raises `PermissionError`; the `finally` (L406) then tries `os.remove` on a never-created path,
masking the original error. **Batch inference is already broken in the shipped frozen app** — the
patcher must redirect this write to a writable absolute location. Part B replaces the PID mechanism
outright (so the file becomes unnecessary), which fixes Bug 2 as a side effect.

### Architecture
1. **New build-time patcher `patches/patch_inference_progress.py`** (registered in `build_macos.py`'s
   `patches_to_apply`, same `"dir"` pattern as `patch_process_tracking.py`). It injects a small
   helper block (path resolver + atomic write + history append) into `rvc/infer/infer.py` and
   rewrites `convert_audio_batch` to: write a start progress record, check a cancel flag per file,
   increment progress after each file, and write a terminal record in `finally`. It also **deletes
   the `infer_pid.txt` write/remove** (the PID is meaningless in single-process and the write is broken frozen).
2. **New build-time patcher `patches/patch_stop_infer.py`** rewrites `stop_infer` in
   `tabs/settings/sections/restart.py` to write the cancel flag (cooperative) instead of PID-kill.
3. **Progress file** `~/Applio/.applio/inference_progress.json`, written atomically (temp +
   `os.replace`). Path resolved via the same `APPLIO_DATA_PATH → ~/Applio/.applio/` logic as
   `patch_process_tracking.py:_get_process_state_path` (replicated in the injected helper — see B1).
4. **Cooperative cancel** via sentinel file `~/Applio/.applio/inference_cancel.flag` (existence =
   cancel requested). The patched loop checks `os.path.exists()` each iteration and breaks cleanly.
5. **Dashboard** (`ProcessDashboardController` / `applio_launcher.py`): the existing 2 s heartbeat
   (`menuUpdateTimerFired_` L4613 → `update_process_list` L3711) additionally reads
   `inference_progress.json`; a `running` record is synthesized into `_active_processes` as a
   proc-shaped dict so the existing sidebar table, detail panel, and idle→active auto-show all work
   without new UI primitives. Dashboard Stop writes the cancel flag (NOT PID-kill).

### Progress file schema (v1)

Single active job is an **invariant**, not a hope — the patched `convert_audio_batch` REFUSES to
start if a `status:"running"` record already exists (see "Concurrency model").

```json
{
  "version": 1,
  "type": "inference",
  "status": "running",            // running | cancelling | completed | cancelled | error | interrupted
  "model_name": "<basename>.pth",
  "input_folder": "<abs path>",   // display-only; NEVER used by dashboard to write/execute
  "output_folder": "<abs path>",  // display-only; "Reveal output" opens this in Finder after os.path.realpath + exists check
  "total": 42,                   // len(audio_files) at start (files matching the extension filter)
  "processed": 7,                // files attempted this run (converted + skipped-already-exist)
  "converted": 6,                // files actually converted this run (excludes skipped)
  "skipped": 1,                  // files skipped because output existed
  "current_file": "track_08.wav",// basename of the file being converted (or next to convert)
  "started_at": 1798420000.0,    // epoch seconds, time.time()
  "ended_at": null,              // epoch seconds on terminal status, else null
  "elapsed": null,               // ended_at - started_at on terminal status, else null
  "error": null                  // string on error/interrupted status, else null
}
```

**Semantics:**
- `processed = converted + skipped` (monotonic, never decreases). The progress bar uses `processed / total`.
- `total` is fixed at start; if the folder contents change mid-run that's accepted (denominator stays).
- Timestamps are epoch floats from `time.time()`. **Do NOT use `datetime.datetime.now()`** in the
  injected code (`rvc/infer/infer.py` is upstream and the `core.py` rebind doesn't apply here, but
  consistency with `patch_process_tracking.py`'s aliasing discipline avoids future drift). Use `time.time()`.
- `model_name` is `os.path.basename(model_path)` — basename only, no directory leakage.
- `input_folder` / `output_folder` are absolute paths (needed for "Reveal output"); see Security
  for the trust boundary.

**Lifecycle (state machine):**
```
[none] --start--> running --finish--> completed
                 |--cancel-flag--> cancelling --loop-exits--> cancelled
                 |--exception--> error
                 |--app-quit/crash--> running(left stale) --startup-sweep--> interrupted
```

### Concurrency model (single writer, atomic rename, lock-free)
- **Exactly one writer** (the Gradio worker thread running `convert_audio_batch`). The dashboard is
  a pure reader (main thread, NSTimer-driven). No `fcntl` lock is needed because:
  - Writes use temp-file + `os.replace`, which is atomic on POSIX (APFS included). A reader sees
    either the old file or the new file in its entirety — never a torn read.
  - Single-writer invariant is enforced at start (refuse if `status:"running"` exists).
- **No reinvention of `patch_process_tracking.py`'s locking** — that locking exists for
  `active_processes.json`, which has multiple writers (several subprocess types). The inference
  file does not have that profile. State this in the patcher's module docstring so a future
  maintainer doesn't "fix" it by adding a lock that the single writer doesn't need.
- **Concurrent-batch rejection:** at start, the patched code reads the existing progress file; if
  `status == "running"` AND `started_at` is within a staleness window (e.g. < 1 h old AND the
  writing process is alive — best-effort), the new batch writes
  `status:"error", error:"another inference is already running"` and raises a
  `RuntimeError("Another batch inference is already running. Stop it first from the Process
  Dashboard.")` so the Gradio handler surfaces it to the user instead of silently clobbering. (If
  the existing record is stale — app crashed — the startup sweep has already marked it
  `interrupted`, so a fresh start proceeds.)

### Patcher design — `patches/patch_inference_progress.py`

**Injected helper block** (mirror `patch_process_tracking.py`'s structure; inject after the
existing imports in `rvc/infer/infer.py`, before `class VoiceConverter`):

```python
# === Inference Progress Tracking (injected by patch) ===
import json as _infer_json
import time as _infer_time
import os as _infer_os

_INFER_PROGRESS_FILE = None
_INFER_CANCEL_FLAG = None

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
    path = _infer_progress_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _infer_json.load(f)
    except (IOError, _infer_json.JSONDecodeError):
        return None

def _write_infer_progress(record):
    # Best-effort: NEVER block inference because the dashboard file can't be written.
    path = _infer_progress_path()
    try:
        _infer_os.makedirs(_infer_os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        fd = _infer_os.open(tmp, _infer_os.O_WRONLY | _infer_os.O_CREAT | _infer_os.O_TRUNC, 0o600)
        with _infer_os.fdopen(fd, "w", encoding="utf-8") as f:
            _infer_json.dump(record, f)
        _infer_os.replace(tmp, path)
    except OSError:
        pass  # tracking is best-effort

def _infer_cancel_requested():
    return _infer_os.path.exists(_infer_cancel_path())
# === End Inference Progress Tracking ===
```

**Anchored rewrite of `convert_audio_batch`** (anchor on the existing L361-406 body; the patcher
matches the `pid = os.getpid()` line through the `finally: os.remove(...)` block — re-confirm the
exact text at plan time against current upstream). The replacement:
- Removes the `pid = os.getpid()` and the `infer_pid.txt` open/close/remove entirely.
- On entry: read existing progress; if `status=="running"` and fresh → raise
  `RuntimeError("Another batch inference is already running...")`.
- After `audio_files` is computed: write the start record (`status:"running"`, `total`,
  `processed:0`, `converted:0`, `skipped:0`, `current_file` = first file or `""`, `started_at`).
  **If `total == 0`:** write `status:"completed", processed:0, ended_at, elapsed:0.0` and return
  early (don't enter the loop, don't flash a running 0/0 card).
- Top of each loop iteration: if `_infer_cancel_requested()`, write
  `status:"cancelling"` (so the dashboard shows "Stopping…"), then break.
- After each `convert_audio` returns (L401): increment `converted` and `processed`; update
  `current_file` to the next file's basename; rewrite the progress record. For the skip branch
  (L395-396): increment `skipped` and `processed`, do NOT call `convert_audio`.
- Wrap the loop in `try/except Exception as e:` that writes `status:"error", error:str(e)` and
  re-raises (so upstream's Gradio handler still reports the error). Then `finally:` writes the
  terminal record (`completed` if not cancelled/error, else the already-set status), sets
  `ended_at`/`elapsed`, and **always removes the cancel flag** (so a post-completion cancel click is
  a no-op). Also append a history entry via the injected `_infer_add_to_history` helper (see below).

**History append from the patcher.** `rvc/infer/infer.py` does NOT have `patch_process_tracking.py`'s
injected `_add_to_history` (that lives in `core.py`). Two options — **choose Option B**:
- ~~Option A: import the core helpers.~~ Rejected — fragile cross-module coupling, and frozen import
  order is not guaranteed.
- **Option B:** inject a slim `_infer_add_to_history` into the same helper block that writes to
  `process_history.json` (same path as `_infer_progress_path`'s sibling, i.e.
  `~/Applio/.applio/process_history.json`). It replicates the schema exactly so the launcher's
  `load_process_history` reader (L601) and the dashboard's history sidebar render it natively:
  ```python
  def _infer_add_to_history(entry):
      # Schema-compatible with applio_launcher.load_process_history / add_to_history.
      # Required fields: type, started_at, completed_at.
      try:
          hist_path = _infer_os.path.join(_infer_os.path.dirname(_infer_progress_path()), "process_history.json")
          _infer_os.makedirs(_infer_os.path.dirname(hist_path), exist_ok=True)
          # Read+write under fcntl to match the launcher's concurrency model
          # (the launcher may be reading/writing simultaneously).
          import fcntl as _fcntl
          lock_path = hist_path + ".lock"
          with open(lock_path, "a") as lf:
              _fcntl.flock(lf.fileno(), _fcntl.LOCK_EX)
              try:
                  hist = {"version": 1, "history": []}
                  if _infer_os.path.exists(hist_path):
                      with open(hist_path, "r", encoding="utf-8") as f:
                          try: hist = _infer_json.load(f) or hist
                          except _infer_json.JSONDecodeError: pass
                  entry["process_id"] = f"inference-{entry.get('started_at')}"
                  hist.setdefault("history", []).insert(0, entry)
                  _HIST_MAX = 50
                  hist["history"] = hist["history"][:_HIST_MAX]
                  tmp = hist_path + ".tmp"
                  fd = _infer_os.open(tmp, _infer_os.O_WRONLY | _infer_os.O_CREAT | _infer_os.O_TRUNC, 0o600)
                  with _infer_os.fdopen(fd, "w", encoding="utf-8") as f:
                      _infer_json.dump(hist, f, indent=2)
                  _infer_os.replace(tmp, hist_path)
              finally:
                  _fcntl.flock(lf.fileno(), _fcntl.LOCK_UN)
      except OSError:
          pass  # best-effort
  ```
  Terminal entry written on completion/cancel/error:
  ```python
  _infer_add_to_history({
      "type": "inference",
      "model_name": <model basename>,
      "started_at": <iso from started_at epoch>,   # ISO string, matches existing schema
      "completed_at": <iso from ended_at epoch>,
      "status": <terminal status>,                 # "completed" | "cancelled" | "error" | "interrupted"
      "total": <int>, "converted": <int>, "skipped": <int>,
  })
  ```
  **Datetime aliasing note:** the existing history schema uses ISO strings
  (`_applio_dt.datetime.now().isoformat()`). Convert epoch floats to ISO with
  `import datetime as _infer_dt` + `_infer_dt.datetime.fromtimestamp(epoch).isoformat()` — do NOT
  use `datetime.datetime.fromtimestamp()` (the rebind discipline, even though `rvc/infer/infer.py`
  itself doesn't rebind, keeps the patcher portable if it's ever moved).

**Idempotency marker:** `IDEMPOTENCY_MARKER = "# === Inference Progress Tracking (injected by patch) ==="`;
the `patch_infer_py` function returns early if that marker is already in the file. Each sub-rewrite
also checks its own specific marker (e.g. `if '_infer_cancel_requested()' in content:`) per CLAUDE.md.

**Registration in `build_macos.py`:** add to `patches_to_apply` (alphabetical-ish, after the other
`rvc/infer/infer.py` patcher to be safe):
```python
("patches/patch_inference_progress.py", "rvc/infer/infer.py", "infer.py - batch inference progress tracking", "dir"),
```
No `PATCH_DEPENDENCIES` entry needed (independent of `patch_refinegan_legacy_infer.py` — different
functions: `convert_audio_batch` vs architecture detection).

### Patcher design — `patches/patch_stop_infer.py`

Rewrites `stop_infer` (`tabs/settings/sections/restart.py:52-74`) to cooperative cancellation.
Anchor on the existing function body. Replacement (conceptual):

```python
def stop_infer():
    # Cooperative cancellation: write the cancel flag. The inference loop
    # checks it per file and exits cleanly. Does NOT kill a PID (single-process:
    # the PID is the whole app). Best-effort: returns silently if no job is running.
    import os as _si_os
    data_path = _si_os.environ.get("APPLIO_DATA_PATH") or _si_os.path.expanduser("~/Applio")
    cancel_flag = _si_os.path.join(data_path, ".applio", "inference_cancel.flag")
    try:
        _si_os.makedirs(_si_os.path.dirname(cancel_flag), exist_ok=True)
        open(cancel_flag, "w").close()
    except OSError:
        pass
```

- `now_dir` (frozen-CWD) is NOT used — the path resolves absolutely. Fixes Bug 2's read side.
- The old `psutil` import in `restart.py` (L6) stays (still used by `stop_train` L11).
- Idempotency: `if 'inference_cancel.flag' in content:` early-return.
- Registration: `("patches/patch_stop_infer.py", "tabs/settings/sections/restart.py", "restart.py - cooperative inference cancel", "dir")`.

**The inference-tab Stop button** (`tabs/inference/inference.py:1821`, label "Stop convert") needs
NO change — it already calls `stop_infer`; the patched `stop_infer` now cancels cooperatively.
Acceptance: clicking it mid-batch cancels within one file's conversion time and the app stays alive.

### Dashboard integration (`applio_launcher.py`)

The dashboard currently keys everything off `get_active_processes()` (L575), which reads
`active_processes.json` only. Inference writes NEITHER that file NOR a PID, so today the dashboard
is blind to it. Integration points:

1. **New module-level reader** `_read_inference_progress()` (parallel to `get_active_processes`,
   ~L575). Reads `~/Applio/.applio/inference_progress.json` (same path resolver as
   `get_process_state_path` but for the inference filename). Returns the record dict or `None`.
   Tolerates missing/corrupt file (return `None`). No locking (read-only, atomic-replace writer).
2. **Synthesize into `_active_processes`** in `update_process_list` (L3711): after reading
   `get_active_processes()`, also read the inference record; if `status` in
   `("running","cancelling")`, synthesize a proc-shaped dict and append to `_active_processes`:
   ```python
   {"type": "inference", "status": <status>, "model_name": <model_name>,
    "total": <total>, "processed": <processed>, "converted": <converted>,
    "skipped": <skipped>, "current_file": <current_file>,
    "started_at_epoch": <started_at>, "input_folder": ..., "output_folder": ...,
    "_is_inference": True}  # discriminator for detail-panel branching
   ```
   This makes the existing sidebar table, idle→active transition, auto-show hook (L3745-3752), and
   action bar all work with no new UI primitives. **The auto-show now fires for inference** (idle→active
   when a batch starts), which is the desired "surface the dashboard when a job starts" behavior.
3. **Detail panel** (`_update_detail_panel`, L2609): branch on `proc.get("_is_inference")`:
   - Do NOT call `_parse_training_metrics` (L2702) for inference (it returns None gracefully, but
     inference-specific stats won't render).
   - Progress bar: `processed / total` (not epoch-fraction). Label: `f"{processed}/{total} files ({pct}%)"`.
   - Stats grid: **Current file** (basename, truncated), **Elapsed** (`now - started_at_epoch`),
     **ETA** (`(total - processed) * avg_per_file` where `avg_per_file = elapsed / max(converted,1)`),
     **Speed** (`converted / elapsed_minutes` files/min). Guard divide-by-zero.
   - Status text: map `cancelling` → "Stopping…", `running` → "Running", terminal → title-case.
4. **Stop action** (`stopProcess_`, L2922): branch on `_is_inference` — instead of
   `psutil.Process(pid).terminate()`, write the cancel flag (same logic as the patched `stop_infer`:
   resolve `~/Applio/.applio/inference_cancel.flag`, `open(...,"w").close()`). Set detail status to
   "Stopping…". Disable Stop + Pause buttons. **Pause is a no-op for inference** (cooperative pause
   isn't possible mid-file; disable the Pause button for inference rows and hide/tooltip "Not
   available for inference").
5. **Reveal output / Open output** (`revealLog_` L2970 / `openLog_` L2982): for inference, target
   `output_folder` instead of a log file. Security: `os.path.realpath()` the folder and confirm
   `os.path.isdir()` before `NSWorkspace`. If missing, log + no-op (don't raise).
6. **History rendering:** inference entries in `process_history.json` (written by the patcher) have
   `type:"inference"` + the standard required fields, so the existing history sidebar
   (`get_recent_processes`, L812) and idle-state browser render them automatically. For a selected
   inference history row, the detail panel (branch #3) shows "Completed — N files converted
   (M skipped)" using the stored `total`/`converted`/`skipped`.

### Startup sweep (stale-record recovery)
On launcher startup (in the existing init path, near where `cleanup_old_history` would be called),
add `_sweep_stale_inference_progress()`:
- Read `inference_progress.json`. If `status == "running"` (the writer was killed mid-batch by a
  crash/quit/SIGKILL), rewrite to `status:"interrupted", error:"interrupted by app restart",
  ended_at: time.time(), elapsed: ended_at - started_at`, and append the matching history entry
  with `status:"interrupted"`. Then remove any stale `inference_cancel.flag`.
- This guarantees the dashboard never shows a phantom "running" inference after a restart, and the
  interrupted run appears in history.

### Edge cases & resilience (enumerated, with handling)

| Case | Handling |
|---|---|
| Empty input folder / zero audio files | Start record detects `total==0` → writes `completed` immediately, returns early. No running 0/0 card. |
| All outputs already exist (skip-all) | `processed` reaches `total` via the skip branch; `converted` stays 0; terminal status `completed`. Card shows "0 converted, N skipped". |
| Permission error / disk-full on progress write | `_write_infer_progress` swallows `OSError` (best-effort). Inference continues; dashboard may lag but conversion is unaffected. Stated invariant: progress tracking never blocks inference. |
| Cancel mid-file | Loop checks per-file; the in-progress `convert_audio` finishes (could be 10-30 s on a long file). Status set to `cancelling` immediately so the dashboard shows "Stopping…". Stated: cancel = "stop before the NEXT file," not abort-current. |
| Cancel after completion | `finally` always removes the cancel flag regardless of how the loop exited, so a late cancel click is a no-op. |
| Cancel during the skip branch | Checked at top of every iteration including skips; cancel wins over skip-all. |
| App killed mid-batch (crash/quit) | `finally` may not run → stale `running` record. Startup sweep marks it `interrupted` and appends history. |
| Dashboard opened after job finished | Job is in `process_history.json`; idle-state history sidebar shows it; detail panel renders inference-specific summary. |
| Two batch tabs started concurrently | Second start refuses (`status:"running"` detected), raises `RuntimeError` surfaced in the Gradio UI. No silent clobber. |
| `output_folder` is deleted mid-run | `convert_audio` raises on write; caught by the loop's `try/except` → `status:"error"`, terminal record written, re-raised to Gradio. |
| Stale `infer_pid.txt` from an old two-process run | Harmless — the new code never reads or writes it; leave any stray file (it's in the read-only bundle path anyway and was never successfully written frozen). |
| User opens dashboard, closes it, job continues | Dashboard window hides (never releases); file is source of truth; reopening re-reads. Job unaffected by dashboard open/close. |

### Security mitigations

- **Trust boundary (load-bearing):** every field in `inference_progress.json` is **display-only**.
  The dashboard NEVER writes/executes a path derived from these fields. The only filesystem action
  driven by a progress field is "Reveal output" / "Open output," which targets `output_folder` —
  and that path is `os.path.realpath()`-resolved and `os.path.isdir()`-checked before
  `NSWorkspace` opens it (no shell, no exec — Finder just reveals an existing folder). A hostile
  `output_folder` (user pointed the batch at a hostile dir) can at most cause Finder to reveal that
  dir, which the user already selected.
- **No path traversal / arbitrary-write:** the cancel-flag path and the progress-file path are
  FIXED (derived from `APPLIO_DATA_PATH`, never from progress fields). User-supplied paths only
  appear as JSON values, never as write targets.
- **Info exposure:** absolute paths + model name live in `~/Applio/.applio/inference_progress.json`.
  Created with `0o600` (`os.open` mode in `_write_infer_progress`) so other local users can't read
  it. `process_history.json` is written `0o600` by the injected `_infer_add_to_history` (matching
  the new code; the existing `patch_process_tracking.py` writer does NOT set perms — note as a
  future improvement, out of scope here).
- **TOCTOU on cancel flag:** `os.path.exists(flag)` then break — classic TOCTOU but harmless (worst
  case: one extra file converts). Accepted; stated in the patcher docstring.
- **Unbounded history growth:** inference entries count against the existing 50-entry cap
  (`_HISTORY_MAX_ENTRIES`). A burst of inference runs will evict older training history. Accepted
  for v1; if it becomes a problem, give inference its own sub-cap (deferred).
- **Lock contention / polling cost:** the dashboard reads `inference_progress.json` every 2 s
  (existing NSTimer cadence). Single reader, single writer, atomic replace — negligible I/O, no lock.

### Part B — Acceptance criteria (observable, testable)

- **B-AC1 (patcher, cert-free):** `venv_macos/bin/python patches/patch_inference_progress.py rvc/infer` → exits 0;
  `venv_macos/bin/python -m py_compile rvc/infer/infer.py` exits 0; the helper block + rewritten
  `convert_audio_batch` are present (grep `_infer_cancel_requested` + `_write_infer_progress`);
  `grep -n "infer_pid" rvc/infer/infer.py` → **zero hits** (the PID file logic is gone). Then
  `git checkout -- rvc/infer/infer.py` to restore (never leave upstream dirty).
- **B-AC2 (stop patcher, cert-free):** `venv_macos/bin/python patches/patch_stop_infer.py tabs/settings/sections` → exits 0;
  `py_compile tabs/settings/sections/restart.py` exits 0; `grep "inference_cancel.flag" tabs/settings/sections/restart.py` → 1 hit; `grep -n "psutil.Process(pid).kill" tabs/settings/sections/restart.py` → zero hits in `stop_infer` (`stop_train` still uses psutil — that's fine). Restore.
- **B-AC3 (idempotency):** running each patcher twice on a patched file makes no change (the
  specific-marker check returns early).
- **B-AC4 (build clean):** `venv_macos/bin/python build_macos.py` (no `--sign`) completes; after
  build, `git status` shows NO upstream files dirty (`rvc/infer/infer.py`, `tabs/settings/sections/restart.py` restored by `post_build_restore`).
- **B-AC5 (frozen smoke — Stop doesn't kill app):** `open dist/Applio.app` → run a batch of ≥3
  audio files → Process Dashboard auto-shows (or open via Window menu) an inference card with
  `processed/total` climbing → click the dashboard Stop (or the inference-tab "Stop convert"
  button) → within one file's conversion time the loop halts, status shows `cancelled`, the app
  process is STILL ALIVE (verify `pgrep -f Applio` unchanged pid), and the run appears in the
  dashboard history sidebar as `cancelled` with correct counts.
- **B-AC6 (frozen smoke — completion + history):** run a small batch to completion → card reaches
  `total/total` → terminal status `completed` → history sidebar shows the run → selecting it
  renders "Completed — N files converted (M skipped)".
- **B-AC7 (frozen smoke — concurrent-batch rejection):** start a batch, then start a second batch
  from a second Gradio tab → the second surfaces a clear error ("Another batch inference is already
  running. Stop it first from the Process Dashboard.") and does NOT clobber the first's progress file.
- **B-AC8 (frozen smoke — empty + skip-all):** point at an empty folder → no card flashes, a
  `completed` 0-file history entry appears; point at a folder where all outputs exist → card shows
  "0 converted, N skipped" then completes.
- **B-AC9 (frozen smoke — interrupted recovery):** start a batch, force-quit the app mid-batch
  (Activity Monitor / `kill -9`) → relaunch → dashboard shows NO phantom running inference; history
  shows the run as `interrupted`.

### Part B — Task decomposition

**Task B1 — `patches/patch_inference_progress.py`.** Files: new `patches/patch_inference_progress.py`;
register in `build_macos.py:patches_to_apply`. Inject helper block (path resolver, atomic 0o600
write, cancel-flag check, history append) + rewrite `convert_audio_batch` (remove `infer_pid.txt`,
add start/loop/cancel/terminal writes, empty-folder early-return, concurrent-batch rejection).
Acceptance: B-AC1, B-AC3. Verify: `venv_macos/bin/python patches/patch_inference_progress.py rvc/infer && venv_macos/bin/python -m py_compile rvc/infer/infer.py && grep -c infer_pid rvc/infer/infer.py` (expect 0); then `git checkout -- rvc/infer/infer.py`.
**Task B2 — `patches/patch_stop_infer.py`.** Files: new `patches/patch_stop_infer.py`; register in
`build_macos.py`. Rewrite `stop_infer` to write the cancel flag cooperatively (absolute path, no
`now_dir`, no PID kill). Acceptance: B-AC2, B-AC3. Verify: run patcher + `py_compile tabs/settings/sections/restart.py`; then `git checkout -- tabs/settings/sections/restart.py`.
**Task B3 — Dashboard integration.** Files: `applio_launcher.py`. Add `_read_inference_progress()`
reader; synthesize inference proc into `_active_processes` in `update_process_list`; branch
`_update_detail_panel` on `_is_inference` (progress = processed/total, ETA/speed math); branch
`stopProcess_` to write the cancel flag + disable Pause for inference; branch `revealLog_`/`openLog_`
to target `output_folder` with realpath+isdir guard. Acceptance: manual dev run shows the card.
Verify: `venv_macos/bin/python -m py_compile applio_launcher.py`; `venv_macos/bin/python applio_launcher.py` + manual batch.
**Task B4 — Startup sweep.** Files: `applio_launcher.py`. Add `_sweep_stale_inference_progress()`
called once at launcher init (marks stale `running` → `interrupted`, appends history, removes stale
cancel flag). Acceptance: B-AC9.
**Task B5 — Frozen validation.** Build + smoke B-AC5 through B-AC9.

---

## Sequencing

**Part A first** (mechanical, low-risk, clears dead code before adding to the dashboard), then
**Part B** (the feature + bug-fix work). Both before the next signed+notarized release.

The current **v3.6.3.6** release has no DMG (intentionally — nothing ships until this lands).
After both parts, cut **v3.6.3.7** with a fresh signed+notarized build
(`venv_macos/bin/python build_macos.py --sign --notarize --dmg`) and the rewritten release description.

---

## Release notes draft (v3.6.3.7)

> **Single-process is now the only architecture.** v3.6.3.6 introduced a single-process mode and
> made it the default; v3.6.3.7 removes the legacy two-process code path entirely. There is no
> longer a `APPLIO_SINGLE_PROCESS` flag and no "wrapper subprocess" fallback — the app runs as one
> process out of the box (one dock icon, one menu, one window). If you previously set
> `APPLIO_SINGLE_PROCESS=0` to opt back into two-process, that setting is now ignored and can be removed.
>
> **Inference progress on the Process Dashboard.** Batch voice conversion now reports live progress
> (files converted / total, current file, ETA, speed) on the Process Dashboard, and completed/cancelled
> runs appear in the dashboard history.
>
> **Bug fix: Stop no longer quits the app.** In single-process mode, the inference-tab "Stop convert"
> button (and any PID-based stop) previously killed the *entire* app, because the inference PID was
> the app PID. Stop is now cooperative — it halts the batch cleanly at the next file and leaves the
> app running. This also fixes a frozen-build issue where batch inference could fail to write its
> stop-PID file in the read-only app bundle.

---

## Risks

- **`rvc/infer/infer.py` and `tabs/settings/sections/restart.py` are upstream** — all
  instrumentation goes through `patches/` (build-time), never a direct edit. After patching,
  `git status` must show no upstream files dirty (restore via `post_build_restore`). Verify the
  patched file `py_compile`s and the injection is correctly placed before committing.
- **Patcher anchors drift on upstream sync** — the 3.6.3 sync broke several anchors (see CLAUDE.md
  "Re-pointing patches after an upstream sync"). The `convert_audio_batch` body and `stop_infer` are
  the anchors; if a future sync rewrites them, the patcher prints "pattern not found" and must be
  re-pointed. Each patcher's regex must match the CURRENT upstream text exactly (re-confirm at plan time).
- **Patcher idempotency** — each patcher checks its OWN specific marker (per CLAUDE.md); do NOT use
  a shared early-return marker.
- **Dashboard synth is a new code path** — the inference proc dict flows through table/delegate/action
  code that today only handles subprocess procs. Test all branches (selection, Stop, Reveal, history
  row) on the frozen build, not just "the card appears."
- **The Stop hazard is a real latent bug in the shipped single-process default** — until Part B lands,
  users clicking Stop during a batch will kill the app. The release notes call this out explicitly.
- **Frozen validation required** — both parts are meaningless without a built `dist/Applio.app`
  smoke test. Part A: app launches single-process-only, no two-process code paths, quit is clean.
  Part B: a batch conversion drives the dashboard card, Stop cancels cleanly without quitting,
  interrupted runs recover on restart.

---

## Frozen smoke test (both parts) — step-by-step

1. `venv_macos/bin/python build_macos.py` (no `--sign` is fine for smoke; cert-free gates per CLAUDE.md).
2. `stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio` (build timestamp is AFTER commit).
3. `git status` → no upstream files dirty.
4. `open dist/Applio.app`. Wait for UI.
5. **Part A:** Window → Process Monitor opens the dashboard (one window). Cmd+Q quits; `pgrep -f Applio` → no orphan.
6. **Part B smoke:**
   - Inference → Batch tab → point at a folder with ≥3 wav files + a model → Convert.
   - Dashboard auto-shows (or open via Window menu) → inference card appears, `processed/total` climbs.
   - Click Stop (dashboard action bar OR inference-tab "Stop convert") → status "Stopping…" → loop halts → `pgrep -f Applio` shows the SAME pid (app alive) → history sidebar shows `cancelled`.
   - Run a second small batch to completion → card reaches total → history shows `completed` with correct counts.
   - Start a batch, force-quit the app mid-batch, relaunch → no phantom running card → history shows `interrupted`.
   - Start a batch in tab 1, start another in tab 2 → tab 2 shows a clear "another inference is already running" error.

---

## Verification commands (cert-free, per CLAUDE.md discipline)

```bash
# Part A — removal completeness
rg -n "APPLIO_SINGLE_PROCESS|_SINGLE_PROCESS|APPLIO_LAUNCHED_BY_LAUNCHER|_spawn_wrapper|_setup_ipc_observer|_ipc_signal_checker" \
  applio_launcher.py macos_wrapper.py build_macos.py    # expect: zero hits
venv_macos/bin/python -m py_compile applio_launcher.py macos_wrapper.py

# Part B — patchers (run directly, NEVER import build_macos)
venv_macos/bin/python patches/patch_inference_progress.py rvc/infer
venv_macos/bin/python -m py_compile rvc/infer/infer.py
rg -n "infer_pid" rvc/infer/infer.py                       # expect: zero hits
rg -n "_infer_cancel_requested|_write_infer_progress" rvc/infer/infer.py   # expect: hits
git checkout -- rvc/infer/infer.py                         # restore upstream

venv_macos/bin/python patches/patch_stop_infer.py tabs/settings/sections
venv_macos/bin/python -m py_compile tabs/settings/sections/restart.py
rg -n "inference_cancel.flag" tabs/settings/sections/restart.py            # expect: 1 hit
git checkout -- tabs/settings/sections/restart.py

# Idempotency (run each patcher twice — second run is a no-op)
venv_macos/bin/python patches/patch_inference_progress.py rvc/infer
venv_macos/bin/python patches/patch_inference_progress.py rvc/infer
git checkout -- rvc/infer/infer.py

# Build + frozen smoke (both parts) — see "Frozen smoke test" above
venv_macos/bin/python build_macos.py
git status                                                # expect: no upstream dirty
```

---

## Out of scope (deferred, with recorded reasons)

- **Single-file convert** — usually seconds; the card would flash and vanish; not worth instrumenting
  the hot path. (Split-audio chunk progress on one very long file is the only edge case; deferred.)
- **TTS** — the slow part (EdgeTTS network fetch) is already tracked as `tts` in
  `active_processes.json`; the in-process inference tail is one short convert. Marginal value.
- **Realtime VC** — different model (long-lived `multiprocessing` spawn, generator-driven, status
  shown in its own tab). Doesn't fit the dashboard's job shape. Its own design if ever wanted.
- **Concurrent batch jobs (real)** — v1 enforces single-active-job (refuses a second start). True
  concurrent tracking would need per-job IDs + a directory of progress files; revisit if a real
  workflow needs it. The refusal is user-visible, not silent.
- **Cooperative pause for inference** — Pause (SIGSTOP/SIGCONT) is meaningless for an in-process
  call; the Pause button is disabled for inference rows. A real "pause between files" could be added
  (a second sentinel), but no user has asked for it.
- **Per-process permissions on `process_history.json`** — the existing
  `patch_process_tracking.py` writer doesn't set 0o600; the new inference writer does. Aligning the
  old writer is a separate hardening pass.
