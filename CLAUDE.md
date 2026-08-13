# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Applio is a voice conversion application built on RVC (Retrieval-Based Voice Conversion). It provides a Gradio web interface for training voice models, performing inference, text-to-speech, and real-time voice conversion. The project supports macOS native app packaging via PyInstaller.

## Efficiency Notes

**Use interminai for file edits >100 lines** - Edit tool consumes ~10 tokens/line; interminai has fixed ~300 token overhead. See global `~/.claude/CLAUDE.md` for vim workflow patterns.

## Build and Run Commands

```bash
# Installation
./run-install.sh              # Cross-platform (Python 3.12, creates .venv)
./install_applio_mac.sh       # macOS native (Python 3.10, creates venv_macos)
run-install.bat               # Windows

# Running (Gradio web UI)
./run-applio.sh               # Linux/macOS
run-applio.bat                # Windows
python app.py --open          # Direct with auto-browser
python app.py --share         # With public URL
python app.py --port 8080     # Custom port

# macOS Native App
python macos_wrapper.py       # Run with native window
venv_macos/bin/python build_macos.py  # Build .app bundle → dist/Applio.app (requires venv_macos)

# Build options (combine as needed):
python build_macos.py --dmg           # Create DMG installer after build
python build_macos.py --sign          # Sign with Developer ID
python build_macos.py --notarize      # Notarize with Apple (requires --sign)

# TensorBoard (training monitoring)
./run-tensorboard.sh          # Linux/macOS
python core.py tensorboard    # Direct

# Docker
docker build -t applio .
docker run -p 6969:6969 applio
```

## Architecture Overview

```
app.py              # Main entry - Gradio web UI initialization
core.py             # Core logic exports (inference, training, TTS)
macos_wrapper.py    # macOS native wrapper (pywebview)
tabs/               # Gradio UI tabs (inference/, train/, tts/, realtime/, etc.)
rvc/                # Voice conversion engine
├── infer/          # Inference pipeline (VoiceConverter, Pipeline)
├── train/          # Training pipeline
├── realtime/       # Real-time voice conversion
├── lib/algorithm/  # Neural network architectures (Synthesizer, generators)
├── lib/predictors/ # F0 extractors (CREPE, FCPE, RMVPE)
├── lib/tools/      # Utilities (TTS, model download, prerequisites)
├── configs/        # Model configs (24k-48kHz), Config singleton
└── models/         # Pretrained models storage
assets/
├── config.json     # App configuration (theme, language, precision)
├── i18n/           # Internationalization (50+ languages)
└── themes/         # Gradio theme definitions
```

## Key Files

| Purpose | File |
|---------|------|
| macOS installer | `install_applio_mac.sh` |
| 44.1kHz patch | `patches/patch_train_44100.py` |
| Code signing config | `assets/entitlements.plist` |
| Fork differences | `FORK_DIFFERENCES.md` |
| Main entry point | `app.py` |
| Core function exports | `core.py` |
| Voice conversion logic | `rvc/infer/infer.py` (VoiceConverter class) |
| Conversion pipeline | `rvc/infer/pipeline.py` (Pipeline class) |
| Training logic | `rvc/train/train.py` |
| Neural architectures | `rvc/lib/algorithm/synthesizers.py` |
| App configuration | `assets/config.json` |
| Platform setup | `rvc/lib/platform.py` |
| macOS native wrapper | `macos_wrapper.py` |
| Build configuration | `build_macos.py` (datas / HIDDEN_IMPORTS / pyinstaller_args) - **NOT `Applio.spec`** (gitignored at `.gitignore:34` and never read by the build; the build runs `PyInstaller.__main__.run(pyinstaller_args)` from `build_macos.py`). `menu_spec` and `applio_update_check` (lazy-imported) are in `HIDDEN_IMPORTS`. |

## Code Conventions

- **Formatter**: Black (auto-runs via GitHub Actions on push to main). The inherited
  `code_formatter.yml` runs black+autoflake on every push touching `*.py` and opens a
  **perpetual `formatter/main` PR** (`peter-evans/create-pull-request`, `delete-branch: true`)
  that respawns on each push until the tree is black-clean. To clear it: merge the PR (all
  reformatted files are fork-owned → no upstream-delta cost; black leaves patch-anchor strings
  in `r'''...'''` untouched), after which the workflow is a no-op guardian. PR #1 merged
  2026-08-13; its SHA is in `.git-blame-ignore-revs` (append future bulk-format commits there).
- **Import cleanup**: autoflake
- **Encoding**: UTF-8 for all file operations
- **No formal test suite** - manual testing through Gradio UI

## Fork Maintenance

This fork maintains minimal delta from upstream - only macOS additions, no core modifications.

