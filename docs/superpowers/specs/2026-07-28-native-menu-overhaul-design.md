# Native macOS Menu Overhaul — Design Spec

**Date:** 2026-07-28
**Status:** v2 — revised after principal-engineer/architect adversarial review. Approved direction (Option A + B); pending implementation plan.
**Owner:** Frédéric Guigand
**Scope:** Fork-only files (`applio_launcher.py`, `macos_wrapper.py`, new `menu_spec.py`
+ `applio_update_check.py` + `tests/test_menu_spec.py`, `Applio.spec`, `requirements_macos.txt`,
`build_macos.py`, docs). No upstream files touched.

**Revision history**
- v1 (2026-07-28): initial design.
- v2 (2026-07-28): incorporated adversarial review (NEEDS MAJOR REVISION). Key changes: (a)
  standalone pywebview renderer is a **documented static subset** — pywebview menus cannot be
  mutated or bind shortcuts (verified `webview/menu.py`, `webview/platforms/cocoa.py`); (b)
  `process.status` drops epoch/ETA (no reliable source); (c) version comparison rewritten with
  `packaging.version` (the inherited logic is a buggy string compare); (d) update-check network
  calls moved off the main thread; (e) first-run DATA_PATH race defined; (f) automatable
  `test_menu_spec.py` added as a gate; (g) "Voice Models" reveal dropped (redundant), `⌘?` dropped.

---

## 1. Problem (from the audit)

The app ships **two divergent native menus**, and which one a user sees depends on how the app is
launched:

| | **Menu A — launcher** (`applio_launcher.py`, PyObjC `NSMenu`) | **Menu B — wrapper** (`macos_wrapper.py`, pywebview `Menu`) |
|---|---|---|
| Shown when | Packaged app (wrapper forced to *Accessory*, owns no menu bar) | Standalone `python macos_wrapper.py` (wrapper is *Regular*) |
| Order | Applio ▸ File ▸ Window (correct) | File ▸ Applio ▸ Edit ▸ Window (**app menu not first — HIG violation**) |
| Shortcuts | ⌘Q, ⌘⇧P, ⌘⇧W (real selectors, live state) | almost all `lambda: None` (entire Edit menu dead) |
| State | 2 s `NSTimer` updates the Progress Monitor item | none |

In the **packaged app the user sees Menu A**, and Menu B is ~50 lines of dead, divergent code
handed to `webview.start(menu=…)`. In **standalone/dev runs Menu B is shown** and Menu A does not
exist. Two sources of truth that disagree on order, contents, and behavior.

