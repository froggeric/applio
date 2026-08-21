# Accessibility Phase 3 — Fork-Local Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the fork-local half of accessibility Phase 3 — the five audit §7 "Phase 3 additions born during Phase 2 execution" plus the two Phase 2 deferrals (log-tail surfacing, typed-path validation) — each with tests, ending in a green full chain and a validated cert-free frozen build.

**Architecture:** All work stays in fork-owned files (applio_i18n, applio_browse_ui, applio_progress_api, applio_a11y.js, applio_launcher, macos_wrapper, patches/, build_macos.py loop). Upstream files are never edited directly — the one upstream-touching change (Browse-field validation wiring) extends the existing build-time patcher `patches/patch_browse_buttons.py`. The upstream Applio + gradio PR program is explicitly OUT OF SCOPE (separate plan after the manual VoiceOver pass clears the user's gate).

**Tech Stack:** Python 3.10 (venv_macos), PyObjC/AppKit (launcher side only), gradio 6.20.0 (`.blur` verified on Textbox and Dropdown), vanilla ES5 JS injected at build time, script-style test suites run via `venv_macos/bin/python tests/test_X.py`.

**Global Constraints (binding every task):**

1. **Upstream files are never modified directly.** `tabs/`, `rvc/`, `core.py`, `app.py`, and upstream-owned `assets/` files stay pristine in git; every upstream-file change goes through a patcher in `patches/` registered in `build_macos.py`'s `patches_to_apply`. Fork-owned files (`applio_*.py`, `assets/applio_a11y.js`, `menu_spec.py`, `macos_wrapper.py`, `applio_launcher.py`, `patches/`, `build_macos.py`, `tests/`, `CLAUDE.md`, `CHANGELOG.md`, `ACCESSIBILITY_AUDIT.md`) are edited directly.
2. **NEVER `import build_macos`** in tests or dev scripts — it runs the entire PyInstaller build at module level. Safe build-file checks: `venv_macos/bin/python build_macos.py --help` (argparse exits before the module-level build) or `py_compile`.
3. **Patcher exit-code convention (this plan establishes it):** `0` = patched or already applied; `2` = anchor/pattern miss; usage guards (`if len(sys.argv) < 2`) keep `1`; `sys.exit(1)` sites inside injected triple-quoted code strings are untouched; `patches/download_pretraineds.py` is exempt (model downloader with its own invocation path at `build_macos.py:471`, not the patch loop — its `1` means "download failed"). The build loop fails the build on ANY nonzero exit.
4. **`applio_progress_api.py` stays AppKit-free and pure:** `build_progress_payload(...)` takes everything as parameters (no globals, no I/O). The launcher imports `applio_progress_api` (lazily); the reverse import is forbidden — the launcher is resolved via `sys.modules` with a `__main__` fallback.
5. **i18n rules:** English source strings ARE the keys; upstream locale files stay pristine; translations live only in the optional fork-owned `assets/applio_i18n_overrides.json`; use the established lazy call-time pattern (`import applio_i18n` / `_t = applio_i18n.native_tr` inside the function, as at `applio_launcher.py:5836-5838`).
6. **JS payload rules (`assets/applio_a11y.js`):** ES5 only (`var`, `function`, no arrow functions/`let`/`const` — match the file's style); DOM writes via `textContent` only, never `innerHTML` with server-derived data; keep the pinned-selector discipline.
7. **Test conventions:** script-style suites with the `sys.path.insert(0, ...)` shim at top, run as `venv_macos/bin/python tests/test_X.py`, ending in a `run_all()` + count line that MUST be updated when tests are added. macOS has no `timeout` command. After running any patcher against real repo sources in a test, verify `git status` shows no leftover patch markers (restore with `git checkout --` if needed).
8. **No pushes, no PRs, no upstream-remote mutations in this plan.** Hard user gate (verbatim, 2026-08-21): "no PR until we have everything 100% test, verified, and confirmed working with 0 regression bug." The upstream Applio/gradio PR program gets its own plan after the manual VoiceOver pass (scheduled 2026-08-22 09:07) comes back clean.
9. Code is Black-formatted on push by CI — write Black-compatible style (double quotes, standard wrapping).
10. Baseline at plan time: `main` at `d41c511e`, clean tree, 62/62 tests green (17+15+3+5+7+5+5+5). Execute on branch `feat/a11y-phase3` forked from `main`.

**User decisions (already made):**

- 2026-08-21 (verbatim): "no PR until we have everything 100% test, verified, and confirmed working with 0 regression bug." → this plan is fork-local only; upstream PRs are deferred to a separate post-pass plan.
- 2026-08-21: "Then you will continue with phase 3" — Phase 3 scope per the recorded deferral list = audit §7 additions + Phase 2 deferrals (fork-local, this plan) + upstream Applio/gradio PRs (gated, separate plan).
- Execution model: subagent-driven development (worked for Phases 1-2).

---

### Task 1: applio_i18n — upstream-accurate locale resolution + corrupt-JSON guards

**Goal:** Make `NativeI18n`'s system-locale fallback match upstream `assets/i18n/i18n.py`'s prefix-glob semantics (any available language starting with the 2-letter prefix wins) and survive corrupt (non-dict) language/overrides JSON without `AttributeError`.

**Files:**
- Modify: `applio_i18n.py:42-61` (both JSON loads), `applio_i18n.py:63-86` (`_resolve_from_config`)
- Test: `tests/test_applio_i18n.py` (extend; 5 → 8 tests)

**Acceptance Criteria:**
- [ ] With system locale `xx_ZZ` and only `xx_YY.json` present (no override set), `NativeI18n` resolves `language == "xx_YY"` (prefix-glob, mirroring upstream `i18n.py:24-30`).
- [ ] Dash-form locales normalize (`fr-FR` → prefix `fr`) before matching.
- [ ] A `languages/<locale>.json` containing a JSON list (not object) is skipped gracefully: `language` falls back to `en_US` and `native_tr(key) == key` — no `AttributeError`.
- [ ] A list-valued `applio_i18n_overrides.json` (or a list-valued per-locale layer inside it) is skipped the same way.
- [ ] Existing 5 tests still pass; suite prints `(8)`.

**Verify:** `venv_macos/bin/python tests/test_applio_i18n.py` → `All applio_i18n tests passed (8).`

**Steps:**

- [ ] **Step 1: Write the failing tests** — append to `tests/test_applio_i18n.py` (before `run_all`):

```python
def test_system_locale_prefix_glob():
    # Upstream semantics (assets/i18n/i18n.py:24-30): first AVAILABLE language
    # whose name startswith(locale[:2]) wins. xx_ZZ must resolve to xx_YY.
    import applio_i18n as _mod

    tmp = _make_tree("en_US")
    lang_dir = os.path.join(tmp, "assets", "i18n", "languages")
    with open(os.path.join(lang_dir, "xx_YY.json"), "w", encoding="utf8") as fh:
        json.dump({"finished": "finito xx"}, fh, ensure_ascii=False)
    with open(os.path.join(tmp, "assets", "config.json"), "w", encoding="utf8") as fh:
        json.dump({"lang": {}}, fh)  # no override -> system-locale path
    orig = _mod._locale.getdefaultlocale
    _mod._locale.getdefaultlocale = lambda: ("xx_ZZ", "UTF-8")
    try:
        tr = applio_i18n.NativeI18n(base_paths=[tmp])
        assert tr.language == "xx_YY", tr.language
        assert tr("finished") == "finito xx"
    finally:
        _mod._locale.getdefaultlocale = orig


def test_corrupt_locale_json_falls_back():
    tmp = _make_tree("xx_XX")
    # Overwrite the locale file with a JSON list -> not a dict.
    with open(
        os.path.join(tmp, "assets", "i18n", "languages", "xx_XX.json"), "w",
        encoding="utf8",
    ) as fh:
        fh.write("[1, 2, 3]")
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr.language == "en_US"
    assert tr("finished") == "finished"  # English key fallback, no crash


def test_corrupt_overrides_json_falls_back():
    tmp = _make_tree("xx_XX")
    with open(
        os.path.join(tmp, "assets", "applio_i18n_overrides.json"), "w", encoding="utf8"
    ) as fh:
        fh.write('["not", "an", "object"]')
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("finished") == "finito"  # locale map still loads; overrides skipped
    # A dict overrides file whose per-locale layer is a list is skipped too.
    with open(
        os.path.join(tmp, "assets", "applio_i18n_overrides.json"), "w", encoding="utf8"
    ) as fh:
        json.dump({"xx_XX": ["bad", "layer"]}, fh)
    tr2 = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr2("finished") == "finito"
```

and register all three in `run_all()` + update the count line to `(8)`.

- [ ] **Step 2: Run to verify failure** — `venv_macos/bin/python tests/test_applio_i18n.py` → prefix-glob test fails (`language == 'en_US'` or KeyError path), corrupt-JSON tests raise `AttributeError`.

- [ ] **Step 3: Implement** — in `applio_i18n.py`, replace the language-load block in `__init__` (currently lines 42-50) with:

```python
        for base in bases:
            path = os.path.join(base, "assets", "i18n", "languages", f"{chosen}.json")
            try:
                with open(path, "r", encoding="utf8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    raise ValueError(f"language file is not an object: {path}")
                self._map = data
                self.language = chosen
                break
            except (OSError, ValueError):
                continue
```

and the overrides block (currently lines 53-61) with:

```python
        for base in bases:
            override_path = os.path.join(base, "assets", "applio_i18n_overrides.json")
            try:
                with open(override_path, "r", encoding="utf8") as fh:
                    overrides = json.load(fh)
                if not isinstance(overrides, dict):
                    raise ValueError(f"overrides file is not an object: {override_path}")
                layer = overrides.get(self.language, {})
                if isinstance(layer, dict):
                    self._map.update(layer)
                break
            except (OSError, ValueError):
                continue
```

and replace the system-locale candidate logic in `_resolve_from_config` (currently lines 73-82, the `sys_locale = ...` block) with:

```python
                sys_locale = (_locale.getdefaultlocale()[0] or "").replace("-", "_")
                if sys_locale:
                    # Upstream semantics (assets/i18n/i18n.py:24-30): first
                    # available language whose name startswith(locale[:2]).
                    prefix = sys_locale.split("_")[0][:2]
                    languages_dir = os.path.join(
                        base, "assets", "i18n", "languages"
                    )
                    try:
                        available = sorted(
                            f[:-5]
                            for f in os.listdir(languages_dir)
                            if f.endswith(".json")
                        )
                    except OSError:
                        available = []
                    matching = [
                        lang for lang in available if lang.startswith(prefix)
                    ]
                    if matching:
                        return matching[0]
```

- [ ] **Step 4: Run to verify pass** — `All applio_i18n tests passed (8).`

- [ ] **Step 5: Commit** — `git add applio_i18n.py tests/test_applio_i18n.py && git commit -m "fix(i18n): upstream-accurate locale prefix-glob + corrupt-JSON guards"`

---

### Task 2: Scope healRecordToggles to the realtime record section

**Goal:** Stop stamping `aria-pressed` on every Start/Stop-labeled button in the document; anchor it to the realtime record toggle's container via the fork-injected `#browse-record_audio_path` Browse button, so the momentary engine Start/Stop pair (`tabs/realtime/realtime.py:941-942`) is never mislabeled as a toggle.

**Files:**
- Modify: `assets/applio_a11y.js:103-110` (`healRecordToggles`; call sites at 167 and 308 unchanged)
- Test: `tests/test_a11y_js_invariants.py` (NEW — source-invariant tests for the JS payload; no browser harness exists in-repo)

**Acceptance Criteria:**
- [ ] `healRecordToggles` resolves `#browse-record_audio_path`, scopes to its container (`.form` first, `gradio-column` fallback), and only stamps buttons inside that scope.
- [ ] The function no longer calls document-wide `querySelectorAll("button")`.
- [ ] When the anchor is absent (page without the realtime tab mounted), the function is a no-op.
- [ ] New suite passes: `All a11y JS invariant tests passed (2).`

**Verify:** `venv_macos/bin/python tests/test_a11y_js_invariants.py` → `All a11y JS invariant tests passed (2).`

**Steps:**

- [ ] **Step 1: Write the failing test** — create `tests/test_a11y_js_invariants.py`:

```python
# tests/test_a11y_js_invariants.py
"""Source invariants for assets/applio_a11y.js (no browser harness in-repo).
Run: venv_macos/bin/python tests/test_a11y_js_invariants.py"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(REPO, "assets", "applio_a11y.js")


def _function_body(name):
    with open(JS, encoding="utf8") as fh:
        src = fh.read()
    m = re.search(rf"function {name}\(.*?\) {{(.*?)\n  }}", src, re.DOTALL)
    assert m, f"function {name} not found in applio_a11y.js"
    return m.group(1)


def test_heal_record_toggles_scoped_to_browse_anchor():
    body = _function_body("healRecordToggles")
    assert "#browse-record_audio_path" in body, (
        "healRecordToggles must anchor on the fork-injected Browse button"
    )
    assert 'document.querySelectorAll("button")' not in body, (
        "healRecordToggles must not scan the whole document for Start/Stop"
    )
    assert "closest" in body and "querySelectorAll" in body, (
        "healRecordToggles must scope via closest() then query within"
    )


def test_failed_tail_wiring_present():
    # Task 4 extends this; guards the persistResult enrichment contract.
    with open(JS, encoding="utf8") as fh:
        src = fh.read()
    assert "failedTail" in src, "failedTail helper must exist (log-tail surfacing)"


def run_all():
    test_heal_record_toggles_scoped_to_browse_anchor()
    test_failed_tail_wiring_present()
    print("All a11y JS invariant tests passed (2).")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 2: Run to verify failure** — the scoping assertion fails (current function scans `document.querySelectorAll("button")`); the `failedTail` assertion also fails (Task 4 hasn't run). NOTE: implement Task 2's production change AND leave `test_failed_tail_wiring_present` failing? NO — adjust: for Task 2, ship the file with ONLY `test_heal_record_toggles_scoped_to_browse_anchor` in `run_all()` and the count `(1)`; Task 4 adds the second test and bumps the count. (The snippet above shows the END state after Task 4; Task 2 lands it with one test.)

- [ ] **Step 3: Implement** — replace `healRecordToggles` in `assets/applio_a11y.js` (lines 103-110) with:

```javascript
  function healRecordToggles() {
    // Scoped to the realtime "Record Audio" section: the fork-injected
    // Browse button for record_audio_path is the only stable fork-controlled
    // DOM anchor in it (the record toggle itself has no elem_id). The engine
    // Start/Stop pair elsewhere in the tab is momentary, NOT a toggle, and
    // must not receive aria-pressed.
    var anchor = document.querySelector("#browse-record_audio_path");
    if (!anchor) { return; }
    var scope = anchor.closest(".form") || anchor.closest("gradio-column");
    if (!scope) { return; }
    scope.querySelectorAll("button").forEach(function (btn) {
      var t = (btn.textContent || "").trim().toLowerCase();
      if (t === "start" || t === "stop") {
        btn.setAttribute("aria-pressed", String(t === "stop"));
      }
    });
  }
```

- [ ] **Step 4: Run to verify pass** — `All a11y JS invariant tests passed (1).`

- [ ] **Step 5: Commit** — `git add assets/applio_a11y.js tests/test_a11y_js_invariants.py && git commit -m "fix(a11y): scope aria-pressed healing to the realtime record toggle"`

---

### Task 3: Unify the terminal-words map behind one shared helper

**Goal:** Eliminate the duplicated `word_key → status` mapping (`applio_progress_api._collect_words` vs `applio_launcher._a11y_terminal_words`) — one AppKit-free helper in `applio_progress_api.py` becomes the single source of truth for the `f"{type}:{name}"` word_key format.

**Files:**
- Modify: `applio_progress_api.py:139-151` (`_collect_words` → delegation; new `terminal_words_from_history`), `applio_launcher.py:5406-5427` (`_a11y_terminal_words` → delegation)
- Test: `tests/test_progress_api.py` (extend; 7 → 8 tests)

**Acceptance Criteria:**
- [ ] `terminal_words_from_history(entries)` exists in `applio_progress_api.py`: skips entries missing any of type/model_name/status, `setdefault` (newest-first wins), `entries=None` → `{}`.
- [ ] Both `_collect_words` and the launcher's `_a11y_terminal_words` delegate to it (no duplicated loop remains in either file).
- [ ] Payload `words` for well-formed history entries is byte-identical to before (existing tests + JS fallback for absent keys unchanged).
- [ ] NOTE — accepted behavior change: `_collect_words` previously defaulted missing fields to `process`/`job`/`completed`; it now skips incomplete entries. The JS consumer already falls back to `"finished"` for absent keys (`assets/applio_a11y.js:242`), so this is a strictness improvement, not a regression. If `tests/test_progress_api.py` asserts the old defaulting, update that assertion in the same commit.
- [ ] Suite prints `(8)`.

**Verify:** `venv_macos/bin/python tests/test_progress_api.py` → `All progress API tests passed (8).`

**Steps:**

- [ ] **Step 1: Write the failing test** — append to `tests/test_progress_api.py`:

```python
def test_terminal_words_from_history_shared_helper():
    entries = [
        {"type": "training", "model_name": "voice", "status": "failed"},
        {"type": "training", "model_name": "voice", "status": "completed"},  # older
        {"type": "extract", "model_name": "", "status": "completed"},  # incomplete
        {"type": "tts", "model_name": "x"},  # incomplete
        None,
    ]
    words = api.terminal_words_from_history(entries)
    assert words == {"training:voice": "failed"}  # setdefault keeps newest; skips gaps
    assert api.terminal_words_from_history(None) == {}
    assert api.terminal_words_from_history([]) == {}
```

Register in `run_all()`, bump the count to `(8)`.

- [ ] **Step 2: Run to verify failure** — `AttributeError: module 'applio_progress_api' has no attribute 'terminal_words_from_history'`.

- [ ] **Step 3: Implement** — in `applio_progress_api.py`, add above `_collect_words` (line ~139):

```python
def terminal_words_from_history(entries):
    """word_key -> terminal status from newest-first history entries.

    Single source of truth for the "{type}:{name}" word_key format, shared
    by the web payload (_collect_words) and the launcher's native
    announcements (_a11y_terminal_words). Skips incomplete entries;
    consumers apply their own display defaults for absent keys.
    """
    words = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        etype = (entry.get("type") or "").strip()
        name = (entry.get("model_name") or "").strip()
        status = (entry.get("status") or "").strip()
        if etype and name and status:
            words.setdefault(f"{etype}:{name}", status)
    return words
```

and replace `_collect_words`'s body (lines 139-151) with:

```python
def _collect_words(launcher):
    try:
        entries = launcher.get_recent_processes(20)
    except Exception:
        return {}
    return terminal_words_from_history(entries)
```

In `applio_launcher.py`, replace `_a11y_terminal_words`'s duplicated loop (lines 5406-5427) with delegation (keep the existing method name, try/except, and logging):

```python
    def _a11y_terminal_words(self):
        """Terminal word map for announcements (shared with the web payload)."""
        try:
            from applio_progress_api import terminal_words_from_history

            return terminal_words_from_history(get_recent_processes(limit=20))
        except Exception:
            logging.exception("[A11y] terminal words unavailable")
            return {}
```

- [ ] **Step 4: Run to verify pass** — `All progress API tests passed (8).` and the full applio_a11y suite still passes (`venv_macos/bin/python tests/test_applio_a11y.py` → 17).

- [ ] **Step 5: Commit** — `git add applio_progress_api.py applio_launcher.py tests/test_progress_api.py && git commit -m "refactor(a11y): single shared terminal-words helper (word_key unification)"`

---

### Task 4: Surface bounded failure log tails in the web payload

**Goal:** When a job fails, the web "Last result" region shows the last log lines (Phase 2 deferral "error surfacing with full log tails" — fork-side portion): the progress route exposes `payload.errors` (bounded), and the JS appends the tail to the persisted terminal text. Spoken announcements stay short (no log spam in the live region).

**Files:**
- Modify: `applio_progress_api.py:118-127` (`build_progress_payload` gains `errors` param), `:203+` (`handle_progress` computes it), new `_recent_error_tails` near `read_log_tail` (`:31-40`)
- Modify: `assets/applio_a11y.js` — terminal push sites (lines ~240-259) + persist loop (~281-283)
- Test: `tests/test_progress_api.py` (7→8 from Task 3, → 11 here), `tests/test_a11y_js_invariants.py` (1 from Task 2, → 2)

**Acceptance Criteria:**
- [ ] `payload["errors"]` is a list of at most 2 entries, newest-first, only statuses `failed`/`error`, each `{"type", "name", "status", "tail"}` with `tail` ≤ 1200 chars (read via the existing seek-based `read_log_tail(path, max_bytes=4096)`, then `[-1200:]`); missing/absent log file → empty `tail`, entry still listed.
- [ ] Live/running jobs still never carry a tail in `jobs` (the unconditional `log_tail` strip in `build_progress_payload` stays).
- [ ] `build_progress_payload` remains pure — errors passed as a parameter.
- [ ] JS: terminal announcements push a third tuple element (the bounded tail suffix, `""` when not applicable); `persistResult` writes `message + " — " + tail`; the spoken `announce()` path is unchanged (no tail). DOM writes remain `textContent`-only.
- [ ] Both suites pass with updated counts (`(11)` and `(2)`).

**Verify:** `venv_macos/bin/python tests/test_progress_api.py && venv_macos/bin/python tests/test_a11y_js_invariants.py` → `(11)` and `(2)` pass lines.

**Steps:**

- [ ] **Step 1: Write the failing tests** — append to `tests/test_progress_api.py`:

```python
def _fake_launcher(history):
    class L:
        def get_recent_processes(self, limit=20):
            return history

    return L()


def test_recent_error_tails_bounded_and_filtered(tmp_path=None):
    import os
    import tempfile

    logdir = tempfile.mkdtemp()
    log = os.path.join(logdir, "train.log")
    with open(log, "w", encoding="utf8") as fh:
        fh.write("x" * 9000 + "TAIL-MARKER")
    history = [
        {"type": "training", "model_name": "voice", "status": "failed",
         "log_path": log},
        {"type": "extract", "model_name": "e", "status": "completed",
         "log_path": log},  # not an error -> excluded
        {"type": "tts", "model_name": "t", "status": "error",
         "log_path": os.path.join(logdir, "missing.log")},  # no file -> empty tail
    ]
    errors = api._recent_error_tails(_fake_launcher(history))
    assert [e["name"] for e in errors] == ["voice", "t"]
    assert errors[0]["tail"].endswith("TAIL-MARKER")
    assert len(errors[0]["tail"]) <= 1200
    assert errors[1]["tail"] == ""


def test_recent_error_tails_limit_two():
    history = [
        {"type": "t", "model_name": f"n{i}", "status": "failed", "log_path": None}
        for i in range(5)
    ]
    errors = api._recent_error_tails(_fake_launcher(history))
    assert len(errors) == 2 and errors[0]["name"] == "n0"  # newest-first, capped


def test_payload_carries_errors_key():
    payload = api.build_progress_payload(
        jobs=[], settings={}, announce_owner="web", now=1.0, words=None,
        errors=[{"type": "training", "name": "voice", "status": "failed",
                 "tail": "boom"}],
    )
    assert payload["errors"][0]["tail"] == "boom"
    assert "errors" in api.build_progress_payload(
        jobs=[], settings={}, announce_owner="web", now=1.0
    )  # default empty list
```

Register in `run_all()`, bump count to `(11)`. Activate `test_failed_tail_wiring_present` in `tests/test_a11y_js_invariants.py`'s `run_all()` (count `(2)`).

- [ ] **Step 2: Run to verify failure** — `AttributeError: _recent_error_tails` / `TypeError: unexpected keyword 'errors'` / JS invariant fails.

- [ ] **Step 3: Implement (API)** — in `applio_progress_api.py`, add near `read_log_tail`:

```python
RECENT_ERRORS_LIMIT = 2
ERROR_TAIL_BYTES = 4096
ERROR_TAIL_CHARS = 1200


def _recent_error_tails(launcher):
    """Bounded failure tails from history for the web payload's errors list."""
    try:
        entries = launcher.get_recent_processes(20)
    except Exception:
        return []
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        status = (entry.get("status") or "").strip().lower()
        if status not in ("failed", "error"):
            continue
        log = entry.get("log_path") or entry.get("log_file")
        tail = ""
        if log and os.path.exists(log):
            try:
                tail = read_log_tail(log, max_bytes=ERROR_TAIL_BYTES)[-ERROR_TAIL_CHARS:]
            except Exception:
                tail = ""
        out.append(
            {
                "type": entry.get("type") or "process",
                "name": entry.get("model_name") or "job",
                "status": status,
                "tail": tail,
            }
        )
        if len(out) >= RECENT_ERRORS_LIMIT:
            break
    return out
```

Extend `build_progress_payload` signature (line 118) with `errors=None` and add to the payload dict (next to `words`): `"errors": list(errors or []),`. In `handle_progress`, where `words` is computed for the payload, add `errors=_recent_error_tails(launcher)` to the `build_progress_payload(...)` call (the launcher variable is the one resolved via `_resolve_launcher()`; if it is None, pass `errors=None`).

- [ ] **Step 4: Implement (JS)** — in `assets/applio_a11y.js`, add a helper near the other small helpers:

```javascript
  function failedTail(errors, job) {
    var list = errors || [];
    for (var i = 0; i < list.length; i++) {
      var e = list[i];
      if (e.type === job.type && e.name === job.name && e.tail) {
        return String(e.tail).slice(-400);
      }
    }
    return "";
  }
```

At the top of the payload-processing function, where `jobs`/`words` are destructured (~line 215-219), also extract `errors`. Change the two terminal push sites (disappearance branch ~line 240-245 and status-transition branch ~line 253-259) to carry the tail as a third tuple element:

```javascript
        var word = words[info.word_key] || "finished";
        var tail = (word === "failed" || word === "error")
          ? failedTail(errors, info) : "";
        announcements.push(["terminal", jobLabel(info) + " " + word, tail]);
```

```javascript
          var tail = (job.status === "failed" || job.status === "error")
            ? failedTail(errors, job) : "";
          announcements.push(["terminal", jobLabel(job) + " " + job.status, tail]);
```

and the persist loop (~line 281-283):

```javascript
    announcements.forEach(function (a) {
      if (a[0] === "terminal") {
        persistResult(a[2] ? a[1] + " — " + a[2] : a[1]);
      }
    });
```

(The spoken `announce(a[1])` loop is untouched — VoiceOver must not read raw logs.)

- [ ] **Step 5: Run to verify pass** — `(11)` and `(2)` pass lines; also rerun `tests/test_applio_a11y.py` (17) as a neighbor check.

- [ ] **Step 6: Commit** — `git add applio_progress_api.py assets/applio_a11y.js tests/test_progress_api.py tests/test_a11y_js_invariants.py && git commit -m "feat(a11y): bounded failure log tails in web payload + Last-result region"`

---

### Task 5: Blur-time validation for all 13 Browse path fields

**Goal:** Typed paths get validated when the field loses focus (Phase 2 deferral "typed-path on-change validation for the remaining fields"): `~` expands (field self-heals), missing paths and wrong types warn via `gr.Warning` (the announced toast channel), wired by the Browse patcher next to every field it already touches.

**Files:**
- Modify: `applio_browse_ui.py` (new `_make_validator` + `attach_path_validation`)
- Modify: `patches/patch_browse_buttons.py:119-122` (generated-line template gains the validation call)
- Test: `tests/test_browse_ui.py` (5 → 8), `tests/test_patch_fixtures.py` (assertion extension; count stays 5)

**Acceptance Criteria:**
- [ ] `attach_path_validation(target, mode)` wires `target.blur(fn=_make_validator(mode), outputs=[target])` — works for `gr.Textbox` AND `gr.Dropdown` targets (both expose `.blur` in gradio 6.20.0; verified `Events.blur` at `dropdown.py:45`).
- [ ] Validator: empty value → returned unchanged, no warning; `~/x` → expanded value returned (self-heal); nonexistent path → `gr.Warning("Path does not exist: …")` and the expanded value returned; `mode="folder"` on a file / `mode in ("file","pth")` on a directory → `gr.Warning("Not a folder…"/"Not a file…")`.
- [ ] The patcher's injected block per field now contains both lines (browse button + validation attach) for all 13 fields; fixture test asserts `attach_path_validation(` appears once per field var.
- [ ] Existing 5 browse tests still pass (the `_picker` seam untouched); suite prints `(8)`.

**Verify:** `venv_macos/bin/python tests/test_browse_ui.py && venv_macos/bin/python tests/test_patch_fixtures.py` → `(8)` and `(5)` pass lines.

**Steps:**

- [ ] **Step 1: Write the failing tests** — append to `tests/test_browse_ui.py`:

```python
def _with_recorded_warnings(fn):
    import gradio as gr

    calls = []
    orig = gr.Warning
    gr.Warning = lambda msg, *a, **k: calls.append(msg)
    try:
        result, warnings = fn(), calls
    finally:
        gr.Warning = orig
    return result, warnings


def test_validator_expands_tilde_and_self_heals():
    v = applio_browse_ui._make_validator("file")
    out, warnings = _with_recorded_warnings(lambda: v("~/no/such/dir"))
    assert out.startswith("/") and "~" not in out
    assert warnings == []  # nonexistent but no type check fires for unknown path? NO:
```

CAREFUL — `~/no/such/dir` does not exist, so the missing-path warning DOES fire. Correct test set:

```python
def test_validator_expands_tilde_and_self_heals():
    import os

    v = applio_browse_ui._make_validator("file")
    home = os.path.expanduser("~")
    out, warnings = _with_recorded_warnings(lambda: v("~"))
    assert out == home and warnings == []  # ~ exists; normalized value self-heals


def test_validator_warns_on_missing_path():
    v = applio_browse_ui._make_validator("file")
    out, warnings = _with_recorded_warnings(lambda: v("/no/such/path.abc"))
    assert out == "/no/such/path.abc"
    assert warnings and warnings[0].startswith("Path does not exist")


def test_validator_warns_on_wrong_type():
    import os

    v = applio_browse_ui._make_validator("folder")
    out, warnings = _with_recorded_warnings(lambda: v(__file__))  # a file, not folder
    assert warnings and warnings[0].startswith("Not a folder")
    assert out == os.path.abspath(__file__) or out == __file__
```

Register in `run_all()`, bump count to `(8)`. In `tests/test_patch_fixtures.py`, extend the browse-buttons fixture assertion to also require, per field var, `f"applio_browse_ui.attach_path_validation({var},"` in the patched output (the file already asserts the browse line per var — mirror it).

- [ ] **Step 2: Run to verify failure** — `AttributeError: _make_validator` and fixture assertion misses.

- [ ] **Step 3: Implement** — in `applio_browse_ui.py`, after `_make_handler`:

```python
def _make_validator(mode):
    def _validate(current_value):
        import os

        import gradio as gr

        if not current_value or not str(current_value).strip():
            return current_value
        value = os.path.expanduser(str(current_value).strip())
        if not os.path.exists(value):
            gr.Warning(f"Path does not exist: {value}")
        elif mode == "folder" and not os.path.isdir(value):
            gr.Warning(f"Not a folder: {value}")
        elif mode in ("file", "pth") and not os.path.isfile(value):
            gr.Warning(f"Not a file: {value}")
        return value

    return _validate


def attach_path_validation(target, mode):
    """Blur-time validation for a path field: expands ~, warns (announced
    toast channel) when the typed path is missing or the wrong type. Wired
    by patch_browse_buttons next to every Browse button."""
    target.blur(fn=_make_validator(mode), outputs=[target])
```

In `patches/patch_browse_buttons.py`, extend the generated-line template (lines 119-122):

```python
        line = (
            f"\n{indent}_applio_browse_{var} = applio_browse_ui.browse_button("
            f'"{mode}", {var}, elem_id="browse-{var}")\n'
            f"{indent}applio_browse_ui.attach_path_validation({var}, \"{mode}\")\n"
        )
```

- [ ] **Step 4: Run to verify pass** — `(8)` and `(5)`; then run the patcher directly against a temp copy and `git checkout` any real sources if touched:

```bash
venv_macos/bin/python patches/patch_browse_buttons.py tabs/train/train.py
git status --short tabs/   # restore if dirty: git checkout -- tabs/train/train.py
```

- [ ] **Step 5: Commit** — `git add applio_browse_ui.py patches/patch_browse_buttons.py tests/test_browse_ui.py tests/test_patch_fixtures.py && git commit -m "feat(a11y): blur-time path validation on all Browse fields (announced warnings)"`

---

### Task 6: Patcher anchor-miss exit codes — miss becomes fatal (exit 2)

**Goal:** A post-upstream-sync anchor miss can never again silently skip a patcher: every `patch_*.py` exits `2` on anchor miss, and `pre_build_patch()` in `build_macos.py` fails the build on ANY nonzero patcher exit, listing all failures. Usage guards keep `1`; injected-string `sys.exit(1)` sites and `download_pretraineds.py` are exempt.

**Files:**
- Modify: all `patches/patch_*.py` exit sites (inventory below), `build_macos.py:941-977` (the patch loop), `CLAUDE.md` (convention text)
- Test: `tests/test_patcher_exit_codes.py` (NEW)

**Exit-site inventory (verified 2026-08-21):**
- Single-expression miss sites — change `sys.exit(0 if X else 1)` to `sys.exit(0 if X else 2)`: `patch_browse_buttons.py:197`, `patch_inference_progress.py:329`, `patch_data_paths.py:199`, `patch_loading_html.py:235`, `patch_custom_pretrained_paths.py:140`, `patch_extract_error_logging.py:88`, `patch_preflight_validation.py:109`, `patch_mute_paths.py:90`, `patch_preprocess_error_logging.py:82`, `patch_stop_infer.py:105`, `patch_static_resources.py:364`, `patch_download_paths.py:116`, `patch_pretrained_selector.py:138`, `patch_refinegan_legacy_infer.py:186`, `patch_stop_feedback.py:112`, `patch_f0_model_paths.py:112`, `patch_refinegan_legacy_train.py:198`, `patch_multiprocessing.py:172`, `patch_refinegan_legacy_discriminator.py:221`, `patch_subprocess_validation.py:279`, `patch_version_checker.py:95`, `patch_train_44100.py:263`, `patch_process_tracking.py:663`, `patch_train_paths.py:117`.
- Multi-line miss exits (the `else`/fallback of a success check, or after a "Pattern not found" print) — change the `1` to `2`: `patch_dataset_paths.py:229`, `patch_inference_progress.py:325`, `patch_stop_infer.py:101`, `patch_progress_routes.py:64`, `patch_refinegan_legacy_infer.py:182`, `patch_refinegan_legacy.py:104`, `patch_refinegan_legacy_train.py:195` (CHECK: this may be the argv usage guard — classify by context, see rule), `patch_multiprocessing.py:169`, `patch_refinegan_legacy_discriminator.py:217`, `patch_web_a11y_payload.py:89`, `patch_train_44100.py:260`.
- Usage guards (`if len(sys.argv) < 2: ... sys.exit(1)`) — KEEP at `1`.
- DO NOT TOUCH: `patch_refinegan_legacy_train.py:102` and `:175` (`sys.exit(1)"""` — inside injected triple-quoted code), `patches/download_pretraineds.py` (downloader, own invocation at `build_macos.py:471`).
- **Classification rule for every site:** usage guard (an `argv`/`argc` check within the previous ~4 lines) → keep 1; anchor/pattern miss (after a "Pattern not found"/"patch failed" print, or the failure branch of a success check) → 2; inside a triple-quoted string → untouched. Also update each patcher's docstring "Exit codes:" line (e.g. `patch_browse_buttons.py:19`) to `0 patched/already, 2 anchor miss`.

**Acceptance Criteria:**
- [ ] Every `patches/patch_*.py` exits `2` on anchor miss and `0` on patched/already; usage guards still exit `1`.
- [ ] `build_macos.py`'s patch loop: exit `0` tolerated; ANY other code (2 = anchor miss, 1/3+ = crash or usage) is collected and the build FAILS after the loop with a message naming every failing patcher and pointing at CLAUDE.md's "Re-pointing patches after an upstream sync".
- [ ] The stale comment `# 0 = patched, 1 = already patched` is replaced with accurate text.
- [ ] CLAUDE.md's re-pointing section documents the new convention.
- [ ] Behavioral test: 3 representative patchers against temp copies → pristine exit 0, re-run exit 0, mutated anchor exit 2.
- [ ] Source-scan test: no `sys.exit(1)` remains in `patches/patch_*.py` except usage guards, the two injected-string sites, and `download_pretraineds.py`.
- [ ] `venv_macos/bin/python build_macos.py --help` still exits 0 (module intact).

**Verify:** `venv_macos/bin/python tests/test_patcher_exit_codes.py && venv_macos/bin/python build_macos.py --help` → `All patcher exit-code tests passed (2).` + argparse help + exit 0.

**Steps:**

- [ ] **Step 1: Write the failing tests** — create `tests/test_patcher_exit_codes.py`:

```python
# tests/test_patcher_exit_codes.py
"""Anchor-miss exit codes: 0 = patched/already, 2 = anchor miss (fatal).
NEVER import build_macos here (module-level PyInstaller build).
Run: venv_macos/bin/python tests/test_patcher_exit_codes.py"""

import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# (patcher, source file, anchor text to mutate). "file"-type arg unless the
# patcher needs the directory -- both included to cover both conventions.
CASES = [
    ("patches/patch_progress_routes.py", "app.py", "prevent_thread_lock="),
    ("patches/patch_browse_buttons.py", "tabs/train/train.py", "dataset_path"),
    ("patches/patch_train_paths.py", "tabs/train/train.py", "dataset_path"),
]

EXEMPT = {"download_pretraineds.py"}  # downloader, not an anchor patcher


def _run(patcher, target):
    return subprocess.run(
        [PY, os.path.join(REPO, patcher), target], capture_output=True, text=True
    )


def test_patcher_exit_codes_behavioral():
    for patcher, source, anchor in CASES:
        tmp = tempfile.mkdtemp()
        dst = os.path.join(tmp, os.path.basename(source))
        shutil.copy(os.path.join(REPO, source), dst)
        first = _run(patcher, dst)
        assert first.returncode == 0, (patcher, first.returncode, first.stdout)
        again = _run(patcher, dst)  # already-patched input
        assert again.returncode == 0, (patcher, again.returncode, again.stdout)
        # Mutate the anchor in a FRESH copy -> miss -> exit 2.
        shutil.copy(os.path.join(REPO, source), dst)
        with open(dst, encoding="utf8") as fh:
            content = fh.read()
        assert anchor in content, (patcher, anchor)
        with open(dst, "w", encoding="utf8") as fh:
            fh.write(content.replace(anchor, anchor + "_MUTATED", 1))
        miss = _run(patcher, dst)
        assert miss.returncode == 2, (patcher, miss.returncode, miss.stdout)


def test_no_unclassified_exit1_remains():
    # Every remaining sys.exit(1) in patches/patch_*.py must be a usage guard
    # (argv check nearby) or live on a line that also closes a triple-quoted
    # injected block (the two known sites end with 'sys.exit(1)"""').
    violations = []
    patches_dir = os.path.join(REPO, "patches")
    for name in sorted(os.listdir(patches_dir)):
        if not (name.startswith("patch_") and name.endswith(".py")) or name in EXEMPT:
            continue
        with open(os.path.join(patches_dir, name), encoding="utf8") as fh:
            lines = fh.readlines()
        for i, line in enumerate(lines):
            if "sys.exit(1)" not in line:
                continue
            if '"""' in line:  # injected-string site
                continue
            context = "".join(lines[max(0, i - 4):i + 1])
            if "argv" not in context and "argc" not in context:
                violations.append(f"{name}:{i + 1}")
    assert not violations, f"unclassified sys.exit(1) sites: {violations}"


def run_all():
    test_patcher_exit_codes_behavioral()
    test_no_unclassified_exit1_remains()
    print("All patcher exit-code tests passed (2).")


if __name__ == "__main__":
    run_all()
```

NOTE on CASES: `patch_progress_routes.py` is registered as "file"-type and takes the file path; `patch_browse_buttons`/`patch_train_paths` are "dir"-type — passing the FILE path works for them too because they resolve `os.path.join(base, filename)` from the argument's directory ONLY when given a dir; CHECK each patcher's `__main__` arg handling first and, where a patcher requires the directory, copy the source into `tmp/<original-parent-name>/<basename>` and pass `tmp/<original-parent-name>` instead. If a chosen CASE patcher's conventions make this awkward, substitute another patcher from the inventory — keep exactly 3 covering both arg types. If the anchor text appears multiple times, mutate ALL occurrences (`.replace(anchor, anchor + "_MUTATED")` without the count) to guarantee the miss.

- [ ] **Step 2: Run to verify failure** — behavioral cases exit 1 (not 2) on miss; source-scan lists the multi-line miss sites.

- [ ] **Step 3: Implement** — apply the exit-site inventory classification across `patches/patch_*.py`; update docstring Exit-codes lines. In `build_macos.py`, replace the loop tail (lines 974-975) and add collection — final shape:

```python
    patch_failures = []  # (description, exit code) — any nonzero fails the build

    for patcher_path, source_file, description, patcher_type in patches_to_apply:
        ...existing body...
        result = subprocess.run(
            [sys.executable, patcher_path, patcher_arg], capture_output=True, text=True
        )

        for line in result.stdout.strip().split("\n"):
            if line:
                print(f"    {line}")

        if result.returncode == 0:
            pass  # 0 = patched or already applied
        else:
            # 2 = anchor miss (upstream moved the anchor); anything else is a
            # crash or invocation failure. Both ship a broken app if skipped.
            patch_failures.append((description, result.returncode))

    if patch_failures:
        for description, code in patch_failures:
            print(f"  PATCH FAILURE: {description} (exit {code})")
        raise SystemExit(
            "Patchers failed (anchor miss = exit 2, see CLAUDE.md "
            "'Re-pointing patches after an upstream sync')."
        )

    return patched_files
```

Update `CLAUDE.md`'s "Re-pointing patches after an upstream sync" bullet to record: patchers exit `0` (patched/already) or `2` (anchor miss); the build fails on any nonzero exit listing all failures; usage guards exit `1` but never fire in the build loop.

- [ ] **Step 4: Run to verify pass** — `All patcher exit-code tests passed (2).` + `venv_macos/bin/python build_macos.py --help` exits 0. Confirm the repo tree has NO patch markers left by the behavioral tests (they operate on temp copies; if any patcher was run against real sources during debugging: `git checkout -- assets core.py rvc tabs app.py`).

- [ ] **Step 5: Commit** — `git add patches/ build_macos.py CLAUDE.md tests/test_patcher_exit_codes.py && git commit -m "build: anchor-miss exit code 2 + fail build on any patcher failure"`

---

### Task 7: i18n-wrap the remaining native English clusters

**Goal:** Route the last hardcoded native-side English strings through `applio_i18n.native_tr` so the overrides file can translate them: loading-screen stages, dashboard status strings, About alert text, and dynamic process-status titles.

**Files:**
- Modify: `macos_wrapper.py:1173-1372` (loading stages), `applio_launcher.py:1189, 2047-2049, 2201-2218, 2231, 3365, 3567-3619, 3844-3851, 5797-5826` (dashboard/About/status maps)
- Test: `tests/test_applio_i18n.py` (8 → 9 after Task 1)

**Site list (string → file):**
- `macos_wrapper.py`: `"Initializing environment..."` (1173), `"Allocating memory..."` (1174), `"Fetching {basename}"` (1296), `"Installing {pkgs}"` (1313), `"Checking Prerequisites..."` (1320), `"Accelerating with {device}"` (1327), `"Loading Neural Networks..."` (1334), `"Hydrating {model}..."` (1342), `"Launching User Interface..."` (1353), `"Configuring Runtime..."` (1372).
- `applio_launcher.py`: `"Running"` (1189), `"Completed"` (2047-2049), `"Pause"` / `"Status: Running"` / `"Running"` / `"Paused"` badge+labels (2201-2218), `"Error"` (2231), `{"running": "Running", "cancelling": "Stopping…"}` (3365), `"Stopping…"` (3567, 3593), `"Paused" if … else "Running"` (3619), status-title map values `{"completed": "Completed", "failed": "Failed", "error": "Failed", "cancelled": "Cancelled", "canceled": "Cancelled", "interrupted": "Interrupted"}` (3844-3851), About alert informative lines (5808-5814: `"Voice Conversion Application"`, `"Based on RVC (Retrieval-Based Voice Conversion)"`, `"Native macOS port by Frédéric Guigand"`, `"© 2024-2026 IA Hispano"`).

**Acceptance Criteria:**
- [ ] Every listed literal is wrapped so `native_tr` receives it (or its format template, e.g. `_t("Fetching {name}").format(name=basename)`) at render/call time — lazy `import applio_i18n` / `_t = applio_i18n.native_tr` inside the function, per the pattern at `applio_launcher.py:5836-5838`. Status-map VALUES are translated where the map is built (raw status strings stay the KEYS); `'failed'` and `'error'` collapse to the SAME translated word so one override covers both.
- [ ] With no overrides file, behavior is byte-identical to today (English keys returned unchanged).
- [ ] New cluster-keys test passes: (a) an overrides tree translating 4+ sample cluster strings returns them via `native_tr`; (b) a source scan asserts every listed literal still appears in its owning file (guards key drift).
- [ ] Suites: `test_applio_i18n.py` prints `(9)`; `test_applio_a11y.py` still 17; `test_menu_spec.py` still 15.

**Verify:** `venv_macos/bin/python tests/test_applio_i18n.py && venv_macos/bin/python tests/test_applio_a11y.py` → `(9)` and `(17)`.

**Steps:**

- [ ] **Step 1: Write the failing test** — append to `tests/test_applio_i18n.py`:

```python
CLUSTER_KEYS = [
    ("macos_wrapper.py", "Initializing environment..."),
    ("macos_wrapper.py", "Loading Neural Networks..."),
    ("applio_launcher.py", "Status: Running"),
    ("applio_launcher.py", "Stopping…"),
    ("applio_launcher.py", "Based on RVC (Retrieval-Based Voice Conversion)"),
]


def test_native_clusters_translatable_and_stable():
    tmp = _make_tree("en_US", extra_keys={})
    overrides = {
        "en_US": {
            "Initializing environment...": "Inicializando entorno...",
            "Loading Neural Networks...": "Cargando redes neuronales...",
        }
    }
    with open(
        os.path.join(tmp, "assets", "applio_i18n_overrides.json"), "w", encoding="utf8"
    ) as fh:
        json.dump(overrides, fh, ensure_ascii=False)
    tr = applio_i18n.NativeI18n(base_paths=[tmp])
    assert tr("Initializing environment...") == "Inicializando entorno..."
    assert tr("Loading Neural Networks...") == "Cargando redes neuronales..."
    # Source-scan: the cluster literals stay verbatim in their owning files so
    # the keys (and any overrides written against them) never drift.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fname, literal in CLUSTER_KEYS:
        with open(os.path.join(repo, fname), encoding="utf8") as fh:
            assert literal in fh.read(), f"{fname} lost key {literal!r}"
```

Register in `run_all()`, bump count to `(9)`.

- [ ] **Step 2: Run to verify failure** — the source-scan branch fails for the not-yet-wrapped literals is NOT how it fails (the literals exist today); it fails only if wrapping REWRITES them. So: run the test — it should PASS pre-implementation for the scan, and the overrides assertions pass only if `_make_tree("en_US")` + overrides work (they do). THEREFORE the meaningful failing signal is different: before wrapping, `native_tr` never receives these keys, which this test cannot see directly. Add the load-bearing assertion — after Step 3 lands, grep-verify wrapping:

```bash
rg -c "native_tr|_t\(" macos_wrapper.py applio_launcher.py
```

Before Step 3: `macos_wrapper.py` shows 0 matches (that IS the failing signal; record it). Adjust the test to ALSO assert wrapping exists (source scan for `_t(` usage count ≥ 10 in each file):

```python
    for fname in ("macos_wrapper.py", "applio_launcher.py"):
        with open(os.path.join(repo, fname), encoding="utf8") as fh:
            src = fh.read()
        assert src.count("_t(") >= 10 or src.count("native_tr") >= 10, (
            f"{fname}: cluster strings not routed through native_tr"
        )
```

Now Step 2 genuinely fails (macos_wrapper has no `_t(` today).

- [ ] **Step 3: Implement** — wrap every site in the list. Representative transformations (apply the same shape everywhere):

```python
# macos_wrapper.py loading stage (was: self.sub_heading = "Initializing environment...")
import applio_i18n
_t = applio_i18n.native_tr
self.sub_heading = _t("Initializing environment...")
self.technical_detail = _t("Allocating memory...")
```

```python
# Formatted stage (was: f"Fetching {basename}" / "Fetching {basename}".format(...)):
stage = _t("Fetching {basename}").format(basename=basename)
```

```python
# applio_launcher dashboard (was: self.pause_btn.setTitle_("Pause")):
self.pause_btn.setTitle_(_t("Pause"))
self.status_label.setStringValue_(_t("Status: Running"))
self.status_badge.setStringValue_(_t("Running"))
```

```python
# Status-title map (3844-3851) — translate VALUES, keep raw keys; 'failed' and
# 'error' share ONE translated word so a single override covers both:
_failed = _t("Failed")
TITLES = {
    "completed": _t("Completed"),
    "failed": _failed,
    "error": _failed,
    "cancelled": _t("Cancelled"),
    "canceled": _t("Cancelled"),
    "interrupted": _t("Interrupted"),
}
```

```python
# About alert (5808-5814):
informative = "\n".join([
    _t("Voice Conversion Application"),
    _t("Based on RVC (Retrieval-Based Voice Conversion)"),
    "",
    _t("Native macOS port by Frédéric Guigand"),
    _t("© 2024-2026 IA Hispano"),
])
```

The `_t = applio_i18n.native_tr` import goes at the TOP of each function that uses it (lazy — `applio_i18n` is AppKit-free so import order is safe, but keep the established call-time pattern). Where a literal appears inside an f-string with variables, translate the TEMPLATE then `.format(...)` — never translate the concatenated result.

- [ ] **Step 4: Run to verify pass** — `(9)`, plus `test_applio_a11y.py` (17) and `test_menu_spec.py` (15) as neighbor checks (announcement templates must be unaffected — their keys are unchanged English).

- [ ] **Step 5: Commit** — `git add macos_wrapper.py applio_launcher.py tests/test_applio_i18n.py && git commit -m "feat(i18n): wrap remaining native English clusters (loading, dashboard, About, status titles)"`

---

### Task 8: Documentation — audit §7, CHANGELOG, CLAUDE.md

**Goal:** Record Phase 3 (fork-local) delivery in the three docs that track it, and stage the upstream-program pointer for the post-pass plan.

**Files:**
- Modify: `ACCESSIBILITY_AUDIT.md` (§7), `CHANGELOG.md` ([Unreleased]), `CLAUDE.md` (a11y section tail + test list)

**Acceptance Criteria:**
- [ ] Audit §7 "Phase 3 additions born during Phase 2 execution": each of the 5 bullets annotated DELIVERED with its commit hash; the "Deferred to Phase 3" items log-tail + typed-path marked delivered (fork side); a new note states the upstream Applio/gradio PR program is pending the manual VoiceOver pass and gets its own plan (gate quote included).
- [ ] CHANGELOG `[Unreleased]` gains a Phase 3 section listing all 7 deliverables + the patcher exit-code convention change (build now fails on anchor miss — behavior change for maintainers).
- [ ] CLAUDE.md: a11y Phase 2 section gains a short Phase 3 (fork-local) paragraph (what shipped, where tests live); the "Re-pointing patches" convention text already updated by Task 6 is cross-checked for consistency; the Phase 2 test-list sentence extended with `test_a11y_js_invariants.py` + `test_patcher_exit_codes.py`.
- [ ] No upstream files touched; `git status` clean apart from these three files.

**Verify:** `git diff --stat` shows exactly the three doc files; `rg -n "Phase 3" ACCESSIBILITY_AUDIT.md | tail -5` shows the DELIVERED annotations.

**Steps:**

- [ ] **Step 1: Edit the three docs** per the AC (content: deliverable lists + commit hashes from Tasks 1-7, gathered via `git log --oneline main..feat/a11y-phase3`).
- [ ] **Step 2: Verify** the diff touches only the three files and every claim matches a real commit hash.
- [ ] **Step 3: Commit** — `git add ACCESSIBILITY_AUDIT.md CHANGELOG.md CLAUDE.md && git commit -m "docs(a11y): Phase 3 fork-local delivery notes + upstream-program staging"`

---

### Task 9: Full-chain validation + cert-free frozen build

**Goal:** Prove the branch is regression-free end to end: every suite green with the new counts, a cert-free frozen build completes with all patchers exiting 0, the bundle carries the updated payload, and the running app serves the progress route with the new `errors` key.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task enforces the user's ruling from the current conversation (2026-08-21, verbatim): "no PR until we have everything 100% test, verified, and confirmed working with 0 regression bug." It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured (suite pass lines, BUILD COMPLETE, stat timestamp, curl JSON).

**Files:**
- No source modifications (validation only). Build artifacts under `build/`, `dist/` (gitignored).

**Acceptance Criteria:**
- [ ] All 9 script suites green: `test_applio_a11y` (17), `test_menu_spec` (15), `test_native_picker` (3), `test_browse_ui` (8), `test_progress_api` (11), `test_patch_fixtures` (5), `test_applio_i18n` (9), `test_a11y_js_invariants` (2), `test_patcher_exit_codes` (2), plus `-m pytest tests/test_inference_progress.py` (5) — 77 total (adjust the expected total if implementation legitimately shifted a count; report any shift).
- [ ] `venv_macos/bin/python build_macos.py` (cert-free smoke) completes with `BUILD COMPLETE`, as the FINAL command of a background run (no trailing `echo` masking the exit code), and the log shows every `Patching:` line with no `PATCH FAILURE`.
- [ ] Post-build: `git status` shows no upstream files with patch markers; restore with `git checkout -- assets core.py rvc tabs app.py` if `tabs/train/train.py` or others are dirty (known behavior).
- [ ] Bundle checks: `stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio` timestamp AFTER the last commit; `dist/Applio.app/Contents/Resources/assets/applio_a11y.js` contains `failedTail` and `#browse-record_audio_path`.
- [ ] Boot smoke: launch `dist/Applio.app`, find the gradio port in `~/Library/Logs/Applio/applio_launcher.log`, `curl -s "http://127.0.0.1:<port>/applio-a11y/progress?client=web"` returns JSON containing `"errors"`, quit via `osascript -e 'tell application "Applio" to quit'`.
- [ ] No pushes, no PRs, no tags (hard gate — branch stays local).

**Verify:** the suite commands + build command below, all green/complete.

**Steps:**

- [ ] **Step 1: Run the full chain**

```bash
for t in test_applio_a11y test_menu_spec test_native_picker test_browse_ui \
         test_progress_api test_patch_fixtures test_applio_i18n \
         test_a11y_js_invariants test_patcher_exit_codes; do
  venv_macos/bin/python tests/$t.py || exit 1
done
venv_macos/bin/python -m pytest tests/test_inference_progress.py -q
```

- [ ] **Step 2: Cert-free build (background-safe)** — ensure no Applio process runs from `dist/` first (`osascript -e 'tell application "Applio" to quit'` + `sleep 3`), then as the run's LAST command:

```bash
venv_macos/bin/python build_macos.py
```

- [ ] **Step 3: Post-build hygiene + bundle checks** per the AC (`git checkout --` restore, `stat`, `rg failedTail dist/Applio.app/Contents/Resources/assets/applio_a11y.js`).

- [ ] **Step 4: Boot smoke** per the AC; capture the curl output as evidence.

- [ ] **Step 5: Report** — no commit (validation only); the implementer's report carries the evidence (suite lines, BUILD COMPLETE, stat, curl JSON head).

---

## Self-Review (completed at write time)

1. **Spec coverage:** audit §7 additions — patcher exit codes (T6), aria-pressed scoping (T2), i18n guards (T1), word-map unification (T3), English clusters (T7) ✓; Phase 2 deferrals — log-tail surfacing (T4), typed-path validation (T5) ✓; docs (T8) + whole-branch validation (T9) ✓. Out of scope by recorded decision: upstream Applio/gradio PRs (separate post-pass plan).
2. **Placeholder scan:** no TBD/TODO; every code step carries real code; Task 6's CASES carries a verified fallback instruction (substitute patchers / handle dir-type args) rather than a blank.
3. **Type consistency:** `terminal_words_from_history(entries)` defined in T3 and consumed by T3 (both call sites) and referenced by T4's neighborhood (no signature drift); `attach_path_validation(target, mode)` defined in T5 and emitted by T5's patcher template only; `failedTail(errors, job)` defined and used within T4's JS edits; `errors=None` param on `build_progress_payload` introduced in T4 and asserted in T4's tests.
4. **Known deliberate roughness:** Task 6's per-site line numbers are a verified snapshot — the classification RULE governs if lines drift; Task 7's test initially passes its scan half (documented, with the added wrapping-count assertion as the real failing signal).
