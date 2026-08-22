# tests/test_a11y_js_invariants.py
"""Source invariants for assets/applio_a11y.js (no browser harness in-repo).
Run: venv_macos/bin/python tests/test_a11y_js_invariants.py"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(REPO, "assets", "applio_a11y.js")


def _function_body(name):
    with open(JS, encoding="utf8") as fh:
        src = fh.read()
    m = re.search(rf"function {name}\(.*?\) {{(.*?)\n  }}", src, re.DOTALL)
    assert m, f"function {name} not found in applio_a11y.js"
    return m.group(1)


def test_heal_record_toggles_scoped_to_browse_anchor():
    body = _function_body("healRecordToggles")
    assert "#browse-record_audio_path" in body, (
        "healRecordToggles must anchor on the fork-injected Browse button"
    )
    assert 'document.querySelectorAll("button")' not in body, (
        "healRecordToggles must not scan the whole document for Start/Stop"
    )
    assert "closest" in body and "querySelectorAll" in body, (
        "healRecordToggles must scope via closest() then query within"
    )
    assert "ACCORDION_BLOCK" in body, (
        "scope must be the live-verified .gr-accordion container"
    )


def test_failed_tail_wiring_present():
    # Guards the persistResult enrichment contract (Task 4).
    with open(JS, encoding="utf8") as fh:
        src = fh.read()
    assert "failedTail" in src, "failedTail helper must exist (log-tail surfacing)"
    assert 'a[1] + " — " + a[2]' in src, "persist loop must append the tail"


def run_all():
    test_heal_record_toggles_scoped_to_browse_anchor()
    test_failed_tail_wiring_present()
    print("All a11y JS invariant tests passed (2).")


if __name__ == "__main__":
    run_all()
