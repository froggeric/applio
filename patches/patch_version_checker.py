#!/usr/bin/env python3
"""
Patcher to fix the Gradio version checker reading a stale config.json (frozen macOS app).

Bug: assets/version_checker.py reads its "local version" from
    config_file = os.path.join(now_dir, "assets", "config.json")   # now_dir = os.getcwd()
In the frozen app the wrapper os.chdir()s to the user data dir, so this resolves to
<data_dir>/assets/config.json. That file is a leftover from an older app build: the wrapper
seeds <data_dir>/assets/config.json from the bundle's config_template ONLY when it does not
already exist (it never overwrites, to preserve user prefs). So after an upgrade the version
field stays stale (e.g. 3.6.2) and the version checker reports the wrong version forever.

Fix: read the version from the BUNDLE's config_template.json (sys._MEIPASS/assets/...),
which always carries the current version shipped with the app. Keep the upstream
CWD-relative behavior in source/dev runs.

Applied at build time by build_macos.py (registered as a "dir" patcher; base_path is the
"assets" directory, so we join "version_checker.py").
"""

import os
import sys


HELPER_CODE = '''


def _applio_version_config_path():
    """Path to the app config carrying the CURRENT version.

    In the frozen app the CWD is the user data dir, whose assets/config.json may be a
    stale leftover from an older app build (the wrapper seeds it from config_template only
    when absent, to preserve user prefs). The current version always ships in the bundle's
    config_template.json, so prefer that. In source/dev runs, keep the upstream
    CWD/assets/config.json behavior.
    """
    if getattr(sys, "frozen", False):
        _base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        for _rel in ("assets/config_template.json", "assets/config.json"):
            _p = os.path.join(_base, _rel)
            if os.path.exists(_p):
                return _p
        return os.path.join(_base, "assets", "config.json")
    return os.path.join(os.getcwd(), "assets", "config.json")
'''


def patch_version_checker(base_path: str) -> bool:
    version_checker_path = os.path.join(base_path, "version_checker.py")

    if not os.path.exists(version_checker_path):
        print(
            f"[patch_version_checker] version_checker.py not found at {version_checker_path}"
        )
        return False

    with open(version_checker_path, "r", encoding="utf-8") as f:
        content = f.read()

    if "_applio_version_config_path" in content:
        print("[patch_version_checker] already patched")
        return True

    patched = False

    # Inject the helper right after the now_dir / sys.path setup.
    inject_anchor = "now_dir = os.getcwd()\nsys.path.append(now_dir)\n"
    if inject_anchor in content:
        content = content.replace(inject_anchor, inject_anchor + HELPER_CODE, 1)
        print("[patch_version_checker] Injected _applio_version_config_path() helper")
        patched = True
    else:
        print("[patch_version_checker] WARNING: injection anchor not found")

    # Route the config_file assignment through the helper.
    old = 'config_file = os.path.join(now_dir, "assets", "config.json")'
    new = "config_file = _applio_version_config_path()"
    if old in content:
        content = content.replace(old, new, 1)
        print("[patch_version_checker] Routed config_file through helper")
        patched = True
    else:
        print("[patch_version_checker] WARNING: config_file assignment not found")

    if patched:
        with open(version_checker_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    print("[patch_version_checker] No changes applied")
    return False


if __name__ == "__main__":
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    sys.exit(0 if patch_version_checker(base_path) else 1)
