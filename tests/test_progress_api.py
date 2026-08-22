# tests/test_progress_api.py
"""Pure-payload tests for applio_progress_api (no AppKit, no launcher import).
Run: venv_macos/bin/python tests/test_progress_api.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applio_progress_api as api


def _training_job():
    return {
        "key": "training:voice:123",
        "type": "training",
        "name": "voice",
        "status": "running",
        "word_key": "training:voice",
        "log_tail": (
            "Starting Preprocess\n"
            "2026-08-21 15:00:00 | epoch=34 | step=21000 | time=00:12:34 | "
            "training_speed=0:34:56 | lowest_value=0.123 (epoch 30 and step 19000)\n"
            "Epoch: 34/200\n"
        ),
    }


def test_inference_stats_enrichment():
    jobs = [
        {
            "key": "inference:batch:app",
            "type": "inference",
            "name": "batch",
            "status": "running",
            "word_key": "inference:batch",
            "total": 10,
            "processed": 5,
            "converted": 5,
            "started_at": 100.0,
        }
    ]
    enriched = api.enrich_jobs(jobs, now=200.0)
    j = enriched[0]
    assert j["pct"] == 50.0
    assert j["detail"] == "5 of 10"
    assert "eta" in j and j["eta"] >= 0


def test_training_metrics_enrichment():
    enriched = api.enrich_jobs([_training_job()], now=1.0)
    j = enriched[0]
    assert j["epoch"] == [34, 200]
    assert j["best_loss"] == 0.123
    assert j["phase"] == "Preprocessing"  # detect_phase_name over the tail


def test_payload_shape_and_settings_echo():
    payload = api.build_progress_payload(
        jobs=[_training_job()], settings={"verbosity": "verbose", "sound": True},
        announce_owner="native", now=123.5, words={"training:voice": "failed"},
    )
    assert payload["now"] == 123.5
    assert payload["announce"] == {"owner": "native"}
    assert payload["settings"] == {"verbosity": "verbose", "sound": True}
    assert payload["words"] == {"training:voice": "failed"}
    assert payload["jobs"][0]["key"] == "training:voice:123"
    assert "log_tail" not in payload["jobs"][0]  # never leaked to the wire


def test_nav_token_fires_callback_once():
    fired = []
    api.set_layout_changed_callback(lambda: fired.append(1))
    api._state["last_nav"] = None
    api._state["last_nav_fire"] = 0.0
    api.handle_progress(nav="tab-a", now=1000.0)
    assert len(fired) == 1
    api.handle_progress(nav="tab-a", now=1001.0)  # same token: no re-fire
    assert len(fired) == 1
    api.handle_progress(nav="tab-b", now=1002.0)  # within debounce window...
    assert len(fired) == 1  # ...so still throttled
    api.handle_progress(nav="tab-c", now=1000.0 + api.NAV_FIRE_MIN_INTERVAL_S)
    assert len(fired) == 2


def test_owner_per_request():
    api.set_announce_owner("native")
    assert api.handle_progress(client="native", now=1.0)["announce"]["owner"] == "native"
    # external browser (no client flag) hears web announcements
    assert api.handle_progress(client=None, now=1.0)["announce"]["owner"] == "web"


def test_log_tail_read_by_seek():
    import os
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as tf:
        for i in range(3000):
            tf.write(f"line {i}\n")
        path = tf.name
    tail = api.read_log_tail(path, max_bytes=4096)
    assert "line 2999" in tail and "line 0\n" not in tail
    assert len(tail.splitlines()) < 3000
    os.unlink(path)


def test_handle_progress_never_raises():
    api.set_layout_changed_callback(None)
    payload = api.handle_progress(nav=None, now=1.0)
    assert "jobs" in payload and "settings" in payload


def test_terminal_words_from_history_shared_helper():
    entries = [
        {"type": "training", "model_name": "voice", "status": "failed"},
        {"type": "training", "model_name": "voice", "status": "completed"},  # older
        {"type": "extract", "model_name": "", "status": "completed"},  # incomplete
        {"type": "tts", "model_name": "x"},  # incomplete
        None,
    ]
    words = api.terminal_words_from_history(entries)
    assert words == {"training:voice": "failed"}  # setdefault keeps newest; skips gaps
    assert api.terminal_words_from_history(None) == {}
    assert api.terminal_words_from_history([]) == {}


def run_all():
    test_inference_stats_enrichment()
    test_training_metrics_enrichment()
    test_payload_shape_and_settings_echo()
    test_nav_token_fires_callback_once()
    test_owner_per_request()
    test_log_tail_read_by_seek()
    test_handle_progress_never_raises()
    test_terminal_words_from_history_shared_helper()
    print("All progress API tests passed (8).")


if __name__ == "__main__":
    run_all()
