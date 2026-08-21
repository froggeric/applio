# applio_a11y.py
"""Accessibility announcement engine for the Applio native app (fork-only).

Pure-Python decision logic (importable/testable with zero AppKit) plus a thin
poster that mirrors applio_launcher's _announce_for_accessibility (userInfo
key "AXAnnouncementKey" — verified against applio_launcher.py:142-151).

Phase 1 scope: job LIFECYCLE announcements only (start/pause/resume/terminal).
No per-tick chatter, no speech synthesis (must never collide with the audio
the user is evaluating). Percentage/epoch milestones are Phase 2.
"""

TERMINAL_STATUSES = {"completed", "failed", "error", "cancelled", "canceled", "interrupted"}


class AnnouncementPolicy:
    """Diffs consecutive process snapshots and decides what to announce."""

    def __init__(self):
        self._seen = {}  # key -> (status, label)

    def events(self, snapshot):
        """Return [(kind, message)] to announce.

        snapshot: dict key -> {"type": str, "name": str, "status": str}
        kind: "start" | "terminal" | "info"
        """
        out = []
        for key, info in snapshot.items():
            status = info.get("status", "running")
            label = f"{info.get('type', 'process')}: {info.get('name') or key}"
            prev = self._seen.get(key, (None, label))[0]
            if prev is None:
                if status == "running":
                    out.append(("start", f"Started {label}"))
            elif prev != status:
                if status in TERMINAL_STATUSES:
                    out.append(("terminal", f"{label} {status}"))
                elif status == "paused":
                    out.append(("info", f"{label} paused"))
                elif status == "running":
                    out.append(("info", f"{label} resumed"))
            self._seen[key] = (status, label)
        for key in [k for k in self._seen if k not in snapshot]:
            prev_status, label = self._seen.pop(key)
            if prev_status in ("running", "paused"):
                out.append(("terminal", f"{label} finished"))
        return out


def post_announcement(message, element):
    """Post a VoiceOver announcement. MUST be called on the main thread.

    Silently no-ops when AppKit is unavailable or posting fails (matches the
    launcher helper's defensive style — applio_launcher.py:142-151).
    """
    try:
        from AppKit import (
            NSAccessibilityPostNotification,
            NSAccessibilityAnnouncementRequestedNotification,
        )

        userInfo = {"AXAnnouncementKey": message}
        NSAccessibilityPostNotification(
            element, NSAccessibilityAnnouncementRequestedNotification, userInfo
        )
    except Exception:
        pass
