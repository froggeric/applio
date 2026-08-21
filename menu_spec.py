# menu_spec.py
"""The single source of truth for Applio's native macOS menu.

Platform-neutral: NO AppKit/pywebview imports, so it is unit-testable under any
Python 3.10. Two thin renderers consume MENU:
  - render_pyobjc  (launcher): full menu, shortcuts, dynamic items (NSTimer-driven)
  - render_pywebview (standalone wrapper): static subset (pywebview Menu is immutable
    and cannot bind shortcuts; pywebview auto-injects the standard app-menu items).

See docs/superpowers/specs/2026-07-28-native-menu-overhaul-design.md.
"""

from dataclasses import dataclass, field

APP_NAME = "Applio"
APP_MENU_TITLE = "Applio"  # PyObjC renderer: bold app-name menu
PYWEBVIEW_APP_KEY = "__app__"  # pywebview renderer: literal title for the app menu


# Modifier tokens (renderer translates to platform masks). Keeps this module AppKit-free.
def CMD():
    return ("cmd",)


def SHIFT():
    return ("shift",)


def OPTION():
    return ("option",)


@dataclass
class MenuItem:
    key: str = ""  # action key; "" for pure separators
    title: str = ""
    shortcut: str = ""  # key equivalents e.g. "q", "p" (PyObjC only)
    mods: tuple = ()  # ("cmd",) / ("cmd","shift") / ("cmd","option") (PyObjC only)
    dynamic: str = ""  # launcher-only hint: "status" | "exists:<subpath>" | ""
    submenu: list = field(default_factory=list)
    separator: bool = False


# ---- Action-key taxonomy ---------------------------------------------------
APP_KEYS = {"app.about", "app.check_updates", "app.hide", "app.hide_others", "app.quit"}
FILE_KEYS = {
    "file.set_data_location",
    "file.reveal_logs",
    "file.reveal_datasets",
    "file.reveal_pretraineds",
    "file.reveal_inference",
    "file.reveal_root",
}
PROCESS_KEYS = {"process.open_dashboard", "process.open_logs"}
WINDOW_KEYS = {
    "window.minimize",
    "window.zoom",
    "window.show_main",
    "window.bring_all_to_front",
}
HELP_KEYS = {"help.guide", "help.docs", "help.report_issue", "help.discord"}
# Edit menu: clipboard via the AppKit responder chain (WKContentView implements
# cut:/copy:/paste:/selectAll:). Launcher-only — pywebview's static renderer
# cannot bind selectors, and its stripped WKWebView context menu (cocoa.py
# willOpenMenu_withEvent_ → removeAllItems) leaves no other clipboard path.
EDIT_KEYS = {
    "edit.undo",
    "edit.redo",
    "edit.cut",
    "edit.copy",
    "edit.paste",
    "edit.select_all",
}
TAXONOMY = APP_KEYS | FILE_KEYS | PROCESS_KEYS | WINDOW_KEYS | HELP_KEYS | EDIT_KEYS

# Display-only items (no dispatch; rendered disabled, mutated by the launcher timer).
DISPLAY_KEYS = {"process.status"}

# Keys the launcher renderer must wire dispatch for.
LAUNCHER_ACTION_KEYS = (
    APP_KEYS | FILE_KEYS | PROCESS_KEYS | WINDOW_KEYS | HELP_KEYS | EDIT_KEYS
) - set()
# Standalone wrapper handles everything EXCEPT the four app-menu items pywebview injects
# (About / Hide / Hide Others / Quit). Verified: webview/platforms/cocoa.py _add_app_menu
# runs unconditionally and provides those.
# also omit window.zoom / window.bring_all_to_front — no pywebview Window API for them
WRAPPER_ACTION_KEYS = LAUNCHER_ACTION_KEYS - {
    "app.about",
    "app.hide",
    "app.hide_others",
    "app.quit",
    "window.zoom",
    "window.bring_all_to_front",
    *EDIT_KEYS,  # selector-based: cannot be rendered by the static pywebview menu
}

# Reveal targets (relative to the resolved data dir).
REVEAL_PATHS = {
    "file.reveal_logs": "logs",
    "file.reveal_datasets": "assets/datasets",
    "file.reveal_pretraineds": "rvc/models/pretraineds",
    "file.reveal_inference": "assets/audios",
    "file.reveal_root": "",
}

