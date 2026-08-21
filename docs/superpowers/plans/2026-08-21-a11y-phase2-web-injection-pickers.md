# Accessibility Phase 2 — Web Injection, Native Pickers, Settings, i18n (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Gradio web UI itself non-visually observable (announcing job progress via an injected JS payload + a `/applio-a11y/progress` route), give every path field a keyboard-reachable Browse button backed by a native NSOpenPanel picker, add an Accessibility settings submenu (announcement verbosity + sound cues, persisted), wire native strings through the existing i18n system, and land the 10 refinements routed from the Phase 1 final review.

**Architecture:** Four new fork-owned Python modules keep logic AppKit-free and testable: `applio_progress_api.py` (progress payload + settings echo), `applio_native_picker.py` (NSOpenPanel marshaled to the main thread), `applio_browse_ui.py` (one-call Browse-button factory used by patched tab code), `applio_i18n.py` (native-string translation). Three new build-time patchers touch upstream files: `patch_progress_routes.py` (app.py — route registration + `prevent_thread_lock` flip), `patch_browse_buttons.py` (13 fields across 6 tab files), `patch_web_a11y_payload.py` (app.py — inject `assets/applio_a11y.js` via the `js=` launch kwarg). Two existing patchers get correctness fixes (`patch_process_tracking.py` write-order race, `patch_stop_feedback.py` scan bound). The launcher gains the settings submenu and consumes the refined `applio_a11y` API. The single-process architecture is what makes this work: the Gradio server runs in-process, so a FastAPI route handler shares module state with the launcher.

**Tech Stack:** Python 3.10, PyObjC/AppKit (NSOpenPanel, NSUserDefaults, NSSound), FastAPI routes on the Gradio app, Gradio 6.20.0 (`js=` launch kwarg verified at `blocks.py:2655`), vanilla ES2017 JavaScript (no build step), plain-script tests (`venv_macos/bin/python tests/test_x.py`; `-m pytest` only where noted).

