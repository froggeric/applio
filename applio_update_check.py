# applio_update_check.py
"""Shared GitHub update check for Applio (fork-only).

Used by:
  - the launcher's manual "Check for Updates..." menu item (tri-state NSAlert)
  - the launcher's silent launch-time check (alert only if newer)

Ports macos_wrapper.py:check_for_updates() but FIXES the version comparison:
the original used a string `!=` (macos_wrapper.py:806) which flagged downgrades
as updates and mis-handled 3.6.10 vs 3.6.9. We use packaging.version (already a
PyInstaller hiddenimport — Applio.spec).
"""
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request

try:
    from packaging.version import parse as _parse_version
except Exception:  # pragma: no cover - packaging is bundled, but stay safe
    _parse_version = None


def _get_version_info():
    """Read the full build version from build_info.json (ported verbatim from
    macos_wrapper.py:197)."""
    for _rel in ("build_info.json", os.path.join("assets", "build_info.json")):
        _candidate = os.path.join(_base_path(), _rel)
        try:
            with open(_candidate, "r", encoding="utf-8") as f:
                _info = json.load(f)
                _full = _info.get("full_version") or _info.get("version")
                if _full:
                    return _full
        except Exception:
            continue
    for _cfg in ("assets/config.json", "assets/config_template.json"):
        try:
            with open(os.path.join(_base_path(), _cfg), "r", encoding="utf-8") as f:
                return json.load(f).get("version", "3.6.3")
        except Exception:
            continue
    return "3.6.3"


def _base_path():
    """Frozen-CWD-safe base (sys._MEIPASS when frozen, else this file's dir).
    `sys` is imported at module top (used at call time, not import time)."""
    return getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))


VERSION = _get_version_info()
GITHUB_REPO = "froggeric/applio-macOS-native-app"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def is_update_available(current_version, latest_version=None, release_url=None):
    """Return (bool, latest_version, release_url).

    If latest_version is None, only does the comparison (used by tests + the
    launch-time check after a fetch). Fail-safe: unparseable tags => no update.
    """
    if not latest_version or not current_version:
        return (False, latest_version, release_url or RELEASES_URL)
    if _parse_version is None:
        # Without packaging, fall back to a strict "different AND not a downgrade
        # heuristic" — but packaging is bundled, so this is defensive only.
        logging.warning("[Update] packaging.version unavailable; falling back to degraded string compare")
        return (latest_version != current_version, latest_version, release_url or RELEASES_URL)
    try:
        return (_parse_version(latest_version) > _parse_version(current_version),
                latest_version, release_url or RELEASES_URL)
    except Exception:
        return (False, latest_version, release_url or RELEASES_URL)


def fetch_latest_release():
    """GET the latest release JSON from GitHub. Returns dict or None on error."""
    try:
        request = urllib.request.Request(
            API_URL, headers={"User-Agent": f"Applio/{VERSION}"}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logging.warning(f"[Update] HTTP error: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        logging.warning(f"[Update] network error: {e.reason}")
    except json.JSONDecodeError as e:
        logging.warning(f"[Update] bad JSON: {e}")
    except Exception as e:
        logging.warning(f"[Update] failed: {e}")
    return None


def _fetch_result():
    """Return (latest_version, release_url, error_message)."""
    data = fetch_latest_release()
    if data is None:
        return (None, RELEASES_URL, "Could not reach GitHub.")
    tag = (data.get("tag_name") or "").lstrip("v")
    return (tag or None, data.get("html_url", RELEASES_URL), None)


def _run_async_on_main(work, on_main):
    """Run blocking `work()` on a daemon thread; pass its result to `on_main()`
    on the main thread via AppHelper.callAfter. Wraps work in an NSAutoreleasePool."""
    import threading

    def _runner():
        result = None
        try:
            from Foundation import NSAutoreleasePool
            pool = NSAutoreleasePool.alloc().init()
            try:
                result = work()
            finally:
                del pool
        except ImportError:
            result = work()
        except Exception as e:
            logging.error(f"[Update] background work failed: {e}")
            result = None
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(on_main, result)
        except Exception:
            on_main(result)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()


def check_for_updates_interactive():
    """Manual menu item: tri-state NSAlert. Network runs off the main thread so
    the 2 s menu timer / event loop never blocks (worst case = the 10 s timeout)."""
    try:
        from AppKit import (NSAlert, NSAlertFirstButtonReturn, NSAlertStyleInformational,
                            NSAlertStyleWarning)
        from PyObjCTools import AppHelper
    except ImportError:
        logging.warning("[Update] AppKit unavailable; skipping interactive check")
        return

    def _on_main(result):
        latest_version, release_url, error_message = result
        alert = NSAlert.alloc().init()
        if error_message or not latest_version:
            alert.setMessageText_("Could Not Check for Updates")
            alert.setInformativeText_(
                f"An error occurred while checking for updates.\n\n"
                f"{error_message or 'No release tag found.'}\n\n"
                "You can manually check for updates on GitHub."
            )
            alert.addButtonWithTitle_("Open GitHub Releases")
            alert.addButtonWithTitle_("OK")
            alert.setAlertStyle_(NSAlertStyleWarning)
            if alert.runModal() == NSAlertFirstButtonReturn:
                subprocess.Popen(['open', release_url])
        elif is_update_available(VERSION, latest_version, release_url)[0]:
            alert.setMessageText_("Update Available")
            alert.setInformativeText_(
                f"A new version of Applio is available.\n\n"
                f"Current version: v{VERSION}\n"
                f"Latest version: v{latest_version}\n\n"
                "Would you like to download the update?"
            )
            alert.addButtonWithTitle_("Download Update")
            alert.addButtonWithTitle_("Later")
            alert.setAlertStyle_(NSAlertStyleInformational)
            if alert.runModal() == NSAlertFirstButtonReturn:
                subprocess.Popen(['open', release_url])
        else:
            alert.setMessageText_("You're Up to Date")
            alert.setInformativeText_(
                f"Applio is running the latest version.\n\nVersion {VERSION}"
            )
            alert.addButtonWithTitle_("OK")
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.runModal()

    _run_async_on_main(_fetch_result, _on_main)


def check_for_updates_at_launch():
    """Silent unless a newer version exists. Network on a daemon thread; the alert
    (if any) is shown on the main thread."""
    def _on_main(result):
        latest_version, release_url, error_message = result
        if error_message or not latest_version:
            return  # silent on error / offline
        available, _, url = is_update_available(VERSION, latest_version, release_url)
        if not available:
            return  # silent when up to date
        try:
            from AppKit import NSAlert, NSAlertFirstButtonReturn, NSAlertStyleInformational
        except ImportError:
            return
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Update Available")
        alert.setInformativeText_(
            f"A new version of Applio is available (v{latest_version}).\n\n"
            f"You are running v{VERSION}."
        )
        alert.addButtonWithTitle_("Open GitHub Releases")
        alert.addButtonWithTitle_("Later")
        alert.setAlertStyle_(NSAlertStyleInformational)
        if alert.runModal() == NSAlertFirstButtonReturn:
            subprocess.Popen(['open', url])

    _run_async_on_main(_fetch_result, _on_main)