# Standard AppKit selectors handled by the responder chain / NSApp (no custom target).
# Shared so both renderers agree which keys are "system" actions. Every standard
# selector key MUST appear here, or the renderer renders it disabled with no action.
STANDARD_SELECTOR_KEYS = {
    "app.hide": "hide:",
    "app.hide_others": "hideOtherApplications:",  # ⌥⌘H — NSApp responder chain
    "app.quit": "terminate:",
    "window.minimize": "performMiniaturize:",
    "window.zoom": "performZoom:",
    "window.bring_all_to_front": "arrangeInFront:",
    "edit.undo": "undo:",
    "edit.redo": "redo:",
    "edit.cut": "cut:",
    "edit.copy": "copy:",
    "edit.paste": "paste:",
    "edit.select_all": "selectAll:",
}

# ---- THE menu --------------------------------------------------------------
MENU = [
    # App menu (first). PyObjC: untitled top-level item -> bold app menu.
    #            pywebview: renderer wraps this submenu with title "__app__".
    MenuItem(
        submenu=[
            MenuItem(key="app.about", title="About Applio"),
            MenuItem(separator=True),
            MenuItem(key="app.check_updates", title="Check for Updates…"),
            MenuItem(separator=True),
            MenuItem(key="app.hide", title="Hide Applio", shortcut="h", mods=("cmd",)),
            MenuItem(
                key="app.hide_others",
                title="Hide Others",
                shortcut="h",
                mods=("cmd", "option"),
            ),
            MenuItem(separator=True),
            MenuItem(key="app.quit", title="Quit Applio", shortcut="q", mods=("cmd",)),
        ]
    ),
    MenuItem(
        title="Edit",
        submenu=[
            MenuItem(key="edit.undo", title="Undo", shortcut="z", mods=("cmd",)),
            MenuItem(
                key="edit.redo",
                title="Redo",
                shortcut="z",
                mods=(
                    "cmd",
                    "shift",
                ),
            ),
            MenuItem(separator=True),
            MenuItem(key="edit.cut", title="Cut", shortcut="x", mods=("cmd",)),
            MenuItem(key="edit.copy", title="Copy", shortcut="c", mods=("cmd",)),
            MenuItem(key="edit.paste", title="Paste", shortcut="v", mods=("cmd",)),
            MenuItem(
                key="edit.select_all",
                title="Select All",
                shortcut="a",
                mods=("cmd",),
            ),
        ],
    ),
    MenuItem(
        title="File",
        submenu=[
            MenuItem(key="file.set_data_location", title="Set Data Location…"),
            MenuItem(separator=True),
            MenuItem(
                title="Reveal in Finder",
                submenu=[
                    MenuItem(
                        key="file.reveal_logs",
                        title="Training Models (logs/)",
                        dynamic="exists:logs",
                    ),
                    MenuItem(
                        key="file.reveal_datasets",
                        title="Datasets",
                        dynamic="exists:assets/datasets",
                    ),
                    MenuItem(
                        key="file.reveal_pretraineds",
                        title="Pretrained Models",
                        dynamic="exists:rvc/models/pretraineds",
                    ),
                    MenuItem(
                        key="file.reveal_inference",
                        title="Inference Outputs",
                        dynamic="exists:assets/audios",
                    ),
                    MenuItem(separator=True),
                    MenuItem(key="file.reveal_root", title="Root Data Folder"),
                ],
            ),
        ],
    ),
    MenuItem(
        title="Process",
        submenu=[
            MenuItem(
                key="process.status", title="No active processes", dynamic="status"
            ),
            MenuItem(separator=True),
            MenuItem(
                key="process.open_dashboard",
                title="Open Progress Dashboard",
                shortcut="p",
                mods=("cmd", "shift"),
            ),
            MenuItem(key="process.open_logs", title="Open Debug Logs…"),
        ],
    ),
    MenuItem(
        title="Window",
        submenu=[
            MenuItem(
                key="window.minimize", title="Minimize", shortcut="m", mods=("cmd",)
            ),
            MenuItem(key="window.zoom", title="Zoom"),
            MenuItem(separator=True),
            MenuItem(key="window.show_main", title="Show Main Window"),
            MenuItem(key="window.bring_all_to_front", title="Bring All to Front"),
        ],
    ),
    MenuItem(
        title="Help",
        submenu=[
            MenuItem(key="help.guide", title="Studio Production Guide"),
            MenuItem(key="help.docs", title="Applio Help"),
            MenuItem(key="help.report_issue", title="Report an Issue"),
            MenuItem(separator=True),
            MenuItem(key="help.discord", title="Applio Discord"),
        ],
    ),
]


def iter_leaves(menu):
    """Yield every non-separator MenuItem at any depth."""
    for item in menu:
        if item.separator:
            continue
        if item.submenu:
            yield from iter_leaves(item.submenu)
        else:
            yield item