The visible Menu A also fails **system congruity** (missing reflexive Mac anchors) and **domain
mental-model fit** (nothing reflects Applio's job: produce audio/models, run long training jobs).
Specifically missing: Hide (⌘H/⌥⌘H), a Process menu, a Help menu, and the "Reveal in Finder"
submenu trapped inside the dead Menu B.

---

## 2. Goals

1. **One canonical menu *structure***, rendered by both processes — structural divergence
   eliminated. The unavoidable launcher/standalone *capability* difference (standalone is static)
   is **documented, not silent**.
2. **HIG-congruent structure** honoring transferred Mac habits (⌘H, ⌘M, ⌘Q) — launcher-side.
3. **Domain fit** — a Process menu and a Help menu reflecting what Applio does.
4. **Rescue orphaned features** — Reveal-in-Finder moves into the live menu.
5. **Real update checking** — manual `Check for Updates…` (tri-state alert) **and** a silent
   launch-time check that alerts only if a newer version exists.
6. **Extend dynamic state** (launcher) — menus that reflect reality (active job, disabled-when-empty).
7. **Delete Menu B** as a competing hand-maintained source of truth.

## 3. Non-goals

- Single-process (Phase 2) — deferred; the menu works within today's two-process model.
- No Edit menu (launcher — enforced; standalone — suppressed, see §8.1).
- No native Settings panel / `⌘,` (Option B). Real settings (theme/precision/language) stay in the
  Gradio Settings tab (`tabs/settings/settings.py`).
- No Tools menu / Open Recent this pass (§11).
- **Dock tile right-click menu** — out of scope.
- Notarization/signing pipeline — unchanged.

---

## 4. Decisions locked

- **Approach A — shared `menu_spec.py`** (platform-neutral data + two thin renderers). Sound **as
  amended** in §5/§8: the pywebview renderer is a static subset, not a feature-equivalent render.
- **Full rebuild** of menu content.
- **Process menu is dashboard-only** — read-only status + "Open Dashboard"; Pause/Resume/Terminate
  stay inside the Progress Monitor window (error-prevention). Status shows job name only (§5.4).
- **No Edit menu.**
- **No native Settings panel / `⌘,`.**
- **Real update checking** (manual tri-state + silent launch-time), with a corrected version
  comparison (§7.1).
- **Help → Studio Production Guide** (bundled, rendered to HTML at build time).
- **Standalone is a documented static subset** — a property of the two frameworks (verified), accepted.

---

## 5. Architecture

### 5.1 `menu_spec.py` (NEW, fork-only) — the single source of truth

A platform-neutral description: a list of `MenuItem` records. Each leaf carries a stable **action
key** (e.g. `"file.reveal_logs"`). Renderers translate keys into PyObjC selectors or pywebview
callbacks; they never hardcode titles/shortcuts.

```python
from dataclasses import dataclass, field

@dataclass
class MenuItem:
    key: str = ""            # action key; "" for separators / status lines
    title: str = ""
    shortcut: str = ""       # key equivalent, e.g. "q", "p"  (PyObjC renderer ONLY)
    mods: tuple = ()         # (CMD,) / (CMD, SHIFT)          (PyObjC renderer ONLY)
    dynamic: str = ""        # launcher-only hint, see §5.4;   "" = static
    submenu: list = field(default_factory=list)
    separator: bool = False

MENU = [
    MenuItem(submenu=[  # FIRST submenu = app menu
        MenuItem(key="app.about", title="About Applio"),
        MenuItem(separator=True),
        MenuItem(key="app.check_updates", title="Check for Updates…"),
        MenuItem(separator=True),
        MenuItem(key="app.hide", title="Hide Applio", shortcut="h", mods=(CMD,)),
        MenuItem(key="app.hide_others", title="Hide Others", shortcut="h", mods=(CMD, OPTION)),
        MenuItem(separator=True),
        MenuItem(key="app.quit", title="Quit Applio", shortcut="q", mods=(CMD,)),
    ]),
    # File, Process, Window, Help — see §6
]
```

**App-menu title convention differs by renderer** (verified `cocoa.py:1033`):
- **PyObjC renderer (launcher):** the first top-level submenu with no title becomes the bold
  app-name menu ("Applio").
- **pywebview renderer (standalone):** the first submenu MUST use the literal title `'__app__'`.
  pywebview's unconditional `_add_app_menu` (`cocoa.py:1048`) already injects the standard
  app-menu items (About, Services, Hide ⌘H, Hide Others ⌥⌘H, Show All, Quit ⌘Q); our `__app__`
  payload is inserted between "About" and "Services". **Titling it `"Applio"` would create a
  duplicate app menu in the wrong position** — the exact HIG violation §1 condemns.

### 5.2 Action-key taxonomy

| Prefix | Keys |
|---|---|
| `app.` | `about`, `check_updates`, `hide`, `hide_others`, `quit` |
| `file.` | `set_data_location`, `reveal_logs`, `reveal_datasets`, `reveal_pretraineds`, `reveal_inference`, `reveal_root` |
| `process.` | `open_dashboard`, `open_logs` |
| `window.` | `minimize`, `zoom`, `show_main`, `bring_all_to_front` |
| `help.` | `guide`, `docs`, `report_issue`, `discord` |

Reveal targets (data-location-relative, same as the dead Menu B): logs → `logs/`, datasets →
`assets/datasets`, pretraineds → `rvc/models/pretraineds`, inference → `assets/audios`, root → `""`.
("Voice Models" is dropped — it opened the same `logs/` folder as "Training Models" and was never in
Menu B.)

### 5.3 Two renderers + per-process dispatch

- **`render_pyobjc(MENU, dispatch) -> NSMenu`** (launcher). Builds `NSMenuItem`s; wires targets to
  the existing `MenuActionHandler` proxy; honors `shortcut`/`mods`; supports dynamic items (§5.4).
  Replaces the hand-built `setup_menu` body.
- **`render_pywebview(MENU, dispatch) -> list`** (standalone wrapper). Builds the pywebview tree.
  Static only — **ignores `shortcut`/`mods`** (pywebview `MenuAction` has no shortcut field,
  `menu.py:22`) and **cannot honor `dynamic`** (verified). Replaces `get_native_menu()`. Before
  `webview.start`, sets `webview_settings['SHOW_DEFAULT_MENUS'] = False` to suppress pywebview's
  auto View/Edit menus (`cocoa.py:1050-1052`).

**Dispatch (`key -> handler`) differs by process:**

| Action key | Launcher (packaged) | Wrapper (standalone) |
|---|---|---|
| `app.about` | launcher `showAbout_` (full version fallback chain, `applio_launcher.py:3691-3710`) | wrapper `show_about_dialog` (confirm version-source parity, §11) |
| `app.check_updates` | shared `check_for_updates_interactive()` — network on a **background thread**, alert on main (§7.1) | same |
| `app.hide` / `hide_others` | `NSApp.hide:` / `hideOtherApplications:` | **omitted** — pywebview injects these |
| `app.quit` | delegate quit cascade (training confirmation) | if `APPLIO_LAUNCHED_BY_LAUNCHER`: `_request_launcher_quit()` (`macos_wrapper.py:262`); else `NSApp.terminate_(None)` |
| `file.set_data_location` | existing `setDataLocation_` (`applio_launcher.py:3743-3786`, writes NSUserDefaults key `"dataPath"`). **Do NOT import the wrapper-only `PreferencesManager`** (`macos_wrapper.py:606`, key `"userDataPath"`) — that is a pre-existing key split; keep each process on its own key. | wrapper `change_data_location` (PreferencesManager) |
| `file.reveal_*` | `FinderHelper.open_path(DATA_PATH/sub)`, where DATA_PATH is **resolved fresh on each click** via the precedence chain (`applio_launcher.py:338-359`: env `APPLIO_DATA_PATH` → `runtime_paths.json` `data_path` → `~/Applio`) — NOT the captured startup env var (stale until restart). Disabled until first-run complete (§8.8). | same, wrapper-local |
| `process.open_dashboard` | launcher `showProgressMonitor_` (rich window) | wrapper `_show_progress_monitor_info` (graceful fallback) |
| `process.open_logs` | open `~/Library/Logs/Applio/` | same |
| `window.*` | `performMiniaturize:`, `performZoom:`, `showMainWindow:`, `arrangeInFront:` | no-op equivalents (pywebview) |
| `help.guide` | open bundled `STUDIO_PRODUCTION_GUIDE.html` (§7.3) | same |
| `help.docs/report/discord` | `webbrowser.open(url)` | same |

**Standalone `__app__` payload** contains only `app.check_updates` (the four keys
`about`/`hide`/`hide_others`/`quit` are omitted — pywebview's `_add_app_menu` injects them).

### 5.4 Dynamic items — **launcher-only**

`MenuItem.dynamic` hints; honored **only by `render_pyobjc`**:

- `"status"` → the `process.status` item title becomes **`● Training: <name>`** (or
  `No active processes`). Source: `~/.applio/active_processes.json` (schema at
  `applio_launcher.py:393-559`: has `model_name`, `status`, `total_epoch` — **no `current_epoch`,
  no ETA**). **Epoch/ETA are deliberately omitted from the menu** — they require fragile log-tail
  parsing (`ProgressWindowController` does this at `:828-843`) that belongs in the dashboard, not
  the menu. If a future richer status is wanted, specify the log-tail contract explicitly first.
- `"exists:<subpath>"` → `file.reveal_*` items: `setEnabled_(os.path.exists(DATA_PATH/subpath))`
  (e.g. "Inference Outputs" disabled until `assets/audios/` exists).

The renderer keeps dynamic `NSMenuItem`s in a dict keyed by action key; the existing 2 s
`NSTimer` (`applio_launcher.py:3541`) mutates them in place (generalize the current
`self.progress_menu_item` pattern). `setTitle_`/`setEnabled_` on existing items from the main
run-loop timer is AppKit-safe even while a menu is open. **Standalone has no dynamic items and no
status line** (pywebview rebuilds menus only on `windowDidBecomeKey_`, `cocoa.py:80-86`, never on a
timer).

---

## 6. The menu (final)

```
Applio
   About Applio
   ─────────────
   Check for Updates…                          [real GitHub check, §7.1; also auto-runs at launch, §7.2]
   ─────────────
   Hide Applio                       ⌘H        [new]
   Hide Others                       ⌥⌘H       [new]
   ─────────────
   Quit Applio                       ⌘Q        (keeps training-active confirmation)

File
   Set Data Location…                         [the one app-level data pref; stays here]
   ─────────────
   Reveal in Finder  ▸                         [rescued from dead Menu B]
      Training Models (logs/)
      Datasets
      Pretrained Models
      Inference Outputs                      (disabled until folder exists)
      ─────────────
      Root Data Folder

Process                                       [new domain menu]
   ● Training: <name>                         [dynamic, launcher-only; or "No active processes"]
   ─────────────
   Open Progress Dashboard          ⌘⇧P      (controls stay inside the dashboard)
   Open Training Logs…

Window
   Minimize                          ⌘M        [finally bound; was unbound]
   Zoom                                        [new]
   ─────────────
   Show Main Window                            (no shortcut — drops the ⌘⇧W hazard)
   Bring All to Front                          [new]

Help                                           [new]
   Studio Production Guide                     [opens bundled guide, §7.3]
   Applio Help                                (docs/wiki in browser; no shortcut — ⌘? dropped, §8.6)
   Report an Issue                             (GitHub issues)
   ─────────────
   Applio Discord
```

Menu-bar order: **Applio · File · Process · Window · Help**.

**Launcher vs standalone:** the tree above is the launcher render. Standalone is a static subset:
no dynamic status line, no `⌘M`/`⌘⇧P` (pywebview can't bind them — it does provide `⌘H`/`⌥⌘H`/`⌘Q`
via the auto app menu), and the app-menu About/Hide/HideOthers/Quit come from pywebview automatically.

---

## 7. New/changed logic

### 7.1 Check for Updates — `app.check_updates` — port + **fix the comparison**

Reuse `macos_wrapper.py:check_for_updates()` (L729) — but **fix its version comparison**. The
current logic (`macos_wrapper.py:806`, `latest_version != VERSION`) is a **string `!=`**, which is
buggy: a *downgrade* reads as "update available"; `3.6.10` vs `3.6.9` mishandles; non-numeric tags
raise. `packaging.version` is **already a PyInstaller hiddenimport** (`Applio.spec:6`).

Port `check_for_updates()` + constants (`VERSION`, `GITHUB_REPO`, `RELEASES_URL`, `API_URL`,
`_get_version_info` — `macos_wrapper.py:226-229`) into shared **`applio_update_check.py`**, split into:

- `fetch_latest_release() -> dict | None` — API GET + existing error handling.
- `is_update_available(current) -> (bool, latest_version, release_url)` —
  `packaging.version.parse(latest) > packaging.version.parse(current)`, wrapped in `try/except`
  that treats unparseable tags as **no update** (fail-safe silent, matching §7.2).
- `check_for_updates_interactive()` — the tri-state `NSAlert` for the manual menu item.

**Threading (applies to both manual and launch-time):** the network call runs on a **background
thread**; only the `NSAlert` hops to the main thread. The manual check must not block the launcher
event loop (a modal alert + a 10 s network timeout would freeze the 2 s menu timer and
`_check_wrapper_died`, visibly stalling the menu — especially during training).

Replace the launcher's current passive path: the accessibility text to update is on the menu item
at `applio_launcher.py:3455` (not in `checkUpdates_`); `checkUpdates_` (~L3726) is rewired to call
`check_for_updates_interactive()`.

### 7.2 Launch-time update check (new)

On launcher startup, a **daemon thread** calls `is_update_available(VERSION)`; on `True` it hops to
the main thread (`performSelectorOnMainThread:` / `AppHelper.callAfter`) to show "Update available —
vX.Y.Z" with **[Open GitHub Releases]** / **[Later]**. **Silent unless a newer version exists** — no
nag, no error dialog at startup. No throttle this pass (alerts each launch while pending; also
mitigates GitHub's 60/hr unauthenticated rate limit by not retrying — see §11 for a daily throttle).

**PyObjC pool:** wrap the network body (`urllib`→`json`, which bridges to autoreleased Foundation
objects) in an `NSAutoreleasePool` on the worker thread (no pool → logged leak). Quit-during-check
is safe (daemon thread dies on exit; `performSelectorOnMainThread:` during `runEventLoop` is
reentrant-safe). Standalone wrapper mode does not auto-check (dev path); its manual menu item works.

### 7.3 Help → Studio Production Guide — `help.guide`

`STUDIO_PRODUCTION_GUIDE.md` (repo root, 279 lines) is **not bundled today** (`Applio.spec:4`).

- **Build time** (`build_macos.py`): render `.md` → `STUDIO_PRODUCTION_GUIDE.html` with
  [python-markdown](https://python-markdown.github.io/) (PyPI `Markdown`), in a minimal readable
  HTML template. **The step is idempotent** — skip if the `.html` is newer than the `.md`, and it
  must not touch tracked source (same rule as the `patches/` idempotency in CLAUDE.md). **Fallback:**
  if the import/convert fails, bundle the `.md` as-is (feature never breaks a build). (`markdown` is
  likely already present transitively via `tensorboard` — verify; the `requirements_macos.txt` pin
  is hygiene, ~zero build-size cost.)
- **`Applio.spec`:** add `('STUDIO_PRODUCTION_GUIDE.html', '.')` (+ `.md` fallback) to `datas`.
- **Runtime (`help.guide`):** resolve `os.path.join(BASE_PATH, "STUDIO_PRODUCTION_GUIDE.html")`
  (frozen-CWD-safe; `sys._MEIPASS` when frozen — lands under `Contents/Resources/`), then
  `webbrowser.open("file://" + path)`.

---

## 8. Constraints & caveats

### 8.1 No Edit menu
Launcher: we simply don't build one. **Standalone: pywebview auto-injects View + Edit menus
(`cocoa.py:1050-1052`) unless suppressed** — `render_pywebview` MUST set
`webview_settings['SHOW_DEFAULT_MENUS'] = False` before `webview.start`, or standalone gets an Edit
menu contrary to this decision. (Keyboard ⌘C/⌘V/⌘A still work in the WKWebView regardless.)

### 8.2 Menu B removal + standalone static subset
Menu B's hand-maintained `get_native_menu()` body is deleted; standalone keeps a menu via
`render_pywebview(MENU, dispatch)` (static subset, `__app__` payload). pywebview's unconditional
`_add_app_menu` still provides About/Services/Hide/HideOthers/Quit. Verify `_add_app_menu` gating
(`cocoa.py:1048` vs 1050) at implementation.

### 8.3 Process menu richness is launcher-side
The rich dashboard is a launcher feature; standalone `process.open_dashboard` falls back to
`_show_progress_monitor_info`. Standalone Process menu is degraded (acceptable; dev path).

### 8.4 Frozen-CWD path resolution
All paths resolved absolutely: data → `APPLIO_DATA_PATH` → `runtime_paths.json` `data_path` →
`~/Applio`; bundled files → `BASE_PATH`/`sys._MEIPASS` (existing invariant; don't regress).

### 8.5 pywebview `menu=` quirks
Keep the lambda-wrapper rule (`MenuAction("X", lambda: fn())`). pywebview ignores `shortcut`/`mods`
and cannot mutate items post-start.

### 8.6 Shortcut collisions
`⌘⇧W` (was "Show Main Window") dropped (collided with "Close All Windows"). `⌘M` = Minimize.
`⌘H`/`⌥⌘H` added. **`⌘?` is dropped from "Applio Help"** — wiring it from a custom `NSMenuItem` is
fiddly (`keyEquivalent='/'` + `Shift|Cmd`, and it conflicts with the Help-book shortcut); not worth
the bug surface. `⌘,` intentionally not added (§3).

### 8.7 Update-check threading & pools
Both manual and launch-time checks run network on a background thread wrapped in an `NSAutoreleasePool`;
UI hops to main. Never block the launcher event loop with a synchronous network call.

### 8.8 First-run DATA_PATH race
On first run the launcher menu appears (DATA_PATH=`~/Applio` default) before the wrapper shows its
native folder dialog (`macos_wrapper.py:1186-1208`). Until `runtime_paths.json` exists (first-run
complete), the launcher **disables `file.set_data_location` and `file.reveal_*`** — otherwise a user
clicking them races the wrapper's `NSOpenPanel` and two dialogs write different keys
(`"dataPath"` vs `"userDataPath"`).

### 8.9 Stale-process display
`process.status` may show a just-finished job for up to ~2 s until `validate_process_state`
(`applio_launcher.py:531-547`) reaps it. Acceptable; document.

---

## 9. File-by-file changes

| File | Change |
|---|---|
| `menu_spec.py` (NEW) | `MenuItem` dataclass, `MENU` constant, action-key constants, `APP_NAME`. |
| `applio_update_check.py` (NEW) | Port of `check_for_updates()` + constants, split into `fetch_latest_release()` + `is_update_available()` (**`packaging.version` compare, fail-safe**) + `check_for_updates_interactive()` (background-thread network + main-thread alert). |
| `applio_launcher.py` | `render_pyobjc(MENU, dispatch)`; replace `setup_menu` body; generalize `_update_menu_state` to a dict of dynamic items (launcher-only); `checkUpdates_` → shared interactive (bg-thread network); add **launch-time update check** (daemon thread + `NSAutoreleasePool` + main-thread alert); `help.guide` opens bundled HTML at `os.path.join(BASE_PATH, …)`; `file.reveal_*`/`set_data_location` resolve DATA_PATH fresh per click and **disable until first-run complete** (§8.8); route `set_data_location` through existing `setDataLocation_` (no wrapper-class import). |
| `macos_wrapper.py` | `render_pywebview(MENU, dispatch)` replaces `get_native_menu()` (static subset; `__app__` payload = only `check_updates`; omit about/hide/hide_others/quit); set `webview_settings['SHOW_DEFAULT_MENUS']=False` before `webview.start`; delete dead Edit/no-op items; `check_for_updates` imported from shared module; keep `webview.start(menu=…)`. |
| `tests/test_menu_spec.py` (NEW) | Pure-Python, GUI-free gate (§10.1). |
| `Applio.spec` | Add `STUDIO_PRODUCTION_GUIDE.html` (+ `.md` fallback) to `datas`. |
| `build_macos.py` | Idempotent `.md → .html` conversion (skip if newer; don't touch tracked source; fallback to `.md`). |
| `requirements_macos.txt` | Add `markdown` (hygiene; verify transitive presence). |
| `README_MACOS.md`, `FORK_DIFFERENCES.md`, `CLAUDE.md`, `CHANGELOG.md` | Document the new menu, the shared-spec architecture + static standalone subset, the guide, the update-check move + version-compare fix. |

---

## 10. Verification

### 10.1 Automated gate (NEW — hard gate, no GUI, no new runner)
`venv_macos/bin/python tests/test_menu_spec.py` (bare asserts; exits non-zero on failure). Asserts:
- `MENU` top-level order == `[Applio, File, Process, Window, Help]`;
- every leaf `MenuItem.key` ∈ the §5.2 taxonomy;
- no key `== "app.settings"` and no top-level title `== "Edit"`;
- for each renderer, `set(MENU leaf keys)` matches the renderer's dispatch-key set exactly (catches
  typos like `reveal_log` vs `reveal_logs`, and dead dispatch entries);
- `is_update_available("3.6.9")`: latest `"3.6.10"` → True; latest `"3.6.9"` → False; latest
  `"3.6.8"` → False; latest `"v3.6.3-rc1"`/`"latest"` → False (fail-safe);
- guide fallback: with a broken `markdown` import, the build step emits the `.md`.

### 10.2 Manual (the repo has no formal test suite)
2. **Launcher render:** run via launcher; full tree, shortcuts (⌘H, ⌘M, ⌘Q) work; `⌘,` does nothing.
3. **Standalone render:** `python macos_wrapper.py` (no launcher env); same tree order, **no
   View/Edit menus**, single bold app menu (no duplicate "Applio"), no no-op items.
4. **Dynamic state:** start training → `process.status` shows `● Training: <name>`; `reveal_inference`
   flips enabled when `assets/audios/` appears.
5. **Manual update check:** offline → error alert; fake-low `VERSION` → "update available" +
   "Open GitHub Releases"; at-current → "up to date"; non-numeric tag → "up to date" (no crash).
6. **Launch-time check:** fake-low `VERSION` + launch → one alert at startup; at-current → silent;
   offline → silent.
7. **First-run:** with no `runtime_paths.json`, launcher `Set Data Location…`/`Reveal ▸` are
   disabled; after the wrapper's first-run dialog completes, they enable.
8. **Guide:** after build, `Contents/Resources/STUDIO_PRODUCTION_GUIDE.html` opens formatted.
9. **No regression:** `git status` clean post-build; dual-dock-icon fix intact; quit cascade +
   training confirmation fire; the 2 s timer does not stall while an update check runs.
10. **Full build:** `venv_macos/bin/python build_macos.py` (cert-free) then `--sign --notarize --dmg`.

---

## 11. Out of scope / future

- **Phase 2 single-process** — enables an Edit menu that drives the webview and launcher-owned main window.
- **Native Settings panel / `⌘,`** mirroring theme/language/precision.
- **Tools menu** — Model Merger (`merge_rvc.py`), Download Pretrained, Open TensorBoard.
- **Open Recent** — last inference outputs / trained models.
- **Daily throttle** for the launch-time check (also mitigates GitHub's 60/hr unauthenticated limit).
- **Richer `process.status`** (epoch/ETA) — requires a defined log-tail contract.
- **About-dialog version-source parity** between standalone and launcher.
- **Dock tile right-click menu.**
- **"Update available" badge** in the app menu / dock tile.
