# Applio Fork Differences from Upstream

This document catalogs all changes between this fork (froggeric/applio) and the upstream repository (IAHispano/Applio).

**Comparison:** `upstream/main` vs `HEAD`

---

## Summary

This fork maintains a **minimal delta** from upstream - only macOS native app additions, no modifications to core functionality. All upstream changes are applied via build-time patchers, not by modifying source files directly.

**Important:** Fork-only files (`applio_launcher.py`, `build_macos.py`, `macos_wrapper.py`, etc.) can be modified directly. Upstream files (like `core.py`, `tabs/train/train.py`) must only be modified via patches at build time.

| Category | Count |
|----------|-------|
| Added Files | 16+ |
| Modified Files | 1 (.gitignore only) |

---

## Added Files (macOS Native App Support)

### Core Application Files

| File | Purpose |
|------|---------|
| `applio_launcher.py` | Native macOS launcher with progress window, process group leader, native menu bar |
| `macos_wrapper.py` | Native macOS app wrapper using PyWebView with native dialogs (NSAlert/NSWindow), external data location, process tracking |
| `menu_spec.py` | Single source of truth for the native menu (Applio/File/Process/Window/Help); rendered by both the PyObjC launcher (full + dynamic) and the pywebview standalone wrapper (static subset) |
| `applio_update_check.py` | Shared update-check logic (queries GitHub releases; uses `packaging.version` to compare). Manual `Check for Updates…` + a silent launch-time check both call it; network runs off the main thread |
| `build_macos.py` | PyInstaller build script for creating `Applio.app` bundle with DMG/PKG options |
| `requirements_macos.txt` | macOS-specific dependencies (pywebview, pyinstaller, pyobjc) |
| `README_MACOS.md` | Build instructions, troubleshooting, and usage documentation |

### Installer Scripts

| File | Purpose |
|------|---------|
| `install_applio_mac.sh` | Standalone macOS installation script with Homebrew dependencies |

### Models Installer (Standalone)

| File | Purpose |
|------|---------|
| `models_installer.py` | Standalone installer that bundles and copies pretrained models to user's data location |
| `ApplioModelsInstaller.spec` | PyInstaller spec for models installer (auto-generated) |

### Build-Time Patches

| File | Purpose |
|------|---------|
| `patches/patch_train_44100.py` | Patches training UI to add 44.1kHz sample rate option |
| `patches/patch_data_paths.py` | Patches core.py to redirect logs_path to external data location |
| `patches/download_pretraineds.py` | Downloads custom pretrained models (KLM49, TITAN, KLM50, VCTK) |
| `patches/patch_refinegan_legacy.py` | Patches RefineGAN for original RVC-Boss pretrained model compatibility |
| `patches/patch_refinegan_legacy_*.py` | Architecture patches for RefineGAN legacy discriminator/generator |
| `patches/patch_process_tracking.py` | Process tracking for training/inference monitoring |
| `patches/patch_static_resources.py` | Static resource path resolution for bundled app |
| `patches/patch_multiprocessing.py` | Multiprocessing fixes for macOS |
| `patches/patch_f0_model_paths.py` | F0 model path resolution |
| `patches/patch_pretrained_selector.py` | Pretrained model selector patches |
| `patches/patch_train_paths.py` | Training path resolution |
| `patches/patch_dataset_paths.py` | Dataset path resolution |
| `patches/patch_extract_error_logging.py` | Enhanced error logging for feature extraction |
| `patches/patch_subprocess_validation.py` | Subprocess validation for training |
| `patches/patch_preflight_validation.py` | Preflight validation for training configuration |

### Assets

| File | Purpose |
|------|---------|
| `assets/entitlements.plist` | macOS code signing entitlements (hardened-runtime: JIT, unsigned-executable-memory, disable-library-validation; + network/camera — no microphone; see README_MACOS.md) |
| `assets/loading.html` | HTML/CSS loading screen shown during backend startup |
| `assets/pretrains_macos_additions.json` | Additional pretrained model definitions for Download tab |
| `STUDIO_PRODUCTION_GUIDE.html` | Rendered (build-time) HTML guide opened from Help → Studio Production Guide; source is the `STUDIO_PRODUCTION_GUIDE.md`, rendered by `build_macos.py:render_guide_html` and bundled via `datas` |

### Tests

| File | Purpose |
|------|---------|
| `tests/test_menu_spec.py` | Pure-Python gate for the menu: asserts `menu_spec.py` structure + taxonomy (Applio/File/Process/Window/Help, key contracts) and the `packaging.version` update-compare. Run: `venv_macos/bin/python tests/test_menu_spec.py` |

