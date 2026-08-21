"""Fork-owned a11y progress API: GET /applio-a11y/progress.

Serves the web-UI payload (live jobs + metrics + terminal words + a11y
settings echo) from the same in-process sources the native dashboard uses.
AppKit-free: the launcher pushes settings/owner/callback; this module never
imports AppKit or the launcher by name. The launcher runs as __main__ (frozen
entry AND dev script), so module resolution goes through sys.modules with a
__main__ fallback — a plain get("applio_launcher") ALWAYS misses in the app.
"""

import logging
import os
import sys
import threading
import time

NAV_FIRE_MIN_INTERVAL_S = 5.0
LOG_TAIL_MAX_BYTES = 262144

_lock = threading.Lock()
_state = {
    "settings": {"verbosity": "standard", "sound": False},
    "announce_owner": "web",
    "layout_cb": None,
    "last_nav": None,
    "last_nav_fire": 0.0,
}
_last_good_payload = None


def read_log_tail(path, max_bytes=LOG_TAIL_MAX_BYTES):
    """Seek-based tail read — training logs grow to multi-MB and this runs
    every poll; never slurp the whole file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            return fh.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def set_settings(settings):
    with _lock:
        _state["settings"] = dict(settings)


def set_announce_owner(owner):
    with _lock:
        _state["announce_owner"] = owner


def set_layout_changed_callback(cb):
    with _lock:
        _state["layout_cb"] = cb


def enrich_jobs(jobs, now):
    out = []
    for job in jobs:
        job = dict(job)
        if job.get("type") == "inference":
            record = {
                "total": job.get("total") or 0,
                "processed": job.get("processed") or 0,
                "converted": job.get("converted") or 0,
                "started_at": job.get("started_at"),
                "ended_at": job.get("ended_at"),
            }
            try:
                from applio_inference_stats import compute_inference_stats

                stats = compute_inference_stats(record, now)
            except Exception:
                stats = {}
            if record["total"]:
                job["pct"] = stats.get("pct", 0.0)
                job["detail"] = f"{record['processed']} of {record['total']}"
                job["eta"] = stats.get("eta", 0.0)
        elif job.get("type") == "training" and job.get("log_tail"):
            try:
                from rvc.lib.tools.process_log_parser import (
                    detect_phase_name,
                    parse_epoch_progress,
                    parse_training_status_line,
                )

                epoch = best = phase = None
                for line in reversed(job["log_tail"].splitlines()):
                    if epoch is None:
                        epoch = parse_epoch_progress(line)
                    if best is None:
                        parsed = parse_training_status_line(line)
                        if parsed:
                            best = parsed
                    if phase is None:
                        phase = detect_phase_name(line)
                    if epoch and best and phase:
                        break
                if phase:
                    job["phase"] = phase
                if epoch:
                    job["epoch"] = [epoch["current"], epoch["total"]]
                    if epoch["total"]:
                        job["pct"] = round(epoch["current"] / epoch["total"] * 100, 1)
                if best:
                    if best.get("best_loss") is not None:
                        job["best_loss"] = best["best_loss"]
                    job["detail"] = (
                        f"epoch {best.get('epoch', '?')} step {best.get('step', '?')}"
                    )
            except Exception:
                logging.debug("[ProgressAPI] training parse failed", exc_info=True)
        out.append(job)
    return out


def build_progress_payload(jobs, settings, announce_owner, now, words=None):
    return {
        "now": now,
        "announce": {"owner": announce_owner},
        "settings": dict(settings),
        "words": dict(words or {}),
        "jobs": [
            {k: v for k, v in job.items() if k != "log_tail"} for job in jobs
        ],
    }


def _resolve_launcher():
    launcher = sys.modules.get("applio_launcher")
    if launcher is None:
        main = sys.modules.get("__main__")
        if main is not None and hasattr(main, "get_active_processes"):
            launcher = main
    return launcher


def _collect_words(launcher):
    """History-derived terminal words: f"{etype}:{name}" -> status (mirrors
    applio_launcher._a11y_terminal_words). Live sources only ever report
    'running', so these words are the ONLY way the web side learns 'failed'."""
    words = {}
    try:
        for entry in launcher.get_recent_processes(20):
            etype = entry.get("type") or "process"
            name = entry.get("model_name") or "job"
            words.setdefault(f"{etype}:{name}", entry.get("status") or "completed")
    except Exception:
        logging.debug("[ProgressAPI] history read failed", exc_info=True)
    return words


def _collect_jobs():
    launcher = _resolve_launcher()
    if launcher is None:
        return []
    jobs = []
    try:
        for proc in launcher.get_active_processes():
            name = proc.get("model_name") or "job"
            ptype = proc.get("type") or "process"
            entry = {
                "key": f"{ptype}:{name}:{proc.get('pid') or 'x'}",
                "type": ptype,
                "name": name,
                "status": proc.get("status", "running"),
                "word_key": f"{ptype}:{name}",
            }
            # Tracked subprocesses store 'log_file' (patch_process_tracking
            # passes log_file=...); 'log_path' exists only on history entries.
            log_path = proc.get("log_file") or proc.get("log_path")
            if ptype == "training" and log_path and os.path.exists(log_path):
                tail = read_log_tail(log_path)
                if tail:
                    entry["log_tail"] = tail
            jobs.append(entry)
    except Exception:
        logging.debug("[ProgressAPI] active-process read failed", exc_info=True)
    try:
        infer = launcher._synthesize_inference_proc()
        if infer:
            name = infer.get("model_name") or "batch"
            jobs.append(
                {
                    "key": f"inference:{name}:app",
                    "type": "inference",
                    "name": name,
                    "status": infer.get("status", "running"),
                    "word_key": f"inference:{name}",
                    "total": infer.get("total"),
                    "processed": infer.get("processed"),
                    "converted": infer.get("converted"),
                    "started_at": infer.get("started_at"),
                    "current_file": infer.get("current_file"),
                }
            )
    except Exception:
        logging.debug("[ProgressAPI] inference synthesis failed", exc_info=True)
    return jobs


def handle_progress(nav=None, client=None, now=None):
    global _last_good_payload
    now = time.time() if now is None else now
    try:
        with _lock:
            settings = dict(_state["settings"])
            owner_state = _state["announce_owner"]
            cb = _state["layout_cb"]
            last_nav = _state["last_nav"]
            last_fire = _state["last_nav_fire"]
            fire = bool(
                cb
                and nav
                and nav != last_nav
                and (now - last_fire) >= NAV_FIRE_MIN_INTERVAL_S
            )
            if fire:
                _state["last_nav"] = nav
                _state["last_nav_fire"] = now
        if fire and cb:
            try:
                cb()
            except Exception:
                logging.debug("[ProgressAPI] layout callback failed", exc_info=True)
        # Per-request owner: only the in-app WKWebView client (client=native,
        # sent when window.pywebview exists) is silenced by the native engine;
        # an external browser at the same port still gets web announcements.
        owner = "native" if (owner_state == "native" and client == "native") else "web"
        launcher = _resolve_launcher()
        jobs = enrich_jobs(_collect_jobs(), now)
        words = _collect_words(launcher) if launcher else {}
        payload = build_progress_payload(jobs, settings, owner, now, words)
        _last_good_payload = payload
        return payload
    except Exception:
        logging.exception("[ProgressAPI] handle_progress failed")
        if _last_good_payload is not None:
            return _last_good_payload  # transient error: keep owner/jobs stable
        return build_progress_payload(
            [], {"verbosity": "standard", "sound": False}, "web", now
        )


def register_routes(app):
    from fastapi import Request
    from starlette.concurrency import run_in_threadpool

    @app.get("/applio-a11y/progress")
    async def applio_a11y_progress(request: Request):
        # handle_progress does blocking file IO; keep it off the event loop.
        return await run_in_threadpool(
            handle_progress,
            nav=request.query_params.get("nav"),
            client=request.query_params.get("client"),
        )
