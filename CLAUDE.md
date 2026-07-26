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
| Code signing config | `assets/entitlements.plist`, `scripts/entitlements_dev_id.plist` |
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
| Build specification | `Applio.spec` |

## Code Conventions

- **Formatter**: Black (auto-runs via GitHub Actions on push to main)
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
- `assets/entitlements.plist`, `scripts/entitlements_dev_id.plist`
- `patches/`, `macos_wrapper.py`, `build_macos.py`, `Applio.spec`
- `install_applio_mac.sh`, `requirements_macos.txt`, `CLAUDE.md`

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
(pandas 2.3.x imports fine on 3.10 but needs numpy 2.x ABI — the old numpy 1.26 caused
`pandas._libs.tslibs.vectorized` failures.) If the fork ever moves to Python 3.11, these can
re-align to upstream's exact pins; that needs `brew install python@3.11` + a fresh `venv_macos`.

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
- **Launch `macos_wrapper.py` from a foreground terminal**, not `nohup ... &` — pywebview's
  AppKit event loop needs an interactive GUI session and blocks/idles when backgrounded.
- **Local `rvc/models` must NOT be deleted.** The default `build_macos.py` is a *lite*
  build: `clean_bundled_models()` strips model weights from `dist/Applio.app` (the bundle
  only — shipped app stays ~870M) and never touches the local filesystem. So keeping the
  ~1.8G of models in gitignored `rvc/models/` does NOT bloat the shipped app, and `rm -rf
  rvc/models/*` only forces a costly ~2G re-download. Leave local models in place; the
  bundle is re-stripped on every build. (A model-bundled build is `--models-installer`, a
  separate app — there is no CLI flag to bundle models into the main app; `--lite` is
  `store_true, default=True`, i.e. always on.)
- **Corrupted `venv_macos` package:** if `import torch`/`pandas` fails with a partial-init /
  circular-import error, the installed wheel is corrupt → fix with
  `venv_macos/bin/python -m pip install --force-reinstall --no-deps <pkg>`.
- **Frozen subprocess CWD is the bundle (`sys._MEIPASS`/Frameworks), not the data dir** —
  so `os.getcwd()`/`now_dir`-relative paths break. Resolve user/data paths absolutely:
  `APPLIO_DATA_PATH` env → `runtime_paths.json` `data_path` → `~/Applio`.
- **`logging.basicConfig` is a no-op once an earlier import configured the root logger** →
  launcher/wrapper logs silently lost. Own the root logger: clear handlers + add a `FileHandler`
  explicitly (see `applio_launcher.py` logging setup, `macos_wrapper.py:setup_logging`).
- **`core.py`'s `from datetime import datetime` rebinds `datetime` to the class**, so injected
  `datetime.datetime.now()` in patches throws `AttributeError`. In patches use
  `import datetime as <alias>` + `<alias>.datetime.now()`.
- **`os._exit(N)` skips stdout flushing** — a preceding diagnostic `print` is lost (e.g.
  `rvc/train/train.py` sample-rate error). Recover via a line-buffered tee (`open(...,buffering=1)`)
  or `PYTHONUNBUFFERED=1`.
- **Reproduce frozen-subprocess behavior without the GUI:** `dist/Applio.app/Contents/MacOS/Applio
  /tmp/script.py args` — entry `applio_launcher.py` dispatches to the script (CWD=bundle).
- `ps -E -p <pid>` (macOS) dumps a frozen process's env — check inherited `APPLIO_*`/`PATH`.

**Build process gotchas:**
- Two entitlements files must stay in sync: `assets/entitlements.plist` (full) and `scripts/entitlements_dev_id.plist` (minimal for Developer ID)
- No microphone entitlement needed - pywebview wrapper doesn't capture audio; Gradio handles it via browser
- **Patcher escape sequences:** In triple-quoted strings, `\\n` produces literal newline. Use `chr(10)` for newlines in patched code.
- Patches in `patches/` are applied to source files before PyInstaller, then source files are restored to pristine state
- PyInstaller cleans `dist/` at start - never delete while builds running
- Build size: ~850MB (~2GB downloads on first launch)
- Signing requires handling broken symlinks (use `path.exists()` before `rglob`)
- PyInstaller cache corruption: clear `~/Library/Application Support/pyinstaller/`
- Notarization fails for PyInstaller apps - users run `xattr -cr Applio.app`
- **Upstream 3.6.3 changed `subprocess.run` calls:** upstream now assigns
  `result = subprocess.run(...)` and adds `if result.returncode != 0: return ...` after each.
  Patches that anchored on bare `subprocess.run(command)\n return f"..."` must be re-pointed to
  the new shape. In the 2026-07-24 sync this broke `patch_process_tracking` (5 sub-fns),
  `patch_subprocess_validation` (2), and `patch_preflight_validation`; `patch_loading_html` also
  needed type `"dir"` (not `"file"`) so `patch_all()` resolves the path. `patch_preprocess_warning`
  was removed as obsolete (upstream now handles empty datasets).

**Pywebview gotchas:**
- Menu callbacks need lambda wrappers: `MenuAction("About", lambda: show_about_dialog())` not `MenuAction("About", show_about_dialog)`

**Native macOS dialogs (PyObjC):**
- All dialogs use native NSAlert/NSWindow/NSPanel instead of pywebview HTML
- CRITICAL: Event loop choice matters - `AppHelper.runEventLoop()` for GUI apps with windows, NOT `runConsoleEventLoop()` (console tools only - causes window freeze)
- NSAlert for confirmations, NSWindow for complex UIs, NSPanel for utility windows
- Dialog classes: `AboutWindowController`, `ProgressWindowController` in `applio_launcher.py`
- CRITICAL: PyObjC method names - `method:with:param:` becomes `method_with_param_` (colons→underscores, append trailing underscore), e.g., `systemFontOfSize:weight:` → `systemFontOfSize_weight_` NOT `systemFontOfSize_ofWeight_`
- CRITICAL: NSBox doesn't have `setFillColor_()` in PyObjC - use bordered style or layer-based background instead
- `addSubview:positioned:relativeTo:` → `addSubview_positioned_relativeTo_` (NOT `addSubview_positioned_relative_`)

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

**Launcher architecture limitation:**
- Both launcher and wrapper have `NSApplicationActivationPolicyRegular`, causing "2 icons in dock" - both are GUI processes

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
- Process types: training, preprocess, extract, inference, tts
- POSIX signals: SIGSTOP (pause), SIGCONT (resume), SIGTERM (terminate)
- Patch order: `patch_process_tracking.py` runs before `patch_subprocess_validation.py`.
  After the 3.6.3 rework, `subprocess_validation` anchors on the success-`return` line (which
  survives process_tracking's Popen transformation), so it injects only its post-run output
  validation (model_info.json / extracted-dir checks) — both patches now coexist on the same
  functions instead of being mutually exclusive.

**GitHub releases:**
- Repo name for releases: `froggeric/applio-macOS-native-app`
- `gh release create` needs `workflow` scope; use `gh api` as fallback
- Create release via API: `gh api repos/{owner}/{repo}/releases -X POST -f tag_name=v{version}`
- Upload assets via curl when `gh release upload` fails: `curl -X POST -H "Authorization: token $(gh auth token)" -H "Content-Type: application/zip" --data-binary @file.zip "https://uploads.github.com/repos/{owner}/{repo}/releases/{release_id}/assets?name=file.zip"`
- Delete release: `gh api repos/{owner}/{repo}/releases/{id} -X DELETE`

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
