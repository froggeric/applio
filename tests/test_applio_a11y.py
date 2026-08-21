# tests/test_applio_a11y.py
"""Pure-Python gate for applio_a11y (no GUI, no AppKit needed for the policy).
Run: venv_macos/bin/python tests/test_applio_a11y.py"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from applio_a11y import AnnouncementPolicy

SNAP = {
    "myvoice": {"type": "training", "name": "myvoice", "status": "running"},
}


def test_new_running_announces_start():
    p = AnnouncementPolicy()
    evts = p.events(SNAP)
    assert ("start", "Started training: myvoice") in evts, evts


def test_steady_state_no_events():
    p = AnnouncementPolicy()
    p.events(SNAP)
    assert p.events(SNAP) == [], "no announcements without a state change"


def test_terminal_transition():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events({"myvoice": {"type": "training", "name": "myvoice", "status": "completed"}})
    assert evts == [("terminal", "training: myvoice completed")], evts


def test_failed_is_terminal():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events({"myvoice": {"type": "training", "name": "myvoice", "status": "failed"}})
    assert evts[0][0] == "terminal" and "failed" in evts[0][1]


def test_pause_resume():
    p = AnnouncementPolicy()
    p.events(SNAP)
    paused = {"myvoice": {"type": "training", "name": "myvoice", "status": "paused"}}
    assert p.events(paused) == [("info", "training: myvoice paused")]
    assert p.events(SNAP) == [("info", "training: myvoice resumed")]


def test_disappeared_running_announces_finished():
    p = AnnouncementPolicy()
    p.events(SNAP)
    evts = p.events({})
    assert evts == [("terminal", "training: myvoice finished")], evts


def test_disappeared_paused_announces_finished():
    p = AnnouncementPolicy()
    p.events(SNAP)
    p.events({"myvoice": {"type": "training", "name": "myvoice", "status": "paused"}})
    evts = p.events({})
    assert evts == [("terminal", "training: myvoice finished")], evts


def test_disappeared_terminal_no_event():
    p = AnnouncementPolicy()
    p.events({"m": {"type": "tts", "name": "m", "status": "completed"}})
    assert p.events({}) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll applio_a11y tests passed ({len(fns)}).")
