"""Factory + handler behavior for applio_browse_ui (no AppKit; gradio only).
Run: venv_macos/bin/python tests/test_browse_ui.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr

import applio_browse_ui


def test_handler_ok_returns_path():
    h = applio_browse_ui._make_handler("file")
    # Monkeypatch the picker to a canned result.
    applio_browse_ui._picker = lambda mode, prompt=None: ("ok", "/tmp/x.wav")
    assert h("/old") == "/tmp/x.wav"


def test_handler_expands_tilde():
    applio_browse_ui._picker = lambda mode, prompt=None: ("ok", "~/audios/out.wav")
    h = applio_browse_ui._make_handler("file")
    assert h("/old").startswith("/") and "~" not in h("/old")


def test_handler_cancel_keeps_current():
    applio_browse_ui._picker = lambda mode, prompt=None: ("cancel", None)
    h = applio_browse_ui._make_handler("folder")
    assert h("/keep/me") == "/keep/me"  # gr.Info fired as a side effect; value kept


def test_handler_unavailable_keeps_current():
    applio_browse_ui._picker = lambda mode, prompt=None: ("unavailable", None)
    h = applio_browse_ui._make_handler("pth")
    assert h("/keep") == "/keep"


def test_browse_button_creates_and_wires():
    applio_browse_ui._picker = lambda mode, prompt=None: ("cancel", None)
    with gr.Blocks():
        box = gr.Textbox(label="x")
        btn = applio_browse_ui.browse_button("file", box, elem_id="browse-test")
        assert isinstance(btn, gr.Button)
        assert btn.elem_id == "browse-test"  # falsible: the factory must pass it through


def run_all():
    test_handler_ok_returns_path()
    test_handler_expands_tilde()
    test_handler_cancel_keeps_current()
    test_handler_unavailable_keeps_current()
    test_browse_button_creates_and_wires()
    print("All browse UI tests passed (5).")


if __name__ == "__main__":
    run_all()