## Modified Files (from Upstream)

**Only `.gitignore` is modified from upstream.** All other changes are either:
- **Added files** (fork-only, can be modified directly)
- **Build-time patches** (applied during build, source files restored after)

| File | Change |
|------|--------|
| `.gitignore` | Added macOS build artifacts, model files (*.pt, *.pth, *.bin), rvc/models/, .archive/ |

**Fork-only files that CAN be modified directly:**
- `applio_launcher.py` - Native launcher (NEW, not in upstream)
- `build_macos.py` - Build script (NEW, not in upstream)
- `macos_wrapper.py` - Native wrapper (NEW, not in upstream)
- `models_installer.py` - Models installer (NEW, not in upstream)
- `menu_spec.py` - Shared menu spec (NEW, not in upstream)
- `applio_update_check.py` - Shared update-check logic (NEW, not in upstream)
- `tests/test_menu_spec.py` - Menu structure + version-compare test (NEW, not in upstream)
- `STUDIO_PRODUCTION_GUIDE.html` - Bundled help guide (NEW, not in upstream)
- All `patches/*.py` files (NEW, not in upstream)

**Upstream files that MUST use build-time patches:**
- `core.py` - Patched at build time, restored after
- `tabs/train/train.py` - Patched at build time, restored after
- `rvc/train/train.py` - Patched at build time, restored after
- `rvc/lib/algorithm/discriminators.py` - Patched at build time, restored after
- All other upstream files

---

## Key macOS-Specific Features

### External Data Storage

On first launch, users select where to store all Applio data (models, datasets, training outputs). This location persists in macOS preferences (`com.iahispano.applio`).

**Benefits:**
- Data persists across app updates
- Large files don't bloat the app bundle
- Users can choose external drives for storage

### Build Modes

| Mode | App Size | Models | Use Case |
|------|----------|--------|----------|
| **LITE** (default) | ~820 MB | Download on first launch | Distribution, updates |
| **Models Bundle** | ~5.3 GB | Bundled in PKG | Offline, preservation |

### `macos_wrapper.py` - Main Features

1. **External Data Location:**
   - First-run folder selection dialog
   - Preferences stored in NSUserDefaults
   - Menu: File → Set Data Location, Open in Finder

2. **Environment Setup:**
   - `PYTORCH_ENABLE_MPS_FALLBACK=1` - GPU fallback for Apple Silicon
   - `PYTORCH_ENABLE_METAL_ACCELERATOR=1` - Metal acceleration
   - Cache redirection to `~/Library/Application Support/Applio/`

3. **Native macOS Dialogs:**
   - About dialog: Native NSPanel with version info, GitHub link, update check
   - Check for Updates: Native NSAlert with **`packaging.version`** comparison (was a buggy string `!=`); shared logic in `applio_update_check.py`, also runs silently at launch
   - Close confirmation: Native NSAlert when closing with active processes
   - Progress monitor: Native NSWindow with pause/resume/terminate controls

4. **Native Progress Window** (`applio_launcher.py`):
   - Training info panel showing best epoch (lowest loss), current epoch, training speed
   - Rich status card with phase detection, tqdm progress parsing
   - Real-time log tailing with smart buffer management
   - Process controls: Terminate, Pause/Resume, Open Logs, Relaunch App
   - Queue-based architecture with memory limits
   - File rotation detection and race condition handling

4. **Process Tracking:**
   - Background training/inference process monitoring
   - State file: `~/.applio/active_processes.json`
   - POSIX signals: SIGSTOP (pause), SIGCONT (resume), SIGTERM (terminate)

5. **Loading Screen:**
   - Serves `assets/loading.html` during backend startup
   - 600-second timeout for first-time model downloads

6. **Subprocess Support:**
   - Training scripts run from app bundle (not user data location)
   - Script path resolution with fallback to BASE_PATH

### Native Menu Bar (spec-driven)

The menu is defined **once** in `menu_spec.py` and rendered by two thin renderers, so the
launcher and the standalone wrapper never drift:

- **Applio** — About, Check for Updates…, Hide ⌘H, Quit ⌘Q
- **File** — Set Data Location…, Reveal in Finder (logs / datasets / audios / models / …)
- **Process** — live `● Training: <name>` status (disabled when idle) + Open Dashboard ⌘⇧P
- **Window** — Minimize ⌘M, Zoom, Show Main
- **Help** — Studio Production Guide, Online Docs, Report an Issue, Discord

