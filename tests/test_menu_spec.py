# tests/test_menu_spec.py
"""Pure-Python gate for menu_spec (no GUI, no AppKit). Run: python tests/test_menu_spec.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from menu_spec import (
    MENU, APP_NAME, APP_MENU_TITLE, PYWEBVIEW_APP_KEY,
    LAUNCHER_ACTION_KEYS, WRAPPER_ACTION_KEYS, DISPLAY_KEYS, TAXONOMY,
    iter_leaves,
)

EXPECTED_TOP_LEVEL = ["Applio", "File", "Process", "Window", "Help"]

def _titles_top_level():
    out = []
    for top in MENU:
        title = top.title or (APP_MENU_TITLE if _is_app_menu(top) else "")
        out.append(title)
    return out

def _is_app_menu(top):
    return top is MENU[0]

def test_top_level_order():
    titles = _titles_top_level()
    assert titles == EXPECTED_TOP_LEVEL, f"top-level order wrong: {titles}"

def test_no_settings_no_edit():
    for leaf in iter_leaves(MENU):
        assert leaf.key != "app.settings", "app.settings must not exist"
    titles = [t.title for t in MENU]
    assert "Edit" not in titles, "no Edit menu"

def test_keys_are_known():
    # Action keys live in TAXONOMY; display-only items (e.g. process.status)
    # live in DISPLAY_KEYS. A leaf may belong to either.
    for leaf in iter_leaves(MENU):
        if not leaf.key:
            continue
        assert leaf.key in TAXONOMY or leaf.key in DISPLAY_KEYS, f"unknown key {leaf.key!r}"

def test_action_key_contracts():
    leaves = {leaf.key for leaf in iter_leaves(MENU) if leaf.key}
    for k in leaves:
        assert k in LAUNCHER_ACTION_KEYS or k in DISPLAY_KEYS, f"orphan key {k!r}"
    assert LAUNCHER_ACTION_KEYS <= leaves, f"launcher keys missing from MENU: {LAUNCHER_ACTION_KEYS - leaves}"
    injected = {"app.about", "app.hide", "app.hide_others", "app.quit"}
    assert WRAPPER_ACTION_KEYS == LAUNCHER_ACTION_KEYS - injected, "wrapper contract mismatch"
    assert injected <= LAUNCHER_ACTION_KEYS, "injected keys must be in launcher set"

def test_display_keys_are_dynamic():
    for leaf in iter_leaves(MENU):
        if leaf.key in DISPLAY_KEYS:
            assert leaf.dynamic, f"display key {leaf.key!r} must be dynamic"

def test_app_menu_const():
    assert PYWEBVIEW_APP_KEY == "__app__"
    assert APP_NAME == "Applio"

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll menu_spec tests passed ({len(fns)}).")
