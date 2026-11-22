import json
import os
import queue
import shutil
import subprocess
import threading
from datetime import UTC, datetime, timedelta

PAUSE_AT = 95


def cli_env(settings):
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")
           if key in os.environ}
    return {**env, "CODEX_HOME": str(settings.codex_home.resolve())}


def read_limits(settings):
    executable = shutil.which("codex")
    if not executable:
        return None
    with subprocess.Popen([executable, "app-server", "--listen", "stdio://"],
                          env=cli_env(settings), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace") as process:
        lines = queue.Queue()

        def collect():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put("")

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()

        def send(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def receive(identifier):
            deadline = datetime.now(UTC) + timedelta(seconds=10)
            while (remaining := (deadline - datetime.now(UTC)).total_seconds()) > 0:
                line = lines.get(timeout=remaining)
                if not line:
                    break
                try:
                    response = json.loads(line)
                except ValueError:
                    continue
                if isinstance(response, dict) and response.get("id") == identifier:
                    return response.get("result")
            return None

        try:
            send({"id": 1, "method": "initialize",
                  "params": {"clientInfo": {"name": "tern", "version": "0.1.0"}}})
            if receive(1) is None:
                return None
            send({"method": "initialized"})
            send({"id": 2, "method": "account/rateLimits/read", "params": {}})
            return receive(2)
        finally:
            process.kill()
            reader.join(timeout=1)


def usage_windows(response):
    snapshot = response.get("rateLimits") or {}
    windows = []
    for key in ("primary", "secondary"):
        value = snapshot.get(key) or {}
        used, minutes, reset = (value.get(field) for field in ("usedPercent", "windowDurationMins", "resetsAt"))
        if not isinstance(used, (int, float)) or not 0 <= used <= 100:
            continue
        try:
            resets = datetime.fromtimestamp(reset, UTC).isoformat() if isinstance(reset, (int, float)) else None
        except (ValueError, OSError, OverflowError):
            resets = None
        windows.append({"used": used, "minutes": minutes, "resets": resets})
    return windows


def refresh_usage(db, settings, *, limited=False):
    clock = datetime.now(UTC)
    previous = db.one("SELECT * FROM codex_usage WHERE id=1")
    if previous and not limited:
        pause = previous["pause_until"]
        reset_passed = pause and 0 <= (clock - datetime.fromisoformat(pause)).total_seconds()
        if not reset_passed and clock - datetime.fromisoformat(previous["checked"]) < timedelta(seconds=90):
            return pause
    try:
        response = read_limits(settings)
    except (OSError, ValueError, queue.Empty):
        response = None
    response = response if isinstance(response, dict) else None
    windows = usage_windows(response) if response else []
    active = [window for window in windows if window["resets"] and window["resets"] > clock.isoformat()]
    blocking = [window["resets"] for window in active if window["used"] >= PAUSE_AT]
    denied = response is not None and response.get("ordinaryUsageAllowed") is False
    if (limited or denied) and not blocking:
        blocking.append((clock + timedelta(hours=1)).isoformat())
    if not windows and previous and previous["pause_until"] and previous["pause_until"] > clock.isoformat():
        blocking.append(previous["pause_until"])
    pause = max(blocking, default=None)
    db.execute("INSERT OR REPLACE INTO codex_usage VALUES(1,?,?,?,?)",
               (clock.isoformat(), json.dumps(windows), bool(windows), pause))
    return pause
