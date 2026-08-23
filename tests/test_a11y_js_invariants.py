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


def test_job_label_scope_aware():
    # Auto-a11y mislabel fix (2026-08-23): a tracked single conversion
    # (scope "single" in the payload job) must announce as "conversion", not
    # "batch inference" — mirroring applio_launcher.inference_job_type. The
    # mapping must key on type "inference" (unchanged; enrich_jobs keys on it)
    # and fall through to "batch inference" when scope is absent (a batch).
    body = _function_body("jobLabel")
    assert 'job.scope === "single"' in body, (
        "jobLabel must map payload scope single -> conversion"
    )
    assert '"conversion"' in body and '"batch inference"' in body, (
        "jobLabel must render conversion vs batch inference"
    )
    assert 't = job.type || "process"' in body, "non-inference types pass through"


def run_all():
    test_heal_record_toggles_scoped_to_browse_anchor()
    test_failed_tail_wiring_present()
    test_job_label_scope_aware()
    print("All a11y JS invariant tests passed (3).")


if __name__ == "__main__":
    run_all()
