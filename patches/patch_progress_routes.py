"""Build-time patcher: expose /applio-a11y/progress on the Gradio app.

Upstream app.py passes prevent_thread_lock=client_mode (False in the app), so
launch() blocks and never returns — everything after the launch call is dead
code in the normal path. We flip the kwarg, register our routes on the
returned FastAPI app, and keep the calling thread alive so launch_gradio()
STILL never returns (the wrapper's supervisor contract). The TensorBoard
proxy below the insertion point stays dead in normal mode — status quo.
Run standalone: venv_macos/bin/python patches/patch_progress_routes.py app.py
"""

import re
import sys

MARKER = "_APPLIO_A11Y_ROUTES_"

KWARG_ANCHOR = re.compile(r"prevent_thread_lock=client_mode,(?P<nl>\s*\n)")
TB_ANCHOR = "    from rvc.lib.tools.launch_tensorboard import get_tb_url"

INJECTED = '''    # {marker}
    try:
        import applio_progress_api

        applio_progress_api.register_routes(app)
    except Exception:
        pass
    if not client_mode:
        import time as _applio_time

        while True:  # keep this backend thread alive; launch() no longer blocks
            _applio_time.sleep(5)
'''


def patch_app(content):
    if MARKER in content:
        return content, "already"
    if not KWARG_ANCHOR.search(content):
        print("Pattern not found: prevent_thread_lock=client_mode")
        return content, "miss"
    content = KWARG_ANCHOR.sub(
        "prevent_thread_lock=True,  # " + MARKER + "\\g<nl>", content, count=1
    )
    idx = content.find(TB_ANCHOR)
    if idx == -1:
        print("Pattern not found: tensorboard import anchor")
        return content, "miss"
    block = INJECTED.format(marker=MARKER)
    content = content[:idx] + block + content[idx:]
    return content, "patched"


if __name__ == "__main__":
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    out, status = patch_app(src)
    if status in ("patched", "already"):
        with open(path, "w", encoding="utf8") as fh:
            fh.write(out)
        print(f"patch_app: {status}")
        sys.exit(0)
    print(f"patch_app: {status}")
    sys.exit(1)