**Launcher (`applio_launcher.py`, PyObjC):** renders the **full + dynamic** menu — binds the
keyboard shortcuts, and a 2 s `NSTimer` refreshes the Process status line and toggles each
Reveal-in-Finder item on whether its folder exists. The old dead "Menu B" (`get_native_menu`)
is deleted.

**Standalone wrapper (`macos_wrapper.py`, pywebview):** renders a **static subset** — pywebview's
`Menu`/`MenuAction` are immutable and can't bind shortcuts or update labels, so shortcuts and the
live Process status are launcher-only. The standalone renderer titles the app menu `__app__`,
sets `webview.settings['SHOW_DEFAULT_MENUS']=False`, and omits the app.* items pywebview injects
(see CLAUDE.md → "Pywebview gotchas").

### `build_macos.py` - Build Options

```bash
venv_macos/bin/python build_macos.py                           # Basic build (LITE, ad-hoc signed)
venv_macos/bin/python build_macos.py --sign --notarize --dmg   # Release: sign + notarize + staple (.app AND .dmg)
venv_macos/bin/python build_macos.py --models-installer        # Standalone models-installer app
# Optional overrides:
#   --keychain-profile NAME   notarytool profile (default: applio-notarize; local interactive)
#   --api-key FILE --api-key-id ID --api-issuer UUID   inline App Store Connect API key (CI/headless; no keychain)
#   --identity "Developer ID Application: ..."   codesign identity
#   --team-id XXXXXXXXXX      Apple team id
#   --build-number N          bump the build (drives VERSION + CFBundleVersion)
```

### Code Signing & Notarization (new in 3.6.3.5)

The fork ships a working **Developer ID sign + Apple notarize + staple** pipeline (the first
notarized release). `--sign --notarize --dmg` produces a Gatekeeper-clean `.app` and `.dmg`:
inside-out Mach-O signing (hardened runtime; entitlements only on the outer bundle) → ditto-zip +
`notarytool submit --keychain-profile applio-notarize` → staple `.app` → build + sign `.dmg`
(preserving the `Python.framework` symlinks) → notarize + staple `.dmg` → final
`spctl`/`stapler validate`. Auth is an App Store Connect **Team Key** (role **App Manager**); **no
secrets live in the repo**. See `README_MACOS.md` → "Code Signing & Notarization" for full setup.

### Build-Time Patchers

All upstream modifications happen at build time:

| Patcher | Target | Change |
|---------|--------|--------|
| `patch_data_paths.py` | `core.py` | Redirects `logs_path` to external data location |
| `patch_train_44100.py` | `tabs/train/train.py` | Adds 44.1kHz sample rate option |
| `download_pretraineds.py` | (downloads) | Fetches custom models during build |

---

## File Locations (macOS App)

### User Data Location (User-Selected)

| Purpose | Path (relative to data location) |
|---------|----------------------------------|
| Training outputs | `logs/` |
| Voice models | `logs/{model_name}/*.pth` |
| Datasets | `assets/datasets/` |
| Inference outputs | `assets/audios/` |
| Pretrained models | `rvc/models/pretraineds/` |
| F0 predictors | `rvc/models/predictors/` |
| Embedders | `rvc/models/embedders/` |

### Cache Locations (Fixed)

| Purpose | Location |
|---------|----------|
| HuggingFace cache | `~/Library/Application Support/Applio/huggingface/` |
| Gradio temp files | `~/Library/Caches/Applio/gradio/` |
| App logs | `~/Library/Logs/Applio/applio_wrapper.log` |

### Preferences

| Purpose | Location |
|---------|----------|
| Data path, first-run flag | `~/Library/Preferences/com.iahispano.applio.plist` |

---

## Syncing with Upstream

To update from upstream:

```bash
git fetch upstream
git merge upstream/main
```

Since this fork only adds files that don't exist in upstream, there should be no merge conflicts. Model files in `rvc/models/` are gitignored and will persist.

---

## Building the macOS App

```bash
# Development (requires venv_macos with dependencies)
source venv_macos/bin/activate
python applio_launcher.py          # foreground terminal (pywebview idles when backgrounded)

# Build app bundle (LITE mode)
venv_macos/bin/python build_macos.py
# Output: dist/Applio.app (~1.6GB, models download on first launch)

# Build models installer (optional, separate artifact)
venv_macos/bin/python build_macos.py --models-installer

# Release build (signed + notarized + stapled .app and .dmg)
venv_macos/bin/python build_macos.py --sign --notarize --dmg
```

See `README_MACOS.md` for detailed instructions.
