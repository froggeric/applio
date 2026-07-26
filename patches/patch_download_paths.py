#!/usr/bin/env python3
"""
Patcher to fix custom-pretrained download paths for the frozen macOS app.

Bug: tabs/download/download.py builds the custom-pretrained dir as a CWD-relative
path in both fetch_pretrained_data() and download_pretrained_model():
    os.path.join("rvc", "models", "pretraineds", "custom")
In the frozen app the subprocess CWD is the bundle (sys._MEIPASS / Contents/Resources),
so downloads wrote into the (read-only) bundle instead of the user's data dir, and the
custom-pretrained dropdown (which scans the data dir) never saw them -> "download didn't
work". This is the same frozen-CWD root cause as the preprocess / custom-pretrained-scan
bugs.

Fix: route both paths through _applio_custom_pretrained_dir(), which resolves the custom
dir ABSOLUTELY against the data path when frozen (APPLIO_DATA_PATH env ->
runtime_paths.json data_path -> ~/Applio) and keeps the upstream CWD-relative behavior in
source/dev runs.

Applied at build time by build_macos.py (registered as a "dir" patcher; base_path is the
"tabs/download" directory, so we join "download.py").
"""

import os
import sys


HELPER_CODE = '''


def _applio_custom_pretrained_dir():
    """Custom-pretrained dir: CWD-relative in dev, data-path-absolute when frozen."""
    if not getattr(sys, "frozen", False):
        return os.path.join("rvc", "models", "pretraineds", "custom")
    _applio_dp = os.environ.get("APPLIO_DATA_PATH")
    if not _applio_dp:
        for _applio_p in (
            os.path.expanduser("~/Library/Application Support/Applio/runtime_paths.json"),
            os.path.expanduser("~/.applio/runtime_paths.json"),
        ):
            if os.path.exists(_applio_p):
                try:
                    import json as _applio_json
                    with open(_applio_p) as _applio_f:
                        _applio_dp = _applio_json.load(_applio_f).get("data_path")
                except Exception:
                    pass
                if _applio_dp:
                    break
    if not _applio_dp:
        _applio_dp = os.path.expanduser("~/Applio")
    return os.path.join(_applio_dp, "rvc", "models", "pretraineds", "custom")
'''


def patch_download_py(base_path: str) -> bool:
    """Patch tabs/download/download.py to resolve the custom-pretrained dir absolutely."""
    download_py_path = os.path.join(base_path, "download.py")

    if not os.path.exists(download_py_path):
        print(f"[patch_download_paths] download.py not found at {download_py_path}")
        return False

    with open(download_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency: the injected helper is the marker.
    if "_applio_custom_pretrained_dir" in content:
        print("[patch_download_paths] download.py already patched")
        return True

    patched = False

    # Inject the helper right after the now_dir / sys.path setup near the top.
    inject_anchor = "now_dir = os.getcwd()\nsys.path.append(now_dir)\n"
    if inject_anchor in content:
        content = content.replace(inject_anchor, inject_anchor + HELPER_CODE, 1)
        print("[patch_download_paths] Injected _applio_custom_pretrained_dir() helper")
        patched = True
    else:
        print("[patch_download_paths] WARNING: injection anchor not found")

    # Route the two CWD-relative custom-dir assignments through the helper.
    assignments = [
        (
            '    pretraineds_custom_path = os.path.join("rvc", "models", "pretraineds", "custom")',
            "    pretraineds_custom_path = _applio_custom_pretrained_dir()",
        ),
        (
            '    save_path = os.path.join("rvc", "models", "pretraineds", "custom")',
            "    save_path = _applio_custom_pretrained_dir()",
        ),
    ]
    for old, new in assignments:
        if old in content:
            content = content.replace(old, new, 1)
            print(
                f"[patch_download_paths] Routed "
                f"{old.strip().split(' = ')[0]} through helper"
            )
            patched = True
        else:
            print(f"[patch_download_paths] WARNING: assignment not found: {old.strip()}")

    if patched:
        with open(download_py_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    print("[patch_download_paths] No changes applied")
    return False


if __name__ == "__main__":
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    sys.exit(0 if patch_download_py(base_path) else 1)
