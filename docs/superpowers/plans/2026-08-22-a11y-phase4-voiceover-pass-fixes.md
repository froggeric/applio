# Accessibility Phase 4 — VoiceOver-Pass Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five findings from the 2026-08-22 manual VoiceOver pass — job start/finish/milestone speech via the toast channel VoiceOver actually announces, the Active-Processes menu showing live jobs WITH progress, a readable Process Dashboard, and a working in-app announcement owner — so the next pass can come back clean and unblock the upstream PR program.

**Architecture:** Lifecycle toasts ship as a new build-time patcher (`patch_job_toasts.py`, the eventual upstream PR content) + an extension of the fork-owned `patch_inference_progress.py` body for batch milestones/terminals (single source, no double-toast). The menu and dashboard get fork-native fixes in `applio_launcher.py` (merged live-proc helper, progress-bearing menu titles, per-row AX values, key-view loop). The broken window-level NSAccessibility speech is demoted to an opt-in "Native" mode; the default "Auto" routes in-app speech through the web live region (the mechanism toasts proved works), with one instrumentation line keeping the native path diagnosable.

**Tech Stack:** Python 3.10 (venv_macos), PyObjC/AppKit, gradio 6.20.0 toasts (`gr.Info`/`gr.Warning` — verified to fire mid-handler from the event thread via LocalContext contextvars, `helpers.py:1145` + `utils.py:1093-1098`), build-time patchers, script-style test suites.

**Global Constraints (binding every task):**

