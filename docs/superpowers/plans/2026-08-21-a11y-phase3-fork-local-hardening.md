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

and replace the system-locale candidate logic in `_resolve_from_config` (currently lines 73-82, the `sys_locale = ...` block — keep the `break` at line 83 and the surrounding `try/except (OSError, ValueError)` untouched) with:

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

(`sorted()` departs from upstream's raw `Path.glob` order on purpose: glob order is filesystem-dependent, and deterministic resolution keeps the new test stable. Note for the test: `_mod._locale.getdefaultlocale = lambda: (...)` rebinds the attribute on the shared `locale` MODULE (applio_i18n did `import locale as _locale`), so it affects every module during the test — acceptable in these serial script-style suites because the `finally:` restores it before any other code reads it.)

- [ ] **Step 4: Run to verify pass** — `All applio_i18n tests passed (8).`

- [ ] **Step 5: Commit** — `git add applio_i18n.py tests/test_applio_i18n.py && git commit -m "fix(i18n): upstream-accurate locale prefix-glob + corrupt-JSON guards"`

---

### Task 2: Scope healRecordToggles to the realtime record section

**Goal:** Stop stamping `aria-pressed` on every Start/Stop-labeled button in the document; anchor it to the realtime record toggle's container via the fork-injected `#browse-record_audio_path` Browse button, so the momentary engine Start/Stop pair (`tabs/realtime/realtime.py:941-942`) is never mislabeled as a toggle.

**Files:**
- Modify: `assets/applio_a11y.js:103-110` (`healRecordToggles`; call sites at 167 and 308 unchanged)
- Test: `tests/test_a11y_js_invariants.py` (NEW — source-invariant tests for the JS payload; no browser harness exists in-repo)

**Scope selector — verified against the installed gradio 6.20.0 bundle:** the scope is the ancestor **`.gr-accordion`** (the existing live-verified `ACCORDION_BLOCK`), NOT `.form`/`gradio-column`:
- `gradio-column` does not exist — the only custom element gradio 6.20.0 registers is `gradio-app` (`index-9Ev7iYt6.js`: `customElements.define("gradio-app", …)`); a Column renders a plain `<div class="column …">` (`Index.svelte_svelte_type_style_lang-Cf19ZTCK.js`: `` u(l,1,`column ${i??""}`,"svelte-siq5d6",…) ``).
- `.form` IS real (`BaseForm-CtCLD5Mv.js` renders `class="form svelte-…"`) but is the wrapper of FormComponents (Textbox/Dropdown/Radio). `gr.Button` is `Button(Component)`, NOT a FormComponent (`components/button.py:20`), so the Browse button has no `.form` of its own, and the record toggle is NOT inside the path field's Column anyway — `tabs/realtime/realtime.py:1091-1111` puts `record_audio_path` inside `with gr.Column():` and the `record_audio = gr.Button(i18n("Start"))` toggle as a SIBLING of that Column, both children of the `gr.Accordion("Record Audio (Optional)")`. The smallest ancestor containing BOTH the anchor and the toggle is the accordion.
- The engine `start_button`/`stop_button` pair (`realtime.py:940-942`) sits at the top of `with gr.Blocks() as ui:` — outside every accordion — so an accordion scope can never reach it.

**Acceptance Criteria:**
- [ ] `healRecordToggles` resolves `#browse-record_audio_path`, scopes to `anchor.closest(ACCORDION_BLOCK)` (`.gr-accordion`), and only stamps buttons inside that scope.
- [ ] The function no longer calls document-wide `querySelectorAll("button")`.
- [ ] When the anchor (or its accordion) is absent (page without the realtime tab mounted), the function is a no-op.
- [ ] New suite passes: `All a11y JS invariant tests passed (1).` (Task 4 adds a second test.)

**Verify:** `venv_macos/bin/python tests/test_a11y_js_invariants.py` → `All a11y JS invariant tests passed (2).`

**Steps:**

- [ ] **Step 1: Write the failing test** — create `tests/test_a11y_js_invariants.py` (Task-2 state: ONE test; Task 4 appends the second):

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
    assert "ACCORDION_BLOCK" in body, (
        "scope must be the live-verified .gr-accordion container"
    )


def run_all():
    test_heal_record_toggles_scoped_to_browse_anchor()
    print("All a11y JS invariant tests passed (1).")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 2: Run to verify failure** — the scoping assertions fail (current function scans `document.querySelectorAll("button")` and has no anchor/`closest`/`ACCORDION_BLOCK` usage).

- [ ] **Step 3: Implement** — replace `healRecordToggles` in `assets/applio_a11y.js` (lines 103-110) with:

```javascript
  function healRecordToggles() {
    // Scoped to the realtime "Record Audio (Optional)" accordion: the
    // fork-injected Browse button for record_audio_path is the only stable
    // fork-controlled DOM anchor in it (the record toggle itself has no
    // elem_id), and the toggle is a SIBLING of the path field's column, so
    // the accordion is the smallest correct scope (verified against gradio
    // 6.20.0: Column renders div.column, Button has no .form wrapper, and
    // gradio-column does not exist). The engine Start/Stop pair at the top
    // of the tab is momentary, NOT a toggle, lives outside every accordion,
    // and must not receive aria-pressed.
    var anchor = document.querySelector("#browse-record_audio_path");
    if (!anchor) { return; }
    var scope = anchor.closest(ACCORDION_BLOCK);
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

In `applio_launcher.py`, replace `_a11y_terminal_words`'s duplicated loop (lines 5406-5427) with delegation — keep the method (it is `self`-bound, called as `self._a11y_terminal_words()` at line 5451), keep its existing docstring (adjust the last sentence to point at the shared helper), and keep the bare `get_recent_processes(limit=20)` call: it resolves to the MODULE-LEVEL function defined at `applio_launcher.py:1001` (`def get_recent_processes(limit: int = 10)`), which is exactly how the current code calls it:

```python
    def _a11y_terminal_words(self):
        """Map snapshot keys -> stored history status for jobs that vanished.

        (keep the existing docstring body; the mapping itself now lives in
        applio_progress_api.terminal_words_from_history — History is
        newest-first, so the most recent entry for a key wins.)
        """
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

Register in `run_all()`, bump count to `(11)`. In `tests/test_a11y_js_invariants.py` (created by Task 2 with a single test), ADD the second test and register it (count → `(2)`):

```python
def test_failed_tail_wiring_present():
    # Guards the persistResult enrichment contract (Task 4).
    with open(JS, encoding="utf8") as fh:
        src = fh.read()
    assert "failedTail" in src, "failedTail helper must exist (log-tail surfacing)"
    assert 'a[1] + " — " + a[2]' in src, "persist loop must append the tail"
```

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
- Test: `tests/test_browse_ui.py` (5 → 9), `tests/test_patch_fixtures.py` (assertion extension; count stays 5)

**Acceptance Criteria:**
- [ ] `attach_path_validation(target, mode)` wires `target.blur(fn=_make_validator(mode), inputs=[target], outputs=[target])` — works for `gr.Textbox` AND `gr.Dropdown` targets (both list `Events.blur` in their `EVENTS` in the installed gradio 6.20.0 — `components/textbox.py:65`, `components/dropdown.py:44`; the 13 fields include both kinds, e.g. `dataset_path`/`g_pretrained_path` are Dropdowns at `tabs/train/train.py:388,725`, `record_audio_path` is a Textbox). A construction-time wiring test proves the API on both component kinds.
- [ ] Validator: empty value → returned unchanged, no warning; `~` → expanded value returned (self-heal); nonexistent path → `gr.Warning("Path does not exist: …")` and the expanded value returned; `mode="folder"` on a file / `mode in ("file","pth")` on a directory → `gr.Warning("Not a folder…"/"Not a file…")`.
- [ ] The patcher's injected block per field now contains both lines (browse button + validation attach) for all 13 fields; fixture test asserts `attach_path_validation(` appears once per field var.
- [ ] **Invariant:** the injected validation line must NOT contain the substring `_applio_browse_` — `tests/test_patch_fixtures.py:115` asserts `patched.count("_applio_browse_") == len(fields)` and would break on any such naming (the `_applio_browse_{var}` assignment var is the only allowed carrier of that prefix).
- [ ] Existing 5 browse tests still pass (the `_picker` seam untouched); suite prints `(9)`.

**Verify:** `venv_macos/bin/python tests/test_browse_ui.py && venv_macos/bin/python tests/test_patch_fixtures.py` → `(9)` and `(5)` pass lines.

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
    import os

    v = applio_browse_ui._make_validator("folder")
    home = os.path.expanduser("~")
    out, warnings = _with_recorded_warnings(lambda: v("~"))
    assert out == home and warnings == []  # home IS a folder -> clean self-heal
    out2, warnings2 = _with_recorded_warnings(lambda: v("   "))
    assert out2 == "   " and warnings2 == []  # blank -> untouched, no warning


def test_validator_warns_on_missing_path():
    v = applio_browse_ui._make_validator("file")
    out, warnings = _with_recorded_warnings(lambda: v("/no/such/path.abc"))
    assert out == "/no/such/path.abc"
    assert warnings and warnings[0].startswith("Path does not exist")


def test_validator_warns_on_wrong_type():
    import os

    here = os.path.abspath(__file__)
    v_folder = applio_browse_ui._make_validator("folder")
    out, warnings = _with_recorded_warnings(lambda: v_folder(here))  # file, not folder
    assert warnings and warnings[0].startswith("Not a folder")
    assert out == here
    v_file = applio_browse_ui._make_validator("file")
    out2, warnings2 = _with_recorded_warnings(lambda: v_file(os.path.dirname(here)))
    assert warnings2 and warnings2[0].startswith("Not a file")  # dir, not file
    assert out2 == os.path.dirname(here)


def test_attach_validation_wires_blur_on_both_kinds():
    # Construction-time wiring on BOTH component kinds used by the 13 fields
    # (Textbox + Dropdown both expose .blur in gradio 6.20.0). Same pattern as
    # test_browse_button_creates_and_wires — no server needed.
    with gr.Blocks():
        tb = gr.Textbox()
        dd = gr.Dropdown(choices=["a"], allow_custom_value=True)
        applio_browse_ui.attach_path_validation(tb, "file")
        applio_browse_ui.attach_path_validation(dd, "pth")
```

Register all four in `run_all()`, bump count to `(9)`. In `tests/test_patch_fixtures.py`, extend the per-field loop in `test_browse_buttons_patch` to also assert `f'applio_browse_ui.attach_path_validation({var}, "{mode}")' in patched` (mirroring the existing browse-line assertion) — and do NOT touch the `count("_applio_browse_")` assertion (see the invariant above).

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
    target.blur(fn=_make_validator(mode), inputs=[target], outputs=[target])
```

In `patches/patch_browse_buttons.py`, extend the generated-line template (lines 119-122). Match the existing single-quoted f-string idiom of the second line — do NOT introduce `\"` escapes inside the double-quoted f-string (they compile on 3.10 but are inconsistent with the file's style):

```python
        line = (
            f"\n{indent}_applio_browse_{var} = applio_browse_ui.browse_button("
            f'"{mode}", {var}, elem_id="browse-{var}")\n'
            f'{indent}applio_browse_ui.attach_path_validation({var}, "{mode}")\n'
        )
```

- [ ] **Step 4: Run to verify pass** — `(9)` and `(5)`; then run the patcher directly against a temp copy and `git checkout` any real sources if touched:

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

**Exit-site inventory (verified 2026-08-21 against the repo; the RULE below governs if lines drift):**
- Single-expression sites — change `sys.exit(0 if X else 1)` to `sys.exit(0 if X else 2)` (the `X` is the patcher's own success flag; False = anchor miss): `patch_browse_buttons.py:197`, `patch_inference_progress.py:329`, `patch_data_paths.py:199`, `patch_loading_html.py:235`, `patch_custom_pretrained_paths.py:140`, `patch_extract_error_logging.py:88`, `patch_preflight_validation.py:109`, `patch_mute_paths.py:90`, `patch_preprocess_error_logging.py:82`, `patch_stop_infer.py:105`, `patch_static_resources.py:364` (NOTE: not currently registered in `patches_to_apply` — still gets the convention for the day it is), `patch_download_paths.py:116`, `patch_pretrained_selector.py:138`, `patch_refinegan_legacy_infer.py:186`, `patch_stop_feedback.py:112`, `patch_f0_model_paths.py:112`, `patch_refinegan_legacy_train.py:198`, `patch_multiprocessing.py:172`, `patch_refinegan_legacy_discriminator.py:221`, `patch_subprocess_validation.py:279`, `patch_version_checker.py:95`, `patch_train_44100.py:263`, `patch_process_tracking.py:663`, `patch_train_paths.py:117`. (Side effect, accepted: `patch_browse_buttons.apply()` also returns False for an unrecognized target path — the REPO-relpath guard at line 177 — which becomes exit 2; that guard can never fire inside the build loop, which always passes registered `tabs/…` paths.)
- Multi-line literal `sys.exit(1)` MISS branches — change the `1` to `2`: `patch_dataset_paths.py:229` (else of the `success1 or success2` check), `patch_progress_routes.py:64` (after a "Pattern not found" print), `patch_web_a11y_payload.py:89` (same).
- Multi-line literal `sys.exit(1)` FILE-NOT-FOUND guards (`if not file_path.exists():`) — change the `1` to `2` (a missing source file in the build is a hard error, same fatality as a miss; NOT a usage guard): `patch_multiprocessing.py:169`, `patch_train_44100.py:260`.
- Usage guards (`if len(sys.argv) < 2: ... sys.exit(1)`) — KEEP at `1`: `patch_inference_progress.py:325`, `patch_refinegan_legacy_infer.py:182`, `patch_refinegan_legacy_train.py:195`, `patch_refinegan_legacy_discriminator.py:217`, `patch_stop_infer.py:101`, `patch_refinegan_legacy.py:104`.
- DO NOT TOUCH: `patch_refinegan_legacy_train.py:102` and `:175` (`sys.exit(1)"""` — inside injected triple-quoted code), `patches/download_pretraineds.py` (downloader, own invocation at `build_macos.py:471`).
- **Classification rule for every site:** usage guard (an `argv`/`argc` check within the previous ~4 lines) → keep 1; anchor/pattern miss (after a "Pattern not found"/"patch failed" print, the failure branch of a success check, or a file-not-found guard) → 2; inside a triple-quoted string → untouched. Also update each patcher's docstring "Exit codes:" line (e.g. `patch_browse_buttons.py:19`) to `0 patched/already, 2 anchor miss`.
- **Benign-nonzero proof (the fail-on-nonzero loop is safe):** simulated 2026-08-21 by running EVERY registrable patcher against a `/tmp` copy of its pristine source with the same argument the build passes (dir or file), then re-running on the patched output — all 27 simulable registrations returned `0` on BOTH runs (`patch_browse_buttons` cannot be simulated off-repo because of its relpath guard, but every historical build passing with it registered is equivalent evidence). No patcher legitimately exits nonzero in a healthy build; the `success1 or success2` shape in `patch_dataset_paths` is noted below as a residual soft spot.

**Acceptance Criteria:**
- [ ] Every `patches/patch_*.py` exits `2` on anchor miss and `0` on patched/already; usage guards still exit `1`.
- [ ] `build_macos.py`'s patch loop: exit `0` tolerated; ANY other code (2 = anchor miss, 1/3+ = crash or usage) is collected and the build FAILS after the loop with a message naming every failing patcher and pointing at CLAUDE.md's "Re-pointing patches after an upstream sync".
- [ ] The two silent `SKIPPED` paths (patcher not found / source file not found) are ALSO collected as failures instead of `continue`-ing silently.
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

# (patcher, source file, anchor text to mutate, arg convention). Arg
# conventions verified against each patcher's __main__:
#   "file" -> patcher takes the SOURCE FILE path (arbitrary location OK);
#   "dir"  -> patcher takes the DIRECTORY and joins a fixed filename inside
#             it (patch_train_paths looks for <base>/train.py).
# patch_browse_buttons is deliberately NOT a case: apply() rejects any target
# whose path relative to the REPO is not a registered tabs/... file (line
# 177), so it cannot be exercised on a temp copy at all.
CASES = [
    ("patches/patch_progress_routes.py", "app.py", "prevent_thread_lock=", "file"),
    ("patches/patch_web_a11y_payload.py", "app.py", "def launch_gradio(", "file"),
    ("patches/patch_train_paths.py", "rvc/train/train.py", "current_dir = os.getcwd()", "dir"),
]
# All three anchors occur EXACTLY ONCE in their pristine source (verified
# 2026-08-21) — replace-all is still used defensively below.

EXEMPT = {"download_pretraineds.py"}  # downloader, not an anchor patcher


def _run(patcher, target):
    return subprocess.run(
        [PY, os.path.join(REPO, patcher), target], capture_output=True, text=True
    )


def test_patcher_exit_codes_behavioral():
    for patcher, source, anchor, convention in CASES:
        tmp = tempfile.mkdtemp()
        dst = os.path.join(tmp, os.path.basename(source))
        shutil.copy(os.path.join(REPO, source), dst)
        arg = dst if convention == "file" else tmp
        first = _run(patcher, arg)
        assert first.returncode == 0, (patcher, first.returncode, first.stdout)
        again = _run(patcher, arg)  # already-patched input
        assert again.returncode == 0, (patcher, again.returncode, again.stdout)
        # Mutate the anchor in a FRESH copy -> miss -> exit 2.
        shutil.copy(os.path.join(REPO, source), dst)
        with open(dst, encoding="utf8") as fh:
            content = fh.read()
        assert anchor in content, (patcher, anchor)
        with open(dst, "w", encoding="utf8") as fh:
            fh.write(content.replace(anchor, anchor + "_MUTATED"))
        miss = _run(patcher, arg)
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

(Both app.py CASES live in SEPARATE `tempfile.mkdtemp()` trees so the two patchers' outputs cannot contaminate each other. If a CASE patcher's conventions ever drift, substitute another patcher from the inventory — keep exactly 3 covering both arg conventions.)

- [ ] **Step 2: Run to verify failure** — behavioral cases exit 1 (not 2) on miss; source-scan lists the multi-line miss sites.

- [ ] **Step 3: Implement** — apply the exit-site inventory classification across `patches/patch_*.py`; update docstring Exit-codes lines. In `build_macos.py`'s `pre_build_patch()` (loop head at line 943, tail at 971-977), ALSO convert the two silent `SKIPPED … continue` paths (patcher not found at ~944-946, source file not found at ~948-950) into collected failures — a missing patcher or source is the same silent-skip class as an anchor miss (all 33 registrations exist in the healthy tree, verified by the simulation above, so this cannot fire spuriously). Final shape of the loop region:

```python
    patch_failures = []  # (description, exit code) — any nonzero fails the build

    for patcher_path, source_file, description, patcher_type in patches_to_apply:
        if not os.path.exists(patcher_path):
            patch_failures.append((description, "patcher not found"))
            continue

        if not os.path.exists(source_file):
            patch_failures.append((description, "source file not found"))
            continue

        # ...unchanged: patched_files capture + patcher_arg resolution...

        result = subprocess.run(
            [sys.executable, patcher_path, patcher_arg], capture_output=True, text=True
        )

        for line in result.stdout.strip().split("\n"):
            if line:
                print(f"    {line}")

        if result.returncode != 0:
            # 0 = patched or already applied. 2 = anchor miss (upstream moved
            # the anchor); anything else is a crash or invocation failure.
            # Both ship a broken app if skipped.
            patch_failures.append((description, str(result.returncode)))

    if patch_failures:
        for description, why in patch_failures:
            print(f"  PATCH FAILURE: {description} ({why})")
        raise SystemExit(
            "Patchers failed (anchor miss = exit 2, see CLAUDE.md "
            "'Re-pointing patches after an upstream sync')."
        )

    return patched_files
```

`pre_build_patch()` is called at module level (`build_macos.py:1010`, before `PyInstaller.__main__.run` at :1014), so the `SystemExit` kills the process BEFORE any PyInstaller work. The `PATCH_DEPENDENCIES` validation block above the loop is untouched.

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
- [ ] Every listed literal is wrapped so `native_tr` receives it (or its format template, e.g. `_t("Fetching {basename}").format(basename=os.path.basename(fname))`) at render/call time — lazy `import applio_i18n` / `_t = applio_i18n.native_tr` inside the function, per the pattern at `applio_launcher.py:5836-5838` (macos_wrapper.py already uses the same shape — quit dialog at :402-416, data-location panel at :561-564). Status-map VALUES are translated where the map is built (raw status strings stay the KEYS); `'failed'` and `'error'` collapse to the SAME translated word so one override covers both.
- [ ] With no overrides file, behavior is byte-identical to today (English keys returned unchanged).
- [ ] New cluster-keys test passes, and its WRAPPED-FORM assertions are the genuine pre-implementation failing signal: (a) an overrides tree translating sample cluster strings returns them via `native_tr`; (b) a source scan asserts every listed literal still appears verbatim in its owning file (guards key drift); (c) a source scan asserts the WRAPPED form `_t("…")` exists for representative sites — this fails before wrapping (the literals exist today but unwrapped) and passes after. (A bare `_t(`-count assertion would NOT work: `macos_wrapper.py` ALREADY has 17 `_t(` / 6 `native_tr` matches and `applio_launcher.py` 12/4 from earlier phases — a count threshold passes pre-implementation and proves nothing.)
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

# Wrapped-form expectations: (file, snippet that must exist after wrapping).
# This is the FAILING half of the test pre-implementation.
WRAPPED_FORMS = [
    ("macos_wrapper.py", '_t("Initializing environment...")'),
    ("macos_wrapper.py", '_t("Loading Neural Networks...")'),
    ("macos_wrapper.py", '_t("Launching User Interface...")'),
    ("applio_launcher.py", '_t("Status: Running")'),
    ("applio_launcher.py", '_t("Pause")'),
    ("applio_launcher.py", '_t("Stopping…")'),
    ("applio_launcher.py", '_t("Failed")'),
    ("applio_launcher.py", '_t("Voice Conversion Application")'),
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
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # (b) raw literals stay verbatim in their owning files so the keys (and
    # any overrides written against them) never drift.
    for fname, literal in CLUSTER_KEYS:
        with open(os.path.join(repo, fname), encoding="utf8") as fh:
            assert literal in fh.read(), f"{fname} lost key {literal!r}"
    # (c) the wrapping itself exists — representative sites in wrapped form.
    for fname, snippet in WRAPPED_FORMS:
        with open(os.path.join(repo, fname), encoding="utf8") as fh:
            assert snippet in fh.read(), f"{fname} missing wrapped form {snippet!r}"
```

Register in `run_all()`, bump count to `(9)`.

- [ ] **Step 2: Run to verify failure** — the `(c)` WRAPPED_FORMS assertions fail (literals exist but unwrapped); `(a)` and `(b)` pass both before and after by design (`(b)` is the key-drift guard, `(a)` proves the overrides plumbing).

- [ ] **Step 3: Implement** — wrap every English user-visible literal inside the listed line ranges (including the ones the site list abbreviates: `"Resume"`, `"Status: Paused"`, `"Status: Completed"`, `"Status: Error controlling process"`, `"Unknown"`). Do NOT wrap log-file lines (`_add_log_line(...)` payloads) or `_announce_for_accessibility` payloads — those flow through `AnnouncementPolicy`'s own translator (wired at `applio_launcher.py:4777-4780`) and double-wrapping would corrupt the keys. Representative transformations (apply the same shape everywhere):

```python
# macos_wrapper.py loading stage (was: self.sub_heading = "Initializing environment...")
import applio_i18n
_t = applio_i18n.native_tr
self.sub_heading = _t("Initializing environment...")
self.technical_detail = _t("Allocating memory...")
```

```python
# Formatted stage (was: self.sub_heading = f"Fetching {os.path.basename(fname)}"):
self.sub_heading = _t("Fetching {basename}").format(basename=os.path.basename(fname))
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
# About alert (5806-5813) — the Version line is NOT translated and stays first:
alert.setInformativeText_(
    f"Version {version}\n\n"
    + "\n".join([
        _t("Voice Conversion Application"),
        _t("Based on RVC (Retrieval-Based Voice Conversion)"),
        "",
        _t("Native macOS port by Frédéric Guigand"),
        _t("© 2024-2026 IA Hispano"),
    ])
)
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
- [ ] All 9 script suites green: `test_applio_a11y` (17), `test_menu_spec` (15), `test_native_picker` (3), `test_browse_ui` (9), `test_progress_api` (11), `test_patch_fixtures` (5), `test_applio_i18n` (9), `test_a11y_js_invariants` (2), `test_patcher_exit_codes` (2), plus `-m pytest tests/test_inference_progress.py` (5) — 78 total (17+15+3+9+11+5+9+2+2+5; adjust the expected total if implementation legitimately shifted a count; report any shift).
- [ ] `venv_macos/bin/python build_macos.py` (cert-free smoke) completes with `BUILD COMPLETE`, as the FINAL command of a background run (no trailing `echo` masking the exit code), and the log shows every `Patching:` line with no `PATCH FAILURE`.
- [ ] Post-build: `git status` shows no upstream files with patch markers; restore with `git checkout -- assets core.py rvc tabs app.py` if `tabs/train/train.py` or others are dirty (known behavior).
- [ ] Bundle checks: `stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio` timestamp AFTER the last commit; `dist/Applio.app/Contents/Resources/assets/applio_a11y.js` contains `failedTail` and `#browse-record_audio_path`.
- [ ] Boot smoke: launch `dist/Applio.app`, wait for the backend (the port is FIXED — `macos_wrapper.py:1167-1168` sets `server_host = "127.0.0.1"`, `server_port = 6969`; no log scraping needed; poll with a short bash retry loop, macOS has no `timeout`), then `curl -s "http://127.0.0.1:6969/applio-a11y/progress?client=web"` returns JSON containing `"errors"`; quit via `osascript -e 'tell application "Applio" to quit'`. (If 6969 never responds, THEN check `~/Library/Logs/Applio/applio_launcher.log` for a bind failure — EADDRINUSE fails fast per the supervisor.)
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

## Self-Review (updated at final-review time)

1. **Spec coverage:** audit §7 additions — patcher exit codes (T6), aria-pressed scoping (T2), i18n guards (T1), word-map unification (T3), English clusters (T7) ✓; Phase 2 deferrals — log-tail surfacing (T4), typed-path validation (T5) ✓; docs (T8) + whole-branch validation (T9) ✓. Out of scope by recorded decision: upstream Applio/gradio PRs (separate post-pass plan).
2. **Placeholder scan:** no TBD/TODO; every code step carries real code; Task 6's CASES patchers/anchors are individually verified (each anchor occurs exactly once in its pristine source; both arg conventions covered; `patch_browse_buttons` excluded because its REPO-relpath guard makes off-repo testing impossible).
3. **Type consistency:** `terminal_words_from_history(entries)` defined in T3 and consumed by T3 (both call sites); `attach_path_validation(target, mode)` defined in T5, emitted by T5's patcher template only, and proven against the real gradio API by T5's wiring test (both `Textbox` and `Dropdown` list `Events.blur`); `failedTail(errors, job)` defined and used within T4's JS edits; `errors=None` param on `build_progress_payload` introduced in T4 and asserted in T4's tests.
4. **Verified against the installed stack (2026-08-21, final review):** gradio 6.20.0 `.form` class real / `gradio-column` nonexistent / Column renders `div.column` (→ T2 scopes via `.gr-accordion`); every registered patcher exits 0 on pristine AND already-patched temp-copy inputs (→ T6's fail-on-nonzero cannot break a healthy build); `macos_wrapper.py` already contains `_t(` usage (→ T7's failing signal is the wrapped-FORM scan, not a count); gradio port fixed at 127.0.0.1:6969 (→ T9's boot smoke curls it directly).
5. **Known deliberate roughness:** Task 6's per-site line numbers are a verified snapshot — the classification RULE governs if lines drift; `patch_dataset_paths.py`'s `success1 or success2` means a single-file anchor miss still exits 0 if the OTHER file patched (pre-existing shape, noted as residual; tightening it to `and` is a one-line follow-up if a sync ever trips it); Task 5's fixture-suite `count("_applio_browse_") == len(fields)` invariant is documented in the AC so the validation line can never reintroduce that substring.
