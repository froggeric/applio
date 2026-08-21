"""One-call Browse buttons for Applio's path fields (a11y Phase 2).

Injected into upstream tab files at build time by patches/patch_browse_buttons.py:
    _applio_browse_output_path = applio_browse_ui.browse_button(
        "file", output_path, elem_id="browse-output_path")
The click handler runs the native NSOpenPanel (applio_native_picker) and
writes the chosen path into the target component. Cancel keeps the current
value; picker-unavailable (plain browser mode) explains itself via gr.Info,
which is the announced toast channel.
"""

import logging


def _default_picker(mode, prompt=None):
    from applio_native_picker import native_browse

    return native_browse(mode, prompt=prompt)


# Indirection seam for tests (gradio has no AppKit loop under pytest-style runs).
_picker = _default_picker


def _make_handler(mode):
    def _browse(current_value):
        import os

        try:
            status, path = _picker(mode)
        except Exception:
            logging.exception("[Browse] picker failed")
            status, path = "cancel", None
        if status == "ok":
            return os.path.expanduser(path)
        import gradio as gr

        if status == "unavailable":
            gr.Info("The native file picker is available only in the Applio app.")
        else:
            gr.Info("No path selected.")
        # Normalize a typed value that passes through this handler, so
        # "~/audio" typed next to a Browse button becomes usable too.
        return os.path.expanduser(current_value) if current_value else current_value

    return _browse


def browse_button(mode, target, elem_id=None):
    import gradio as gr

    try:
        from assets.i18n.i18n import I18nAuto

        label = I18nAuto()("Browse…")
    except Exception:
        # I18nAuto opens assets/config.json unconditionally; on a fresh
        # checkout that file is gitignored-and-absent -> fall back to English.
        label = "Browse…"
    button = gr.Button(
        label,
        variant="secondary",
        size="sm",
        elem_id=elem_id or f"browse-{mode}",
    )
    button.click(fn=_make_handler(mode), inputs=[target], outputs=[target])
    return button
