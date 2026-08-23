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


def test_jobs_running_gates_output_change_speech():
    # Re-test round 2, fix B: while a job runs, per-textarea output changes
    # must not SPEAK — announce() replaces the shared live region text, so
    # the per-file batch updates drowned the job's own announcements. The
    # visible Last-result record survives (persistResult still runs), and
    # idle behavior is unchanged (still verbosity-gated).
    with open(JS, encoding="utf8") as fh:
        src = fh.read()
    assert "var jobsRunning = false" in src, "module-level jobsRunning flag"
    body = _function_body("announceOutputChanges")
    assert "jobsRunning" in body, (
        "announceOutputChanges must gate its announce() on jobsRunning"
    )
    assert "persistResult(short)" in body, (
        "the visible Last-result record must survive the speech gate"
    )
    assert "jobsRunning = " in _function_body("handlePayload"), (
        "handlePayload must refresh jobsRunning from every poll payload"
    )


def test_one_combined_announce_per_poll():
    # Re-test round 2, fix B (intra-poll stomp): several events arriving in
    # one poll must be spoken as ONE announce() call — announce() replaces
    # textContent, so per-event calls overwrite each other and only the last
    # is heard. The owner/verbosity gate around the spoken path is unchanged.
    body = _function_body("handlePayload")
    assert "forEach(function (a) { announce(a[1]); })" not in body, (
        "per-event announce() calls stomp each other — join into one call"
    )
    assert '.join(" — ")' in body, "events must be combined via join"
    assert len(re.findall(r"\bannounce\(", body)) == 1, (
        "handlePayload must contain exactly one announce() call (combined)"
    )


def run_all():
    test_heal_record_toggles_scoped_to_browse_anchor()
    test_failed_tail_wiring_present()
    test_job_label_scope_aware()
    test_jobs_running_gates_output_change_speech()
    test_one_combined_announce_per_poll()
    print("All a11y JS invariant tests passed (5).")


if __name__ == "__main__":
    run_all()