**Global Constraints:**
- **Never edit upstream files directly** (upstream = anything in `git ls-tree upstream/main --name-only`; all `tabs/`, `app.py`, `core.py`, `rvc/` are upstream). Upstream changes go through `patches/*.py` patchers only. After testing any patcher: `git checkout -- app.py tabs` (and `assets core.py rvc` if touched). `git status` must show no patch markers before any commit.
- **Never `import build_macos`** for testing — the whole build runs at module level. Safe check: `venv_macos/bin/python build_macos.py --help` (exits before the build). Test a patcher standalone: `venv_macos/bin/python patches/patch_X.py <base_arg>` then restore sources.
- **All AppKit UI on the main thread.** Route handlers and Gradio event fns run on uvicorn/executor threads in the same process — marshal with `AppHelper.callAfter` and never touch NSApp objects directly from those threads. Blocking waits (`threading.Event.wait`) are allowed on those worker threads, never on the main thread.
- **`menu_spec.py` stays AppKit-free** (importable under any Python; consumed by tests).
- **No double announcements.** The native launcher already announces job lifecycle via `NSAccessibility`. The web payload must NOT repeat those in-app: the JS sends `client=native` when `window.pywebview` exists, and the route answers `announce.owner == "native"` only for that client — silencing the web job-announcement arm inside the WKWebView. An EXTERNAL browser pointing at the Gradio port still gets `owner == "web"` announcements (real feature, not dead code). Web-local concerns (focus restore, accordion healing, Last-result region, toast capture, output-change announcements) always run. NOTE: pristine dev (`python app.py`) has neither the route nor the payload — both exist only in the patched/built tree.
- **Gradio 6.20.0 has NO `js_api=` launch kwarg** (verified: no such parameter in `blocks.py` `launch()`). Do not design JS→Python callbacks around it. The picker is a Gradio event (`gr.Button.click` → Python handler → native panel). The only JS→Python channel is the polling route.
- **The route path is `/applio-a11y/progress`** — NOT `/api/progress`. Gradio owns `/api/*` (its own REST API); a custom path avoids any routing conflict.
- **`prevent_thread_lock` flip semantics** (Task 7): in the default (non-`--client`) path upstream passes `prevent_thread_lock=False` so `launch()` never returns and everything after the launch call in `app.py` (the entire TensorBoard proxy, `app.py:244-279`) is dead code. Our patch flips it to `True` and MUST keep the calling thread alive with its own infinite sleep so `launch_gradio()` still never returns in normal mode (the wrapper's supervisor contract depends on it). The TensorBoard proxy stays dead in normal mode (our sleep precedes it) — status quo, no regression.
- **Frozen importability:** new root-level modules (`applio_progress_api`, `applio_native_picker`, `applio_browse_ui`, `applio_i18n`) AND `rvc.lib.tools.process_log_parser` (currently ships as unimportable DATA — CLAUDE.md "Frozen module importability") go into `build_macos.py` HIDDEN_IMPORTS. `assets/applio_a11y.js` ships automatically via the existing `("assets", "assets")` datas entry.
- **Patcher conventions:** each patch function checks for its OWN `_APPLIO_*` marker (per-fn idempotency, never a shared early-return); exit 0 = patched/already-patched, 1 = anchor miss; after patching, `py_compile` the patched file and verify injected code placement, then `git checkout --` the source.
- **Announcement coalescing stands** (Phase 1): lifecycle events only, never per-tick. Verbose mode adds milestone announcements (≥25% steps) on the WEB side only; the native channel never gains per-tick chatter.
- New user-visible web strings go through the tab modules' existing `i18n(...)` (English fallback is graceful — `i18n.py:52` returns the key). Native strings route through `applio_i18n` (Task 10); untranslated keys degrade to English.
- **Line numbers cited below were verified against `main` HEAD `7c5849eb` on 2026-08-21** by a five-agent anchor pass; re-locate anchors by content before editing.
- Commits: fork-conventional messages (`feat(a11y): …`), one per task. Black runs via CI on push.

**User decisions (already made):**
- Phase 2 scope = audit §6 roadmap: web-side announcements, pickers/Browse buttons, settings submenu, native-string i18n, persistent Last-result region, routed refinements. Upstream Applio + gradio PRs are Phase 3 (separate effort, NOT this plan).
- The audit's `js_api=FileBridge` idea is dropped — gradio 6.20.0 has no `js_api` (verified). Browse buttons are server-side Gradio events calling a native picker (this plan, Task 4/5).
- Settings submenu offers Announcements (Off/Standard/Verbose) + Sound cues. Braille cadence and speech synthesis stay out (AX announcements mirror to braille by nature; speech would collide with converted-audio evaluation — Phase 1 ruling, unchanged).
- i18n wiring degrades gracefully: untranslated keys fall back to the English key text (`i18n.py:52` semantics); we do not edit the 60 upstream locale files. Future real translations land in a fork-owned `assets/applio_i18n_overrides.json` layered over the locale map.
- Phase 1's VoiceOver checklist (audit §7) had not produced results when this plan was written; Task 11's verification section folds whatever it reports into the final manual pass.

**Review provenance (2026-08-21):** anchors (launch site, gradio 6.20.0 kwargs, path-field inventory, i18n loader, current fork-owned APIs, all 10 refinement sites) were gathered by five parallel read-only agents against `7c5849eb` and cross-checked; the plan then passed an adversarial senior review (see review log at the end of the file).

**Verification base for every task:** `venv_macos/bin/python -m py_compile <changed .py files>` plus the task's own `Verify` command. Menu-spec tasks additionally run `venv_macos/bin/python tests/test_menu_spec.py`.

---

### Task 1: `applio_a11y.py` refinements — statuses, keys, badge count, lazy words, arg order

**Goal:** Harden the announcement engine with the five pure refinements routed from the Phase 1 final review: a derived `LIVE_STATUSES` constant, `word_key`-based terminal-word lookup (so snapshot keys can carry pids without breaking word lookup), a pure `count_live` badge helper, a `missing_keys` method enabling lazy history reads, and `post_announcement` arg-order alignment with the launcher's `_announce_for_accessibility`.

**Files:**
- Modify: `applio_a11y.py` (TERMINAL_STATUSES at L13-20; events at L40-72; `post_announcement` at L75)
- Test: `tests/test_applio_a11y.py` (10 existing tests at L16-82; runner at L88-95)

**Acceptance Criteria:**
- [ ] `LIVE_STATUSES = {"running", "paused"}` is defined next to `TERMINAL_STATUSES`; the disappear-branch guard at L70 uses it; a module-level invariant asserts the two sets are disjoint
- [ ] `events()` disappearance branch POPS the vanished key from `_seen` (single announcement, then gone — the current code at L69 already pops; the rewrite must keep that) and looks up the terminal word by the `word_key` captured into the `_seen` tuple when the key was first seen: `words.get(word_key, "finished")` with `word_key = info.get("word_key", key)` stored at insertion time (the vanished entry is NOT in `snapshot` anymore — reading it from the snapshot would always miss)
- [ ] New pure function `count_live(snapshot) -> int` counts entries whose status is in `LIVE_STATUSES` (a paused job counts — it is live and resumable)
- [ ] New method `AnnouncementPolicy.missing_keys(snapshot) -> set` returns `set(self._seen) - set(snapshot)` without mutating `_seen`
- [ ] `post_announcement` signature becomes `(element, message)` — same order as `applio_launcher.py:143 _announce_for_accessibility(element, message)` — and the module docstring no longer claims a mirrored-but-swapped order; the single cross-module call site (`applio_launcher.py:5407`, updated in Task 2) is the only caller
- [ ] All 10 existing tests pass unchanged (except the file's test count comment), plus the new tests below → `venv_macos/bin/python tests/test_applio_a11y.py` reports 17 tests

**Verify:** `venv_macos/bin/python tests/test_applio_a11y.py` → `All applio_a11y tests passed (17).`

**Steps:**

- [ ] **Step 1: Write the failing tests** — append to `tests/test_applio_a11y.py` (script style, matching the existing helpers; entries are dicts like the launcher builds):

```python
def test_live_statuses_disjoint_from_terminal():
    import applio_a11y

    assert applio_a11y.LIVE_STATUSES == {"running", "paused"}
    assert not (applio_a11y.LIVE_STATUSES & applio_a11y.TERMINAL_STATUSES)


def test_count_live_includes_paused():
    snap = {
        "training:a:1": {"type": "training", "name": "a", "status": "running"},
        "training:b:2": {"type": "training", "name": "b", "status": "paused"},
        "tts:c:3": {"type": "tts", "name": "c", "status": "completed"},
    }
    assert applio_a11y.count_live(snap) == 2


def test_word_key_overrides_snapshot_key_for_terminal_word():
    pol = applio_a11y.AnnouncementPolicy()
    pol.prime(
        {
            "training:voice:123": {
                "type": "training",
                "name": "voice",
                "status": "running",
                "word_key": "training:voice",
            }
        }
    )
    events = pol.events(
        {}, terminal_words={"training:voice": "failed"}
    )
    assert ("terminal", "training: voice failed") in events


def test_missing_keys_is_readonly():
    pol = applio_a11y.AnnouncementPolicy()
    pol.prime({"a:1": {"type": "a", "name": "x", "status": "running"}})
    missing = pol.missing_keys({})
    assert missing == {"a:1"}
    assert set(pol._seen) == {"a:1"}  # _seen untouched
    # steady state: nothing missing
    assert pol.missing_keys({"a:1": {"type": "a", "name": "x", "status": "running"}}) == set()


def test_two_jobs_same_type_name_distinct_keys():
    pol = applio_a11y.AnnouncementPolicy()
    pol.prime({})
    snap = {
        "training:voice:111": {"type": "training", "name": "voice", "status": "running"},
        "training:voice:222": {"type": "training", "name": "voice", "status": "running"},
    }
    starts = [e for e in pol.events(snap) if e[0] == "start"]
    assert len(starts) == 2


def test_disappeared_unknown_status_silent():
    # prev status in neither LIVE nor TERMINAL (e.g. a raw "cancelling" leak):
    # documented behavior — no event (same as today's tuple guard, now derived)
    pol = applio_a11y.AnnouncementPolicy()
    pol._seen = {"tts:x:1": ("cancelling", "tts: x", "tts:x")}
    assert pol.events({}) == []


def test_disappeared_key_popped_single_announcement():
    pol = applio_a11y.AnnouncementPolicy()
    pol._seen = {"training:a:1": ("running", "training: a", "training:a")}
    first = pol.events({})
    assert ("terminal", "training: a finished") in first
    # second call must NOT re-announce (key was popped, not kept)
    assert pol.events({}) == []
    assert pol.missing_keys({}) == set()
```

- [ ] **Step 2: Run to verify they fail** — `venv_macos/bin/python tests/test_applio_a11y.py` → AttributeError/NameError on `LIVE_STATUSES` / `count_live` / `missing_keys`; word-key test gets `"training: voice finished"` instead.

- [ ] **Step 3: Implement** in `applio_a11y.py`:

```python
TERMINAL_STATUSES = {
    "completed",
    "failed",
    "error",
    "cancelled",
    "canceled",
    "interrupted",
}
LIVE_STATUSES = {"running", "paused"}
assert not (LIVE_STATUSES & TERMINAL_STATUSES)  # statuses partition into live/terminal/other


def count_live(snapshot):
    """Live (announceable-resumable) job count: running + paused."""
    return sum(1 for v in snapshot.values() if v.get("status") in LIVE_STATUSES)
```

In `events()`, replace the disappear branch. Two coordinated changes: (1) `_seen` values widen from `(status, label)` to `(status, label, word_key)` — set `word_key = info.get("word_key", key)` at EVERY insertion site (the update path AND `prime`; the vanished entry is no longer in `snapshot`, so the word key must ride in `_seen`); (2) the loop KEEPS the pop (the current code at L69 pops — dropping it would re-announce every vanished job every heartbeat forever):

```python
        for key in [k for k in self._seen if k not in snapshot]:
            prev_status, label, word_key = self._seen.pop(key)
            if prev_status in LIVE_STATUSES:
                out.append(("terminal", f"{label} {words.get(word_key, 'finished')}"))
```

Add the method:

```python
    def missing_keys(self, snapshot):
        """Keys present in _seen but absent from snapshot (candidates for
        disappearance announcements) — read-only, lets the caller decide
        whether the terminal-words history read is worth doing this tick."""
        return set(self._seen) - set(snapshot)
```

Change the poster signature (and its docstring) to:

```python
def post_announcement(element, message):
    """Post an AX announcement from `element` (same arg order as
    applio_launcher._announce_for_accessibility)."""
```

The body is unchanged.

- [ ] **Step 4: Run all tests** → 17 pass (10 existing + the 7 new). (The launcher still calls `post_announcement(msg, element)` until Task 2 — that is the next task's first step; do NOT run the app in between.)

- [ ] **Step 5: Commit**

```bash
git add applio_a11y.py tests/test_applio_a11y.py
git commit -m "feat(a11y): LIVE_STATUSES, word_key, count_live, missing_keys, poster arg order"
```

---

### Task 2: Launcher refinements — pid keys, badge truth, Stopping row, lazy history, call-site order

**Goal:** Consume Task 1's API in `applio_launcher.py`: snapshot keys gain pids (same-type:name collisions no longer overwrite), the dock badge counts paused jobs, a cancelling batch shows "Stopping" in the sidebar, terminal words are read from history only when something disappeared, and the `post_announcement` call site matches the new arg order.

**Files:**
- Modify: `applio_launcher.py` (`_a11y_snapshot` L5301-5351; `_a11y_terminal_words` L5353-5374; `_a11y_heartbeat` L5376-5397; `_a11y_post` call at L5407; row builder L3816-3830, the word at L3827; the `{phase}` comment at L1903-1906)

**Acceptance Criteria:**
- [ ] `_a11y_snapshot` keys are `f"{type}:{name}:{pid}"` for subprocess procs (pid already read at L5318; use `pid or "x"`) and `f"inference:{name}:app"` for the synthesized batch; each entry gains `"word_key": f"{type}:{name}"` (subprocess) / `f"inference:{name}"`... **correction:** history entries are written with the proc's `type` from `active_processes.json`, where the synthesized inference is recorded with type `inference` by `patch_inference_progress.py` — so `word_key` for inference is `f"inference:{name}"`. Verify against `_a11y_terminal_words` (L5370, `f"{etype}:{name}"`) while implementing.
- [ ] `_a11y_heartbeat` computes `missing = self._a11y_policy.missing_keys(snap)` and calls `self._a11y_terminal_words()` ONLY when `missing` is non-empty, passing `{}` otherwise (drops a locked whole-file JSON read every 2 s)
- [ ] Badge count uses `applio_a11y.count_live(snap)` (paused jobs keep the badge alive)
- [ ] `applio_a11y.post_announcement(element, msg)` at the `_a11y_post` call site (was `(msg, element)`)
- [ ] Sidebar active-row word (L3827): `status == "cancelling"` → `"Stopping"` checked BEFORE the `_ps_stopped` probe (which is forced False for synthesized inference procs at L3488)
- [ ] L1903-1906: the AX-value comment tells the truth — the AX value intentionally uses natural case (`f"{phase} — …"`) while the visual uses `{phase.upper()}`; amend the comment to say so (code unchanged)
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py` passes; `venv_macos/bin/python tests/test_applio_a11y.py` still passes (no policy change)

**Verify:** `venv_macos/bin/python -m py_compile applio_launcher.py && venv_macos/bin/python tests/test_applio_a11y.py`

**Steps:**

- [ ] **Step 1:** Fix the call order first (the app is broken w.r.t. Task 1 until this lands): `applio_launcher.py:5407` → `applio_a11y.post_announcement(element, msg)`.
- [ ] **Step 2:** `_a11y_snapshot`: subprocess loop — after the existing `pid = proc.get("pid")` (L5318) and pause probe, build

```python
            key = f"{proc.get('type', 'process')}:{name}:{pid or 'x'}"
            snap[key] = {
                "type": proc.get("type", "process"),
                "name": name,
                "status": status,
                "word_key": f"{proc.get('type', 'process')}:{name}",
            }
```

  Inference block (L5330-5350): key `f"inference:{name}:app"`, entry gains `"word_key": f"inference:{name}"`. (Keep the existing spoken label type `"batch inference"` in the native snapshot — it is label text only; `word_key` is what must match history's `"inference"` type, and Task 6's payload independently emits type `"inference"`. Do not "align" the label.)
- [ ] **Step 3:** `_a11y_heartbeat` (L5376-5397) — replace the unconditional words read and the badge count:

```python
        snap = self._a11y_snapshot()
        missing = self._a11y_policy.missing_keys(snap)
        words = self._a11y_terminal_words() if missing else {}
        events = self._a11y_policy.events(snap, terminal_words=words)
        ...
        live = applio_a11y.count_live(snap)
        AppHelper.callAfter(self._a11y_update_badge, live)
```

  (`_a11y_terminal_words` itself is unchanged — its `f"{etype}:{name}"` keys now match `word_key`.)
- [ ] **Step 4:** Sidebar word at L3827 (function-body indent is 12 spaces there — the `word = "Paused" if ...` line it replaces sits inside `if row < len(self._active_processes):`):

```python
            if proc.get("status") == "cancelling":
                word = "Stopping"
            elif proc.get("_ps_stopped"):
                word = "Paused"
            else:
                word = "Running"
```

- [ ] **Step 5:** Comment amendment at L1903-1904 to: `# AX value mirrors the visual line minus the emoji; casing stays natural (screen readers read "Feature extraction" naturally — the visual .upper() is styling only).`
- [ ] **Step 6:** Run Verify; commit:

```bash
git add applio_launcher.py
git commit -m "feat(a11y): pid-keyed snapshots, live badge count, Stopping row, lazy history read"
```

---

### Task 3: Patcher correctness fixes — history-before-untrack write order, bounded upload scan

**Goal:** Close the history-write race (a job can vanish from `active_processes.json` a heartbeat-read before its history entry lands, announcing "finished" — or a STALE word from an older same-name run — instead of "failed") by writing history BEFORE untracking in all four injected `finally` blocks; and bound `patch_stop_feedback.patch_upload`'s return-statement scan to `save_to_wav2`'s body so a missing anchor can never inject a toast into a later function.

**Files:**
- Modify: `patches/patch_process_tracking.py` — **its sub-patchers inject into `core.py`** (`patch_core_py` reads `core.py`; sub-fns `patch_run_preprocess_script` / `patch_run_extract_script` / `patch_run_train_script` / `patch_run_index_script` / `patch_voice_conversion` at ≈L283/334/384/453/486, each `content -> tuple[str, bool]`). The four tracked-job blocks (untrack at ≈L314/364/423/513 in the replacement strings; history writes at ≈L316-325/366-…/425-441/515-526 — AFTER the finally, at function-body indent) are what moves.
- Modify: `patches/patch_stop_feedback.py` (`patch_upload` L52-68)
- Test: create `tests/test_patch_fixtures.py`

**Acceptance Criteria:**
- [ ] In every injected block of `patch_process_tracking.py`, the `_add_to_history({...})` call (with its entry construction) textually precedes the `_untrack_process(<type>)` call, both INSIDE the `finally:` block, each wrapped in its own `try/except Exception: pass`, with the status expression guarded so it cannot raise `NameError` when `subprocess.Popen` itself failed (`_proc` unbound): `"_proc" in locals() and _proc.returncode == 0` — history then correctly records `failed` for Popen-failure runs instead of crashing the finally
- [ ] The training block's `_snapshot_training_metrics(...)` + `_history_entry` construction moves inside the finally with `_add_to_history`, placed AFTER `_log_file.close()` (the snapshot opens the file itself)
- [ ] `patch_stop_feedback.patch_upload` finds the first `\n    return` only within `save_to_wav2`'s body (bounded by the next `\ndef ` after the `def save_to_wav2(` match); "no return inside the body" → `"miss"` like the existing L60-61 path
- [ ] `tests/test_patch_fixtures.py` proves: (a) running the real sub-fns over PRISTINE `core.py` produces output where every `_untrack_process(` CALL SITE (skip the injected `def` lines) is preceded by an `_add_to_history(` call within the same function; (b) the current tree order (untrack first) FAILS the assertion; (c) a synthetic content where `save_to_wav2` has no own return but a later def does → `patch_upload` reports `"miss"` and returns content unchanged; (d) the test guards itself against a dirty tree (`assert "_APPLIO_" not in src and "_track_process(" not in src` before patching)
- [ ] `venv_macos/bin/python -m py_compile patches/patch_process_tracking.py patches/patch_stop_feedback.py` passes, and the patched `core.py` output `py_compile`s (write to a temp file)
- [ ] Sources restored pristine after testing (`git checkout -- core.py`; `git status` clean)

**Verify:** `venv_macos/bin/python tests/test_patch_fixtures.py && git checkout -- core.py && git status --short core.py` (empty)

**Steps:**

- [ ] **Step 1: Write the failing tests** — `tests/test_patch_fixtures.py`, script-style:

```python
"""Fixture tests for patcher correctness (history-write order + bounded scan).
Run: venv_macos/bin/python tests/test_patch_fixtures.py
Reads PRISTINE upstream core.py from the repo; guards against a dirty tree."""

import importlib.util
import os
import py_compile
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patched_core(tracking):
    src = open(os.path.join(REPO, "core.py"), encoding="utf8").read()
    assert "_track_process(" not in src, "core.py is dirty (patched?) - restore first"
    content = src
    ok = 0
    for fn_name in (
        "patch_run_preprocess_script",
        "patch_run_extract_script",
        "patch_run_train_script",
        "patch_run_index_script",
        "patch_voice_conversion",
    ):
        fn = getattr(tracking, fn_name)
        content, patched = fn(content)
        ok += 1 if patched else 0
    assert ok >= 4, f"expected >=4 patched blocks, got {ok} (anchors drifted?)"
    return content


def test_history_written_before_untrack():
    tracking = _load("patch_process_tracking", "patches/patch_process_tracking.py")
    patched = _patched_core(tracking)
    # Anchored regex = CALL sites only: a def line ("    def _untrack_process(")
    # cannot match ^[ \t]*_untrack_process\(. (A plain find() would also hit
    # the injected helper definitions — that false-positive pattern is why
    # this uses the anchor.)
    sites = list(re.finditer(r"(?m)^[ \t]*_untrack_process\(", patched))
    assert len(sites) >= 4, f"expected >=4 untrack call sites, found {len(sites)}"
    for m in sites:
        u = m.start()
        # enclosing function = nearest preceding top-level def
        fstart = patched.rfind("\ndef ", 0, u)
        fend = patched.find("\ndef ", u)
        body = patched[fstart:fend if fend != -1 else len(patched)]
        h = body.find("_add_to_history(")
        assert h != -1 and h < body.find("_untrack_process("), (
            "untrack precedes history-add inside a tracked function"
        )
    # sanity: the patched output compiles
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(patched)
    py_compile.compile(tf.name, doraise=True)
    os.unlink(tf.name)


def test_upload_scan_bounded_to_function_body():
    stop = _load("patch_stop_feedback", "patches/patch_stop_feedback.py")
    synthetic = (
        "def save_to_wav2(bin_file):\n"
        "    uploaded = bin_file.name\n"
        "\n"
        "def later_function(x):\n"
        "    return x\n"
    )
    content, status = stop.patch_upload(synthetic)
    assert status == "miss", "scan must not cross the function boundary"
    assert "gr.Info" not in content
    good = (
        "def save_to_wav2(bin_file):\n"
        "    uploaded = bin_file.name\n"
        "    return uploaded\n"
    )
    content, status = stop.patch_upload(good)
    assert status == "patched" and "gr.Info" in content


def run_all():
    test_history_written_before_untrack()
    test_upload_scan_bounded_to_function_body()
    print("All patch fixture tests passed (2).")


if __name__ == "__main__":
    run_all()
```

  IMPLEMENTER NOTE: read `patches/patch_process_tracking.py` first and confirm the real sub-fn names/count before finalizing the loop (`patch_run_index_script` exists alongside the four tracked-job fns; include whatever fns carry `_untrack_process` injections). The contract is fixed: every `_untrack_process(` call site's enclosing function contains an `_add_to_history(` call BEFORE it, `>= 4` sites, and the patched output compiles.

- [ ] **Step 2: Run** → the order test FAILS against the current patcher output (untrack precedes history today — that is the race being fixed); the bounded-scan test fails (toast injected into `later_function`).

- [ ] **Step 3: Fix `patch_process_tracking.py`** — in each of the four tracked-job replacement strings the CURRENT shape is: `_untrack_process(<type>)` bare inside `finally:`, and the `_add_to_history({...})` call (plus, for training, `_snapshot_training_metrics` + `_history_entry` construction) AFTER the finally at function-body indent, unguarded, referencing `_proc.returncode`. Move the history write INTO the finally, FIRST, self-guarded. Representative transformation (preprocess block):

```python
        # BEFORE (current, inside the function):        # AFTER:
        #   finally:                                    #   finally:
        #       _log_file.close()                       #       _log_file.close()
        #       _untrack_process("preprocess")          #       try:
        #   _add_to_history({                           #           _add_to_history({
        #       "type": "preprocess",                   #               "type": "preprocess",
        #       "status": "completed"                   #               "status": (
        #           if _proc.returncode == 0            #                   "completed"
        #           else "failed", ...                  #                   if "_proc" in locals()
        #   })                                          #                   and _proc.returncode == 0
        #                                               #                   else "failed"
        #                                               #               ), ...
        #                                               #           })
        #                                               #       except Exception:
        #                                               #           pass
        #                                               #       try:
        #                                               #           _untrack_process("preprocess")
        #                                               #       except Exception:
        #                                               #           pass
```

  The training block additionally moves `_snapshot_training_metrics(_log_file_path, _prior_points)` and the `_history_entry` dict construction inside the finally, between `_log_file.close()` and `_add_to_history(_history_entry)` (the snapshot opens the log file itself — it needs the file CLOSED, hence after `.close()`). Keep each of the four history dicts' existing field sets byte-identical apart from the guarded status expression.

  Rationale: once the key vanishes from `active_processes.json` (untrack), a concurrent heartbeat read can no longer race a missing history entry — the word is guaranteed present first. Bonus: Popen-failure runs now land in history as `failed` (today the unguarded `_proc.returncode` raises `NameError` in exactly that case, masking the original exception). The `_add_to_history` impl (L174-193, atomic tmp+rename under file lock) is untouched.

- [ ] **Step 4: Fix `patch_stop_feedback.patch_upload`** (L52-68) — bound the scan:

```python
def patch_upload(content):
    if UPLOAD_MARKER in content:
        return content, "already"
    idx = content.find("def save_to_wav2(")
    if idx == -1:
        return content, "miss"
    body_end = content.find("\ndef ", idx)
    if body_end == -1:
        body_end = len(content)
    ret = content.find("\n    return", idx, body_end)
    if ret == -1:
        return content, "miss"
    # ... existing injection at `ret`, unchanged
```

- [ ] **Step 5: Run tests → 2 pass.** Then `git checkout -- core.py tabs` and confirm clean.

- [ ] **Step 6: Commit**

```bash
git add patches/patch_process_tracking.py patches/patch_stop_feedback.py tests/test_patch_fixtures.py
git commit -m "fix(a11y): history-before-untrack write order; bounded upload-anchor scan"
```

---

### Task 4: `applio_native_picker.py` — NSOpenPanel marshaled to the main thread

**Goal:** A fork-owned, AppKit-lazy module that opens a native NSOpenPanel (file / folder / .pth-filtered) from ANY thread — Gradio event handlers run on executor threads — by marshaling the modal panel onto the main AppKit thread via `AppHelper.callAfter` and waiting on an `Event`. Returns a (status, path) tuple with a clean unavailable-path for dev runs without an AppKit loop.

**Files:**
- Create: `applio_native_picker.py`
- Test: `tests/test_native_picker.py`
- Modify: `applio_launcher.py` (`ApplioLauncher.__init__` a11y-state block at L4757-4760 — add the one-line `mark_native_loop_available()` call)
- Modify: `build_macos.py` (HIDDEN_IMPORTS block L505-574 — add `"applio_native_picker"` next to `"applio_a11y"`)

**Acceptance Criteria:**
- [ ] `native_browse(mode, prompt=None, timeout=PICK_TIMEOUT_S)` returns `("ok", <abs path str>)` / `("cancel", None)` / `("unavailable", None)`; modes: `"file"`, `"folder"`, `"pth"`
- [ ] Panel configuration per mode: folder → `canChooseDirectories=True, canChooseFiles=False`; file/pth → inverse; pth additionally `setAllowedFileTypes_(["pth"])`; always `allowsMultipleSelection=False`, `resolvesAliases=True`
- [ ] The panel runs via `AppHelper.callAfter` on the main thread; the caller blocks on `threading.Event().wait(timeout=timeout)`; a timeout yields `("cancel", None)`
- [ ] **Availability is an explicit flag, NOT `NSApp is None`** — verified: PyObjC materializes a non-None `NSApp` proxy even with no run loop, so that check is dead code and a dev Browse click would block a Gradio worker the full timeout. `mark_native_loop_available()` (module fn, sets a flag) is called ONCE from `applio_launcher.__init__`; `native_browse` returns `("unavailable", None)` immediately when the flag is unset (plain `python app.py` / test processes) — never blocks
- [ ] `pick_ui_config(mode)` is a pure function returning the panel-config dict (testable without AppKit); the AppKit path is a thin shell over it
- [ ] Every failure path is exception-guarded (a picker crash must never take the app down); `logging.debug("[Picker] …")` diagnostics
- [ ] `venv_macos/bin/python tests/test_native_picker.py` passes (fast — the unavailable path is asserted with `timeout=0.5`); `"applio_native_picker"` in HIDDEN_IMPORTS; the `mark_native_loop_available()` call present in `applio_launcher.__init__`

**Verify:** `venv_macos/bin/python tests/test_native_picker.py && venv_macos/bin/python build_macos.py --help 2>&1 | head -1 && grep -c applio_native_picker build_macos.py` → tests pass, help prints usage, grep ≥ 1

**Steps:**

- [ ] **Step 1: Failing tests** — `tests/test_native_picker.py`:

```python
"""Pure-config + fallback tests for applio_native_picker (no AppKit needed).
Run: venv_macos/bin/python tests/test_native_picker.py"""

import applio_native_picker as picker


def test_pick_ui_config_modes():
    assert picker.pick_ui_config("folder") == {
        "files": False,
        "dirs": True,
        "allowed": None,
    }
    assert picker.pick_ui_config("file") == {"files": True, "dirs": False, "allowed": None}
    assert picker.pick_ui_config("pth") == {
        "files": True,
        "dirs": False,
        "allowed": ["pth"],
    }


def test_unknown_mode_raises():
    try:
        picker.pick_ui_config("weird")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown mode must raise ValueError")


def test_unavailable_without_native_loop():
    # The availability flag is unset in this process (only the launcher sets
    # it) -> immediate ("unavailable", None). Empirically necessary: PyObjC
    # materializes a non-None NSApp proxy even with no run loop, so an
    # NSApp-based check would queue the panel for a loop that never runs and
    # block for the full timeout.
    picker._native_loop_available = False
    status, path = picker.native_browse("file", timeout=0.5)
    assert status == "unavailable"
    assert path is None


def run_all():
    test_pick_ui_config_modes()
    test_unknown_mode_raises()
    test_unavailable_without_native_loop()
    print("All native picker tests passed (3).")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 2: Run** → ImportError (module missing).

- [ ] **Step 3: Implement** `applio_native_picker.py`:

```python
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
```

- [ ] **Step 4: Run tests → 3 pass.** Add `"applio_native_picker"` to HIDDEN_IMPORTS in `build_macos.py` (next to `"applio_a11y"`); sanity-check with `venv_macos/bin/python build_macos.py --help`.

- [ ] **Step 5: Set the availability flag at native startup** — in `applio_launcher.py` `__init__`, inside the a11y-state block (L4757-4760), add:

```python
        try:
            import applio_native_picker

            applio_native_picker.mark_native_loop_available()
        except Exception:
            pass
```

  (`py_compile applio_launcher.py` after.)

- [ ] **Step 6: Commit**

```bash
git add applio_native_picker.py tests/test_native_picker.py applio_launcher.py build_macos.py
git commit -m "feat(a11y): native NSOpenPanel picker marshaled to the main thread"
```

---

### Task 5: `applio_browse_ui.py` + `patch_browse_buttons.py` — Browse buttons on all path fields

**Goal:** A one-call factory (`applio_browse_ui.browse_button(mode, target, elem_id=…)`) that creates a `gr.Button("Browse…")` and wires its click to a handler which runs the native picker and writes the chosen path into the target component (returning the current value untouched on cancel/unavailable, with a spoken `gr.Info` explaining why); plus a build-time patcher inserting one factory line after each of the 13 path-field definitions across 6 upstream tab files.

**Files:**
- Create: `applio_browse_ui.py`, `patches/patch_browse_buttons.py`
- Modify (build-time only, restored after): `tabs/train/train.py`, `tabs/inference/inference.py`, `tabs/tts/tts.py`, `tabs/realtime/realtime.py`, `tabs/voice_blender/voice_blender.py`, `tabs/extra/sections/processing.py`
- Test: `tests/test_browse_ui.py` (factory wiring, AppKit-free) and fixture tests for the patcher in `tests/test_patch_fixtures.py` (extend)
- Modify: `build_macos.py` — register the patcher (6 registration tuples, type `"file"`, one per source) + HIDDEN_IMPORTS `"applio_browse_ui"`

**Fields table (mode → file:line → field variable; all 13 names verified against `7c5849eb`):**

| # | mode | file | field var (def line) |
|---|------|------|----------------------|
| 1 | folder | `tabs/train/train.py:388` | `dataset_path` (gr.Dropdown, `allow_custom_value=True`) |
| 2 | pth | `tabs/train/train.py:725` | `g_pretrained_path` (gr.Dropdown, `allow_custom_value=True`) |
| 3 | pth | `tabs/train/train.py:734` | `d_pretrained_path` (gr.Dropdown, `allow_custom_value=True`) |
| 4 | file | `tabs/inference/inference.py:578` | `output_path` |
| 5 | folder | `tabs/inference/inference.py:1213` | `input_folder_batch` |
| 6 | folder | `tabs/inference/inference.py:1220` | `output_folder_batch` |
| 7 | file | `tabs/tts/tts.py:146` | `input_tts_path` |
| 8 | file | `tabs/tts/tts.py:157` | `output_tts_path` |
| 9 | file | `tabs/tts/tts.py:163` | `output_rvc_path` |
| 10 | file | `tabs/realtime/realtime.py:1092` | `record_audio_path` |
| 11 | pth | `tabs/voice_blender/voice_blender.py:38` | `model_fusion_a` |
| 12 | pth | `tabs/voice_blender/voice_blender.py:49` | `model_fusion_b` |
| 13 | pth | `tabs/extra/sections/processing.py:15` | `model_view_model_path` |

  (The batch fields are `input_folder_batch` / `output_folder_batch` — NOT `input_folder`/`output_folder`; a wrong name means the anchor silently skips and the button never ships. The fixture test below asserts `inserted == len(fields)` so any name drift fails loudly.)

  Excluded by design: the two "Folder Name" embedder fields (`tabs/train/train.py:574`, `tabs/inference/inference.py:1148`) — their handler takes `os.path.basename`, so a picked full path would be silently truncated (anchor report §2); a Browse button there would mislead.

**Acceptance Criteria:**
- [ ] `browse_button(mode, target, elem_id=None)` creates `gr.Button(i18n("Browse…"), variant="secondary", size="sm", elem_id=elem_id)` and wires `.click(fn=_make_handler(mode), inputs=[target], outputs=[target])`, returning the button
- [ ] The handler: `("ok", path)` → returns `path`; `("cancel", None)` → `gr.Info("No path selected.")` + returns the current value; `("unavailable", None)` → `gr.Info("The native file picker is available only in the Applio app.")` + returns the current value
- [ ] The patcher inserts `_applio_browse_<var> = applio_browse_ui.browse_button("<mode>", <var>, elem_id="browse-<var>")` immediately AFTER the field's full definition statement (paren-balanced scan from the definition line), plus one module import `import applio_browse_ui` after the existing `i18n = I18nAuto()` line — per file, once
- [ ] Every patch function has its own `_APPLIO_BROWSE_<file>` marker check; exit 0 patched/already, 1 anchor miss; a field whose anchor is not found is SKIPPED with a printed warning (the other fields in that file still patch) — partial failure must not abort the file
- [ ] Fixture tests: pristine source → patched output contains the import + one factory line per field, each AFTER its definition's closing paren and BEFORE the next statement; synthetic content missing one field → that field skipped, others patched
- [ ] All 6 patched files `py_compile` after patching; sources restored pristine after testing; `"applio_browse_ui"` in HIDDEN_IMPORTS; 6 registration tuples added to `patches_to_apply`. `_find_statement_end` is paren-balanced but string/comment-blind — verified safe for all 13 current definitions (including `output_path`'s nested conditional at inference.py:578-590); after any upstream sync, re-run the Browse fixture test so a renamed field fails loudly instead of shipping 12/13 buttons
- [ ] `venv_macos/bin/python tests/test_browse_ui.py` passes; extended `tests/test_patch_fixtures.py` passes

**Verify:** `venv_macos/bin/python tests/test_browse_ui.py && venv_macos/bin/python tests/test_patch_fixtures.py && git checkout -- tabs && git status --short tabs` (empty) `&& grep -c patch_browse_buttons build_macos.py` → ≥ 6

**Steps:**

- [ ] **Step 1: Failing test** — `tests/test_browse_ui.py` (gradio is importable in venv without a server):

```python
"""Factory + handler behavior for applio_browse_ui (no AppKit; gradio only).
Run: venv_macos/bin/python tests/test_browse_ui.py"""

import gradio as gr

import applio_browse_ui


def test_handler_ok_returns_path():
    h = applio_browse_ui._make_handler("file")
    # Monkeypatch the picker to a canned result.
    applio_browse_ui._picker = lambda mode, prompt=None: ("ok", "/tmp/x.wav")
    assert h("/old") == "/tmp/x.wav"


def test_handler_expands_tilde():
    applio_browse_ui._picker = lambda mode, prompt=None: ("ok", "~/audios/out.wav")
    h = applio_browse_ui._make_handler("file")
    assert h("/old").startswith("/") and "~" not in h("/old")


def test_handler_cancel_keeps_current():
    applio_browse_ui._picker = lambda mode, prompt=None: ("cancel", None)
    h = applio_browse_ui._make_handler("folder")
    assert h("/keep/me") == "/keep/me"  # gr.Info fired as a side effect; value kept


def test_handler_unavailable_keeps_current():
    applio_browse_ui._picker = lambda mode, prompt=None: ("unavailable", None)
    h = applio_browse_ui._make_handler("pth")
    assert h("/keep") == "/keep"


def test_browse_button_creates_and_wires():
    applio_browse_ui._picker = lambda mode, prompt=None: ("cancel", None)
    with gr.Blocks():
        box = gr.Textbox(label="x")
        btn = applio_browse_ui.browse_button("file", box, elem_id="browse-test")
        assert isinstance(btn, gr.Button)
        assert btn.elem_id == "browse-test"  # falsible: the factory must pass it through


def run_all():
    test_handler_ok_returns_path()
    test_handler_expands_tilde()
    test_handler_cancel_keeps_current()
    test_handler_unavailable_keeps_current()
    test_browse_button_creates_and_wires()
    print("All browse UI tests passed (5).")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `applio_browse_ui.py`:

```python
"""One-call Browse buttons for Applio's path fields (a11y Phase 2).

Injected into upstream tab files at build time by patches/patch_browse_buttons.py:
    _applio_browse_output_path = applio_browse_ui.browse_button(
        "file", output_path, elem_id="browse-output_path")
The click handler runs the native NSOpenPanel (applio_native_picker) and
writes the chosen path into the target component. Cancel keeps the current
value; picker-unavailable (plain browser mode) explains itself via gr.Info,
which is the announced toast channel.
"""

import logging


def _default_picker(mode, prompt=None):
    from applio_native_picker import native_browse

    return native_browse(mode, prompt=prompt)


# Indirection seam for tests (gradio has no AppKit loop under pytest-style runs).
_picker = _default_picker


def _make_handler(mode):
    def _browse(current_value):
        import os

        try:
            status, path = _picker(mode)
        except Exception:
            logging.exception("[Browse] picker failed")
            status, path = "cancel", None
        if status == "ok":
            return os.path.expanduser(path)
        import gradio as gr

        if status == "unavailable":
            gr.Info("The native file picker is available only in the Applio app.")
        else:
            gr.Info("No path selected.")
        # Normalize a typed value that passes through this handler, so
        # "~/audio" typed next to a Browse button becomes usable too.
        return os.path.expanduser(current_value) if current_value else current_value

    return _browse


def browse_button(mode, target, elem_id=None):
    import gradio as gr

    try:
        from assets.i18n.i18n import I18nAuto

        label = I18nAuto()("Browse…")
    except Exception:
        # I18nAuto opens assets/config.json unconditionally; on a fresh
        # checkout that file is gitignored-and-absent -> fall back to English.
        label = "Browse…"
    button = gr.Button(
        label,
        variant="secondary",
        size="sm",
        elem_id=elem_id or f"browse-{mode}",
    )
    button.click(fn=_make_handler(mode), inputs=[target], outputs=[target])
    return button
```

- [ ] **Step 4: Implement** `patches/patch_browse_buttons.py`. Structure: per-file patch fn + a shared insertion core.

```python
"""Build-time patcher: insert a11y Browse buttons after each path field.
Run standalone: venv_macos/bin/python patches/patch_browse_buttons.py tabs/train/train.py
Exit codes: 0 patched/already, 1 anchor miss."""

import re
import sys

# (file, marker tag) -> [(field_var, mode), ...]
FIELDS = {
    "tabs/train/train.py": [
        ("dataset_path", "folder"),
        ("g_pretrained_path", "pth"),
        ("d_pretrained_path", "pth"),
    ],
    "tabs/inference/inference.py": [
        ("output_path", "file"),
        ("input_folder_batch", "folder"),
        ("output_folder_batch", "folder"),
    ],
    "tabs/tts/tts.py": [
        ("input_tts_path", "file"),
        ("output_tts_path", "file"),
        ("output_rvc_path", "file"),
    ],
    "tabs/realtime/realtime.py": [
        ("record_audio_path", "file"),
    ],
    "tabs/voice_blender/voice_blender.py": [
        ("model_fusion_a", "pth"),
        ("model_fusion_b", "pth"),
    ],
    "tabs/extra/sections/processing.py": [
        ("model_view_model_path", "pth"),
    ],
}

IMPORT_LINE = "import applio_browse_ui  # _APPLIO_BROWSE_IMPORT_"
I18N_ANCHOR = re.compile(r"^(i18n = I18nAuto\(\))\s*$", re.MULTILINE)


def _find_statement_end(content, start_idx):
    """Index just past the balanced-paren statement starting at/after start_idx."""
    depth = 0
    seen_open = False
    i = start_idx
    while i < len(content):
        ch = content[i]
        if ch == "(":
            depth += 1
            seen_open = True
        elif ch == ")":
            depth -= 1
            if seen_open and depth == 0:
                # swallow a trailing newline
                j = i + 1
                if j < len(content) and content[j] == "\n":
                    j += 1
                return j
        i += 1
    return -1


def patch_file(content, fields, marker):
    if marker in content:
        return content, "already"
    if not I18N_ANCHOR.search(content):
        print(f"Pattern not found: i18n = I18nAuto() - {marker}")
        return content, "miss"
    patched = I18N_ANCHOR.sub(r"\1\n" + IMPORT_LINE, content, count=1)
    inserted = skipped = 0
    for var, mode in fields:
        m = re.search(rf"^(?P<indent>[ \t]*){re.escape(var)} = gr\.(?:Textbox|Dropdown)\(", patched, re.MULTILINE)
        if not m:
            print(f"Pattern not found: {var} definition - skipped")
            skipped += 1
            continue
        # m.end()-1 points at the "(" the regex matched; balance from there.
        end = _find_statement_end(patched, m.end() - 1)
        if end == -1:
            print(f"Unbalanced statement: {var} - skipped")
            skipped += 1
            continue
        indent = m.group("indent")
        line = (
            f"\n{indent}_applio_browse_{var} = applio_browse_ui.browse_button("
            f'"{mode}", {var}, elem_id="browse-{var}")\n'
        )
        patched = patched[:end] + line + patched[end:]
        inserted += 1
    if inserted == 0:
        print(f"No fields patched - {marker}")
        return content, "miss"
    patched += f"\n# {marker}\n"
    print(f"Browsed {inserted} field(s), skipped {skipped}")
    return patched, "patched"
```

  Then one thin wrapper per file (`patch_train`, `patch_inference`, `patch_tts`, `patch_realtime`, `patch_voice_blender`, `patch_processing`) following the repo's existing patcher style (read file at `sys.argv[1]`, call `patch_file`, write back, exit code), each with its own marker `_APPLIO_BROWSE_<STEM>` (the marker rides as a trailing comment line — strip-safe because `patch_file` checks `marker in content`). VERIFY each field var name against the actual source before finalizing FIELDS (the anchor pass flagged 5 as "verify": the two pretrained dropdowns, batch folders, tts outputs, record path, model-view path).

  **Registration** in `build_macos.py` `patches_to_apply` (six tuples, after the `patch_stop_feedback` entries):

```python
        (
            "patches/patch_browse_buttons.py",
            "tabs/train/train.py",
            "train.py - a11y Browse buttons",
            "file",
        ),
        # ... identical tuples for inference.py, tts.py, realtime.py,
        # voice_blender.py, extra/sections/processing.py
```

  The per-file wrappers dispatch on `sys.argv[0]`-independent explicit fn — simplest: the standalone `__main__` block takes the target path as argv[1] and looks up FIELDS by repo-relative path (normalize with `os.path.relpath`).

- [ ] **Step 5: Extend** `tests/test_patch_fixtures.py` with a Browse-fixture test: for EACH of the six files, run `patch_file` over the PRISTINE source and assert `inserted == len(fields)` for that file (NO skips — a skipped field means a variable name drifted and a button silently never ships; the test prints the patcher's skip warnings on failure), plus `import applio_browse_ui` appears after `i18n = I18nAuto()`, each `_applio_browse_<var>` line lands after its definition's closing paren, and the patched output `py_compile`s (temp file). Also assert the guard: `"_APPLIO_BROWSE_" not in src` before patching (dirty-tree protection). One synthetic negative case: content missing one field definition → that field skipped, status still "patched", the OTHER fields inserted. **Register the new test fn in `run_all()` and bump its printed count — this file is script-style; a test not added to `run_all()` never executes (the same applies to every later task that extends this file: Tasks 7 and 8).**

- [ ] **Step 6: Run everything; restore sources; commit**

```bash
venv_macos/bin/python tests/test_browse_ui.py && venv_macos/bin/python tests/test_patch_fixtures.py
git checkout -- tabs
git add applio_browse_ui.py patches/patch_browse_buttons.py tests/test_browse_ui.py tests/test_patch_fixtures.py build_macos.py
git commit -m "feat(a11y): Browse buttons with native picker on all 13 path fields"
```

---

### Task 6: `applio_progress_api.py` — progress payload, settings echo, nav-token hook

**Goal:** An AppKit-free module (uvicorn-thread-safe) that builds the `/applio-a11y/progress` JSON payload from the same sources the launcher's dashboard uses: live subprocess jobs, the synthesized in-app batch, inference stats, and training-log metrics via `process_log_parser`. It also carries the a11y settings echo (so the web payload respects verbosity), the announce-owner flag (no double announcements), and the nav-token → LayoutChanged hook (Task 9/launcher wire-up).

**Files:**
- Create: `applio_progress_api.py`
- Test: `tests/test_progress_api.py`
- Modify: `build_macos.py` (HIDDEN_IMPORTS: `"applio_progress_api"`, `"rvc.lib.tools.process_log_parser"`)

**Acceptance Criteria:**
- [ ] `build_progress_payload(jobs, settings, announce_owner, now, words=None)` is PURE (dict in → JSON-serializable dict out; no IO) and returns `{"now": …, "announce": {"owner": …}, "settings": {"verbosity": …, "sound": …}, "words": {word_key: terminal_status}, "jobs": […]}` where each job dict is `{"key", "type", "name", "status", "word_key"}` + optional `"phase"`, `"pct"`, `"detail"`, `"eta"`, `"epoch": [cur, total]`, `"best_loss"`. The `words` map (history-derived terminal statuses, `f"{etype}:{name}" -> status`, built exactly like the launcher's `_a11y_terminal_words` at applio_launcher.py:5353-5374) is REQUIRED: live-job sources only ever report `status == "running"` (`get_active_processes` filters on it; `_synthesize_inference_proc` returns None on terminal), so without `words` the web side can never say "failed" — a failed training run would announce "finished"
- [ ] `enrich_jobs(jobs, now)` (also pure) computes `pct`/`eta`/`speed` for inference jobs via `applio_inference_stats.compute_inference_stats`, and for training jobs parses the log tail (supplied per-job as `"log_tail": "<text>"` by the IO layer) via `process_log_parser.parse_training_status_line` + `parse_epoch_progress` + `detect_phase_name` (sets `phase`, e.g. "Preprocessing"/"Training")
- [ ] The IO layer `_collect_jobs()` resolves the launcher module via `sys.modules.get("applio_launcher")` **with a `__main__` fallback** — the launcher runs as `__main__` in BOTH the frozen app (PyInstaller entry) and dev (`venv_macos/bin/python applio_launcher.py`), so the name lookup ALWAYS misses in production:

```python
    launcher = sys.modules.get("applio_launcher")
    if launcher is None:
        main = sys.modules.get("__main__")
        if main is not None and hasattr(main, "get_active_processes"):
            launcher = main
    if launcher is None:
        return []
```

- [ ] Tracked subprocess procs carry the log path under **`log_file`** (set by `patch_process_tracking.py:308`'s `_track_process("training", …, log_file=_log_file_path)`; `log_path` exists only on history entries) — read `proc.get("log_file") or proc.get("log_path")`, matching the launcher's own reads at applio_launcher.py:3285/3464/3681/3742
- [ ] The training-log tail is read by SEEK (last 256 KB), never whole-file `readlines()` — training logs grow to multi-MB over a run and the route polls every 2 s
- [ ] `set_settings(settings_dict)` / `set_announce_owner(owner)` / `set_layout_changed_callback(cb)` module-level setters; `handle_progress(nav=None, client=None, now=None)` returns the payload (injectable `now` for tests). Nav handling: when `nav` differs from the last-seen token (and ≥`NAV_FIRE_MIN_INTERVAL_S` since the last fire), invokes the layout callback. Per-request owner: `client == "native"` (the JS sends this when `window.pywebview` exists) and the module owner is "native" → announce owner "native"; anything else → "web" (an external browser pointing at the port gets web announcements even while the app runs)
- [ ] Failure fallback: on ANY exception, return the CACHED last-good payload if one exists (a transient error must not flip owner to "web" and burst "finished" announcements for every seen job); if no cache exists, return the empty payload with owner "web"
- [ ] `register_routes(app)` attaches `GET /applio-a11y/progress` as an async def that OFFLOADS `handle_progress` via `starlette.concurrency.run_in_threadpool` (the function does blocking file IO — running it on the event loop would stall every Gradio request) and reads `request.query_params.get("nav")` + `request.query_params.get("client")`; called by Task 7's patched `app.py`
- [ ] `venv_macos/bin/python tests/test_progress_api.py` passes (including the nav test with injectable `now`, and a test that a `log_file`-keyed training entry gets `epoch`/`best_loss`)

**Verify:** `venv_macos/bin/python tests/test_progress_api.py`

**Steps:**

- [ ] **Step 1: Failing tests** — `tests/test_progress_api.py`:

```python
"""Pure-payload tests for applio_progress_api (no AppKit, no launcher import).
Run: venv_macos/bin/python tests/test_progress_api.py"""

import applio_progress_api as api


def _training_job():
    return {
        "key": "training:voice:123",
        "type": "training",
        "name": "voice",
        "status": "running",
        "word_key": "training:voice",
        "log_tail": (
            "Starting Preprocess\n"
            "2026-08-21 15:00:00 | epoch=34 | step=21000 | time=00:12:34 | "
            "training_speed=0:34:56 | lowest_value=0.123 (epoch 30 and step 19000)\n"
            "Epoch: 34/200\n"
        ),
    }


def test_inference_stats_enrichment():
    jobs = [
        {
            "key": "inference:batch:app",
            "type": "inference",
            "name": "batch",
            "status": "running",
            "word_key": "inference:batch",
            "total": 10,
            "processed": 5,
            "converted": 5,
            "started_at": 100.0,
        }
    ]
    enriched = api.enrich_jobs(jobs, now=200.0)
    j = enriched[0]
    assert j["pct"] == 50.0
    assert j["detail"] == "5 of 10"
    assert "eta" in j and j["eta"] >= 0


def test_training_metrics_enrichment():
    enriched = api.enrich_jobs([_training_job()], now=1.0)
    j = enriched[0]
    assert j["epoch"] == [34, 200]
    assert j["best_loss"] == 0.123
    assert j["phase"] == "Preprocessing"  # detect_phase_name over the tail


def test_payload_shape_and_settings_echo():
    payload = api.build_progress_payload(
        jobs=[_training_job()], settings={"verbosity": "verbose", "sound": True},
        announce_owner="native", now=123.5, words={"training:voice": "failed"},
    )
    assert payload["now"] == 123.5
    assert payload["announce"] == {"owner": "native"}
    assert payload["settings"] == {"verbosity": "verbose", "sound": True}
    assert payload["words"] == {"training:voice": "failed"}
    assert payload["jobs"][0]["key"] == "training:voice:123"
    assert "log_tail" not in payload["jobs"][0]  # never leaked to the wire


def test_nav_token_fires_callback_once():
    fired = []
    api.set_layout_changed_callback(lambda: fired.append(1))
    api._state["last_nav"] = None
    api._state["last_nav_fire"] = 0.0
    api.handle_progress(nav="tab-a", now=1000.0)
    assert len(fired) == 1
    api.handle_progress(nav="tab-a", now=1001.0)  # same token: no re-fire
    assert len(fired) == 1
    api.handle_progress(nav="tab-b", now=1002.0)  # within debounce window...
    assert len(fired) == 1  # ...so still throttled
    api.handle_progress(nav="tab-c", now=1000.0 + api.NAV_FIRE_MIN_INTERVAL_S)
    assert len(fired) == 2


def test_owner_per_request():
    api.set_announce_owner("native")
    assert api.handle_progress(client="native", now=1.0)["announce"]["owner"] == "native"
    # external browser (no client flag) hears web announcements
    assert api.handle_progress(client=None, now=1.0)["announce"]["owner"] == "web"


def test_log_tail_read_by_seek():
    import os
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as tf:
        for i in range(3000):
            tf.write(f"line {i}\n")
        path = tf.name
    tail = api.read_log_tail(path, max_bytes=4096)
    assert "line 2999" in tail and "line 0\n" not in tail
    assert len(tail.splitlines()) < 3000
    os.unlink(path)


def test_handle_progress_never_raises():
    api.set_layout_changed_callback(None)
    payload = api.handle_progress(nav=None, now=1.0)
    assert "jobs" in payload and "settings" in payload


def run_all():
    test_inference_stats_enrichment()
    test_training_metrics_enrichment()
    test_payload_shape_and_settings_echo()
    test_nav_token_fires_callback_once()
    test_owner_per_request()
    test_log_tail_read_by_seek()
    test_handle_progress_never_raises()
    print("All progress API tests passed (7).")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `applio_progress_api.py`:

```python
"""Fork-owned a11y progress API: GET /applio-a11y/progress.

Serves the web-UI payload (live jobs + metrics + terminal words + a11y
settings echo) from the same in-process sources the native dashboard uses.
AppKit-free: the launcher pushes settings/owner/callback; this module never
imports AppKit or the launcher by name. The launcher runs as __main__ (frozen
entry AND dev script), so module resolution goes through sys.modules with a
__main__ fallback — a plain get("applio_launcher") ALWAYS misses in the app.
"""

import logging
import os
import sys
import threading
import time

NAV_FIRE_MIN_INTERVAL_S = 5.0
LOG_TAIL_MAX_BYTES = 262144

_lock = threading.Lock()
_state = {
    "settings": {"verbosity": "standard", "sound": False},
    "announce_owner": "web",
    "layout_cb": None,
    "last_nav": None,
    "last_nav_fire": 0.0,
}
_last_good_payload = None


def read_log_tail(path, max_bytes=LOG_TAIL_MAX_BYTES):
    """Seek-based tail read — training logs grow to multi-MB and this runs
    every poll; never slurp the whole file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            return fh.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def set_settings(settings):
    with _lock:
        _state["settings"] = dict(settings)


def set_announce_owner(owner):
    with _lock:
        _state["announce_owner"] = owner


def set_layout_changed_callback(cb):
    with _lock:
        _state["layout_cb"] = cb


def enrich_jobs(jobs, now):
    out = []
    for job in jobs:
        job = dict(job)
        if job.get("type") == "inference":
            record = {
                "total": job.get("total") or 0,
                "processed": job.get("processed") or 0,
                "converted": job.get("converted") or 0,
                "started_at": job.get("started_at"),
                "ended_at": job.get("ended_at"),
            }
            try:
                from applio_inference_stats import compute_inference_stats

                stats = compute_inference_stats(record, now)
            except Exception:
                stats = {}
            if record["total"]:
                job["pct"] = stats.get("pct", 0.0)
                job["detail"] = f"{record['processed']} of {record['total']}"
                job["eta"] = stats.get("eta", 0.0)
        elif job.get("type") == "training" and job.get("log_tail"):
            try:
                from rvc.lib.tools.process_log_parser import (
                    detect_phase_name,
                    parse_epoch_progress,
                    parse_training_status_line,
                )

                epoch = best = phase = None
                for line in reversed(job["log_tail"].splitlines()):
                    if epoch is None:
                        epoch = parse_epoch_progress(line)
                    if best is None:
                        parsed = parse_training_status_line(line)
                        if parsed:
                            best = parsed
                    if phase is None:
                        phase = detect_phase_name(line)
                    if epoch and best and phase:
                        break
                if phase:
                    job["phase"] = phase
                if epoch:
                    job["epoch"] = [epoch["current"], epoch["total"]]
                    if epoch["total"]:
                        job["pct"] = round(epoch["current"] / epoch["total"] * 100, 1)
                if best:
                    if best.get("best_loss") is not None:
                        job["best_loss"] = best["best_loss"]
                    job["detail"] = (
                        f"epoch {best.get('epoch', '?')} step {best.get('step', '?')}"
                    )
            except Exception:
                logging.debug("[ProgressAPI] training parse failed", exc_info=True)
        out.append(job)
    return out


def build_progress_payload(jobs, settings, announce_owner, now, words=None):
    return {
        "now": now,
        "announce": {"owner": announce_owner},
        "settings": dict(settings),
        "words": dict(words or {}),
        "jobs": [
            {k: v for k, v in job.items() if k != "log_tail"} for job in jobs
        ],
    }


def _resolve_launcher():
    launcher = sys.modules.get("applio_launcher")
    if launcher is None:
        main = sys.modules.get("__main__")
        if main is not None and hasattr(main, "get_active_processes"):
            launcher = main
    return launcher


def _collect_words(launcher):
    """History-derived terminal words: f"{etype}:{name}" -> status (mirrors
    applio_launcher._a11y_terminal_words). Live sources only ever report
    'running', so these words are the ONLY way the web side learns 'failed'."""
    words = {}
    try:
        for entry in launcher.get_recent_processes(20):
            etype = entry.get("type") or "process"
            name = entry.get("model_name") or "job"
            words.setdefault(f"{etype}:{name}", entry.get("status") or "completed")
    except Exception:
        logging.debug("[ProgressAPI] history read failed", exc_info=True)
    return words


def _collect_jobs():
    launcher = _resolve_launcher()
    if launcher is None:
        return []
    jobs = []
    try:
        for proc in launcher.get_active_processes():
            name = proc.get("model_name") or "job"
            ptype = proc.get("type") or "process"
            entry = {
                "key": f"{ptype}:{name}:{proc.get('pid') or 'x'}",
                "type": ptype,
                "name": name,
                "status": proc.get("status", "running"),
                "word_key": f"{ptype}:{name}",
            }
            # Tracked subprocesses store 'log_file' (patch_process_tracking
            # passes log_file=...); 'log_path' exists only on history entries.
            log_path = proc.get("log_file") or proc.get("log_path")
            if ptype == "training" and log_path and os.path.exists(log_path):
                tail = read_log_tail(log_path)
                if tail:
                    entry["log_tail"] = tail
            jobs.append(entry)
    except Exception:
        logging.debug("[ProgressAPI] active-process read failed", exc_info=True)
    try:
        infer = launcher._synthesize_inference_proc()
        if infer:
            name = infer.get("model_name") or "batch"
            jobs.append(
                {
                    "key": f"inference:{name}:app",
                    "type": "inference",
                    "name": name,
                    "status": infer.get("status", "running"),
                    "word_key": f"inference:{name}",
                    "total": infer.get("total"),
                    "processed": infer.get("processed"),
                    "converted": infer.get("converted"),
                    "started_at": infer.get("started_at"),
                    "current_file": infer.get("current_file"),
                }
            )
    except Exception:
        logging.debug("[ProgressAPI] inference synthesis failed", exc_info=True)
    return jobs


def handle_progress(nav=None, client=None, now=None):
    global _last_good_payload
    now = time.time() if now is None else now
    try:
        with _lock:
            settings = dict(_state["settings"])
            owner_state = _state["announce_owner"]
            cb = _state["layout_cb"]
            last_nav = _state["last_nav"]
            last_fire = _state["last_nav_fire"]
            fire = bool(
                cb
                and nav
                and nav != last_nav
                and (now - last_fire) >= NAV_FIRE_MIN_INTERVAL_S
            )
            if fire:
                _state["last_nav"] = nav
                _state["last_nav_fire"] = now
        if fire and cb:
            try:
                cb()
            except Exception:
                logging.debug("[ProgressAPI] layout callback failed", exc_info=True)
        # Per-request owner: only the in-app WKWebView client (client=native,
        # sent when window.pywebview exists) is silenced by the native engine;
        # an external browser at the same port still gets web announcements.
        owner = "native" if (owner_state == "native" and client == "native") else "web"
        launcher = _resolve_launcher()
        jobs = enrich_jobs(_collect_jobs(), now)
        words = _collect_words(launcher) if launcher else {}
        payload = build_progress_payload(jobs, settings, owner, now, words)
        _last_good_payload = payload
        return payload
    except Exception:
        logging.exception("[ProgressAPI] handle_progress failed")
        if _last_good_payload is not None:
            return _last_good_payload  # transient error: keep owner/jobs stable
        return build_progress_payload(
            [], {"verbosity": "standard", "sound": False}, "web", now
        )


def register_routes(app):
    from fastapi import Request
    from starlette.concurrency import run_in_threadpool

    @app.get("/applio-a11y/progress")
    async def applio_a11y_progress(request: Request):
        # handle_progress does blocking file IO; keep it off the event loop.
        return await run_in_threadpool(
            handle_progress,
            nav=request.query_params.get("nav"),
            client=request.query_params.get("client"),
        )
```

- [ ] **Step 4: Run tests → 7 pass.** Add both HIDDEN_IMPORTS entries to `build_macos.py` (`"applio_progress_api"` next to `"applio_a11y"`; `"rvc.lib.tools.process_log_parser"` — REQUIRED for frozen: it currently ships as unimportable DATA only).

- [ ] **Step 5: Commit**

```bash
git add applio_progress_api.py tests/test_progress_api.py build_macos.py
git commit -m "feat(a11y): /applio-a11y/progress payload module (pure core + IO shell)"
```

---

### Task 7: `patches/patch_progress_routes.py` — app.py route registration + `prevent_thread_lock` flip

**Goal:** The build-time patcher that makes the Gradio app expose the progress route: flip `prevent_thread_lock=client_mode` → `prevent_thread_lock=True` so `launch()` RETURNS, register our routes on the returned FastAPI app, then keep the calling thread alive (normal mode) so `launch_gradio()` still never returns — preserving the wrapper supervisor contract. The TensorBoard proxy that follows in the file stays unreachable in normal mode (status quo — it is dead code today).

**Files:**
- Create: `patches/patch_progress_routes.py`
- Modify (build-time only): `app.py` (`launch_gradio` L219-242; the kwarg at L226; launch call end ≈L242)
- Modify: `build_macos.py` — register the patcher (type `"file"`, source `app.py`)
- Test: extend `tests/test_patch_fixtures.py`

**Acceptance Criteria:**
- [ ] Patched `app.py`: the `prevent_thread_lock=client_mode,` line becomes `prevent_thread_lock=True,  # _APPLIO_A11Y_ROUTES_`; immediately after the launch call's closing paren and BEFORE the `from rvc.lib.tools.launch_tensorboard import get_tb_url` import (L244-245), the block below is inserted
- [ ] The inserted block registers routes via `applio_progress_api.register_routes(app)` inside try/except, then — only when `not client_mode` — sleeps forever (`while True: time.sleep(5)`) so the function still never returns in the normal path
- [ ] Standalone run on pristine `app.py` → "patched"; second run → "already"; `venv_macos/bin/python -m py_compile app.py` passes on the patched output; restored pristine after
- [ ] Fixture test asserts: kwarg flipped, block present, block positioned BEFORE the tensorboard import, `while True` guarded by `if not client_mode:`
- [ ] Registered in `build_macos.py` `patches_to_apply` as `("patches/patch_progress_routes.py", "app.py", "app.py - a11y progress route", "file")`

**Verify:** `venv_macos/bin/python tests/test_patch_fixtures.py && venv_macos/bin/python patches/patch_progress_routes.py app.py && venv_macos/bin/python -m py_compile app.py && grep -c _APPLIO_A11Y_ROUTES_ app.py && git checkout -- app.py && git status --short app.py` (empty)

**Steps:**

- [ ] **Step 1: Fixture test** — add to `tests/test_patch_fixtures.py`:

```python
def test_progress_routes_patch():
    routes = _load("patch_progress_routes", "patches/patch_progress_routes.py")
    src = open(os.path.join(REPO, "app.py"), encoding="utf8").read()
    patched, status = routes.patch_app(src)
    assert status in ("patched", "already")
    assert "prevent_thread_lock=True,  # _APPLIO_A11Y_ROUTES_" in patched
    block = patched.find("applio_progress_api.register_routes(app)")
    tb = patched.find("from rvc.lib.tools.launch_tensorboard import get_tb_url")
    assert block != -1 and tb != -1 and block < tb
    keepalive = patched.find("while True:", block)
    guard = patched.find("if not client_mode:", block)
    assert guard != -1 and keepalive != -1 and guard < keepalive
```

  (`patch_app(content) -> (content, status)` is the patcher's pure fn — same shape as `patch_upload`.)

- [ ] **Step 2: Run** → fails (patcher missing).

- [ ] **Step 3: Implement** `patches/patch_progress_routes.py`:

```python
"""Build-time patcher: expose /applio-a11y/progress on the Gradio app.

Upstream app.py passes prevent_thread_lock=client_mode (False in the app), so
launch() blocks and never returns — everything after the launch call is dead
code in the normal path. We flip the kwarg, register our routes on the
returned FastAPI app, and keep the calling thread alive so launch_gradio()
STILL never returns (the wrapper's supervisor contract). The TensorBoard
proxy below the insertion point stays dead in normal mode — status quo.
Run standalone: venv_macos/bin/python patches/patch_progress_routes.py app.py
"""

import re
import sys

MARKER = "_APPLIO_A11Y_ROUTES_"

KWARG_ANCHOR = re.compile(r"prevent_thread_lock=client_mode,(?P<nl>\s*\n)")
TB_ANCHOR = "    from rvc.lib.tools.launch_tensorboard import get_tb_url"

INJECTED = '''    # {marker}
    try:
        import applio_progress_api

        applio_progress_api.register_routes(app)
    except Exception:
        pass
    if not client_mode:
        import time as _applio_time

        while True:  # keep this backend thread alive; launch() no longer blocks
            _applio_time.sleep(5)
'''


def patch_app(content):
    if MARKER in content:
        return content, "already"
    if not KWARG_ANCHOR.search(content):
        print("Pattern not found: prevent_thread_lock=client_mode")
        return content, "miss"
    content = KWARG_ANCHOR.sub(
        "prevent_thread_lock=True,  # " + MARKER + "\\g<nl>", content, count=1
    )
    idx = content.find(TB_ANCHOR)
    if idx == -1:
        print("Pattern not found: tensorboard import anchor")
        return content, "miss"
    block = INJECTED.format(marker=MARKER)
    content = content[:idx] + block + content[idx:]
    return content, "patched"


if __name__ == "__main__":
    path = sys.argv[1]
    with open(path, "r", encoding="utf8") as fh:
        src = fh.read()
    out, status = patch_app(src)
    if status in ("patched", "already"):
        with open(path, "w", encoding="utf8") as fh:
            fh.write(out)
        print(f"patch_app: {status}")
        sys.exit(0)
    print(f"patch_app: {status}")
    sys.exit(1)
```

  CAUTION — the injection sits between the launch call's closing `)` (≈L242) and the tensorboard import (L244-245). If upstream moves the tensorboard block, the patcher reports "miss" rather than injecting in the wrong place. If `client_mode`'s guard shape differs at execution time (read `app.py:55-59` — `client_mode = _args.client`), keep the injected `if not client_mode:` exactly: in normal mode it must block; in client mode the existing mount + keep-alive at L285-288 takes over.

- [ ] **Step 4: Register** the 4-tuple in `build_macos.py` `patches_to_apply`; run the standalone patcher against `app.py`, `py_compile`, grep the marker, then `git checkout -- app.py`.

- [ ] **Step 5: Run fixture tests; commit**

```bash
git add patches/patch_progress_routes.py tests/test_patch_fixtures.py build_macos.py
git commit -m "feat(a11y): app.py progress-route registration via prevent_thread_lock flip"
```

---

### Task 8: `assets/applio_a11y.js` + `patches/patch_web_a11y_payload.py` — the web payload

**Goal:** The fork-owned JavaScript payload injected via gradio's `js=` launch kwarg (runs on page load). It (1) creates a polite live region and a persistent "Last result" region; (2) heals gradio a11y gaps — accordion `aria-expanded`, `aria-pressed` on record toggles, `alt` on images from their block labels, `:focus-visible` outlines for checkboxes/radios; (3) restores focus when a Start/Stop button swap removes the focused element; (4) captures toast text into the Last-result region (the 10 s toast problem); (5) polls `/applio-a11y/progress` every 2 s and — only when `announce.owner === "web"` — announces job lifecycle (start/terminal, and ≥25 % milestones under verbose); (6) reports a nav token so the native side can re-post LayoutChanged after SPA navigation.

**Files:**
- Create: `assets/applio_a11y.js`
- Create: `patches/patch_web_a11y_payload.py`
- Modify (build-time only): `app.py` (the `js=` dict entry at L230-237)
- Modify: `build_macos.py` — register patcher (type `"file"`, source `app.py`)
- Test: extend `tests/test_patch_fixtures.py`

**Acceptance Criteria:**
- [ ] `assets/applio_a11y.js` is an IIFE with a re-init guard (`window.__APPLIO_A11Y__`), creates `#applio-a11y-live` (`role=status aria-live=polite aria-atomic=true`, `.sr-only` styling) and `#applio-a11y-last` (visible, `role=region aria-label="Last result"`, appended to the gradio root container — fallback `document.body`), injects the focus-visible CSS once, and survives gradio re-renders (regions are re-created if missing — checked on every poll tick)
- [ ] Live-region writes are change-only (never rewrite identical textContent — mirrors `loading.html`'s `announceStage` dedupe)
- [ ] **Output-textbox mutation announcements** (audit §5 [P] + webui-semantics-1, previously missing from this task): the debounced observer watches output textboxes; when a non-empty value is REPLACED by a different non-empty value and the box is not focused (user not typing), announce "Output changed: <first 120 chars>" through the live region (gated on `verbosity !== "off"`; deduped) and persist it to Last-result
- [ ] **Selectors verified against the installed gradio 6.20.0 bundle BEFORE finalizing** — bundle-grep evidence: `label-wrap`, `gradio-image`, `gradio-container`, `[data-testid="toast-body"]`, `tab-button` EXIST; `block-accordion`, `gradio-accordion`, `tab-nav` DO NOT (do not use them). Accordion healing targets the `label-wrap` button of each accordion block with the container selector pinned from a LIVE DOM inspection during implementation (`python app.py` + browser devtools), setting `aria-expanded` from the block's open state and updating on click (capture-phase, no `stopPropagation`). The nav token reads the selected tab from the REAL tab-nav markup (aria-selected/tab-button shape) — same live-DOM session
- [ ] `aria-pressed` on the realtime record Start/Stop toggle button (text-content based toggle detection); `alt` propagation: for each image block, if the `<img>` lacks `alt`, copy the block's label text
- [ ] Focus restore: on focusout/removal, if the focused element was a removed button (Start/Convert/Record swap pattern), move focus to the nearest focusable sibling or the live region — never leave focus on `body` silently
- [ ] Toast capture: MutationObserver on the toast container (gradio `[data-testid="toast-body"]`); each toast's text is written into `#applio-a11y-last` with a timestamp (gradio's own role=status already announces toasts — persist only, never re-announce)
- [ ] Polling: `fetch('/applio-a11y/progress?nav=<token>&client=<native|web>')` every 2000 ms; on failure backs off ×4 (8 s) and retries; `client=native` is sent exactly when `window.pywebview` exists (the in-app WKWebView) — that is what silences duplicate announcements in-app while an external browser at the same port still gets them; nav token = the selected gradio tab label (observed via the MutationObserver)
- [ ] Job announcements ONLY when `payload.announce.owner === "web"`: new key → "Started <type> <name>"; gone key (was running OR paused) → announced ONCE with the TERMINAL WORD from `payload.words[word_key]` (history-derived; without it a failed run says "finished"), then the key is DELETED from `seen` (never re-announced); terminal transitions of surviving keys likewise use the payload status. First poll after load PRIMES silently (documented trade-off: a job that ended while the page was closed is not announced — lesser evil vs re-announcing every running job on reload). `seen` bookkeeping (status/milestone updates) runs OUTSIDE the owner/verbosity gate so a later flip cannot burst stale announcements
- [ ] Verbose milestones: only the HIGHEST newly-crossed threshold announces per tick (a 0→60 jump says "50%", not "25% then 50%")
- [ ] Verbose gating: `payload.settings.verbosity` — "off" silences job announcements; "standard" = lifecycle only; "verbose" = + milestones
- [ ] The patcher: on pristine `app.py`, the `js=` entry becomes a call to an injected helper `_applio_a11y_js(client_mode)` defined before `launch_gradio`, which reads `assets/applio_a11y.js` (dev: `now_dir`-relative; frozen: `sys._MEIPASS` fallback — the asset ships via the existing `("assets","assets")` datas) and concatenates the realtime `main.js` ONLY when `client_mode`; returns `None` when neither file exists. Marker `_APPLIO_A11Y_JS_`; "miss" if the js= entry anchor is not found
- [ ] `node --check assets/applio_a11y.js` passes (syntax gate, no runtime test infra); fixture test: pristine app.py → patched contains the helper + the `js=` call; patched output `py_compile`s; restored after
- [ ] Registered in `build_macos.py` (`("patches/patch_web_a11y_payload.py", "app.py", "app.py - inject a11y web payload", "file")`)

**Verify:** `node --check assets/applio_a11y.js && venv_macos/bin/python tests/test_patch_fixtures.py && venv_macos/bin/python patches/patch_web_a11y_payload.py app.py && venv_macos/bin/python -m py_compile app.py && git checkout -- app.py && git status --short app.py` (empty)

**Steps:**

- [ ] **Step 1: Write `assets/applio_a11y.js`** — complete payload:

```javascript
/* Applio a11y web payload (fork-owned; injected via gradio js= on load).
   Regions are created up-front (live regions must exist before updates),
   writes are change-only, and job announcements run only for clients the
   native engine does NOT already cover (announce.owner === "web": external
   browsers; the in-app WKWebView sends client=native and is silenced). */
(function () {
  "use strict";
  if (window.__APPLIO_A11Y__) { return; }
  window.__APPLIO_A11Y__ = true;

  var POLL_MS = 2000, BACKOFF_MS = 8000;
  var MILESTONES = [25, 50, 75, 100];
  /* Mirrors applio_a11y.TERMINAL_STATUSES — a status NOT in this list (e.g.
     a batch showing "cancelling" while Stop takes effect) must never be
     announced as a terminal word. */
  var TERMINAL = ["completed", "failed", "error", "cancelled", "canceled", "interrupted"];
  var verbosityNow = "standard";  // latest payload setting; gates output-change announces
  var lastLive = "", lastNav = null, pollFailures = 0;
  var seen = {};      // job key -> {status, ms}
  var primed = false;
  var lastOutputText = {};  // textbox elem_id/text -> last announced value

  /* SELECTORS: label-wrap, gradio-image, gradio-container,
     [data-testid="toast-body"] verified present in the gradio 6.20.0
     bundle; ACCORDION_CONTAINER and TAB_NAV SELECTOR must be pinned from a
     live DOM session (python app.py + devtools) before shipping — the
     bundle does NOT contain block-accordion/gradio-accordion/tab-nav. */
  var ACCORDION_BLOCK = "ACCORDION_CONTAINER_SELECTOR";  // pin from live DOM
  var ACCORDION_BUTTON = "button.label-wrap, .label-wrap button";
  var TAB_SELECTED = "TAB_NAV_SELECTED_SELECTOR";        // pin from live DOM

  function ensureRegions() {
    var root = document.querySelector(".gradio-container") || document.body;
    var live = document.getElementById("applio-a11y-live");
    if (!live) {
      live = document.createElement("div");
      live.id = "applio-a11y-live";
      live.className = "sr-only";
      live.setAttribute("role", "status");
      live.setAttribute("aria-live", "polite");
      live.setAttribute("aria-atomic", "true");
      root.appendChild(live);
      // fresh region: allow the next announce even if identical to the last
      // text written into the (now-removed) previous region
      lastLive = "";
      var style = document.createElement("style");
      style.id = "applio-a11y-style";
      style.textContent =
        "#applio-a11y-live.sr-only{position:absolute;width:1px;height:1px;" +
        "overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;}" +
        "#applio-a11y-last{margin:8px 16px;padding:8px 12px;font-size:0.95em;" +
        "border:1px solid rgba(128,128,128,0.4);border-radius:8px;}" +
        "input[type=checkbox]:focus-visible,input[type=radio]:focus-visible{" +
        "outline:2px solid #4c9ffe;outline-offset:2px;}";
      document.head.appendChild(style);
    }
    var last = document.getElementById("applio-a11y-last");
    if (!last) {
      last = document.createElement("div");
      last.id = "applio-a11y-last";
      last.setAttribute("role", "region");
      last.setAttribute("aria-label", "Last result");
      last.textContent = "";
      root.appendChild(last);
    }
    return { live: live, last: last };
  }

  function announce(text) {
    var regions = ensureRegions();
    if (!text || text === lastLive) { return; }
    lastLive = text;
    regions.live.textContent = text;
  }

  function persistResult(text) {
    var regions = ensureRegions();
    var stamp = new Date().toLocaleTimeString();
    regions.last.textContent = stamp + " — " + text;
  }

  /* --- static healing ------------------------------------------------- */

  function healAccordions() {
    if (ACCORDION_BLOCK.indexOf("SELECTOR") !== -1) { return; } // unpinned: no-op
    document.querySelectorAll(ACCORDION_BLOCK).forEach(function (acc) {
      var btn = acc.querySelector(ACCORDION_BUTTON);
      if (!btn) { return; }
      var open = acc.classList.contains("open") || acc.hasAttribute("open");
      btn.setAttribute("aria-expanded", String(open));
    });
  }

  function healRecordToggles() {
    document.querySelectorAll("button").forEach(function (btn) {
      var t = (btn.textContent || "").trim().toLowerCase();
      if (t === "start" || t === "stop") {  // realtime record toggle ("Start"/"Stop")
        btn.setAttribute("aria-pressed", String(t === "stop"));
      }
    });
  }

  function healImageAlts() {
    document.querySelectorAll("gradio-image, .image-container").forEach(function (block) {
      var img = block.querySelector("img");
      if (!img || img.getAttribute("alt")) { return; }
      var label = block.querySelector("label span, .icon-button + span");
      if (label && label.textContent.trim()) {
        img.setAttribute("alt", label.textContent.trim());
      }
    });
  }

  /* --- output-textbox mutation announcements (audit webui-semantics-1) -- */

  function announceOutputChanges() {
    document.querySelectorAll('textarea').forEach(function (ta) {
      if (ta === document.activeElement) { return; }  // user typing
      var id = ta.id || ta.name || ta.getAttribute("data-testid") || "";
      if (!id) { return; }
      var value = ta.value || "";
      var prev = lastOutputText[id];
      lastOutputText[id] = value;
      if (!value || prev === undefined || prev === value || !prev) { return; }
      var short = value.length > 120 ? value.slice(0, 120) + "…" : value;
      if (verbosityNow !== "off") {  // AC: output-change announces respect verbosity
        announce("Output changed: " + short);
      }
      persistResult(short);
    });
  }

  /* --- focus restore --------------------------------------------------- */

  document.addEventListener("focusout", function (ev) {
    var el = ev.target;
    if (!el || !el.tagName || el.tagName !== "BUTTON") { return; }
    window.setTimeout(function () {
      if (document.contains(el)) { return; }           // still there: nothing to do
      var anchor = el.id ? document.getElementById(el.id) : null;
      var target = anchor;
      if (!target) {
        var regions = ensureRegions();
        target = regions.last;                         // predictable landing spot
        target.setAttribute("tabindex", "-1");
      }
      try { target.focus(); } catch (e) { /* detached mid-fix */ }
    }, 50);
  }, true);

  /* --- observers -------------------------------------------------------- */

  var healTimer = null;
  function scheduleHeal() {
    if (healTimer) { return; }
    healTimer = window.setTimeout(function () {
      healTimer = null;
      healAccordions(); healRecordToggles(); healImageAlts();
      announceOutputChanges(); readNav();
    }, 250);
  }

  function readNav() {
    if (TAB_SELECTED.indexOf("SELECTOR") !== -1) { return; }  // unpinned: no-op
    var sel = document.querySelector(TAB_SELECTED);
    if (sel) {
      var token = (sel.textContent || "").trim();
      if (token && token !== lastNav) { lastNav = token; }
    }
  }

  function observeToasts() {
    var obs = new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        Array.prototype.forEach.call(m.addedNodes || [], function (node) {
          if (!node.querySelectorAll) { return; }
          var bodies = node.querySelectorAll('[data-testid="toast-body"]');
          Array.prototype.forEach.call(bodies, function (b) {
            persistResult(b.textContent.trim());
          });
          if (node.matches && node.matches('[data-testid="toast-body"]')) {
            persistResult(node.textContent.trim());
          }
        });
      });
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  /* --- progress polling -------------------------------------------------- */

  function jobLabel(job) {
    return (job.type || "process") + " " + (job.name || "");
  }

  function handlePayload(payload) {
    var owner = payload && payload.announce && payload.announce.owner;
    var verbosity = (payload && payload.settings && payload.settings.verbosity) || "standard";
    verbosityNow = verbosity;
    var words = (payload && payload.words) || {};
    var jobs = (payload && payload.jobs) || [];
    var current = {};
    jobs.forEach(function (job) { current[job.key] = job; });

    if (!primed) {
      // First poll after load: adopt silently. Cost: a job that ENDED while
      // the page was closed is not announced. Lesser evil vs re-announcing
      // every running job as "Started" on every reload. info rides along so
      // a later disappearance still announces a labeled terminal.
      jobs.forEach(function (job) {
        seen[job.key] = { status: job.status, ms: -1, info: job };
      });
      primed = true;
      return;
    }

    // Bookkeeping runs OUTSIDE the gate so owner/verbosity flips can never
    // burst stale announcements later.
    var announcements = [];
    Object.keys(seen).forEach(function (key) {
      var prev = seen[key];
      if (!(key in current) && (prev.status === "running" || prev.status === "paused")) {
        var info = prev.info || {};
        var word = words[info.word_key] || "finished";
        announcements.push(["terminal", jobLabel(info) + " " + word]);
        delete seen[key];  // announce ONCE, then forget
      }
    });
    jobs.forEach(function (job) {
      var prev = seen[job.key];
      if (!prev) {
        announcements.push(["start", "Started " + jobLabel(job)]);
        seen[job.key] = { status: job.status, ms: -1, info: job };
      } else {
        if (prev.status === "running" && job.status !== "running" &&
            TERMINAL.indexOf(job.status) !== -1) {
          // only REAL terminal words (a "cancelling" status is not terminal —
          // the final word arrives via the disappearance branch or stays silent,
          // matching applio_a11y's LIVE/TERMINAL partition on the native side)
          announcements.push(["terminal", jobLabel(job) + " " + job.status]);
        }
        if (verbosity === "verbose" && typeof job.pct === "number" &&
            job.status === "running") {
          var highest = -1;
          MILESTONES.forEach(function (ms) {
            if (job.pct >= ms && prev.ms < ms && ms > highest) { highest = ms; }
          });
          if (highest > 0) {
            announcements.push(["milestone", jobLabel(job) + " " + highest + "%"]);
            prev.ms = highest;
          }
        }
        prev.status = job.status;
        prev.info = job;
      }
    });
    // Drop terminal keys that vanished earlier (already deleted above);
    // nothing else to clean.

    // Terminal results persist to the visible Last-result region for EVERY
    // client (visual, not spoken — no doubling with native announcements);
    // the spoken live-region announcements run only for web-owner clients.
    announcements.forEach(function (a) {
      if (a[0] === "terminal") { persistResult(a[1]); }
    });
    if (owner === "web" && verbosity !== "off") {
      announcements.forEach(function (a) { announce(a[1]); });
    }
  }

  function poll() {
    var qs = [];
    if (lastNav) { qs.push("nav=" + encodeURIComponent(lastNav)); }
    qs.push("client=" + (window.pywebview ? "native" : "web"));
    var url = "/applio-a11y/progress" + (qs.length ? "?" + qs.join("&") : "");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) { throw new Error(String(r.status)); } return r.json(); })
      .then(function (payload) { pollFailures = 0; handlePayload(payload); })
      .catch(function () { pollFailures += 1; })
      .finally(function () {
        ensureRegions();
        window.setTimeout(poll, pollFailures > 2 ? BACKOFF_MS : POLL_MS);
      });
  }

  /* --- boot ------------------------------------------------------------- */

  function boot() {
    ensureRegions();
    healAccordions(); healRecordToggles(); healImageAlts(); readNav();
    observeToasts();
    var mo = new MutationObserver(scheduleHeal);
    mo.observe(document.body, { childList: true, subtree: true });
    poll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
```

  IMPLEMENTER NOTE — MANDATORY live-DOM session before finalizing: bundle-grep evidence says `label-wrap`, `gradio-image`, `gradio-container`, `[data-testid="toast-body"]`, and `tab-button` exist in gradio 6.20.0, while `block-accordion`, `gradio-accordion`, and `tab-nav` DO NOT. The two placeholders `ACCORDION_BLOCK` and `TAB_SELECTED` are deliberately unpinned sentinel strings (`"…SELECTOR"`) — the healing/nav functions no-op until you run `python app.py`, open devtools, inspect the real accordion block container and the selected-tab element, and replace the sentinels with the verified selectors. A selector that silently matches nothing is the failure mode the sentinels prevent. This is the one place live verification beats fixture tests; spend the time.

- [ ] **Step 2: Syntax gate** — `node --check assets/applio_a11y.js` → clean.

- [ ] **Step 3: Fixture test** — add to `tests/test_patch_fixtures.py`:

```python
def test_web_payload_patch():
    payload = _load("patch_web_a11y_payload", "patches/patch_web_a11y_payload.py")
    src = open(os.path.join(REPO, "app.py"), encoding="utf8").read()
    patched, status = payload.patch_app(src)
    assert status in ("patched", "already")
    assert "def _applio_a11y_js(" in patched and "_APPLIO_A11Y_JS_" in patched
    assert '"js": _applio_a11y_js(client_mode),' in patched
```

- [ ] **Step 4: Implement** `patches/patch_web_a11y_payload.py`. The pure core replaces the `js=` entry (anchor: the exact upstream text from `app.py:230-237` — `"css": "footer{display:none !important}",` stays untouched):

```python
import re
import sys

MARKER = "_APPLIO_A11Y_JS_"

JS_ANCHOR = re.compile(
    r'"js": \(\n'
    r"(?P<body>(?:.*\n)*?)"
    r'(?P<close>\s*\),\n)'  # the entry's closing paren before the dict close
)

HELPER = '''def _applio_a11y_js(client_mode):  # {marker}
    """Fork (a11y): web payload JS + optional realtime client JS."""
    parts = []
    for cand in (
        os.path.join(now_dir, "assets", "applio_a11y.js"),
        os.path.join(getattr(sys, "_MEIPASS", now_dir), "assets", "applio_a11y.js"),
    ):
        try:
            if os.path.exists(cand):
                parts.append(pathlib.Path(cand).read_text(encoding="utf-8"))
                break
        except Exception:
            pass
    if client_mode:
        parts.append(
            pathlib.Path(os.path.join(now_dir, "tabs", "realtime", "main.js")).read_text()
        )
    return "\\n;\\n".join(parts) if parts else None


'''
```

  The patch: (1) insert `HELPER` immediately before `def launch_gradio(`; (2) replace the whole `"js": (…),` entry with `"js": _applio_a11y_js(client_mode),`. The regex above is the guide — MATCH THE ACTUAL UPSTREAM TEXT when implementing (read `app.py:226-242`; the entry spans to `),\n` before the `}` that closes the GRADIO_6 dict). `sys`/`os`/`pathlib` are already imported in app.py — VERIFY all three; if `sys` is missing, the helper uses `import sys` inside. Standalone `__main__` block: same shape as Task 7's.

- [ ] **Step 5: Register** the tuple in `build_macos.py`; standalone-run the patcher against `app.py`, `py_compile`, restore.

- [ ] **Step 6: Commit**

```bash
git add assets/applio_a11y.js patches/patch_web_a11y_payload.py tests/test_patch_fixtures.py build_macos.py
git commit -m "feat(a11y): web payload - live region, healing, focus restore, progress polling"
```

---

### Task 9: Accessibility settings submenu — verbosity + sound cues, persisted, consumed everywhere

**Goal:** A native Accessibility submenu (App menu → Accessibility) with checkable items: Announcements Off/Standard/Verbose (radio behavior) and Sound Cues (toggle), persisted in NSUserDefaults under namespaced `a11y.*` keys, consumed by the launcher's announcement gate + NSSound cues, and echoed to the web payload via `applio_progress_api.set_settings`. The four action items live in the menu SPEC (not built ad-hoc) so the existing dispatch machinery wires them — and so menu rebuilds after `webview.start` re-render them automatically.

**Files:**
- Modify: `menu_spec.py` (key sets L45-95, `DISPLAY_KEYS` L77, App-menu section L128-144)
- Modify: `applio_launcher.py` (`_build_launcher_dispatch` L5472-5505; `_build_native_menu` L5031-5060; `_a11y_heartbeat` L5376-5397; `_a11y_post` L5399-5414; `__init__` a11y state L4757-4760)
- Test: `tests/test_menu_spec.py` (13 existing tests — one formula test is AMENDED by this task)

**Acceptance Criteria:**
- [ ] `menu_spec.py`: `A11Y_CHILD_KEYS = {"a11y.verbosity.off", "a11y.verbosity.standard", "a11y.verbosity.verbose", "a11y.sound_cues"}`; `A11Y_KEYS = A11Y_CHILD_KEYS | {"a11y.menu"}`; `TAXONOMY |= A11Y_KEYS`; `LAUNCHER_ACTION_KEYS |= A11Y_CHILD_KEYS` (NOT the parent — it is display-only like `process.status`, so it joins `DISPLAY_KEYS`); `WRAPPER_ACTION_KEYS` explicitly subtracts `*A11Y_CHILD_KEYS` (the standalone wrapper has no announcement engine; without the explicit subtraction the derived set at menu_spec.py:87 would leak them in and fail the plan's own disjointness assertion)
- [ ] The App-menu submenu gains, after `Check for Updates…` and before the hide separator: `MenuItem(key="a11y.menu", title="Accessibility", submenu=[…])` with the four children as regular leaves — `MenuItem(key="a11y.verbosity.off", title="Announcements: Off")`, `…standard`, `…verbose`, `MenuItem(key="a11y.sound_cues", title="Sound Cues")`. Because the children are spec leaves with dispatch callables, `_fill_ns_menu` wires them through the EXISTING tagged mechanism on every build (rebuild-safe by construction — no ad-hoc tag counter, no `_dynamic_items` dependency; the review caught that an empty-spec `submenu=[]` item without a `dynamic` hint never reaches `_dynamic_items` and renders disabled-forever)
- [ ] The existing formula test in `tests/test_menu_spec.py` (`WRAPPER_ACTION_KEYS == LAUNCHER_ACTION_KEYS - injected - EDIT_KEYS`) is AMENDED to also subtract `*A11Y_CHILD_KEYS` — updating an existing test's expectation is called out here deliberately, not slipped in
- [ ] `applio_launcher.py`: `_build_launcher_dispatch` gains four zero-arg callables (`lambda: self._set_a11y_verbosity("off")` etc.); `_set_a11y_verbosity(value)` / `_toggle_a11y_sound()` write `NSUserDefaults` keys `"a11y.verbosity"` (string, default `"standard"`, validated to the three legal values) and `"a11y.sound_cues"` (bool, default False) + `synchronize()`, push `applio_progress_api.set_settings({"verbosity": …, "sound": …})` (lazy import, exception-guarded), then call `_refresh_a11y_submenu()`
- [ ] `_refresh_a11y_submenu()` sets radio state: `setState_(NSOnState)` on the current verbosity item, `NSOffState` on the other two; sound cues toggles its own state. It resolves items via the EXISTING `self._find_item_by_key(key)` (L5425, backed by `_key_to_tag` which every `_build_native_menu` pass repopulates) and is called (a) at the end of `_build_native_menu` — so states survive the pywebview menu re-wipe — and (b) after every toggle. No 2 s rebuild (states change only via this menu)
- [ ] Consumption: `_a11y_heartbeat` skips announcement processing entirely when `self._a11y_verbosity == "off"` — events are computed but neither the `[A11y]` log lines nor the posts fire (the badge still updates; the smoke test greps for absent log lines); `_a11y_post` also returns early under "off" as defense in depth. On `kind == "terminal"` with `self._a11y_sound_cues`, play `NSSound.soundNamed_("Basso" if bad else "Glass").play()` (try/except; reuse the `bad` word check already computed for `requestUserAttention_`)
- [ ] `venv_macos/bin/python tests/test_menu_spec.py` passes (13 existing incl. the amended formula + 2 new: submenu presence under `MENU[0].submenu` — NOT `MENU[0].submenu[0]`, which is the About leaf — and set disjointness `not (A11Y_KEYS & WRAPPER_ACTION_KEYS)` with all five keys in `TAXONOMY`)
- [ ] `venv_macos/bin/python -m py_compile applio_launcher.py menu_spec.py`

**Verify:** `venv_macos/bin/python tests/test_menu_spec.py && venv_macos/bin/python -m py_compile applio_launcher.py menu_spec.py`

**Steps:**

- [ ] **Step 1: Failing tests** — extend `tests/test_menu_spec.py`:

```python
def test_a11y_menu_present():
    import menu_spec

    app_menu_items = menu_spec.MENU[0].submenu  # the App menu's item list
    a11y = [mi for mi in app_menu_items if mi.key == "a11y.menu"]
    assert a11y and a11y[0].title == "Accessibility"
    child_keys = {mi.key for mi in a11y[0].submenu}
    assert child_keys == menu_spec.A11Y_CHILD_KEYS


def test_a11y_keys_sets():
    import menu_spec

    assert menu_spec.A11Y_KEYS <= menu_spec.TAXONOMY
    assert menu_spec.A11Y_CHILD_KEYS <= menu_spec.LAUNCHER_ACTION_KEYS
    assert not (menu_spec.A11Y_KEYS & menu_spec.WRAPPER_ACTION_KEYS)
    assert "a11y.menu" in menu_spec.DISPLAY_KEYS
```

  And amend the existing formula test: wherever it asserts `WRAPPER_ACTION_KEYS == LAUNCHER_ACTION_KEYS - injected - EDIT_KEYS`, subtract `*A11Y_CHILD_KEYS` as well.

- [ ] **Step 2: Run** → fail (no A11Y_KEYS).

- [ ] **Step 3: menu_spec.py** — after `EDIT_KEYS` (L66-73):

```python
A11Y_CHILD_KEYS = {
    "a11y.verbosity.off",
    "a11y.verbosity.standard",
    "a11y.verbosity.verbose",
    "a11y.sound_cues",
}
A11Y_KEYS = A11Y_CHILD_KEYS | {"a11y.menu"}
```

  `TAXONOMY` (L74) gains `| A11Y_KEYS`; `LAUNCHER_ACTION_KEYS` (L80-82) gains `| A11Y_CHILD_KEYS`; `DISPLAY_KEYS` (L77) becomes `{"process.status", "a11y.menu"}`; `WRAPPER_ACTION_KEYS` (L87-95) explicitly subtracts `*A11Y_CHILD_KEYS` in addition to its current exclusions. Insert into the App-menu submenu after `app.check_updates`:

```python
                    MenuItem(
                        key="a11y.menu",
                        title="Accessibility",
                        submenu=[
                            MenuItem(key="a11y.verbosity.off", title="Announcements: Off"),
                            MenuItem(
                                key="a11y.verbosity.standard",
                                title="Announcements: Standard",
                            ),
                            MenuItem(
                                key="a11y.verbosity.verbose",
                                title="Announcements: Verbose",
                            ),
                            MenuItem(key="a11y.sound_cues", title="Sound Cues"),
                        ],
                    ),
```

- [ ] **Step 4: applio_launcher.py** — in `__init__` (next to `self._a11y_primed` L4760). Guarded read: `__init__` must not gain an unguarded PyObjC import (the module keeps a NATIVE_APIS_AVAILABLE fallback path), so fall back to defaults when Foundation is unavailable:

```python
        self._a11y_verbosity = "standard"
        self._a11y_sound_cues = False
        try:
            from Foundation import NSUserDefaults

            defaults = NSUserDefaults.standardUserDefaults()
            verbosity = defaults.stringForKey_("a11y.verbosity") or "standard"
            if verbosity in ("off", "standard", "verbose"):
                self._a11y_verbosity = verbosity
            self._a11y_sound_cues = bool(defaults.boolForKey_("a11y.sound_cues"))
        except Exception:
            logging.debug("[A11y] settings read failed", exc_info=True)
        self._push_a11y_settings()
```

  New methods (place near the other `_a11y_*` methods at L5301+):

```python
    def _push_a11y_settings(self):
        try:
            import applio_progress_api

            applio_progress_api.set_settings(
                {"verbosity": self._a11y_verbosity, "sound": self._a11y_sound_cues}
            )
        except Exception:
            pass

    def _set_a11y_verbosity(self, value):
        from Foundation import NSUserDefaults

        self._a11y_verbosity = value
        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setObject_forKey_(value, "a11y.verbosity")
        defaults.synchronize()
        self._push_a11y_settings()
        self._refresh_a11y_submenu()

    def _toggle_a11y_sound(self):
        from Foundation import NSUserDefaults

        self._a11y_sound_cues = not self._a11y_sound_cues
        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setBool_forKey_(self._a11y_sound_cues, "a11y.sound_cues")
        defaults.synchronize()
        self._push_a11y_settings()
        self._refresh_a11y_submenu()

    def _refresh_a11y_submenu(self):
        import AppKit

        try:
            current_verbosity = {
                "off": "a11y.verbosity.off",
                "standard": "a11y.verbosity.standard",
                "verbose": "a11y.verbosity.verbose",
            }[self._a11y_verbosity]
            for key in (
                "a11y.verbosity.off",
                "a11y.verbosity.standard",
                "a11y.verbosity.verbose",
                "a11y.sound_cues",
            ):
                row = self._find_item_by_key(key)
                if not row:
                    continue
                if key.startswith("a11y.verbosity."):
                    row.setState_(
                        AppKit.NSOnState
                        if key == current_verbosity
                        else AppKit.NSOffState
                    )
                else:
                    row.setState_(
                        AppKit.NSOnState if self._a11y_sound_cues else AppKit.NSOffState
                    )
        except Exception:
            pass
```

  Wire the four actions in `_build_launcher_dispatch` (zero-arg callables, the established pattern):

```python
            "a11y.verbosity.off": lambda: self._set_a11y_verbosity("off"),
            "a11y.verbosity.standard": lambda: self._set_a11y_verbosity("standard"),
            "a11y.verbosity.verbose": lambda: self._set_a11y_verbosity("verbose"),
            "a11y.sound_cues": self._toggle_a11y_sound,
```

  Call `self._refresh_a11y_submenu()` at the END of `_build_native_menu` (after `_fill_ns_menu` populated `_key_to_tag`) — this is what makes the states survive the post-`webview.start` menu rebuild.

- [ ] **Step 5: Gate announcement processing** — `_a11y_heartbeat` (L5376-5397): keep the snapshot + badge computation; when `self._a11y_verbosity == "off"`, STILL call `self._a11y_policy.events(snap, terminal_words={})` every tick and DISCARD the result, skipping only the per-event `logging.info(f"[A11y] {kind}: {msg}")` + `AppHelper.callAfter(self._a11y_post, msg, kind)` loop. Calling events() is what keeps `_seen` current — if it is skipped entirely, flipping Announcements back on later announces "Started X" for every already-running job (the exact burst the bookkeeping-outside-the-gate rule exists to prevent on the web side; same invariant here). Passing `terminal_words={}` under "off" keeps the history-read lazy (the words only shape messages, which are discarded). In `_a11y_post`, add an early `if self._a11y_verbosity == "off": return` as defense in depth. Add the sound cue in the terminal branch:

```python
        if kind == "terminal":
            bad = any(w in msg for w in ("fail", "error", "cancel", "interrupt"))
            NSApp.requestUserAttention_(
                NSCriticalRequest if bad else NSInformationalRequest
            )
            if self._a11y_sound_cues:
                try:
                    from AppKit import NSSound

                    NSSound.soundNamed_("Basso" if bad else "Glass").play()
                except Exception:
                    pass
```

  (This restructures the existing block so `bad` is computed once and shared by attention + sound.)

- [ ] **Step 6: Register the layout callback** (completes routed refinement #5): in `__init__` after `_push_a11y_settings()`:

```python
        try:
            import applio_progress_api

            applio_progress_api.set_announce_owner("native")
            applio_progress_api.set_layout_changed_callback(
                lambda: AppHelper.callAfter(self._post_webview_layout_changed)
            )
        except Exception:
            pass
```

  New launcher method `_post_webview_layout_changed` (guarded; walks `NSApp.windows()` for the WKWebView contentView exactly as `_enable_webview_keyboard_access` does, and posts `NSAccessibilityLayoutChangedNotification` on it). Reuse/share the webview-finding helper with `_enable_webview_keyboard_access`.

- [ ] **Step 7: Run tests + py_compile; commit**

```bash
git add menu_spec.py applio_launcher.py tests/test_menu_spec.py
git commit -m "feat(a11y): Accessibility submenu - verbosity + sound cues, persisted, echoed to web"
```

---

### Task 10: `applio_i18n.py` — native-string i18n plumbing

**Goal:** A fork-owned, AppKit-free translation module that loads the app's existing locale (from `assets/config.json`, CWD/`_MEIPASS`-resolved) and translates fork-native user-facing strings with graceful English fallback. Wire it into: `applio_a11y` message templates + terminal status words, the quit-confirm / data-location / update-check / boot-timeout alerts, and menu titles at render time (both renderers).

**Files:**
- Create: `applio_i18n.py`
- Modify: `applio_a11y.py` (templates at L59-71), `applio_launcher.py` (alert clusters: quit confirm L4705-4715, data-location L5641-5693, menu render in `_fill_ns_menu` L4490/4507/4513-4514), `macos_wrapper.py` (boot-timeout alert L1525-1530, close-confirm L390-410, first-run L551-580/L1823-1827), `applio_update_check.py` (3 alerts)
- Modify: `build_macos.py` (HIDDEN_IMPORTS: `"applio_i18n"`)
- Optional (created only when a real translation exists): `assets/applio_i18n_overrides.json` — fork-owned overrides layered over the upstream locale map; ships via the existing `("assets","assets")` datas
- Test: `tests/test_applio_i18n.py`

**Acceptance Criteria:**
- [ ] `applio_i18n.native_tr(key)` — module-level callable; returns the translated string or the key itself when missing (never raises); singleton loader, lazy, thread-safe; locale resolution mirrors `assets/i18n/i18n.py:13-30`: `config.json` `lang.override`/`lang.selected_lang` else system locale prefix-match, else `en_US`; the language JSON is loaded from the first existing of `<now_dir>/assets/i18n/languages/`, `<sys._MEIPASS>/assets/i18n/languages/`
- [ ] **NO upstream i18n file is edited** — all 60 `assets/i18n/languages/*.json` are upstream-owned (`git ls-tree upstream/main`), and editing `en_US.json` would be both a policy violation and a behavioral no-op (the fallback already returns the English key). Instead `NativeI18n` layers an OPTIONAL fork-owned `assets/applio_i18n_overrides.json` (`{locale: {key: translation}}` — absent by default) over the loaded locale map: future real translations land there with zero upstream delta. A test covers the layering with a synthetic overrides file injected via `base_paths`
- [ ] Key scheme: natural English source strings as keys (repo convention), e.g. `"Started {label}"`, `"{label} paused"`, `"{label} resumed"`, `"{label} {status}"`, `"finished"`, `"completed"`, `"failed"`, `"Quit Applio?"`, `"Active Processes Running"`, `"Update Available"` — English needs no entries (the key IS the text)
- [ ] `applio_a11y.AnnouncementPolicy` accepts an optional translator at construction (`AnnouncementPolicy(translator=None)` → identity default); templates become `t("Started {label}").format(label=label)` etc.; terminal status words pass through `t(word)` (unknown words fall back to the raw word — screen-reader-critical no-op)
- [ ] The launcher passes `applio_i18n.native_tr` when constructing the policy (L4757-4759); the alert clusters wrap their message strings in `_t(...)`; `_fill_ns_menu` renders `title = _tr(mi.title)` (launcher renderer) and `macos_wrapper`'s standalone renderer does the same at its title-use sites (L1010/1015/1027/1031) — menu_spec itself stays untouched (titles remain English literals in the spec; translation happens at render)
- [ ] Boot/loading.html stage strings and dashboard status strings stay English this phase (documented follow-up; the loading screen has its own i18n path via the i18n config the wrapper already copies)
- [ ] `venv_macos/bin/python tests/test_applio_i18n.py` passes: fallback (missing key → key), override-locale selection, `_MEIPASS` fallback ordering (inject paths), template formatting through the translator, `AnnouncementPolicy(translator=...)` produces translated events, overrides layering
- [ ] `py_compile` all touched modules; `venv_macos/bin/python tests/test_applio_a11y.py` still passes (identity translator preserves existing expectations)

**Verify:** `venv_macos/bin/python tests/test_applio_i18n.py && venv_macos/bin/python tests/test_applio_a11y.py && venv_macos/bin/python -m py_compile applio_i18n.py applio_a11y.py applio_launcher.py macos_wrapper.py applio_update_check.py`

**Steps:**

- [ ] **Step 1: Failing tests** — `tests/test_applio_i18n.py`:

```python
"""Tests for applio_i18n (pure; injectable paths; no AppKit).
Run: venv_macos/bin/python tests/test_applio_i18n.py"""

import json
import os
import tempfile

import applio_i18n


def _make_tree(locale, extra_keys=None):
    tmp = tempfile.mkdtemp()
    lang_dir = os.path.join(tmp, "assets", "i18n", "languages")
    os.makedirs(lang_dir)
    data = {"Started {label}": "Cominciato {label}", "finished": "finito"}
    if extra_keys:
        data.update(extra_keys)
    with open(os.path.join(lang_dir, f"{locale}.json"), "w", encoding="utf8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    with open(os.path.join(tmp, "assets", "config.json"), "w", encoding="utf8") as fh:
        json.dump({"lang": {"override": True, "selected_lang": locale}}, fh)
    return tmp


def test_override_locale_and_format():
    tmp = _make_tree("xx_XX")
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("Started {label}").format(label="training: voice") == "Cominciato training: voice"
    assert tr("finished") == "finito"


def test_missing_key_falls_back_to_key():
    tmp = _make_tree("xx_XX")
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("Quit Applio?") == "Quit Applio?"


def test_missing_language_file_falls_back_english():
    tmp = _make_tree("xx_XX")
    tr = applio_i18n.NativeI18n(base_paths=[tmp], locale="zz_ZZ")
    assert tr("finished") == "finished"


def test_policy_translator():
    import applio_a11y

    tmp = _make_tree("xx_XX")
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    pol = applio_a11y.AnnouncementPolicy(translator=tr)
    events = pol.events({"t:a:1": {"type": "t", "name": "a", "status": "running"}})
    assert ("start", "Cominciato t: a") in events


def test_overrides_layer_over_locale_map():
    tmp = _make_tree("xx_XX", extra_keys={"finished": "finito (override)"})
    # Simulate the fork-owned overrides file on top of the locale tree.
    with open(
        os.path.join(tmp, "assets", "applio_i18n_overrides.json"), "w", encoding="utf8"
    ) as fh:
        json.dump({"xx_XX": {"finished": "finito (fork)"}}, fh, ensure_ascii=False)
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("finished") == "finito (fork)"  # overrides win
    assert tr("Quit Applio?") == "Quit Applio?"  # genuinely missing -> English key
    # ("Started {label}" IS in the xx_XX fixture map, so it is NOT a
    # missing-key probe — use a key the locale file does not define)


def run_all():
    test_override_locale_and_format()
    test_missing_key_falls_back_to_key()
    test_missing_language_file_falls_back_english()
    test_policy_translator()
    test_overrides_layer_over_locale_map()
    print("All applio_i18n tests passed (5).")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `applio_i18n.py`:

```python
"""Native-string i18n for the Applio fork (AppKit-free).

Mirrors assets/i18n/i18n.py's locale resolution (config lang.override /
selected_lang / system locale) but resolves config + language files across
dev cwd and the frozen bundle (sys._MEIPASS). Missing keys return the key
(English source text) — graceful degradation, repo convention.
"""

import json
import locale as _locale
import os
import threading

_LOCK = threading.Lock()
_INSTANCE = None

DEFAULT_LOCALE = "en_US"


def _candidate_base_paths():
    paths = []
    cwd = os.getcwd()
    paths.append(cwd)
    meipass = getattr(__import__("sys"), "_MEIPASS", None)
    if meipass and meipass != cwd:
        paths.append(meipass)
    return paths


class NativeI18n:
    def __init__(self, base_paths=None, locale_override=None):
        self._map = {}
        self.language = DEFAULT_LOCALE
        bases = base_paths if base_paths is not None else _candidate_base_paths()
        chosen = locale_override or self._resolve_from_config(bases)
        for base in bases:
            path = os.path.join(base, "assets", "i18n", "languages", f"{chosen}.json")
            try:
                with open(path, "r", encoding="utf8") as fh:
                    self._map = json.load(fh)
                self.language = chosen
                break
            except (OSError, ValueError):
                continue
        # Optional fork-owned overrides layer (absent until real translations
        # exist; upstream locale files stay pristine).
        for base in bases:
            override_path = os.path.join(base, "assets", "applio_i18n_overrides.json")
            try:
                with open(override_path, "r", encoding="utf8") as fh:
                    overrides = json.load(fh)
                    self._map.update(overrides.get(self.language, {}))
                    break
            except (OSError, ValueError):
                continue

    @staticmethod
    def _resolve_from_config(bases):
        for base in bases:
            try:
                with open(os.path.join(base, "assets", "config.json"), encoding="utf8") as fh:
                    lang = json.load(fh).get("lang", {})
                if lang.get("override"):
                    return lang.get("selected_lang") or DEFAULT_LOCALE
                sys_locale = _locale.getdefaultlocale()[0] or ""
                if sys_locale:
                    prefix = sys_locale.split("_")[0]
                    for cand in (sys_locale, f"{prefix}_{prefix.upper()}"):
                        if os.path.exists(
                            os.path.join(base, "assets", "i18n", "languages", f"{cand}.json")
                        ):
                            return cand
                break
            except (OSError, ValueError):
                continue
        return DEFAULT_LOCALE

    def __call__(self, key):
        return self._map.get(key, key)


def native_tr(key):
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = NativeI18n()
        return _INSTANCE(key)
```

- [ ] **Step 4: Wire the consumers.**
  - `applio_a11y.py`: `AnnouncementPolicy.__init__(self, translator=None)` → `self._t = translator or (lambda s: s)`; templates become `self._t("Started {label}").format(label=label)`, `self._t("{label} paused").format(label=label)`, `self._t("{label} resumed").format(label=label)`; terminal branches: `word = self._t(words.get(word_key, "finished"))` and `word = self._t(status)`. Keep the message SHAPES identical under the identity translator (existing tests must pass unchanged).
  - `applio_launcher.py`: policy construction gains `translator=applio_i18n.native_tr` (lazy import at construction site); alert strings wrapped: quit confirm (`_t("Quit Applio?")` etc.), data-location dialog texts, update-check call sites stay in their module; `_fill_ns_menu` title render: `item.setTitle_(_tr(mi.title))` at the three title sites — import `_tr = applio_i18n.native_tr` lazily INSIDE `_fill_ns_menu` (module-level import would couple menu building to config presence — keep it call-time).
  - `macos_wrapper.py`: standalone renderer title sites + boot-timeout/close-confirm/first-run alert strings wrapped in `applio_i18n.native_tr(...)` (lazy import inside the functions).
  - `applio_update_check.py`: the 3 alerts' message/button strings wrapped (lazy import inside `check_for_updates_interactive`).
  - DO NOT touch `assets/i18n/languages/*.json` (all 60 are upstream-owned; English needs no entries — the key IS the fallback text). When adding the overrides layer to `NativeI18n`, read `assets/applio_i18n_overrides.json` if present and merge `overrides.get(self.language, {})` over the loaded map.

- [ ] **Step 5: Run all tests** (new + a11y + menu_spec untouched-but-green); py_compile everything touched.

- [ ] **Step 6: Commit**

```bash
git add applio_i18n.py applio_a11y.py applio_launcher.py macos_wrapper.py applio_update_check.py tests/test_applio_i18n.py build_macos.py
git commit -m "feat(a11y): native-string i18n plumbing with graceful English fallback"
```

---

### Task 11: Integration — build wiring, docs, full test pass, frozen validation

**Goal:** Close the loop: all registrations verified in `build_macos.py`, all tests green, CLAUDE.md/CHANGELOG updated, a cert-free frozen build validated end-to-end (routes served, payload injected, Browse buttons present, picker opens), sources restored.

**Files:**
- Modify: `CLAUDE.md` (new Phase 2 section in the a11y area), `CHANGELOG.md` ([Unreleased] entry)
- Verify-only: `build_macos.py` registrations from Tasks 4-8

**Acceptance Criteria:**
- [ ] `patches_to_apply` contains ALL new tuples (browse ×6, progress routes, web payload) in a sensible order — `patch_progress_routes.py` and `patch_web_a11y_payload.py` BOTH patch `app.py`: verify they anchor on DISJOINT text (kwarg line vs `js=` entry) and are order-independent; if not, document the required order in a comment
- [ ] HIDDEN_IMPORTS contains `applio_progress_api`, `applio_native_picker`, `applio_browse_ui`, `applio_i18n`, `rvc.lib.tools.process_log_parser` (plus Phase 1's entries untouched)
- [ ] Full test suite: `venv_macos/bin/python tests/test_applio_a11y.py && venv_macos/bin/python tests/test_menu_spec.py && venv_macos/bin/python tests/test_native_picker.py && venv_macos/bin/python tests/test_browse_ui.py && venv_macos/bin/python tests/test_progress_api.py && venv_macos/bin/python tests/test_patch_fixtures.py && venv_macos/bin/python tests/test_applio_i18n.py && venv_macos/bin/python -m pytest tests/test_inference_progress.py -v` → all green
- [ ] `git status` clean of patch markers; cert-free build `venv_macos/bin/python build_macos.py` → `BUILD COMPLETE`; afterwards `git checkout -- assets core.py rvc tabs app.py` and tree clean
- [ ] Frozen smoke (manual, `dist/Applio.app`): app boots; `curl -s "http://127.0.0.1:<gradio_port>/applio-a11y/progress?client=native" | head -c 400` returns JSON with `"announce":{"owner":"native"}`; WITHOUT `client=native` the same URL reports `"owner":"web"` (per-request semantics); start a batch conversion, then re-curl and assert `jobs` is non-empty (catches the launcher-as-`__main__` resolution failing silently); the injected payload is verifiable via the served config — `curl -s http://127.0.0.1:<port>/config | grep -c applio_a11y` ≥ 1 (the `js=` payload is serialized into the page config; grepping the HTML body for `applio-a11y-live` finds nothing — the region is created client-side); Training tab shows a "Browse…" button under Dataset Path; clicking it opens the native panel and fills the field; Accessibility submenu items toggle and persist across relaunch; with verbosity Off, a batch run writes NO `[A11y]` lines to `~/Library/Logs/Applio/applio_launcher.log` (heartbeat-side gating, Task 9); the "Last result" region shows the last toast text
- [ ] CLAUDE.md documents: the new modules, the `/applio-a11y/progress` route + per-request announce-owner rule, the `prevent_thread_lock` flip (and that the TensorBoard proxy remains dead in normal mode), the picker pattern, the `a11y.*` defaults keys, and the patcher-order note — plus a **Deferred to Phase 3** list: error surfacing with full log tails, typed-path on-change validation for the remaining fields (the Browse handler's `expanduser` is the partial Phase 2 fix), upstream Applio + gradio PRs (audit §5 [U]/§6)
- [ ] CHANGELOG `[Unreleased]` entry summarizing Phase 2 user-visible changes

**Verify:** the full test chain above + `stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio` newer than the last commit

**Steps:**

- [ ] **Step 1:** Audit `build_macos.py` registrations + HIDDEN_IMPORTS against this plan's Acceptance Criteria; fix any gap.
- [ ] **Step 2:** Run the full test chain; fix failures.
- [ ] **Step 3:** Write CLAUDE.md + CHANGELOG entries. Run `venv_macos/bin/python -m black <new/changed .py files>` first if black is installed in the venv (CI's formatter PR will otherwise rewrite long lines — e.g. the progress-api fallback return); accept the churn if black is absent locally.
- [ ] **Step 4:** Cert-free build; restore sources; verify tree clean + timestamps; run the frozen smoke list; record results (and fold in the user's VoiceOver checklist findings from audit §7 if available by then).
- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs(a11y): Phase 2 - web injection, pickers, settings, i18n"
```

---

## Self-Review (completed during planning, revised after adversarial review)

1. **Spec coverage** — audit §6 Phase 2 items → tasks: `/applio-a11y/progress` route + JS payload (6, 7, 8); Browse buttons + pickers + partial path normalization (4, 5 — the handler's `expanduser` covers values passing through Browse; full typed-path on-change validation is DEFERRED to Phase 3 and recorded in Task 11's CLAUDE.md step); Accessibility settings submenu (9); i18n plumbing (10); Last-result region (8, including output-textbox mutation announcements — audit §5 [P] + webui-semantics-1, added during review); routed refinements (1, 2, 3, 9). Error surfacing with log tails: partially covered — terminal announcements carry real status words (Phase 1 + Task 3's race fix), the payload carries history-derived terminal words, toasts and output changes persist; full log-tail surfacing is deferred to Phase 3 (upstream `gr.Error` routing) and recorded on the Phase 3 list. Braille cadence + speech synthesis: excluded by user decision. Phase 3 upstream PRs: excluded by scope.
2. **Placeholder scan** — no TBD/TODO; every code step carries actual code. The two "pin at implementation" spots carry sentinel no-op values + mandatory live-DOM instructions (Task 8's two unpinned selectors) or exact sub-fn lists verified in the repo (Task 3).
3. **Type consistency** — `post_announcement(element, message)` used consistently (Tasks 1, 2); `native_browse` returns `(status, path)` consumed as such in Task 5; `word_key` produced in Task 2's snapshot, consumed in Task 1's policy (via the `_seen` tuple) and Task 6's payload (mirrored by `_collect_words`); `applio_progress_api.set_settings/set_announce_owner/set_layout_changed_callback/register_routes/handle_progress(nav, client, now)` produced in Task 6, consumed in Tasks 7 (register_routes) and 9 (setters, owner, callback); `browse_button(mode, target, elem_id)` produced in Task 5 and referenced by the patcher's inserted lines; `A11Y_CHILD_KEYS`/`A11Y_KEYS`/`DISPLAY_KEYS` memberships consistent between Task 9's spec edits and its tests.

## Review log (adversarial senior review)

- **Round 1 (2026-08-21):** three parallel principal-level reviewers (lenses: correctness/anchors, integration/regressions, completeness) verified the plan against the working tree — including live PyObjC probes (`NSApp is None` → False, killing the planned availability check), gradio 6.20.0 bundle greps (selectors), and every file:line anchor. Findings: 7 unique Criticals, ~15 Importants, ~10 Minors. All Criticals and Importants fixed in this revision:
  1. Policy disappearance loop now POPS vanished keys (was: infinite 2 s re-announce).
  2. Picker availability via explicit `mark_native_loop_available()` flag + injectable timeout (was: dead `NSApp is None` check → 600 s hang in dev/tests).
  3. Progress API resolves the launcher via `sys.modules` `__main__` fallback (launcher never runs under its own name) and reads `log_file` (not `log_path`) for tracked procs.
  4. JS `seen` map deletes announced-disappearance keys; status bookkeeping outside the owner/verbosity gate; milestones announce highest-crossed only; terminal words come from `payload.words` (history) so "failed" is reachable; paused-then-gone announces.
  5. Per-request announce owner (`client=native` ↔ `window.pywebview`): the web announcement arm is real for external browsers instead of unreachable in every configuration.
  6. Accessibility submenu redesigned: four spec children wired by the existing dispatch machinery (was: ad-hoc tag mechanism that never reached `_dynamic_items` — silent no-op), states via `_find_item_by_key`, refresh at end of every `_build_native_menu` (rebuild-safe), WRAPPER set subtracts the children explicitly, existing formula test amended, heartbeat gates `[A11y]` logging under "off".
  7. `en_US.json` (upstream-owned) edit dropped; fork-owned `applio_i18n_overrides.json` layer instead.
  Plus: Task 3 fixture test retargeted to `core.py` with the real sub-fn names/return shapes and a dirty-tree guard; the history-before-untrack reorder restated against the REAL block structure (guarded status, own try/excepts, Popen-failure → history "failed"); batch field names corrected to `input_folder_batch`/`output_folder_batch` with a no-silent-skips fixture assertion; `I18nAuto` config-missing crash guarded in `browse_button`; `expanduser` in the Browse handler; route handler offloaded via `run_in_threadpool` with seek-based log tails; nav debounce made test-injectable; output-textbox mutation announcements added; cached last-good payload fallback; smoke test corrected (`/config` grep, non-empty `jobs`, per-request owner, `[A11y]`-absent check); Phase 3 deferral list recorded.
  Minors accepted as-is where cosmetic (black line-length churn noted in Task 11; `{phase}` comment fix kept minimal; Task 1→2 intermediate breakage documented — feature branch only).
- **Round 2 verification (2026-08-21):** two scoped verifiers re-checked every revised region (Python tasks 1-6 + cross-task consistency; JS payload `node --check`, the `js=` anchor against real `app.py:231-237`, menu_spec/launcher dispatch mechanics, `iter_leaves` behavior, the existing formula-test text). All items PASS; one omission found and fixed (the `NativeI18n` overrides-loading code added to the class block). `window.pywebview` confirmed injected unconditionally by pywebview (`webview/util.py inject_pywebview`), validating the in-app client detection. Plan is implementation-ready.
- **Round 3 (senior final review, 2026-08-21):** full-plan pass focused on cross-task seams, second-order logic, and live-repo re-verification of the riskiest claims (all 13 Browse field anchors + the paren-balanced statement scanner simulated against AST offsets — every naive end lands exactly one newline past the AST statement end, never crossing into the next statement; `prevent_thread_lock` flip traced through gradio 6.20.0 `http_server.start_server`/`Server.run_in_thread` — bind failures raise on the CALLING thread before the thread-lock matters, so the supervisor's OSError fail-fast is preserved, and `start_backend`'s `from app import launch_gradio` + block-forever contract is exactly maintained by the injected sleep; `compute_inference_stats`/`process_log_parser`/`_synthesize_inference_proc`/`get_recent_processes` shapes confirmed, incl. live-progress `started_at` being an epoch float, not ISO; gradio `launch()` returns the 3-tuple upstream already unpacks as `app, _, _`, and `"js": self.js` is serialized into the served `/config`, validating the smoke grep). Issues found and fixed in place:
  1. Task 1, Step 4 — test count said "16 pass"; 10 existing + 7 new = 17 (matches the AC/Verify lines).
  2. Task 3, Step 4 — the rewritten `patch_upload` referenced `_APPLIO_A11Y_UPLOAD_MARKER`, a name that does not exist (the real constant is `UPLOAD_MARKER`, value `"# _APPLIO_A11Y_UPLOAD"`); literal transcription would NameError.
  3. Task 3, Step 5 — said "3 pass" (the file has 2 test fns) and restored only `tabs`; now "2 pass" + `git checkout -- core.py tabs`.
  4. Task 8, JS — `announceOutputChanges` was NOT gated on verbosity although the task's own AC requires it; added the module-level `verbosityNow` (set from each payload, before the prime-return) and the gate.
  5. Task 8, JS — the surviving-key terminal branch announced ANY status change (a batch showing "cancelling" would have been announced as a terminal word); now gated on a JS-side TERMINAL set mirroring `applio_a11y.TERMINAL_STATUSES`, so "cancelling" stays silent until the real terminal word — native/web parity.
  6. Task 8, JS — `healRecordToggles` matched a "record" literal (no such button in the app — the realtime toggle is "Start"/"Stop" — and aria-pressed=true on it would be wrong); removed, and pressed now means exactly `t === "stop"`.
  7. Task 8, JS — if gradio re-render destroys and `ensureRegions` re-creates the live region, the stale `lastLive` would suppress an identical re-announce into the fresh region; reset `lastLive` on region creation.
  8. Task 9 — internal contradiction: the AC said events are computed (but not logged/posted) under verbosity "off", while Step 5 said compute `events` only when not off — the Step-5 version stales `_seen` and announces "Started X" for every running job the moment the user re-enables announcements. Step 5 now mandates calling `events(snap, terminal_words={})` and discarding the result under "off" (keeps `_seen` fresh; keeps the history read lazy).
  9. Task 9, Step 4 — the `__init__` settings read added an UNGUARDED `from Foundation import NSUserDefaults` to a module that keeps a NATIVE_APIS_AVAILABLE fallback path; now try/except-guarded with English/standard defaults.
  10. Task 2, Step 4 — the sidebar-word replacement was written at 16-space indent; the real site (`applio_launcher.py` `tableView_objectValueForTableColumn_row_`) is 12-space; corrected + noted.
  11. Task 5, Step 5 — `tests/test_patch_fixtures.py` is script-style, but no step said to register later tests in `run_all()` (a test not registered never runs); added the instruction, explicitly covering the Task 7/8 extensions.
  12. Task 10 — `test_overrides_layer_over_locale_map` asserted `tr("Started {label}") == "Started {label}"` as the missing-key probe, but the `_make_tree` fixture ALWAYS writes that key into the locale file (the assertion would fail against a correct implementation); probe switched to `"Quit Applio?"`.
  Verified clean, no change needed: Task 7's two app.py patchers anchor on disjoint text (kwarg line vs `js=` entry + `def launch_gradio(`) and are order-independent; Task 5's insertions collide with none of the three existing `tabs/train/train.py` patchers; the i18n anchor `i18n = I18nAuto()` exists verbatim in all six tab files; `("assets", "assets")` datas at `build_macos.py:578` ships the JS; Task 4's `__main__`/HIDDEN_IMPORTS anchors (`applio_launcher.py:4757-4760`, `build_macos.py:542`); Task 9's launcher anchors (`_find_item_by_key` L5425, `_a11y_post` terminal branch L5402-5412, `_enable_webview_keyboard_access` L5099, module-level `AppHelper` import L128). Accepted as-is (reasons in the review notes): the Task 7 injection lands after the "# Mount TensorBoard proxy" comment (import anchor is more durable than a comment anchor); `Promise.prototype.finally` is ES2018 not ES2017 (universally supported in WKWebView; `node --check` clean); `setAllowedFileTypes_` deprecation (still functional); a picker timeout can orphan a still-open modal on the main thread (600 s edge, harmless); native-side silence for a "cancelling" disappearance (pre-existing Phase 1 semantics, explicitly pinned by Task 1's `test_disappeared_unknown_status_silent`, web now matches); module-level `assert` stripped under `python -O` (the frozen app does not run -O). Criteria verdicts: Correctness — 4 code-level bugs fixed (2, 4, 5, 12); Regressions — none beyond the documented Task 1→2 feature-branch window; supervisor/OSError-paths explicitly re-verified safe; Best Practices — 2 fixes (6, 9); Completeness — 4 fixes (1, 3, 10, 11); Integration — no new conflicts found (disjointness + datas + anchors verified). Plan is IMPLEMENTATION-READY.