**Sync with upstream:**
```bash
git remote add upstream https://github.com/IAHispano/Applio.git   # once
git fetch upstream
git merge upstream/main
```

The fork keeps macOS work in separate files, so the git merge is nearly conflict-free
(last sync 3.6.2 → 3.6.3 on 2026-07-24: only `.gitignore`, `rvc/train/preprocess/preprocess.py`,
and `tabs/train/train.py` touched both sides; only `.gitignore` actually conflicted).
**The real work after a merge is re-pointing build-time patches** (see "Re-pointing patches
after an upstream sync" below), because upstream rewrites the source our `patches/*.py` anchor on.

**Re-pointing patches after an upstream sync:**
- Iterate WITHOUT a full build: `build_macos.py` runs the *entire* build at module level
  (line ~677 `pre_build_patch()` → PyInstaller), so **never `import build_macos`** for testing.
  Instead run each patcher directly, e.g. `venv_macos/bin/python patches/patch_X.py <arg>`,
  then `git checkout -- <source>` to restore.
- Each patcher prints `Pattern not found` / `patch failed` when upstream changed its anchor;
  re-point the regex/string to the new code, then verify the patched file `py_compile`s and the
  injected code is correctly placed before committing.
- **Patcher indent capture:** in `patch_process_tracking.py` capture the leading indent with
  `\n+([ \t]+)` (horizontal only), NOT `(\n\s+)`. `patch_preflight_validation` runs first and
  leaves a blank line before `result = subprocess.run(...)`, so `(\n\s+)` grabs that newline and
  every injected line gets a spurious blank line. Each replacement reproduces one leading newline
  (start content on the line after `r'''`).
- **Tracking patches that switch `subprocess.run`→`Popen`/`communicate()`** (e.g. TTS): wrap in
  `try/finally` so `_untrack_process()` always runs, and use `stdout=PIPE, stderr=PIPE` +
  `communicate()` to preserve upstream's `RuntimeError(stderr)` behavior.

**Safe-to-modify files** (macOS-only, not in upstream):
- `assets/entitlements.plist`
- `patches/`, `macos_wrapper.py`, `build_macos.py`, `Applio.spec`
- `menu_spec.py`, `applio_update_check.py`, `tests/test_menu_spec.py`, `STUDIO_PRODUCTION_GUIDE.html`
- `install_applio_mac.sh`, `requirements_macos.txt`, `CLAUDE.md`
- Fork-only additions also live INSIDE `rvc/`: `rvc/lib/algorithm/generators/refinegan_legacy.py`,
  `rvc/lib/tools/applio_paths.py`, `rvc/lib/tools/process_log_parser.py` (verify any path with the
  `git ls-tree` command below).

**Verify file origin:** `git ls-tree upstream/main --name-only | grep <path>`

## Platform Notes

**Python Version Requirements:**
| Context | Python | Virtual Env |
|---------|--------|-------------|
| `install_applio_mac.sh` | 3.10 | `venv_macos` |
| `build_macos.py` | 3.10 | `venv_macos` |
| `run-install.sh` | 3.12 | `.venv` |
| `run-applio.sh` | 3.12 | `.venv` |

**Important:** PyInstaller builds require Python 3.10 (3.12+ has compatibility issues).

**Python 3.10 vs upstream's 3.11+ stack (post-3.6.3 sync):** Upstream now pins packages
that require Python 3.11+ (numpy 2.4.6, scipy 1.18, matplotlib 3.11, pandas 2.3+). The fork
stays on 3.10 (PyInstaller), so `requirements_macos.txt` uses the latest py3.10-compatible
versions instead: **numpy 2.2.6, scipy 1.15.3, numba 0.66.0, matplotlib 3.10.9, pandas 2.2.x+**.
(pandas 2.3.x imports fine on 3.10 but needs numpy 2.x ABI - the old numpy 1.26 caused
`pandas._libs.tslibs.vectorized` failures.) If the fork ever moves to Python 3.11, these can
re-align to upstream's exact pins; that needs `brew install python@3.11` + a fresh `venv_macos`.

**Phase 2 - single-process merge (shipped in 3.6.3.7):**
The two-process launcher+wrapper was merged into ONE native process (fixed: Hide not hiding the
Gradio window; the menu swapping by which process was frontmost). Single-process is now the only
architecture; the two-process code and the `APPLIO_SINGLE_PROCESS` flag were removed in 3.6.3.7. The
app runs as one process (one dock icon, one menu, one window). **Frozen-validated** (training,
reopen, quit, menu, and dashboard all work in the built `dist/Applio.app` on Apple Silicon). The
**Process Dashboard** shows real-time metrics (best epoch/loss, current/total epoch, step, speed,
derived ETA + epoch-fraction bar), a loss-vs-epoch curve with always-on green highlights at
significant improvements, an action bar (Stop / Pause-Resume / Reveal Log / Open Log), best-epoch
durability across restart + retraining the same model, auto-show on job start, and idle-state
history browsing.
- **Run (dev):** `venv_macos/bin/python applio_launcher.py`
- **Run (built app):** `open dist/Applio.app`
- **Architecture:** the launcher calls `macos_wrapper.start_gui(launcher=self)` (import-safe - `import macos_wrapper` has zero side effects) then `webview.start(func=self._reassert_menu_and_delegate)`. pywebview clobbers `NSApp.delegate()` and wipes the main menu once at `first_show`; the func re-seats both on the main thread via `AppHelper.callAfter`. With NO `menu=` passed, pywebview does NOT re-wipe on focus (`windowDidBecomeKey_`'s `if i and i.menu` guard is False when `i.menu` is None) - verified against `venv_macos/.../webview/platforms/cocoa.py`.
- **Gotchas:** (1) `NSApplication.delegate` is a WEAK (assign) ref - REUSE `self._app_delegate` (created in `_setup_menu`); NEVER inline `ApplioAppDelegate.alloc()…` in `_reassert_menu_and_delegate` (its only Python ref would GC → dangling delegate → crash on next reopen/quit). (2) `on_window_closing` runs on the MAIN thread - quit via `AppHelper.callAfter(lambda: NSApp.terminate_(None))`, NEVER synchronous (the ≤5 s `killpg`-wait would block the close event + re-enter AppKit → spinning cursor); `_user_confirmed_quit` (set before the deferred terminate) prevents the double-prompt. (3) The Gradio supervisor `_supervised_backend` (N=3, linear backoff) wraps `start_backend`, which RAISES on failure; `OSError` (e.g. EADDRINUSE) fails fast; `exc_info=True` keeps the traceback. (4) `setup_logging` is ADDITIVE (no `removeHandler`, no `sys.stdout`/`stderr` reassign) so launcher logs reach `applio_launcher.log`. (5) A hard GUI crash (segfault) is unrecoverable - accepted tradeoff; training checkpoints + `active_processes.json` mitigate data loss.
- **DEV can't run training/dataset scripts** - they resolve to `~/Applio/rvc/train/*` (data dir), not the repo → `No such file`. Training works only in the FROZEN build (scripts bundled, resolved via `_MEIPASS`). Validate training on `dist/Applio.app`, not dev.
- **Dev hides Gradio/training stdout** - a "generic error" in the UI is invisible in the log. Read the background-launch task's stdout file (`/private/tmp/.../tasks/<id>.output`) or run in a foreground terminal.

**macOS Development:**
- Use `requirements_macos.txt` (includes pywebview, pyinstaller, pyobjc)
- PyTorch uses MPS (Metal Performance Shaders) on Apple Silicon
- Install `setuptools<70` for pkg_resources support
- First run downloads ~300MB models (600s timeout in wrapper)
- User data: `~/Library/Application Support/Applio/` (cache), external path for models/training
- Logs: `~/Library/Logs/Applio/`
- Key environment variables in `macos_wrapper.py`:
  - `PYTORCH_ENABLE_MPS_FALLBACK=1`
  - `GRADIO_TEMP_DIR=~/Library/Caches/Applio/gradio`
  - `HF_HOME=~/Library/Application Support/Applio/huggingface`
- macOS has no `timeout` command - use `gtimeout` (coreutils) or background-launch + poll; never bare `timeout N` in a run/test command.

**External Data Storage:**
- First-run prompts user to select data location via native macOS folder dialog
- Preferences stored in NSUserDefaults (`com.iahispano.applio`)
- Default location: `~/Applio/`
- Build-time patcher (`patches/patch_data_paths.py`) redirects `core.py`'s `logs_path` to use `now_dir`
- Menu: File → Set Data Location..., Open in Finder (various subfolders)

**Subprocess Script Path Resolution:**
- Script execution mode in `macos_wrapper.py` searches BASE_PATH as fallback
- Required because scripts (in app bundle) won't exist in DATA_PATH (user data location)
- Scripts found at `os.path.join(BASE_PATH, script_relative_path)` when not in cwd

**Subprocess Environment Variables:**
- macOS uses "spawn" not "fork" - subprocesses DON'T inherit parent's env vars
- `macos_wrapper.py` must set `APPLIO_DATA_PATH`, `APPLIO_LOGS_PATH` BEFORE `runpy.run_path()`
- File-based config at `~/Library/Application Support/Applio/runtime_paths.json` provides process-safe path resolution
- See `DEBUGGING_HISTORY.md` for full investigation of this issue

**Build outputs:**
- `build/` - PyInstaller intermediate files
- `dist/` - Final `Applio.app` bundle

**CRITICAL: Build environment:**
- MUST run `build_macos.py` from within `venv_macos` - running outside produces broken app
- Outside venv: PyObjC not bundled → runtime error "AppHelper is not defined"
- Outside venv: "Hidden import 'xxx' not found" warnings for torch, gradio, etc.
- Setup: `/opt/homebrew/bin/brew install python@3.10` then `/opt/homebrew/bin/python3.10 -m venv venv_macos`

**Debugging Frozen Apps:**
- Use file-based logging (`/tmp/applio_debug.txt`) for code that runs before stdout capture
- **Silent exception handling:** In multiprocessing spawn mode, stdout is lost. Use file-based logging (e.g., `~/Library/Logs/Applio/extraction_errors.log`)
- Check `DEBUGGING_HISTORY.md` for documented debugging sessions and solutions
- After fixes, verify build timestamp is AFTER commit timestamp: `stat -f "%Sm" dist/Applio.app/Contents/MacOS/Applio`
- All fixes must go through `patches/` - NEVER modify upstream files directly
- **After patching, verify `git status` shows no upstream files have patch markers.** If present, restore with `git checkout` before committing.
- When stuck after 3+ fix attempts: STOP and question the architecture (per systematic-debugging skill)
- **Launch `macos_wrapper.py` from a foreground terminal**, not `nohup ... &` - pywebview's
  AppKit event loop needs an interactive GUI session and blocks/idles when backgrounded.
- **Local `rvc/models` must NOT be deleted.** The default `build_macos.py` is a *lite*
  build: `clean_bundled_models()` strips model weights from `dist/Applio.app` (the bundle
  only - shipped app stays ~1.6GB) and never touches the local filesystem. So keeping the
  ~1.8G of models in gitignored `rvc/models/` does NOT bloat the shipped app, and `rm -rf
  rvc/models/*` only forces a costly ~2G re-download. Leave local models in place; the
  bundle is re-stripped on every build. (A model-bundled build is `--models-installer`, a
  separate app - there is no CLI flag to bundle models into the main app; `--lite` is
  `store_true, default=True`, i.e. always on.)
- **Corrupted `venv_macos` package:** if `import torch`/`pandas` fails with a partial-init /
  circular-import error, the installed wheel is corrupt → fix with
  `venv_macos/bin/python -m pip install --force-reinstall --no-deps <pkg>`.
- **Frozen subprocess CWD is the bundle (`sys._MEIPASS`/Frameworks), not the data dir**,
  so `os.getcwd()`/`now_dir`-relative paths break. Resolve user/data paths absolutely:
  `APPLIO_DATA_PATH` env → `runtime_paths.json` `data_path` → `~/Applio`.
- **`logging.basicConfig` is a no-op once an earlier import configured the root logger** →
  launcher/wrapper logs silently lost. Own the root logger: clear handlers + add a `FileHandler`
  explicitly (see `applio_launcher.py` logging setup, `macos_wrapper.py:setup_logging`).
- **`core.py`'s `from datetime import datetime` rebinds `datetime` to the class**, so injected
  `datetime.datetime.now()` in patches throws `AttributeError`. In patches use
  `import datetime as <alias>` + `<alias>.datetime.now()`.
- **`os._exit(N)` skips stdout flushing** - a preceding diagnostic `print` is lost (e.g.
  `rvc/train/train.py` sample-rate error). Recover via a line-buffered tee (`open(...,buffering=1)`)
  or `PYTHONUNBUFFERED=1`.
- **Post-training SIGTERM**: `rvc/train/train.py` ends with `os._exit(...)` which orphans its persistent DataLoader workers; their teardown signals the launcher's process group (session leader via `setsid`) -> spurious SIGTERM. In single-process, `_handle_terminate` ignores SIGTERM (Cmd+Q still quits via `applicationShouldTerminate_`).
- **Frozen module importability**: modules NOT in PyInstaller's traced graph (e.g. `rvc.lib.tools.process_log_parser` - nothing imports it) ship as DATA in `Contents/Resources`, NOT importable modules in `Contents/Frameworks`. A `from rvc... import ...` works in dev, fails (ImportError) frozen. Inline what you need into fork-owned code, or add to HIDDEN_IMPORTS. Check: `find dist/Applio.app/Contents/Frameworks -path "*<module>*"` (absent = not importable).
- **Reproduce frozen-subprocess behavior without the GUI:** `dist/Applio.app/Contents/MacOS/Applio
  /tmp/script.py args` - entry `applio_launcher.py` dispatches to the script (CWD=bundle).
- `ps -E -p <pid>` (macOS) dumps a frozen process's env - check inherited `APPLIO_*`/`PATH`.

**Build process gotchas:**
- Single entitlements file: `assets/entitlements.plist` (the old `scripts/entitlements_dev_id.plist` was deleted - it had drifted). Signing/notarization is built into `build_macos.py --sign --notarize --dmg` (the standalone `scripts/*.sh` were removed).
- No microphone entitlement needed - pywebview wrapper doesn't capture audio; Gradio handles it via browser
- **Patcher escape sequences:** In triple-quoted strings, `\\n` produces literal newline. Use `chr(10)` for newlines in patched code.
- Patches in `patches/` are applied to source files before PyInstaller, then source files are restored to pristine state
- **`post_build_restore` reliably leaves `tabs/train/train.py` dirty** (3 patchers touch it: dataset_paths, train_44100, refinegan_legacy_train). After EVERY build run `git checkout -- assets core.py rvc tabs`; never commit it patched
- PyInstaller cleans `dist/` at start - never delete while builds running
- Before `rm -rf dist build`: no `Applio` process may run from `dist/` (it holds file handles, so `rm` fails with "Directory not empty"). Quit it (`osascript -e 'tell application "Applio" to quit'`) + `sleep 3` first
- Build size: ~1.6GB lite (post-3.6.3 dependency stack; ~2GB models download on first launch)
- **Smoke = cert-free** `venv_macos/bin/python build_macos.py` (no flags; ad-hoc, runs locally) validates functionality; reserve `--sign --notarize --dmg` for the actual release
- Signing requires handling broken symlinks (use `path.exists()` before `rglob`)
- PyInstaller cache corruption: clear `~/Library/Application Support/pyinstaller/`
- **Signing & notarization (working):** `venv_macos/bin/python build_macos.py --sign --notarize --dmg`
  produces a notarized+stapled `.app` and `.dmg`. Auth = `--keychain-profile applio-notarize`
  (App Store Connect **Team Key**, **App Manager** role - stored via
  `xcrun notarytool store-credentials`). Pipeline: inside-out Mach-O sign (leaf binaries get
  `--options runtime --timestamp` only; entitlements only on the outer bundle) → notarize `.app`
  (ditto zip) → staple `.app` → build+sign `.dmg` (`--timestamp`) → notarize `.dmg` → staple `.dmg`.
  `CFBundleVersion` must be ≤3 numeric segments (derived `3060305`-style integer, NOT the 4-segment
  display VERSION). A stapled artifact should not need `xattr -cr` from end users. **Validated
  end-to-end 2026-07-26** - `v3.6.3.5` is the first notarized release (both `.app` + `.dmg` pass
  `spctl`/`stapler validate` as `Notarized Developer ID`). Cut a release: `build_macos.py --sign
  --notarize --dmg` → commit/push → `git tag v<VERSION>` → `gh release create v<VERSION>
  dist/Applio-<VERSION>.dmg` (if `gh release` 403s on scope, use `gh api` to create + `curl` to upload
  the asset - see "GitHub releases" below).
- **CI signing:** `.github/workflows/release-macos.yml` (tag `v*` → build+sign+notarize+staple, attaches
  the DMG to the release) and `ci-macos.yml` (build-only, path-filtered, no cert). The release job runs
  in a protected `signing` **environment** and uses inline API-key auth (`build_macos.py --api-key …
  --api-key-id … --api-issuer …` - no keychain on the runner; the `--keychain-profile` path is for
  local). Secrets in the `signing` env: `MACOS_CERTIFICATE` (base64 .p12), `MACOS_CERTIFICATE_PWD`,
  `APP_STORE_CONNECT_KEY` (base64 .p8), `APP_STORE_CONNECT_KEY_ID`, `APP_STORE_CONNECT_ISSUER`. These
  are GitHub-side settings - a human must create the env + secrets; can't be done from code. macOS
  runners bill at ~10× and are metered even on public repos, hence the path-filtering + tag-only triggers.
  **Validated end-to-end 2026-07-27** (test tag → green run → notarized DMG auto-attached to the release;
  ~15 min). Each release run PAUSES for manual approval (required reviewers on the `signing` env);
  approve via Actions UI → *Review deployments* → `signing` → *Approve and deploy*; can't be done from code.
- **DMG symlink trap:** `create_dmg` MUST use `shutil.copytree(..., symlinks=True)`. Python.framework
  uses symlinks (`Python -> Versions/Current/Python`, `Resources -> Versions/Current/Resources`,
  `Current -> Versions/3.x`); the default `symlinks=False` flattens them into real files, breaking
  the framework's signature seal → the DMG notarization is rejected with "The signature of the binary
  is invalid" on the Python framework paths (the `.app` zip notarization still passes - only the DMG
  copy breaks). Staple the `.app` before building the DMG.
- **Mach-O detection must use bytes mode:** `file -b <path>` can emit non-UTF-8 bytes → `subprocess.run(text=True)`
  raises UnicodeDecodeError mid-sign. Use `capture_output=True` (no `text=True`) and test `b"Mach-O" in r.stdout`.
- **Verifying a notarized DMG:** `spctl --assess --type execute <dmg>` reports "rejected (…does not seem to be an
  app)" / "Insufficient Context" - expected for a disk image. The authoritative DMG check is
  `xcrun stapler validate <dmg>` → "The validate action worked!". (`.app` uses spctl; `.dmg` uses stapler.)
  Applied in `_final_verify`: the `.app` is gated on spctl/codesign/stapler, the `.dmg` ONLY on stapler
  validate - do NOT regress to gating the DMG on spctl (it hard-fails the whole build on a valid DMG;
  this exact bug shipped once and was caught by the CI release test).
