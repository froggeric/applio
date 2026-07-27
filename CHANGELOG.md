# Changelog

All notable changes to this macOS-native fork of Applio. Versions follow
`{Applio release}.{build}` (e.g. `3.6.3.5` = Applio 3.6.3, fork build 5).

## [Unreleased]

### Added
- **CI: macOS build + signed/notarized releases via GitHub Actions.**
  - `.github/workflows/ci-macos.yml` — path-filtered, build-only smoke test (ad-hoc, no cert) with
    `CFBundleVersion` + `codesign` assertions.
  - `.github/workflows/release-macos.yml` — on a `v*` tag, builds + signs + notarizes + staples the
    `.app`/`.dmg` on a `macos-14` runner and attaches the DMG to the release. Runs in a protected
    `signing` environment; inline App Store Connect API-key auth (no keychain on the runner). Validated
    end-to-end.
- `build_macos.py --api-key/--api-key-id/--api-issuer` — inline notarytool auth (CI/headless);
  `--keychain-profile` remains the default for local runs.

### Fixed
- `_final_verify` now gates the `.dmg` only on `xcrun stapler validate` (it was hard-failing on
  `spctl`, which reports "does not seem to be an app" for a disk image). Caught by the CI release test.

---

## [3.6.3.5] — 2026-07-26

### Added
- **Developer ID code signing + Apple notarization.** `build_macos.py --sign --notarize --dmg` now
  produces a **Gatekeeper-clean, signed + notarized + stapled** `.app` and `.dmg`. This is the first
  notarized release — end users no longer need `xattr -cr`. Authentication uses an App Store Connect
  API key (`--keychain-profile`); no secrets live in the repo.
- Voice model + FAISS index **merger tool** (`merge_rvc.py`) with weighted merging, auto-naming from
  model metadata, and merge-metadata output. See `MERGE_ALGORITHM.md`.
- `LSMinimumSystemVersion = 12.0.0` in the app `Info.plist` (Gatekeeper gives a clear message on
  unsupported macOS instead of a cryptic crash).

### Fixed (frozen-app reliability)
- Custom-pretrained **dropdown empty** and **downloads landing inside the bundle** — both now resolve
  to the external data directory when frozen (the frozen-CWD invariant).
- **Version surfaces inconsistent** — About dialog, loading screen, wrapper log, and the in-app
  version checker now all read `3.6.3.x` consistently (the checker reads the bundle's
  `config_template.json`, not a stale data-dir copy).
- **Training process tracking** — `verify_process_identity` now treats `psutil.AccessDenied` as
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

## [3.6.3] — 2026-03-03 (upstream sync baseline)

First release on the upstream 3.6.3 base. See `git log v3.6.3..HEAD` for the full delta.
