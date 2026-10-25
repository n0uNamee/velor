#!/usr/bin/env python3
"""Detached, loopback-only VÉLOR demo launcher. Does not read .env files."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "data" / "runtime"
METADATA = RUNTIME / "local-dev.json"
PYTHON = ROOT / ".venv" / "bin" / "python"
VITE = ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
PORTS = {"backend": 8001, "frontend": 5173}


def load_records():
    if not METADATA.exists():
        return {}
    try:
        data = json.loads(METADATA.read_text())
        if data.get("project") != str(ROOT) or not isinstance(data.get("services"), dict):
            raise ValueError
        return {name: item for name, item in data["services"].items() if name in PORTS and isinstance(item, dict)}
    except (ValueError, OSError, AttributeError):
        raise RuntimeError("Invalid launcher metadata; refusing to overwrite or stop processes") from None


def save_records(records):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    temporary = METADATA.with_suffix(".tmp")
    temporary.write_text(json.dumps({"project": str(ROOT), "services": records}, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(METADATA)


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def snapshot(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return None
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "stat=", "-o", "command="],
            capture_output=True, text=True, timeout=3, check=False,
        )
        fields = result.stdout.strip().split(maxsplit=6)
        if result.returncode or len(fields) != 7 or "Z" in fields[5]:
            return None
        return {"started": " ".join(fields[:5]), "command": shlex.split(fields[6])}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def valid_command(name, command):
    if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
        return False
    if name == "backend":
        interpreters = {str(PYTHON), str(Path(sys.base_prefix) / "Resources/Python.app/Contents/MacOS/Python")}
        return len(command) == 2 and command[0] in interpreters and command[1] == str(ROOT / "run_backend.py")
    return (len(command) == 7 and Path(command[0]).is_absolute() and Path(command[0]).name == "node"
            and command[1:] == [str(VITE), "--host", "127.0.0.1", "--port", "5173", "--strictPort"])


def owned(name, record):
    if not record or not valid_command(name, record.get("command")):
        return False
    current = snapshot(record.get("pid"))
    return bool(current and valid_command(name, current["command"]) and current["started"] == record.get("started"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def health(name):
    url = f"http://127.0.0.1:{PORTS[name]}" + ("/api/health" if name == "backend" else "/")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=1) as response:
            if response.status != 200:
                return "not ready"
            if name == "backend":
                data = json.loads(response.read(65536))
                if data.get("status") == "ok" and data.get("mode") == "demo" and data.get("environment") == "development":
                    return "healthy demo/development"
                return "unexpected backend configuration"
            return "healthy"
    except (OSError, ValueError, urllib.error.URLError):
        return "not ready"


def status(records):
    ready = True
    for name, port in PORTS.items():
        record = records.get(name, {})
        if owned(name, record):
            result = health(name)
            print(f"{name}: PID {record['pid']}; {result}; http://127.0.0.1:{port}")
            ready = ready and result.startswith("healthy")
        else:
            state = "port occupied by an unrecorded process; untouched" if listening(port) else "stopped"
            print(f"{name}: {state}; http://127.0.0.1:{port}")
            ready = False
    return 0 if ready else 1


def child_environment(frontend=False):
    environment = os.environ.copy()
    # Vite receives no provider/Telegram credentials, including VITE-prefixed variants.
    if frontend:
        for key in list(environment):
            upper = key.upper()
            if any(word in upper for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "OPENROUTER", "TELEGRAM")):
                environment.pop(key, None)
        environment["VELOR_API_TARGET"] = "http://127.0.0.1:8001"
    environment.update({"VELOR_ENV": "development", "VELOR_DEV_AUTH": "1", "VELOR_MODE": "demo",
                        "VELOR_ALLOW_PAID_REQUESTS": "0", "VELOR_PROVIDER_BUDGET_USD": "0",
                        "VELOR_ANALYSIS_RESERVE_USD": "0", "VELOR_RENDER_RESERVE_USD": "0",
                        "VELOR_DATA_DIR": str(ROOT / "data"), "VELOR_FRONTEND_DIST": "",
                        "VELOR_PORT": "8001", "VELOR_LOCKED_PREVIEW": "0"})
    return environment


def start(records):
    node = shutil.which("node")
    if not PYTHON.is_file() or not VITE.is_file() or not node:
        raise RuntimeError("Install .venv dependencies and frontend/node_modules; node must be available")
    # Check both ports before creating either process. Unknown listeners are never stopped.
    for name, port in PORTS.items():
        if listening(port) and not owned(name, records.get(name)):
            raise RuntimeError(f"Port {port} is occupied by an unrecorded process; no takeover attempted")
    commands = {"backend": [str(PYTHON), str(ROOT / "run_backend.py")],
                "frontend": [str(Path(node).absolute()), str(VITE), "--host", "127.0.0.1", "--port", "5173", "--strictPort"]}
    RUNTIME.mkdir(parents=True, exist_ok=True)
    for name, command in commands.items():
        if owned(name, records.get(name)):
            continue
        # Recheck immediately before launch to fail safely if another listener appeared.
        if listening(PORTS[name]):
            raise RuntimeError(f"Port {PORTS[name]} became occupied; no takeover attempted")
        with (RUNTIME / f"{name}.log").open("ab", buffering=0) as output:
            process = subprocess.Popen(command, cwd=ROOT / "frontend" if name == "frontend" else ROOT,
                                       env=child_environment(name == "frontend"), stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        current = None
        for _ in range(20):
            current = snapshot(process.pid)
            if current or process.poll() is not None:
                break
            time.sleep(0.05)
        records[name] = {"pid": process.pid, "command": command,
                         "started": current["started"] if current else None, "port": PORTS[name]}
        save_records(records)
        if not current or not owned(name, records[name]):
            raise RuntimeError(f"{name} failed to start or could not be verified; inspect data/runtime/{name}.log")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if all(owned(name, records.get(name)) and health(name).startswith("healthy") for name in PORTS):
            break
        time.sleep(0.25)
    print(f"Logs and PID metadata: {RUNTIME}")
    return status(records)


def stop(records):
    refused = False
    for name in PORTS:
        record = records.get(name)
        if not record:
            continue
        if not owned(name, record):
            print(f"{name}: recorded process absent or command/start time changed; no signal sent")
            records.pop(name, None)
            continue
        pid = record["pid"]
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while owned(name, record) and time.monotonic() < deadline:
                time.sleep(0.1)
            if owned(name, record):
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.1)
            if owned(name, record):
                refused = True
                print(f"{name}: PID {pid} still running; record retained")
                continue
        except ProcessLookupError:
            pass
        except PermissionError:
            refused = True
            print(f"{name}: PID {pid} could not be stopped; record retained")
            continue
        records.pop(name, None)
        print(f"{name}: stopped recorded PID {pid}")
    save_records(records)
    return 1 if refused else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "stop"))
    action = parser.parse_args().action
    try:
        records = load_records()
        return {"start": start, "status": status, "stop": stop}[action](records)
    except (RuntimeError, OSError) as error:
        print(f"VÉLOR local demo: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
