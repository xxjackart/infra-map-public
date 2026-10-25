#!/usr/bin/env python3
"""Browser regression checks for the infra-map v6.2 artifact.

Serves the repository root on 127.0.0.1:4175, loads tests/run.html in real
headless Chrome (same-origin iframe of /docs/index.html), lets the runner drive
clicks and assertions, then parses the dumped DOM for data-status="passed".

Chrome is located via CHROME_BIN or standard macOS/Linux install paths.
No third-party packages are required.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 4175
RUNNER = "/tests/run.html"
PREFLIGHT = ["/docs/index.html", "/docs/map.js", "/docs/icons/n8n.svg", "/tests/run.html"]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib signature
        pass


def start_server(port: int = PORT) -> ThreadingHTTPServer:
    try:
        server = ThreadingHTTPServer((HOST, port), partial(QuietHandler, directory=str(ROOT)))
    except OSError as exc:
        raise SystemExit(
            f"Cannot bind http://{HOST}:{port} ({exc}). "
            "Stop the process using that port and rerun the browser tests."
        ) from exc
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="infra-map-http", daemon=True)
    thread.start()
    return server


def wait_for_server(port: int = PORT, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=1):
                return
        except OSError as exc:  # pragma: no cover - startup race
            last_error = exc
            time.sleep(0.05)
    raise SystemExit(f"HTTP server on {HOST}:{port} did not become ready: {last_error}")


def find_chrome() -> str:
    override = os.environ.get("CHROME_BIN")
    if override:
        path = Path(override)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise SystemExit(f"CHROME_BIN is set but not executable: {override}")
    candidates: list[str] = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        "/opt/google/chrome/chrome",
    ]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise SystemExit(
        "Chrome/Chromium not found. Set CHROME_BIN to a Chrome binary or install "
        "Google Chrome in a standard location."
    )


def preflight() -> None:
    for path in PREFLIGHT:
        url = f"http://{HOST}:{PORT}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status != 200:
                    raise SystemExit(f"preflight failed: {url} -> HTTP {response.status}")
        except urllib.error.URLError as exc:
            raise SystemExit(f"preflight failed: {url} -> {exc}") from exc


def chrome_command(chrome: str, profile: str, url: str) -> list[str]:
    command = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--metrics-recording-only",
        "--mute-audio",
        "--force-device-scale-factor=1",
        "--window-size=1600,1200",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=45000",
        "--dump-dom",
        url,
    ]
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        command.insert(1, "--no-sandbox")
    return command


def extract_status(dom: str) -> str | None:
    match = re.search(r"<pre[^>]*\bid=['\"]runner-output['\"][^>]*>", dom, re.I)
    if match:
        status = re.search(r"data-status=['\"]([^'\"]+)['\"]", match.group(0), re.I)
        if status:
            return status.group(1).lower()
    status = re.search(r"data-runner-status=['\"]([^'\"]+)['\"]", dom, re.I)
    return status.group(1).lower() if status else None


def extract_report(dom: str) -> str:
    match = re.search(r"<pre[^>]*\bid=['\"]runner-output['\"][^>]*>(.*?)</pre>", dom, re.S | re.I)
    if not match:
        return "(runner output element not found)"
    return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()


def main() -> int:
    chrome = find_chrome()
    server = start_server()
    profile = tempfile.mkdtemp(prefix="infra-map-chrome-")
    url = f"http://{HOST}:{PORT}{RUNNER}"
    try:
        wait_for_server()
        preflight()
        print(f"chrome:  {chrome}")
        print(f"profile: {profile}")
        print(f"server:  http://{HOST}:{PORT} (repo root: {ROOT})")
        print(f"runner:  {url}\n")
        command = chrome_command(chrome, profile, url)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        print("FAIL: Chrome did not finish within 180s", file=sys.stderr)
        return 1
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(profile, ignore_errors=True)

    dom = completed.stdout
    status = extract_status(dom)
    report = extract_report(dom)
    print(report)
    print(f"\ndump-dom bytes: {len(dom)}; chrome exit code: {completed.returncode}")
    sys.stdout.flush()

    if status != "passed":
        if status is None:
            print("FAIL: runner status attribute not found in dump-dom output", file=sys.stderr)
        else:
            print(f"FAIL: runner status is {status!r}, expected 'passed'", file=sys.stderr)
        stderr_tail = (completed.stderr or "").strip()
        if stderr_tail:
            print("\nchrome stderr (tail):\n" + stderr_tail[-4000:], file=sys.stderr)
        return 1

    if completed.returncode != 0:
        print(f"WARN: Chrome exited with code {completed.returncode} despite passed runner", file=sys.stderr)
    print("browser checks: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