1. **Upstream files are never modified in git** — `tabs/`, `rvc/`, `core.py`, `app.py` stay pristine; all upstream-touching changes go through `patches/` registered in `build_macos.py` `patches_to_apply` (4-tuple `(patcher_path, source_file, description, patcher_type)`). Fork-owned files are edited directly.
2. **NEVER `import build_macos`** (module-level PyInstaller build). Safe check: `venv_macos/bin/python build_macos.py --help` (exit 0).
3. **Patcher exit codes (CLAUDE.md:134-139):** `0` = patched/already, `2` = anchor miss (build fails), `1` = usage guard only. Per-sub-patch OWN idempotency markers (`# _APPLIO_TOASTS_*`); never a shared early-return. After running any patcher against real sources in tests, restore with `git checkout --` and verify `git status` clean.
4. **Toast split (binding design decision — no double announcements):** SINGLE inference / TTS / training-start / preprocess / extract / download toasts are TAB-side (`patch_job_toasts.py`). BATCH inference toasts (start + milestones + terminal + error) are ENGINE-side ONLY, inside the fork-owned `INFER_BATCH_REPLACEMENT` body of `patch_inference_progress.py` — `enforce_terms_batch` and its `except` get NO toasts (errors raised by the injected body, including the concurrent-run `RuntimeError`, toast there before `raise`).
5. **Frozen-safety:** the menu/dashboard progress math must use the launcher's module-level `_parse_training_log_line` (applio_launcher.py:1020-1065) and `applio_inference_stats.compute_inference_stats` — NEVER `applio_progress_api.enrich_jobs`'s training branch (imports `rvc.lib.tools.process_log_parser`, which ships as DATA in the frozen app → dev-works/frozen-silent divergence). Engine-side toast strings stay English + numeric-dominant (lazy `import gradio` inside a try/except helper; `rvc/infer/infer.py` must not grow top-level gradio/i18n imports). Tab-side toast strings are `i18n("...")`-wrapped (each tab module already has `i18n = I18nAuto()` + `import gradio as gr`).
6. **AppKit idioms:** new delegate selectors follow the repo's NSObject pattern (`tableView_didAddRowView_forRow_` on ProcessDashboardController); verify symbol names exist before adding to the try/except AppKit import block (CLAUDE.md L72-89); pure helpers live at MODULE level in applio_launcher.py (PyObjC validates methods on NSView subclasses — never add helpers as LossChartView methods); native strings via `applio_i18n.native_tr`.
7. **Test conventions:** script-style suites (`venv_macos/bin/python tests/test_X.py`, sys.path shim, `run_all()` + count line updated). `applio_launcher` IS importable in dev (verified) — launcher module-level helpers are directly testable. macOS has no `timeout` command. Baseline: 78 tests green across 10 suites at `main` @ `3a31efbb`.
8. **No pushes, no PRs, no tags.** The 2026-08-22 pass came back with findings — the gate stays shut until the NEXT pass is clean. Execute on branch `feat/a11y-phase4`.
9. Black-compatible style (double quotes; CI's unpinned black is the arbiter — prefer its split shapes).
10. The 2 s `menuUpdateTimerFired_` NSTimer must never die: every menu/dashboard rebuild stays inside `try/except Exception` + `logging.debug(..., exc_info=True)` (never a bare except).

**User decisions (already made):**

- 2026-08-22 pass results (verbatim findings recorded in ACCESSIBILITY_AUDIT.md §7): toasts work; no job-start announcement; no easy progress monitoring ("maybe adding toasts at regular intervals would solve it"); Active Processes "never shows anything — fix it or remove that option which is confusing; however showing entries like 'inference batch audio 43% 2/3 files processed' … could be extremely useful"; dashboard "kind of unusable for blind users … stuck on the list of current and previous runs pane".
- 2026-08-22 (toast ownership): lifecycle + milestone toasts ship fork-side first, become the upstream Applio PR once the pass is clean; rich progress monitoring stays fork-native; the upstream PR keeps fork concepts out (minimal, unconditional).
- Standing gate (2026-08-21, verbatim): "no PR until we have everything 100% test, verified, and confirmed working with 0 regression bug."
- Execution model: subagent-driven development.

---

### Task 1: Announce mode — Auto default (web live region) + Native opt-in + instrumentation

**Goal:** Replace the silently-broken default (in-app announcements owned by window-level NSAccessibility posts, unheard across 3 builds) with an "Auto" default that routes in-app speech through the web live region (the channel toasts proved works), keep "Native" as an opt-in menu mode, and add one log line that makes the native path diagnosable forever.

**Files:**
- Modify: `applio_launcher.py:4841-4852` (owner set in `__init__`), `:5493-5518` (`_a11y_post`), `:5542-5551`-adjacent (settings setters + `_push_a11y_settings`), `menu_spec.py:77-83` (`A11Y_CHILD_KEYS`) + the Accessibility submenu items
- Modify: `applio_progress_api.py` settings echo (announce mode rides along)
- Test: `tests/test_menu_spec.py` (15 → 17), `tests/test_progress_api.py` (11 → 12)

**Acceptance Criteria:**
- [ ] New persisted setting `a11y.announce_mode` ∈ {"auto", "native"}, default "auto", set via two new submenu items under Accessibility: "Announcements: Auto (recommended)" (`a11y.announce.auto`) and "Announcements: Native (experimental)" (`a11y.announce.native`), checkmark on the active one, persisted in NSUserDefaults like `a11y.verbosity`.
- [ ] Mode → owner mapping: "auto" → `applio_progress_api.set_announce_owner("web")` (in-app web client announces via live region); "native" → `set_announce_owner("native")` (current behavior). Applied at `__init__` and on every mode change.
- [ ] `_a11y_post` under "auto": SKIPS `applio_a11y.post_announcement` (keep `requestUserAttention_`, sound cues, and the `[A11y]` heartbeat log line — all focus-independent and working); under "native": unchanged. One instrumentation line added before the post decision: `logging.info("[A11y] post vo=%s element=%r firstResponder=%r", NSWorkspace...isVoiceOverEnabled(), element, window.firstResponder())` guarded so it never breaks the timer.
- [ ] `applio_progress_api.set_settings`/payload echo carries `announce_mode`; per-request owner rule (`owner = "native" if (owner_state == "native" and client == "native") else "web"`) UNTOUCHED — external browsers unaffected either way.
- [ ] Tests: menu_spec gains the two keys (set-membership + formula test updated — the suite already parametrizes over `A11Y_CHILD_KEYS`); progress_api gains a settings-echo test for announce_mode. `test_applio_a11y.py` (17) untouched and green.

**Verify:** `venv_macos/bin/python tests/test_menu_spec.py && venv_macos/bin/python tests/test_progress_api.py && venv_macos/bin/python tests/test_applio_a11y.py` → `(17)`, `(12)`, `(17)`.

**Steps:**

- [ ] **Step 1: Failing tests** — in `tests/test_menu_spec.py` extend the a11y key tests with `"a11y.announce.auto"`, `"a11y.announce.native"` (membership in A11Y_CHILD_KEYS + renderable as spec leaves + WRAPPER_ACTION_KEYS subtraction intact). In `tests/test_progress_api.py` add:

```python
def test_settings_echo_announce_mode():
    payload = api.build_progress_payload(
        jobs=[], settings={"verbosity": "standard", "sound": False,
                           "announce_mode": "auto"},
        announce_owner="web", now=1.0,
    )
    assert payload["settings"]["announce_mode"] == "auto"
```

- [ ] **Step 2: Run to see both fail** (missing keys / missing echo field).
- [ ] **Step 3: Implement.** In `menu_spec.py`: add the two keys to `A11Y_CHILD_KEYS` and two `MenuItem(key=..., title=...)` leaves to the Accessibility submenu after the verbosity group (same shape as `a11y.verbosity.*`). In `applio_launcher.py`: read `a11y.announce_mode` (NSUserDefaults, default "auto") in `__init__`; replace the unconditional `set_announce_owner("native")` with a `_apply_announce_mode()` that maps auto→"web", native→"native" and calls `set_announce_owner`; add `_set_a11y_announce_mode(mode)` setter (persist + `_apply_announce_mode` + `_push_a11y_settings` + `_refresh_a11y_submenu(menu=...)` — mirror `_set_a11y_verbosity`); add the two dispatch entries where the other a11y children dispatch. In `_a11y_post`:

```python
            element = (
                NSApp.keyWindow() or NSApp.mainWindow() or self._main_window.native
            )
            try:  # _APPLIO_AX_DIAGNOSTIC — settles routing questions from logs
                from AppKit import NSWorkspace

                logging.info(
                    "[A11y] post mode=%s vo=%s element=%r",
                    self._a11y_announce_mode,
                    NSWorkspace.sharedWorkspace().isVoiceOverEnabled(),
                    element,
                )
            except Exception:
                pass
            if self._a11y_announce_mode != "native":
                pass  # Auto: window-level AX posts are unheard when VO focus is
                # in the WKWebView (3 builds of evidence); the web live region
                # owns speech. Attention/sound/log below still run.
            else:
                applio_a11y.post_announcement(element, msg)
```

(attention/sound block follows unchanged for both modes). In `applio_progress_api.py`: thread `announce_mode` through `set_settings` → `build_progress_payload` settings echo (default "auto").

- [ ] **Step 4: Run to green.** **Step 5: Commit** — `feat(a11y): announce mode Auto=web live region, Native opt-in + AX post diagnostic log`

---

### Task 2: `patch_job_toasts.py` — lifecycle toasts (single inference, TTS, training start, preprocess, extract, download)

**Goal:** The jobs that start/finish silently get announced through gradio toasts (the VoiceOver-proven channel), injected at build time via a new multi-target patcher modeled on `patch_stop_feedback.py` — the code that later becomes the upstream Applio PR.

**Files:**
- Create: `patches/patch_job_toasts.py`
- Modify: `build_macos.py` `patches_to_apply` (+4 tuples) — NEVER import it; edit + verify via `--help`
- Test: `tests/test_patch_fixtures.py` (+1 test → 6), `tests/test_patcher_exit_codes.py` (CASES +1, count stays 2)

**Injection spec (per file, verbatim anchors verified at 3a31efbb):**

- `tabs/inference/inference.py` — `enforce_terms` ONLY (batch is engine-side, Task 3). After `try:` (line 1171) and into the except:

```python
            try:
                gr.Info(i18n("Converting audio..."))  # _APPLIO_TOASTS_INFERENCE
                result = run_infer_script(*args)
                gr.Info(result[0])  # _APPLIO_TOASTS_INFERENCE
                return result
            except Exception:
                traceback.print_exc()
                gr.Warning(  # _APPLIO_TOASTS_INFERENCE
                    "An error occurred during audio conversion. Please check the console logs for more details."
                )
                return (
                    "An error occurred during audio conversion. Please check the console logs for more details.",
                    None,
                )
```

- `tabs/tts/tts.py` — `enforce_terms`, identical shape (anchor lines 356-368; strings "Converting audio..." → i18n("Starting text-to-speech..."), error string = the TTS wording verbatim; marker `# _APPLIO_TOASTS_TTS`).
- `tabs/train/train.py` — (a) `enforce_terms` (754-759): START only — insert `gr.Info(i18n("Training started..."))  # _APPLIO_TOASTS_TRAIN` before `return run_train_script(*args)` (no terminal toast: hours later + heartbeat/web already announce it); (b) preprocess + extract: inject two wrapper defs directly above the `def enforce_terms` line and rewire the two unique `fn=` literals:

```python
        def _applio_preprocess_toast(*args):  # _APPLIO_TOASTS_TRAIN
            gr.Info(i18n("Preprocessing dataset..."))
            result = run_preprocess_script(*args)
            if isinstance(result, str):
                if result.lower().startswith("error"):
                    gr.Warning(result)
                else:
                    gr.Info(result)
            return result

        def _applio_extract_toast(*args):  # _APPLIO_TOASTS_TRAIN
            gr.Info(i18n("Extracting features..."))
            result = run_extract_script(*args)
            if isinstance(result, str):
                if result.lower().startswith("error"):
                    gr.Warning(result)
                else:
                    gr.Info(result)
            return result
```

  then `fn=run_preprocess_script,` → `fn=_applio_preprocess_toast,` (line 502) and `fn=run_extract_script,` → `fn=_applio_extract_toast,` (line 597).
- `tabs/download/download.py` — same wrapper pattern for `fn=run_download_script,` (line 202; marker `# _APPLIO_TOASTS_DOWNLOAD`): `gr.Info(i18n("Downloading model..."))`, then success `gr.Info(result)` / `gr.Warning(result)` when the string contains "error" (core returns "An error occurred downloading the model…" / "Model downloaded successfully.").
- DO NOT TOUCH: `tabs/download/download.py:146/161` and `tabs/train/train.py:861-872` (already toast; they are the i18n() convention reference). NEVER anchor on the shared terms-of-use lines — disambiguate per-file on the distinct `run_*_script(*args)` call line.

**Patcher shape:** `TARGETS = [("tabs/inference/inference.py", "inference.py", patch_inference), ("tabs/tts/tts.py", "tts.py", patch_tts), ("tabs/train/train.py", "train.py", patch_train), ("tabs/download/download.py", "download.py", patch_download)]`; `apply(base_path)` resolves `os.path.join(base_path, repo_rel)` or `os.path.join(base_path, basename)` (both standalone-file and dir-type args work, like patch_stop_feedback); per-file status print `  [job_toasts] <file>: patched|already|miss`; `sys.exit(0 if all patched/already else 2)`; usage guard keeps 1. Each sub-patch checks its OWN marker first.

**Acceptance Criteria:**
- [ ] All 4 files patched as specced; running the patcher twice → all "already", exit 0 both times; mutated anchor in a temp copy → exit 2.
- [ ] Patched outputs `py_compile` clean; `enforce_terms_batch` in inference.py receives NO toasts (Task 3 owns batch).
- [ ] Registered in `build_macos.py` as 4 "dir"-type tuples; `--help` exits 0.
- [ ] Fixture test: pristine sources patched in temp copies → each expected injected line present verbatim (one assertion block per file); exit-code CASES gain patch_job_toasts (dir-type, `tabs/tts/tts.py`, anchor `def enforce_terms(terms_accepted, *args):` mutated mid-anchor).
- [ ] Tree restored clean after test runs (`git status --short` empty).

**Verify:** `venv_macos/bin/python tests/test_patch_fixtures.py && venv_macos/bin/python tests/test_patcher_exit_codes.py && venv_macos/bin/python build_macos.py --help` → `(6)`, `(2)`, help + exit 0.

**Steps:** write failing fixture test → run (fail: no patcher) → implement patcher + registration → green → `--help` → commit `feat(a11y): job lifecycle toasts (single infer, tts, train start, preprocess, extract, download)`.

---

### Task 3: Batch-inference toasts — start, milestones, terminals (engine-side, in `patch_inference_progress.py`)

**Goal:** The batch flow (the user's exact test case) gets start, 25/50/75% milestone, completion/cancelled, and error toasts — all inside the fork-owned injected body, verified to work mid-loop (gradio's LocalContext contextvars live on the handler thread; `Queue.log_message` delivers toasts to the SSE stream immediately, not at handler completion).

**Files:**
- Modify: `patches/patch_inference_progress.py` — `INFER_PROGRESS_HELPERS` (+`_infer_toast`), `INFER_BATCH_REPLACEMENT` (loop entry ~L166, terminal block ~L208-218, error block ~L226-244)
- Test: `tests/test_inference_progress.py` (pytest, 5 → 7)

**Acceptance Criteria:**
- [ ] Helper in `INFER_PROGRESS_HELPERS`:

```python
def _infer_toast(msg):
    """Fire a gradio toast from inside the batch loop (handler thread has
    live LocalContext; falls back to print when headless)."""
    try:
        import gradio as gr

        gr.Info(msg)
    except Exception:
        print(msg)
```

- [ ] Start (before the loop): `_infer_toast(f"Batch conversion started: {total} files")`.
- [ ] Milestones: `_next_milestone = 25` initialized with the counters; after each per-file `_write_infer_progress`, `if total >= 8 and total and processed * 100 // total >= _next_milestone: _infer_toast(f"{processed}/{total} files converted ({_next_milestone}%)"); _next_milestone += 25` (small batches: start+terminal only — no spam).
- [ ] Terminal block (completed/cancelled): `_infer_toast(f"Batch conversion {status}: {converted} converted, {skipped} skipped in {elapsed:.0f}s")` (counts + elapsed already computed there).
- [ ] Error block: `_infer_toast("Batch conversion failed: " + str(e))` before the existing `raise` (covers mid-loop errors AND the concurrent-run RuntimeError which raises from the same body — so the tab-side `enforce_terms_batch` except needs no toast, per Global Constraint 4).
- [ ] `tests/test_inference_progress.py` +2: generated-output assertions that the milestone + terminal + error `_infer_toast` calls exist in the patched text and `import gradio` appears ONLY inside `_infer_toast` (never at module top of the generated engine code).

**Verify:** `venv_macos/bin/python -m pytest tests/test_inference_progress.py -q` → `7 passed`.

**Steps:** failing pytest assertions → implement in the patcher's constant strings → green → standalone patcher run on a temp copy + `git checkout --` restore → commit `feat(a11y): batch inference start/milestone/terminal toasts (engine-side)`.

---

### Task 4: Active-Processes menu — show inference + live progress titles

**Goal:** Fix the never-populates bug (menu fed only `get_active_processes()`; the in-process batch is synthesized elsewhere) and upgrade titles to live progress ("Inference: batch — 43% (2/3 files)", "Training: voice — epoch 34/200"), unifying the live-proc merge the dashboard already uses.

**Files:**
- Modify: `applio_launcher.py` — new module-level `_merged_live_procs()` + `_menu_job_title(proc)`; `_update_menu_state:5314` + stale comment 5310-5312; `_refresh_status_submenu:5337-5381` rewrite; dashboard call sites 3928 + 4450 switched to the helper
- Test: NEW `tests/test_menu_jobs.py` (4 tests, script-style, `import applio_launcher` — verified importable)

**Acceptance Criteria:**
- [ ] `_merged_live_procs()`: `procs = get_active_processes(); inf = _synthesize_inference_proc(); if inf: procs.append(inf); return procs` — used by the menu AND both dashboard merge sites (three copies → one).
- [ ] `_menu_job_title(proc)` (module-level, AppKit-free, i18n via `native_tr` at call time): inference → `f"{_t('Inference')}: {name or 'batch'} — {pct}% ({processed}/{total} {_t('files')})"` (pct via `compute_inference_stats`); cancelling → "stopping…" variant; training → `f"{_t('Training')}: {name} — {_t('epoch')} {cur}/{total_epoch}"` with cur from `_parse_training_log_line` on the proc's `log_file` tail (256 KB seek-tail read), "starting…" before the first status line; preprocess/extract → name only; tts → "TTS: active job" (tracked bare); any paused subprocess → append " — paused". Name capped at 30 chars (leading "…"), whole line ≤ 64 chars.
- [ ] `_refresh_status_submenu()` (no arg): builds merged list + titles; **skips the NSMenu rebuild when the title tuple is unchanged** (`self._last_status_titles`) — no flicker/AX churn; placeholder `"No active processes"` unchanged; click dispatch to the dashboard unchanged; whole body stays in the existing `except Exception: logging.debug(..., exc_info=True)` guard.
- [ ] New main-thread cost per tick ≤ one bounded training-log tail read + regex (comparable to the dashboard's existing `_parse_training_metrics`); all other data already read that tick.
- [ ] `tests/test_menu_jobs.py`: (1) inference title format from a synthetic proc (43%/2-of-3); (2) training title with a fake log tail via monkeypatched `_parse_training_log_line`-equivalent seam (build the title fn to take the parsed epoch as a param so the test stays AppKit-free: `_menu_job_title(proc, training_epoch=None)`); (3) merged helper with monkeypatched sources; (4) long-name truncation + paused suffix.
- [ ] `venv_macos/bin/python tests/test_menu_spec.py` still (17).

**Verify:** `venv_macos/bin/python tests/test_menu_jobs.py && venv_macos/bin/python tests/test_menu_spec.py` → `(4)` and `(17)`.

**Steps:** new failing test file → implement helpers + rewrite → green → commit `fix(a11y): Active Processes menu shows all live jobs with progress (inference included)`.

---

### Task 5: Dashboard readability — per-row AX values, template progress, chart value, key-view loop, selection announcement

**Goal:** Make the Process Dashboard readable by a blind user: rows announce their metrics, the progress bar announces template text (not bare percent), the loss chart's value summarizes the curve, Tab deterministically exits the runs list, and selecting a row announces its summary — so the user is never "stuck on the list pane".

**Files:**
- Modify: `applio_launcher.py` — module-level `_row_ax_summary(proc, metrics=None, total_epoch=None, eta=None)`; `ProcessDashboardController`: `tableView_didAddRowView_forRow_` (new delegate method), progress-value templates at 3190-3192 / 3420-3422, indeterminate-spin branch 3194-3201, `LossChartView.set_points` 2434-2447 value string, key-view loop in `_create_detail_panel`, selection announcement in `tableViewSelectionDidChange_` 3896-3916, dead `status_badge` branch 3045-3048 removed
- Test: NEW `tests/test_dashboard_ax.py` (3 tests: summary builder training/inference/empty)

**Acceptance Criteria:**
- [ ] `_row_ax_summary` (module-level, AppKit-free): training → `f"epoch {cur} of {total}, best loss {best:.4g}, ETA {eta}"` (inputs: `_parse_training_metrics`-shaped dict + total_epoch; ETA via `_derive_eta` when available); inference → `f"{processed} of {total} files converted, {pct:.0f} percent"`; unknown/missing → `""`. English keys wrapped `native_tr` at call time.
- [ ] `tableView_didAddRowView_forRow_(self, view, row)`: resolves the proc via the same row arithmetic as the dataSource (active first, then recent), sets `view.setAccessibilityLabel_(f"{_t('Training run')} {name}" / f"{_t('Inference batch')} {name}")` and `view.setAccessibilityValue_(summary)` — visible cell text stays short, VoiceOver reads the full string; re-fires on each 3 s reloadData.
- [ ] Progress values: training branch → `f"{_t('Epoch')} {cur} of {total}, {int(frac*100)} {_t('percent')}"`; inference branch → `f"{processed} of {total} {_t('files')}, {int(pct)} {_t('percent')}"`; indeterminate branch → `_t("Working, no metrics yet")` (replaces the stale-value bug).
- [ ] Chart `set_points` value: `f"{_t('Loss chart')}: {n} {_t('epochs plotted')}, {first_ep}–{last_ep}. {_t('Loss fell from')} {first_loss:.4g} {_t('to')} {last_loss:.4g}. {_t('Best')} {best:.4g} @ {best_ep}. {len(improvements)} {_t('significant improvements')}."` (keep the "no data yet" case); built at MODULE level via the existing `_chart_text_attr`-style helper pattern — never a LossChartView method.
- [ ] Key-view loop set once after the buttons exist: `process_table → stop_btn → pause_btn → reveal_btn → open_btn → process_table` (`setNextKeyView_` chain — Tab deterministically exits the list).
- [ ] Selection announcement in `tableViewSelectionDidChange_` after `_update_detail_panel()`: gated on `NSWorkspace.sharedWorkspace().isVoiceOverEnabled()` AND verbosity != "off", `applio_a11y.post_announcement(self.process_table, f"{summary}. {_t('Detail pane updated.')}")` — main-thread (selection events are), reuse `_row_ax_summary`; wrapped in try/except so selection never breaks.
- [ ] Dead `status_badge` branch in `_set_detail_status` (3045-3048) deleted (the dashboard never initializes a badge).
- [ ] `tests/test_dashboard_ax.py` covers the summary builder's three shapes (pure function, no AppKit needed).

**Verify:** `venv_macos/bin/python tests/test_dashboard_ax.py && venv_macos/bin/python tests/test_applio_a11y.py` → `(3)` and `(17)`.

**Steps:** failing summary tests → implement builder + delegate + templates + loop + announcement → green → commit `feat(a11y): dashboard per-row AX values, template progress, chart summary, key loop, selection announcement`.

---

### Task 6: Documentation — audit §7, CHANGELOG, CLAUDE.md

**Goal:** Record the Phase 4 fixes against the pass findings they resolve, and stage the next manual-pass checklist.

**Files:**
- Modify: `ACCESSIBILITY_AUDIT.md` (§7), `CHANGELOG.md` ([Unreleased]), `CLAUDE.md` (a11y Phase 4 paragraph + patcher/test list updates)

**Acceptance Criteria:**
- [ ] Each of the 5 pass findings annotated with its fix + commit hash; a new "re-test checklist" subsection for the NEXT manual pass (toasts on start/milestone/finish of a batch; menu shows the batch with % + a training job with epoch; dashboard rows read metrics, Tab exits the list; Announcements submenu shows Auto active).
- [ ] CHANGELOG [Unreleased] Phase 4 section (toasts, menu, dashboard AX, announce mode + the Auto-default behavior change).
- [ ] CLAUDE.md: Phase 4 paragraph (announce-mode Auto semantics, batch-toast split rule, frozen-safe enrichment rule), `patch_job_toasts` added to patcher mentions, new test files listed.
- [ ] Exactly the three doc files in the diff.

**Verify:** `git diff --stat` → 3 files; `rg -n "Phase 4" ACCESSIBILITY_AUDIT.md | tail -5`.

**Steps:** edit per AC → verify → commit `docs(a11y): Phase 4 delivery notes + re-test checklist`.

---

### Task 7: Full-chain validation + cert-free frozen build (gate)

**Goal:** Prove the branch regression-free end to end: every suite green with the new counts, the frozen build completes with all patchers (now including `patch_job_toasts`) exiting 0, the bundle carries the new code, the running app serves the progress route with `announce_mode` in settings, and the menu/dashboard code paths import clean in the frozen binary.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task enforces the owner's standing ruling (2026-08-21, verbatim): "no PR until we have everything 100% test, verified, and confirmed working with 0 regression bug." It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every acceptance criterion has been re-validated independently, with output captured.

**Files:** none (validation only; artifacts gitignored).

**Acceptance Criteria:**
- [ ] All suites green: test_applio_a11y (17), test_menu_spec (17), test_native_picker (3), test_browse_ui (9), test_progress_api (12), test_patch_fixtures (6), test_applio_i18n (9), test_a11y_js_invariants (2), test_patcher_exit_codes (2), test_menu_jobs (4), test_dashboard_ax (3), pytest test_inference_progress (7) — 91 total (adjust/report legitimate shifts).
- [ ] Cert-free build: `venv_macos.py` background run, build as FINAL command, `BUILD COMPLETE`, every `Patching:` line includes the 4 new `job_toasts` registrations, zero `PATCH FAILURE`; post-build `git checkout -- assets core.py rvc tabs app.py` if dirty; tree clean.
- [ ] Bundle: binary timestamp AFTER last commit; `dist/Applio.app/Contents/Resources/assets/applio_a11y.js` unchanged-marker check (Task 1 didn't touch JS — verify no accidental drift); `patches/patch_job_toasts.py` present in bundle resources; frozen-boot smoke: launch, poll `curl -s "http://127.0.0.1:6969/applio-a11y/progress?client=web"` → JSON contains `"announce_mode"`, quit via osascript.
- [ ] Toast smoke in the frozen app: reproduce frozen-subprocess behavior headlessly — `dist/Applio.app/Contents/MacOS/Applio /tmp/toast_check.py` is NOT available for gradio-context toasts (they need the event loop); instead assert the patched tab sources exist in the bundle's Frameworks graph via `find dist/Applio.app/Contents -name "inference.py"` + `rg -c "_APPLIO_TOASTS_INFERENCE"` on it (patched-at-build = markers present in the BUILT copies).
- [ ] No pushes, no PRs, no tags.

**Verify:** the suite loop + build command from Task 9 of the Phase 3 plan, adapted with the two new suites; evidence captured in the report.

**Steps:** full chain → cert-free build → hygiene + bundle checks → boot smoke → evidence report (no commit).

---

## Self-Review (completed at write time)

1. **Spec coverage:** pass finding 1+2 (start announcements) → T2/T3 toasts; finding 3 (progress monitoring) → T3 milestones + T4 menu progress; finding 4 (menu empty/confusing) → T4; finding 5 (dashboard) → T5; the underlying step-4 routing question → T1 (demote + instrument, per the exploration's grounded recommendation). Docs T6, gate T7. The upstream Applio/gradio PR program remains OUT of scope (own plan after a clean pass).
2. **Placeholder scan:** every code step carries real code; anchors are verbatim from the 2026-08-22 exploration at 3a31efbb.
3. **Type consistency:** `_menu_job_title(proc, training_epoch=None)` defined in T4 and tested there; `_row_ax_summary(proc, metrics=None, total_epoch=None, eta=None)` defined + tested in T5, consumed by rows/progress/announcement; `_infer_toast` defined in T3's helper block; markers `_APPLIO_TOASTS_{INFERENCE,TTS,TRAIN,DOWNLOAD}` unique per file; `a11y.announce.{auto,native}` keys consistent across menu_spec/T1/tests.
4. **Known deliberate roughness:** T2's wrapper defs inject ABOVE `def enforce_terms` in train.py (indentation must match the enclosing scope — the patcher matches the `def enforce_terms(terms_accepted, *args):` line and inserts at its indentation); preprocess/extract/tts have no percent in v1 (nothing computed frozen-safely today — noted, not placeholdered).
