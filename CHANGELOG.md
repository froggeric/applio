# Changelog

All notable changes to this macOS-native fork of Applio. Versions follow
`{Applio release}.{build}` (e.g. `3.6.3.5` = Applio 3.6.3, fork build 5).

## [Unreleased]

### Added

- **Accessibility, Phase 3 (fork-local hardening).** Seven targeted fixes from the Phase 2 review,
  all fork-side (no upstream files), each with tests:
  - **Localized native strings, completed.** The remaining native English clusters — boot loading
    stages, headings and technical details, dashboard statuses, the About alert, dynamic
    process-status titles — resolve through the app language; locale matching now follows
    upstream's prefix-glob semantics, and a corrupt language file is skipped instead of crashing.
  - **Scoped record-toggle healing.** The injected `aria-pressed` repair no longer stamps every
    Start/Stop-labeled button; it is scoped to the realtime record toggle.
  - **One terminal-words map.** The web payload and the native announcer share a single helper,
    removing a two-place sync point.
  - **Failure log tails in the web UI.** Failed jobs append a bounded log tail (last 1200
    characters, at most 2 jobs) to the "Last result" region — readable with a screen reader;
    spoken announcements are unchanged.
  - **Path validation on every Browse field.** All 13 path fields warn on blur when the typed
    path does not exist (an announced toast), after `~/…` expansion.
  - New test suites `tests/test_a11y_js_invariants.py` and `tests/test_patcher_exit_codes.py`.
- **Accessibility, Phase 2 (web UI, pickers, settings, i18n).** Screen-reader support now reaches
  inside the Gradio web UI, and path fields get native pickers:
  - **Announcements in the web UI.** A live region + "Last result" region are injected into the
    page; job milestones ("25% of epoch 12/50"), completions, failures, and output-text changes are
    announced in external browsers too (the in-app window keeps its native VoiceOver engine — no
    double-speaking). Accordion and tab semantics are healed for VoiceOver, and focus is restored
    after Gradio re-renders.
  - **Browse… buttons on every path field.** All 13 path fields across Training, Inference, TTS,
    Realtime, Voice Blender, and Processing get a "Browse…" button opening a native macOS
    file/folder panel; the chosen path fills the field, and typed `~/…` paths are expanded.
  - **Accessibility settings submenu.** Announcements: Off / Standard / Verbose, plus Sound Cues —
    persisted across launches, applied to both the native engine and the web UI.
  - **Localized native strings.** Menu, picker, and announcement strings resolve through the
    app's language setting (fork-owned translation layer; upstream files untouched).
- **Accessibility, Phase 1 (native wrapper foundation).** Voice support across the native app:
  - **Announced job lifecycle + dock badge.** Posts VoiceOver announcements (with `[A11y]`
    lines in `~/Library/Logs/Applio/applio_launcher.log`) when a training, preprocessing,
    feature-extraction, or batch-inference job starts, finishes, errors, or is cancelled;
    the dock badge shows the active-job count and finished jobs request dock attention.
  - **Edit menu + keyboard shortcuts.** Edit → Cut/Copy/Paste/Select All (⌘X/⌘C/⌘V/⌘A) reaches
    text fields inside the web UI through the responder chain; ⌘L opens the Logs folder, ⇧⌘D
    sets the data location, ⌘0 refocuses the main window, ⇧⌘R reveals the data folder in Finder.
  - **Process menu live jobs submenu.** The Process menu now lists active background jobs;
    selecting one opens the dashboard (Pause/Resume live in its action bar) instead of a
    static disabled status line.
  - **Enabled downloads.** Model export / download links open a native save panel instead of
    being silently swallowed by the webview.
  - **Accessible boot/loading screen.** The startup screen is a polite live region announcing
    each boot stage, its progress bar exposes real values, the window title tracks the stage,
    and a stalled boot raises an alert instead of hanging forever.
- **Mic permission string.** Re-added `NSMicrophoneUsageDescription` so realtime voice
  conversion can request microphone access instead of being silently denied.

### Fixed

- **Truthful accessibility labels.** Dashboard labels track Pause/Resume, inference mode, and
  real status; dashboard rows, the loss chart, and progress bars expose their values to
  VoiceOver; the progress window's live log zone reads as words instead of glyph noise.
- **Safe dialog defaults.** Destructive confirms put Cancel first and never bind Return (Enter
  on the quit confirm does nothing; Escape cancels); update alerts activate properly; progress
  dialogs land focus on a safe first responder. The close confirmation defaults to "Keep
  Running". First run without a chosen data location now asks instead of silently defaulting.
- **Announced Stop/upload feedback.** Stop and file-upload actions in the web UI post
  spoken/spoken-equivalent feedback via a build-time patch instead of failing silently.

### Changed