- **Background build exit codes:** don't end a backgrounded build with `; echo "exit=$?"` - the task reports the
  LAST command's exit (the echo = 0), masking a failed build. Make the build the final command and read its real
  exit/output (`tail` the output file, check for `BUILD COMPLETE` / hard-fail markers).
- **Cert-free gates for signing changes:** a plain `build_macos.py` run (no `--sign`) is safe (`--help`/`py_compile`
  exit before the module-level build) and verifies `CFBundleVersion` in the built Info.plist + git-cleanliness
  without the cert; unit-test Mach-O detection by copying the fn to a temp script (`import build_macos` runs the build).
- **GHA macOS runners have no `rg`:** use `grep -E`/`grep -Eq` in workflow steps (a `rg -q` in
  `ci-macos.yml` once failed the run with "command not found"; locally `rg` exists, so this is CI-only).
- **Monitoring a CI run:** `gh run watch <id> -R froggeric/applio-macOS-native-app --exit-status`
  (make it the LAST command - a trailing `echo` masks its real exit). `status=waiting` = the `signing`
  environment's required-reviewer gate (approve in the Actions UI, not from code); `status=queued` =
  waiting for a runner. `gh run view <id> --log-failed` pulls the failed step's output.
- **Testing `release-macos.yml`:** push a throwaway tag (`git tag vX-citest && git push --tags`),
  approve the run, confirm, then tear down with `gh release delete vX-citest --cleanup-tag -y` (unlike
  `gh release create`, `gh release delete` needs no workflow scope). Don't use a real version tag for tests.
