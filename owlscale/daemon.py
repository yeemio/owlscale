"""
owlscale.daemon — Background monitor that polls state.json and writes
per-agent trigger files when tasks transition to "dispatched".

Public API
----------
    run_daemon(owlscale_dir, poll_interval, drive_shell)
    start_daemon(owlscale_dir, poll_interval, drive_shell) -> int
    stop_daemon(owlscale_dir) -> bool
    get_daemon_status(owlscale_dir) -> dict
    tail_daemon_log(owlscale_dir, n) -> list[str]
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PID_FILE = "daemon.pid"
META_FILE = "daemon.meta.json"
LOG_FILE = "log/daemon.log"
TRIGGER_EXT = ".trigger"
TRIGGER_TMP_EXT = ".trigger.tmp"

DISPATCHED = "dispatched"


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

@dataclass
class _DaemonState:
    last_mtime: float
    last_size: int
    task_snapshot: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers: trigger file
# ---------------------------------------------------------------------------

def _read_meta(owlscale_dir: Path) -> dict:
    meta_path = owlscale_dir / META_FILE
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_meta(owlscale_dir: Path, data: dict) -> None:
    meta_path = owlscale_dir / META_FILE
    meta_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _next_seq(owlscale_dir: Path) -> int:
    """Increment and persist the global trigger sequence counter."""
    meta = _read_meta(owlscale_dir)
    seq = meta.get("trigger_seq", 0) + 1
    meta["trigger_seq"] = seq
    _write_meta(owlscale_dir, meta)
    return seq


def write_trigger(
    owlscale_dir: Path,
    agent_id: str,
    task_id: str,
    pending_task_ids: list[str],
) -> Path:
    """
    Write an atomic coalescing trigger file for agent_id.
    Returns the path to the written trigger file.
    """
    agents_dir = owlscale_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    seq = _next_seq(owlscale_dir)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    payload = {
        "version": 1,
        "agent_id": agent_id,
        "event": "dispatch",
        "task_id": task_id,
        "sequence": seq,
        "generated_at": now,
        "pending_task_ids": pending_task_ids,
    }

    trigger_path = agents_dir / f"{agent_id}{TRIGGER_EXT}"
    tmp_path = agents_dir / f"{agent_id}{TRIGGER_TMP_EXT}"

    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp_path), str(trigger_path))

    return trigger_path


# ---------------------------------------------------------------------------
# Helpers: state.json loading
# ---------------------------------------------------------------------------

def _load_state_json(owlscale_dir: Path) -> dict:
    """Load state.json tasks dict. Raises on error."""
    data = json.loads((owlscale_dir / "state.json").read_text(encoding="utf-8"))
    return data.get("tasks", {})


def _load_roster(owlscale_dir: Path) -> dict:
    roster_path = owlscale_dir / "roster.json"
    if not roster_path.exists():
        return {}
    try:
        return json.loads(roster_path.read_text(encoding="utf-8")).get("agents", {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Adapter dispatch
# ---------------------------------------------------------------------------

def invoke_adapter(owlscale_dir: Path, agent_id: str, task_id: str) -> bool:
    """
    Read roster.json for agent delivery config, dispatch to adapter.
    Non-fatal — always returns bool.
    """
    try:
        roster = _load_roster(owlscale_dir)
        agent_data = roster.get(agent_id, {})
        delivery = agent_data.get("delivery", {})
        mode = delivery.get("mode", "none")

        if mode == "ghostty-applescript":
            from owlscale.adapters.ghostty import inject_prompt
            window_title = delivery.get("window_title") if delivery.get("target") == "window-title" else None
            return inject_prompt(agent_id, task_id, window_title=window_title)

        if mode == "tmux":
            _log(owlscale_dir, f"tmux adapter: stub — would wake {agent_id} for {task_id}")
            return True

        # mode == "none" or anything unrecognised
        return False

    except Exception as exc:  # noqa: BLE001
        _log(owlscale_dir, f"[warn] adapter error for {agent_id}/{task_id}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(owlscale_dir: Path, message: str) -> None:
    """Append a timestamped line to daemon.log."""
    try:
        log_path = owlscale_dir / LOG_FILE
        log_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{now}  {message}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Foreground daemon loop
# ---------------------------------------------------------------------------

def _pending_for_agent(snapshot: dict, agent_id: str) -> list[str]:
    return [
        tid for tid, d in snapshot.items()
        if d.get("assignee") == agent_id and d.get("status") == DISPATCHED
    ]


def run_daemon(
    owlscale_dir: Path,
    poll_interval: float = 1.0,
    drive_shell: bool = False,
) -> None:
    """Foreground daemon loop. Blocks until SIGTERM/KeyboardInterrupt."""
    state_path = owlscale_dir / "state.json"
    _log(owlscale_dir, f"daemon started  poll={poll_interval}s  drive_shell={drive_shell}")

    # --- startup reconciliation ---
    try:
        task_snapshot = _load_state_json(owlscale_dir)
    except Exception:
        task_snapshot = {}

    for task_id, data in task_snapshot.items():
        if data.get("status") == DISPATCHED:
            agent_id = data.get("assignee", "")
            if not agent_id:
                continue
            pending = _pending_for_agent(task_snapshot, agent_id)
            try:
                write_trigger(owlscale_dir, agent_id, task_id, pending)
                _log(owlscale_dir, f"startup: trigger written for {agent_id}: {task_id}")
            except Exception as exc:
                _log(owlscale_dir, f"[warn] startup trigger error: {exc}")
            if drive_shell:
                invoke_adapter(owlscale_dir, agent_id, task_id)

    try:
        stat = os.stat(state_path)
        ds = _DaemonState(
            last_mtime=stat.st_mtime,
            last_size=stat.st_size,
            task_snapshot=task_snapshot,
        )
    except OSError:
        ds = _DaemonState(last_mtime=0.0, last_size=0, task_snapshot=task_snapshot)

    # --- main poll loop ---
    running = True

    def _handle_sigterm(signum, frame):
        nonlocal running
        running = False

    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except ValueError:
        pass  # not in main thread — signal handling skipped (e.g. in tests)

    try:
        while running:
            time.sleep(poll_interval)
            if not running:
                break

            try:
                stat = os.stat(state_path)
            except OSError:
                continue

            if stat.st_mtime == ds.last_mtime and stat.st_size == ds.last_size:
                continue

            # state.json changed — parse it
            try:
                new_snapshot = _load_state_json(owlscale_dir)
            except json.JSONDecodeError:
                time.sleep(0.1)
                try:
                    new_snapshot = _load_state_json(owlscale_dir)
                except Exception:
                    continue
            except Exception:
                continue

            # detect newly dispatched tasks
            for task_id, data in new_snapshot.items():
                if data.get("status") != DISPATCHED:
                    continue
                prev_status = ds.task_snapshot.get(task_id, {}).get("status")
                if prev_status == DISPATCHED:
                    continue  # already dispatched before

                agent_id = data.get("assignee", "")
                if not agent_id:
                    continue

                pending = _pending_for_agent(new_snapshot, agent_id)
                try:
                    write_trigger(owlscale_dir, agent_id, task_id, pending)
                    _log(owlscale_dir, f"trigger written for {agent_id}: {task_id}")
                except Exception as exc:
                    _log(owlscale_dir, f"[warn] trigger write error: {exc}")

                if drive_shell:
                    try:
                        invoke_adapter(owlscale_dir, agent_id, task_id)
                    except Exception as exc:
                        _log(owlscale_dir, f"[warn] adapter error: {exc}")

            ds.task_snapshot = new_snapshot
            ds.last_mtime = stat.st_mtime
            ds.last_size = stat.st_size

    except KeyboardInterrupt:
        pass

    _log(owlscale_dir, "daemon stopped")


# ---------------------------------------------------------------------------
# Background start/stop
# ---------------------------------------------------------------------------

def start_daemon(
    owlscale_dir: Path,
    poll_interval: float = 1.0,
    drive_shell: bool = False,
) -> int:
    """Start daemon as detached background process. Returns PID."""
    log_path = owlscale_dir / LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "owlscale", "daemon", "run",
        "--poll", str(poll_interval),
    ]
    if drive_shell:
        cmd.append("--drive-shell")

    log_fd = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True,
        cwd=str(owlscale_dir.parent),
    )
    log_fd.close()

    pid = proc.pid

    # Write PID file
    pid_path = owlscale_dir / PID_FILE
    pid_path.write_text(str(pid), encoding="utf-8")

    # Write/update meta
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    meta = _read_meta(owlscale_dir)
    meta.update({
        "pid": pid,
        "started_at": now,
        "poll_interval": poll_interval,
        "mode": "drive_shell" if drive_shell else "trigger_only",
        "workspace": str(owlscale_dir),
    })
    _write_meta(owlscale_dir, meta)

    return pid


def stop_daemon(owlscale_dir: Path) -> bool:
    """Send SIGTERM to daemon. Returns True if process was running."""
    pid_path = owlscale_dir / PID_FILE
    if not pid_path.exists():
        return False

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pid_path.unlink(missing_ok=True)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return False
    except Exception:
        pid_path.unlink(missing_ok=True)
        return False

    # Wait up to 3s for graceful exit
    for _ in range(30):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break

    # SIGKILL if still alive
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        pass

    pid_path.unlink(missing_ok=True)
    return True


def get_daemon_status(owlscale_dir: Path) -> dict:
    """
    Return {running: bool, pid: int|None, started_at: str|None,
            poll_interval: float|None, mode: str|None, trigger_seq: int}
    """
    meta = _read_meta(owlscale_dir)
    trigger_seq = meta.get("trigger_seq", 0)

    pid_path = owlscale_dir / PID_FILE
    if not pid_path.exists():
        return {
            "running": False, "pid": None,
            "started_at": None, "poll_interval": None,
            "mode": None, "trigger_seq": trigger_seq,
        }

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return {
            "running": False, "pid": None,
            "started_at": None, "poll_interval": None,
            "mode": None, "trigger_seq": trigger_seq,
        }

    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    except PermissionError:
        alive = True  # process exists but owned by different user

    return {
        "running": alive,
        "pid": pid if alive else None,
        "started_at": meta.get("started_at"),
        "poll_interval": meta.get("poll_interval"),
        "mode": meta.get("mode"),
        "trigger_seq": trigger_seq,
    }


def tail_daemon_log(owlscale_dir: Path, n: int = 50) -> list[str]:
    """Return last n lines of daemon.log."""
    log_path = owlscale_dir / LOG_FILE
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return lines[-n:]
