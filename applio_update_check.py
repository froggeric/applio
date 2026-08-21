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


def _version_roots():
    """Candidate dirs to search for build_info.json / config (frozen-CWD-safe).

    sys._MEIPASS is Contents/Frameworks for these processes, but build_info.json is
    written to Contents/Resources by build_macos.py — so also derive the bundle's
    Contents/{Resources,Frameworks} from sys.executable and search them all.
    """
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    try:
        # sys.executable == .../Applio.app/Contents/MacOS/Applio
        contents = os.path.dirname(os.path.dirname(sys.executable))
        roots.append(os.path.join(contents, "Resources"))
        roots.append(os.path.join(contents, "Frameworks"))
    except Exception:
        pass
    seen = set()
    out = []
    for r in roots:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out or [os.path.dirname(os.path.abspath(__file__))]


def _get_version_info():
    """Read the full build version (e.g. '3.6.3.5') from build_info.json."""
    for root in _version_roots():
        for _rel in ("build_info.json", os.path.join("assets", "build_info.json")):
            try:
                with open(os.path.join(root, _rel), "r", encoding="utf-8") as f:
                    _info = json.load(f)
                    _full = _info.get("full_version") or _info.get("version")
                    if _full:
                        return _full
            except Exception:
                continue
    # Last resort: upstream config version (no build number).
    for root in _version_roots():
        for _cfg in (
            "assets/config.json",
            "assets/config_template.json",
            "config.json",
            "config_template.json",
        ):
            try:
                with open(os.path.join(root, _cfg), "r", encoding="utf-8") as f:
                    return json.load(f).get("version", "3.6.3")
            except Exception:
                continue
    return "3.6.3"


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
        logging.warning(
            "[Update] packaging.version unavailable; falling back to degraded string compare"
        )
        return (
            latest_version != current_version,
            latest_version,
            release_url or RELEASES_URL,
        )
    try:
        return (
            _parse_version(latest_version) > _parse_version(current_version),
            latest_version,
            release_url or RELEASES_URL,
        )
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
        from AppKit import (
            NSAlert,
            NSAlertFirstButtonReturn,
            NSAlertStyleInformational,
            NSAlertStyleWarning,
            NSApp,
        )
        from PyObjCTools import AppHelper
    except ImportError:
        logging.warning("[Update] AppKit unavailable; skipping interactive check")
        return

    import applio_i18n

    _t = applio_i18n.native_tr

    def _on_main(result):
        latest_version, release_url, error_message = result
        alert = NSAlert.alloc().init()
        if error_message or not latest_version:
            alert.setMessageText_(_t("Could Not Check for Updates"))
            alert.setInformativeText_(
                _t(
                    "An error occurred while checking for updates.\n\n"
                    "{error}\n\n"
                    "You can manually check for updates on GitHub."
                ).format(error=error_message or _t("No release tag found."))
            )
            alert.addButtonWithTitle_(_t("Open GitHub Releases"))
            alert.addButtonWithTitle_(_t("OK"))
            alert.setAlertStyle_(NSAlertStyleWarning)
            NSApp.activateIgnoringOtherApps_(True)
            buttons = alert.buttons()
            # Escape on the last button only when there's a choice; a lone OK
            # must keep its auto-Return (setting \x1b would replace it).
            if len(buttons) > 1:
                buttons[-1].setKeyEquivalent_("\x1b")
            if alert.runModal() == NSAlertFirstButtonReturn:
                subprocess.Popen(["open", release_url])
        elif is_update_available(VERSION, latest_version, release_url)[0]:
            alert.setMessageText_(_t("Update Available"))
            alert.setInformativeText_(
                _t(
                    "A new version of Applio is available.\n\n"
                    "Current version: v{current}\n"
                    "Latest version: v{latest}\n\n"
                    "Would you like to open the releases page to get the new version?"
                ).format(current=VERSION, latest=latest_version)
            )
            alert.addButtonWithTitle_(_t("Open Releases Page…"))
            alert.addButtonWithTitle_(_t("Later"))
            alert.setAlertStyle_(NSAlertStyleInformational)
            NSApp.activateIgnoringOtherApps_(True)
            buttons = alert.buttons()
            # Escape on the last button only when there's a choice; a lone OK
            # must keep its auto-Return (setting \x1b would replace it).
            if len(buttons) > 1:
                buttons[-1].setKeyEquivalent_("\x1b")
            if alert.runModal() == NSAlertFirstButtonReturn:
                subprocess.Popen(["open", release_url])
        else:
            alert.setMessageText_(_t("You're Up to Date"))
            alert.setInformativeText_(
                _t("Applio is running the latest version.\n\nVersion {version}").format(
                    version=VERSION
                )
            )
            alert.addButtonWithTitle_(_t("OK"))
            alert.setAlertStyle_(NSAlertStyleInformational)
            NSApp.activateIgnoringOtherApps_(True)
            buttons = alert.buttons()
            # Escape on the last button only when there's a choice; a lone OK
            # must keep its auto-Return (setting \x1b would replace it).
            if len(buttons) > 1:
                buttons[-1].setKeyEquivalent_("\x1b")
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
            from AppKit import (
                NSAlert,
                NSAlertFirstButtonReturn,
                NSAlertStyleInformational,
                NSApp,
            )
        except ImportError:
            return
        import applio_i18n

        _t = applio_i18n.native_tr

        alert = NSAlert.alloc().init()
        alert.setMessageText_(_t("Update Available"))
        alert.setInformativeText_(
            _t(
                "A new version of Applio is available (v{latest}).\n\n"
                "You are running v{current}."
            ).format(latest=latest_version, current=VERSION)
        )
        alert.addButtonWithTitle_(_t("Open GitHub Releases"))
        alert.addButtonWithTitle_(_t("Later"))
        alert.setAlertStyle_(NSAlertStyleInformational)
        NSApp.activateIgnoringOtherApps_(True)
        buttons = alert.buttons()
        # Escape on the last button only when there's a choice; a lone OK
        # must keep its auto-Return (setting \x1b would replace it).
        if len(buttons) > 1:
            buttons[-1].setKeyEquivalent_("\x1b")
        if alert.runModal() == NSAlertFirstButtonReturn:
            subprocess.Popen(["open", url])

    _run_async_on_main(_fetch_result, _on_main)