- **Upstream 3.6.3 changed `subprocess.run` calls:** upstream now assigns
  `result = subprocess.run(...)` and adds `if result.returncode != 0: return ...` after each.
  Patches that anchored on bare `subprocess.run(command)\n return f"..."` must be re-pointed to
  the new shape. In the 2026-07-24 sync this broke `patch_process_tracking` (5 sub-fns),
  `patch_subprocess_validation` (2), and `patch_preflight_validation`; `patch_loading_html` also
  needed type `"dir"` (not `"file"`) so `patch_all()` resolves the path. `patch_preprocess_warning`
  was removed as obsolete (upstream now handles empty datasets).

**Pywebview gotchas:**
- Menu callbacks need lambda wrappers: `MenuAction("About", lambda: show_about_dialog())` not `MenuAction("About", show_about_dialog)`
- **Menu is spec-driven (`menu_spec.py`):** ONE source of truth rendered by both processes. The launcher renders the full dynamic menu (PyObjC); the standalone wrapper renders a STATIC subset (pywebview `Menu`/`MenuAction` are immutable and cannot bind shortcuts - `venv_macos/.../webview/menu.py`). Standalone renderer MUST: title the app menu `__app__` (NOT "Applio" - that duplicates it), set `webview.settings['SHOW_DEFAULT_MENUS']=False` BEFORE `webview.start` (else pywebview auto-adds View/Edit; note: `webview.start` has NO `webview_settings` kwarg - use `webview.settings[...]`), and omit `app.about/hide/hide_others/quit` from its `__app__` payload (pywebview's unconditional `_add_app_menu` injects them). Verify with `venv_macos/bin/python tests/test_menu_spec.py`.
- **Update-check version compare must use `packaging.version`** (already a hiddenimport). The old `check_for_updates` used string `!=` (flagged downgrades as updates). Shared logic lives in `applio_update_check.py`; the manual item + a silent launch-time check both use it; network runs off the main thread (NSAutoreleasePool on the worker thread).

**Native macOS dialogs (PyObjC):**
- All dialogs use native NSAlert/NSWindow/NSPanel instead of pywebview HTML
- CRITICAL: Event loop choice matters - `AppHelper.runEventLoop()` for GUI apps with windows, NOT `runConsoleEventLoop()` (console tools only - causes window freeze)
- NSAlert for confirmations, NSWindow for complex UIs, NSPanel for utility windows
- Dialog classes: `AboutWindowController`, `ProgressWindowController` in `applio_launcher.py`
- CRITICAL: PyObjC method names - `method:with:param:` becomes `method_with_param_` (colons→underscores, append trailing underscore), e.g., `systemFontOfSize:weight:` → `systemFontOfSize_weight_` NOT `systemFontOfSize_ofWeight_`
- CRITICAL: NSBox doesn't have `setFillColor_()` in PyObjC - use bordered style or layer-based background instead
- `addSubview:positioned:relativeTo:` → `addSubview_positioned_relativeTo_` (NOT `addSubview_positioned_relative_`)
- CRITICAL: any class used as an NSWindow/NSTableView delegate, dataSource, or NSNotificationCenter observer MUST be an NSObject subclass (`class X(NSObject)` + `alloc().initWith…_()` + `objc.super(X, self).init()`) - a plain Python class crashes on `conformsToProtocol:` (ProcessDashboardController hit this). Same pattern as MenuActionHandler/ApplioAppDelegate.
- PyObjC NSTrackingArea in a frozen app: `NSTrackingActiveInActiveApp` may NOT deliver `mouseMovedWithEvent_` (the frozen app's "active" state is unreliable). Use `NSTrackingActiveAlways` + `window.setAcceptsMouseMovedEvents_(True)` for reliable hover/tracking on a custom NSView.
- PyObjC preserves ObjC selector case - `-[NSColor CGColor]` is `.CGColor()`, not `.cgColor()`. Verify a name imports (`python -c "from AppKit import X"`) BEFORE adding it to the `try/except`-wrapped top-level AppKit import (L72-89) - a bad name silently flips `NATIVE_APIS_AVAILABLE=False` app-wide.

**Progress window responsiveness:**
- Timer must be started AFTER background thread: call `_start_timer()` after `_start_file_thread()`
- Initial log read limited to last 50 lines (not entire file) to prevent queue flooding
- Window needs `activateIgnoringOtherApps_(True)` to receive mouse/keyboard events
- Text buffer limited to 100 lines with batch updates to prevent UI slowdown
- CRITICAL: Never use bare `except:` in queue processing - use `except queue.Empty:` to catch empty queue; bare except silently swallows AttributeError from typos, hiding real bugs

**Smart log display:**
- Live zone shows active tqdm progress in single line (not spam of hundreds of lines)
- Log zone shows only phase transitions, errors, and completions
- Phase completion includes duration (e.g., "[14:32:15] Preprocessing complete (2m 35s)")
- tqdm detection: regex `^\s*\d+%\|.*\|\s*\d+/\d+\s*\[` matches progress bar lines
- Phase detection: strips timestamps, matches "Starting X", "Xing", "X started" patterns
- 2-second timeout without tqdm activity triggers phase completion logging

**Rich Status Card:**
- Phase icon + name (📁 Preprocessing, 🔬 Feature extraction, 🎯 Training, 🎵 Inference, 🗣️ TTS)
- Visual progress bar with Unicode blocks (████░░░) + percentage
- Stats grid: Speed, ETA, Phase Time, Items

**Log syntax highlighting:**
- Timestamps in gray
- Phase starts (→) in blue
- Completions (✓) in green
- Errors (✗) in red
- Warnings (⚠) in orange
- Epoch milestones (◆) in purple
- Monospace font (Menlo 11pt)

**Status badge:**
- Pill-shaped, color-coded: Running (green), Paused (orange), Completed (blue), Error (red)

**Patch idempotency pattern:**
- Each patch function must check for its OWN specific marker (e.g., `if '_track_process("training"' in content`)
- DO NOT use a shared `IDEMPOTENCY_MARKER` check that returns early - this prevents actual patches from being applied

- **"dir" type patchers:** base_path is the directory containing the source file, use `os.path.join(base_path, "filename.py")` not the full path
- **runtime_paths.json keys:** Uses `data_path` for the data directory (not `base_path`)

**Version management:**
- Upstream renamed `assets/config.json` → `assets/config_template.json` (3.6.3) and now
  **gitignores `config.json`**; `app.py` creates `config.json` at runtime by copying the template.
- At **build time** the template is the source of truth (`config.json` is gitignored + locally
  regenerated), so `build_macos.py` and `patches/patch_loading_html.py` read `config_template.json`
  FIRST, then fall back to `config.json` (reading config.json first would embed a stale dev-local
  version). Runtime reads of `config.json` elsewhere are fine (app regenerates it).
- `macos_wrapper.py` copies the bundled template out as `config.json` for the running app.
- `macos_wrapper.py` reads VERSION dynamically from the config + BUILD_NUMBER
- `build_macos.py` uses same source - both must stay in sync
- `patch_loading_html.py` reads from the config for loading screen version

**Background process tracking:**
- State file: `~/.applio/active_processes.json` (single source of truth)
- Process types: training, preprocess, extract, tts (inference is in-process and tracked separately - see below)
- POSIX signals: SIGSTOP (pause), SIGCONT (resume), SIGTERM (terminate)
- Patch order: `patch_process_tracking.py` runs before `patch_subprocess_validation.py`.
  After the 3.6.3 rework, `subprocess_validation` anchors on the success-`return` line (which
  survives process_tracking's Popen transformation), so it injects only its post-run output
  validation (model_info.json / extracted-dir checks) - both patches now coexist on the same
  functions instead of being mutually exclusive.

**Batch-inference progress tracking (3.6.3.7):** inference runs IN-PROCESS (not a subprocess), so it
is NOT in `active_processes.json`. Tracked separately:
- `patches/patch_inference_progress.py` injects into `rvc/infer/infer.py:convert_audio_batch` to write
  `~/Applio/.applio/inference_progress.json` (single writer, atomic temp+`os.replace`, no lock) +
  check a cancel flag per file + append a schema-compatible history entry; it also
  `os.makedirs(audio_output_path, exist_ok=True)` (batch inference failed with an opaque soundfile
  "System error" on a missing output folder).
- `patches/patch_stop_infer.py` rewrites `stop_infer` to write `~/Applio/.applio/inference_cancel.flag`
  (cooperative) - the old PID-kill killed the whole app because the inference PID == the app PID in
  single-process.
- The dashboard synthesizes an `_is_inference` proc into `_active_processes` from the progress file
  (`_synthesize_inference_proc` in `applio_launcher.py`, at BOTH `update_process_list` +
  `refresh_process_list`); the stats math lives in the AppKit-free `applio_inference_stats.py`
  (pytest-importable). `_render_inference_detail` normalizes the history schema (ISO started_at /
  completed_at to epoch) so completed runs show counts/duration. `_sweep_stale_inference_progress`
  marks a stale `running` record `interrupted` on startup.

**GitHub releases:**
- Repo name for releases: `froggeric/applio-macOS-native-app`
- `gh release create` needs `workflow` scope; use `gh api` as fallback
- Create release via API: `gh api repos/{owner}/{repo}/releases -X POST -f tag_name=v{version}`
- Upload assets via curl when `gh release upload` fails: `curl -X POST -H "Authorization: token $(gh auth token)" -H "Content-Type: application/zip" --data-binary @file.zip "https://uploads.github.com/repos/{owner}/{repo}/releases/{release_id}/assets?name=file.zip"`
- Delete release: `gh api repos/{owner}/{repo}/releases/{id} -X DELETE`
- Delete a release ASSET: `gh api -X DELETE repos/{owner}/{repo}/releases/assets/{asset_id}` (path is `releases/assets/{asset_id}`, NOT `releases/{release_id}/assets/{id}`, which 404s)
- **Manual release vs CI:** pushing a `v*` tag auto-runs `release-macos.yml` (build+sign+attach). If you cut a release MANUALLY (local signed DMG + curl upload), `gh run cancel <id>` the triggered run right after tagging; otherwise it clashes on the same asset name + bills macOS minutes

**Version management:**
- Check upstream version: `git show upstream/main:assets/config_template.json | grep version`
- `build_macos.py` reads version from the config (template at build time) - keep both in sync

## Data Flow

**Voice Conversion Pipeline:**
```
Input Audio → AudioProcessor → Hubert embeddings → F0 extraction →
RVC Pipeline → PostProcessor (Pedalboard effects) → Output Audio
```

**Training Pipeline:**
```
Dataset → Preprocess (slicer) → Extract features → Train model →
Checkpoints in logs/{model_name}/
```

## Pretrained Models

**Vocoders** (neural architectures): HiFi-GAN, RefineGAN, MRF HiFi-GAN
**Pretrained models** (trained weights): Titan, KLM, Snowie, etc. - work WITH a vocoder

| Location | Purpose |
|----------|---------|
| `rvc/models/pretraineds/{vocoder}/` | Built-in pretrained weights |
| `rvc/models/pretraineds/custom/` | Community models (via Download tab) |
| `assets/pretrains.json` | Model download manifest |

**Adding new models:**
1. Add entry to `assets/pretrains_macos_additions.json` (format: `{"ModelName": {"48k": {"D": "url", "G": "url"}}}`)
2. For new sample rates, create `rvc/configs/{rate}.json` and add to `version_config_paths` in `config.py`

**44.1kHz Sample Rate (macOS fork only):**
- Config: `rvc/configs/44100.json`
- Applied at build time via `patches/patch_train_44100.py`
- Modifies `tabs/train/train.py` to add 44100 Hz option

**Recovering deleted HuggingFace files:**
```
https://huggingface.co/{repo}/resolve/{commit_hash}/{file_path}
```