- **Build now fails on a missed patch anchor — maintainer-facing behavior change.** A patcher
  that cannot find its anchor after an upstream sync exits with code `2` and the build stops,
  listing every failure; previously an anchor miss could pass silently (exit `1` was read as
  "already patched"). Exit `1` remains the standalone usage guard, and `patches/download_pretraineds.py`
  (model downloader, own invocation path) is exempt.

---

## [3.6.4.0] - 2026-08-13

First release on the **upstream Applio 3.6.4** base. Signed and notarized — download the DMG and
open it directly (no `xattr -cr` needed).

### Synced with upstream Applio 3.6.4

- **New command-line interface.** Upstream rebuilt Applio's CLI on [Click](https://click.palletsprojects.com/)
  (`python core.py <command>`), replacing the old argparse parser. This is a terminal/developer
  feature; the macOS app is unaffected — its UI, training, inference, TTS, and the script-launching
  functions it calls are unchanged.
- **Realtime voice conversion fixes** from upstream: block-frame processing and a warmup
  progress-bar fix.
- New runtime dependency **`click`** (pinned `click==8.1.8` in `requirements_macos.txt`); it is
  bundled into the app, so users need do nothing.

### Notes

- Every macOS-specific feature carries over unchanged and is validated on this build: the
  single-process native app, the Process Dashboard (training + batch inference), the RefineGAN-Legacy
  vocoder, 44.1 kHz training, the native menu bar, and external data storage.
- Build verified end-to-end: all 24 build-time patches apply cleanly against the upstream-rewritten
  `core.py`/`app.py`, and the app boots to the main UI reporting version 3.6.4.

### Changed

- `BUILD_NUMBER` reset to `0` for the new upstream base — display version `3.6.4.0`,
  `CFBundleVersion` `3060400`.

---

## [3.6.3.7] - 2026-07-31

### Added
- **Process Dashboard: batch voice-conversion progress.** The dashboard now tracks batch inference
  (Process → Open Progress Dashboard, ⌘⇧P): files converted / total, current file, derived ETA, and
  speed (files/min), with an auto-show on batch start. Completed and cancelled batch runs appear in
  the dashboard history, and a stale `running` record left by a crash or quit is marked `interrupted`
  on the next launch so the dashboard never shows a phantom running job.

### Changed
- **Single-process is now the only architecture.** The two-process code and the `APPLIO_SINGLE_PROCESS`
  flag were removed; the app runs as one native process (one dock icon, one menu, one window). The
  previous legacy fallback (`APPLIO_SINGLE_PROCESS=0`) is gone.

### Fixed
- **Inference "Stop" no longer quits the whole app.** In single-process the inference PID was the app
  PID, so the old PID-kill Stop quit Applio mid-batch. Batch inference Stop now cancels cooperatively
  via a cancel flag checked per file. Also fixes a frozen-build issue where batch inference could not
  write its stop-PID file in the read-only app bundle (the PID file is gone, replaced by the cancel
  flag in the writable data directory).
- **Batch conversion creates its output folder.** Batch inference now creates the output folder if it
  does not exist (it previously failed on the first file with an opaque soundfile "System error" when
  the chosen output path was missing). Completed batch runs also show their file counts and duration
  on the dashboard and in history, not just a bare "completed" status.

---

## [3.6.3.6] - 2026-07-30

### Added
- **Process Dashboard** (Process → Open Progress Dashboard, ⌘⇧P): a live training-monitoring window.
  Shows real-time metrics - best epoch + loss, current/total epoch, step, speed, and a derived ETA,
  beside an epoch-fraction progress bar, plus a **loss-vs-epoch curve that highlights significant
  improvements** (green markers + epoch numbers at notable loss drops). An **action bar** offers
  Stop / Pause-Resume / Reveal Log in Finder / Open Log. **Best-epoch metrics are snapshotted into
  history**, so they survive an app restart and re-training the same model. The dashboard
  **auto-shows when a job starts**, and when idle lets you **browse finished runs** from history.
- **Phase 2 single-process merge (now the default):** merges the two-process launcher+wrapper into
  one native process (fixes Hide-not-hiding + menu-swaps-by-focus). The `APPLIO_SINGLE_PROCESS` flag
  default flipped to `"1"`, so single-process is now the standard (the app runs as one process out of
  the box: one dock icon, one menu, one window); two-process is the legacy fallback
  (`APPLIO_SINGLE_PROCESS=0`, byte-for-byte the old path). Functionally complete and
  **frozen-validated** (training, reopen, quit, menu, and dashboard all work in the built app). Tasks
  through 3a done (single-instance surfacing via `bring_to_front`). Remaining: dead two-process code
  removal + drop the flag (Task 4). Plan: `~/.claude/plans/phase2-single-process-merge.md`.
- **Native menu overhaul:** one shared `menu_spec.py` rendered by a PyObjC renderer
  (launcher) and a pywebview static-subset renderer (standalone). New Process + Help menus;
  Reveal-in-Finder rescued; Hide ⌘H / Minimize ⌘M; the dead Menu B deleted.
- **Real update checking:** manual `Check for Updates…` queries GitHub releases, and a silent
  launch-time check alerts only if a newer version exists. Version comparison fixed (was a buggy
  string compare; now `packaging.version`).
- **Studio Production Guide** bundled (rendered HTML) under Help.
- `tests/test_menu_spec.py` - pure-Python structure + version-compare gate.
- **CI: macOS build + signed/notarized releases via GitHub Actions.**
  - `.github/workflows/ci-macos.yml` - path-filtered, build-only smoke test (ad-hoc, no cert) with
    `CFBundleVersion` + `codesign` assertions.
  - `.github/workflows/release-macos.yml` - on a `v*` tag, builds + signs + notarizes + staples the
    `.app`/`.dmg` on a `macos-14` runner and attaches the DMG to the release. Runs in a protected
    `signing` environment; inline App Store Connect API-key auth (no keychain on the runner). Validated
    end-to-end.
- `build_macos.py --api-key/--api-key-id/--api-issuer` - inline notarytool auth (CI/headless);
  `--keychain-profile` remains the default for local runs.

### Fixed
- **Process Dashboard window did not open at all** - `ProcessDashboardController` now subclasses
  `NSObject` (a plain Python class crashed on `conformsToProtocol:`) and the missing `AppKit`
  constants (`NSBoxPrimary`, …) are imported so the window constructs. Loss-vs-epoch axes are fixed
  and the stray "Title" placeholder text removed.
- Post-training `SIGTERM` no longer quits the whole app (single-process).
- `_final_verify` now gates the `.dmg` only on `xcrun stapler validate` (it was hard-failing on
  `spctl`, which reports "does not seem to be an app" for a disk image). Caught by the CI release test.

---

## [3.6.3.5] - 2026-07-26

### Added
- **Developer ID code signing + Apple notarization.** `build_macos.py --sign --notarize --dmg` now
  produces a **Gatekeeper-clean, signed + notarized + stapled** `.app` and `.dmg`. This is the first
  notarized release - end users no longer need `xattr -cr`. Authentication uses an App Store Connect
  API key (`--keychain-profile`); no secrets live in the repo.
- Voice model + FAISS index **merger tool** (`merge_rvc.py`) with weighted merging, auto-naming from
  model metadata, and merge-metadata output. See `MERGE_ALGORITHM.md`.
- `LSMinimumSystemVersion = 12.0.0` in the app `Info.plist` (Gatekeeper gives a clear message on
  unsupported macOS instead of a cryptic crash).

### Fixed (frozen-app reliability)
- Custom-pretrained **dropdown empty** and **downloads landing inside the bundle** - both now resolve
  to the external data directory when frozen (the frozen-CWD invariant).
- **Version surfaces inconsistent** - About dialog, loading screen, wrapper log, and the in-app
  version checker now all read `3.6.3.x` consistently (the checker reads the bundle's
  `config_template.json`, not a stale data-dir copy).
- **Training process tracking** - `verify_process_identity` now treats `psutil.AccessDenied` as
  "alive" so the quit-while-training confirmation fires reliably mid-training.
- **Frozen training pipeline** (preprocess → extract → train) + dev-mode dock icon + error logging.

### Changed
- **Native macOS app lifecycle (Phase 1):** single dock icon, unified quit cascade, crash-recovery
  relaunch, "Keep Running" (hide vs quit), and instant reopen.
- Synced with **upstream Applio 3.6.3** (minimal delta; macOS work stays in fork-only files).

### Internal (build/release)
- Rewrote `build_macos.py` signing/notarization: inside-out Mach-O signing (catches bare executables
  the old `*.so`/`*.dylib` glob missed, including the Python interpreter and `torch/bin/*`),
  entitlements only on the outer bundle, `ditto`-zip submission, `status: Accepted` parsing with
  automatic JSON-log pull on failure, staple-`.app`-before-building-DMG, `shutil.copytree(symlinks=True)`
  to preserve the `Python.framework` symlinks, and hard-fail `codesign --verify` / `spctl` gates.
- Fixed `CFBundleVersion` (was the invalid 4-segment `3.6.3.5`; now a monotonic `3060305`-style integer).
- Removed the orphaned `scripts/sign_bundle.sh`, `scripts/notarize.sh`, `scripts/entitlements_dev_id.plist`.
- `.gitignore` hardened against credential leaks (`*.p8`, `*.p12`, `*.key`).

---

## [3.6.3] - 2026-03-03 (upstream sync baseline)

First release on the upstream 3.6.3 base. See `git log v3.6.3..HEAD` for the full delta.
