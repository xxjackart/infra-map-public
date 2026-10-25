#!/usr/bin/env python3
"""Print regression checks for the infra-map v6.2 artifact.

Serves the repository root on 127.0.0.1:4176, prints /docs/index.html with real
headless Chrome (--print-to-pdf), validates the PDF structure and size, and
asserts the print stylesheet scales with transform, never with zoom.

Stdlib only. Chrome is located through CHROME_BIN or standard install paths
(shared with tests/run_browser_tests.py).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_browser_tests import find_chrome, start_server, wait_for_server  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 4176
URL = f"http://{HOST}:{PORT}/docs/index.html"
URL_SELECTED = f"{URL}#map-n8n"


class Checker:
    def __init__(self) -> None:
        self.passed = 0
        self.failures: list[tuple[str, str]] = []

    def check(self, name: str, fn) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - report any harness failure
            detail = str(exc) or exc.__class__.__name__
            self.failures.append((name, detail))
            print(f"[FAIL] {name} :: {detail}")
        else:
            self.passed += 1
            print(f"[PASS] {name}")


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def braced_block(text: str, marker: str) -> str:
    start = text.find(marker)
    expect(start >= 0, f"missing CSS block marker: {marker}")
    opening = text.find("{", start)
    expect(opening >= 0, f"missing opening brace after {marker}")
    depth = 0
    for index in range(opening, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index]
    raise AssertionError(f"unterminated CSS block for {marker}")


def fetch(path: str) -> bytes:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}{path}", timeout=10) as response:
            expect(response.status == 200, f"GET {path} -> HTTP {response.status}")
            return response.read()
    except urllib.error.URLError as exc:
        raise AssertionError(f"GET {path} failed: {exc}") from exc


def main() -> int:
    chrome = find_chrome()
    checker = Checker()
    server = start_server(PORT)
    workdir = Path(tempfile.mkdtemp(prefix="infra-map-print-"))
    profile = workdir / "profile"
    pdf = workdir / "infra-map.pdf"
    try:
        wait_for_server(PORT)
        preflight = fetch("/docs/index.html")
        expect(preflight, "empty /docs/index.html response")

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
            "--mute-audio",
            f"--user-data-dir={profile}",
            "--virtual-time-budget=15000",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf}",
            URL,
        ]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            command.insert(1, "--no-sandbox")
        print(f"chrome:  {chrome}")
        print(f"page:    {URL}")
        print(f"pdf:     {pdf}\n")
        completed = None
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT),
            )
        except subprocess.TimeoutExpired:
            completed = None

        html_text = preflight.decode("utf-8", errors="replace")
        data = pdf.read_bytes() if pdf.is_file() else b""

        def css_contract() -> None:
            print_css = braced_block(html_text, "@media print")
            canvas = re.search(r"\.atlas-canvas\s*\{([^}]*)\}", print_css)
            expect(canvas is not None, "print CSS must style .atlas-canvas")
            expect(re.search(r"transform:\s*scale\(\s*(?:\.8|0\.8)\s*\)", canvas.group(1)) is not None,
                   "print CSS must contain transform: scale(.8)")
            expect("transform-origin: top left" in canvas.group(1),
                   "print canvas transform must anchor at top left")
            expect(not re.search(r"(?<![\w-])zoom\s*:", print_css),
                   "print CSS must not declare zoom")
            expect("zoom" not in print_css, "print CSS must not contain the zoom keyword")
            viewport = re.search(r"\.atlas-viewport\s*\{([^}]*)\}", print_css)
            expect(viewport is not None, "print CSS must style .atlas-viewport")
            expect("overflow: visible" in viewport.group(1), "print viewport must not clip the scaled canvas")
            expect(re.search(r"height:\s*512px", viewport.group(1)) is not None,
                   "print viewport height must equal 640 * 0.8")
            station = re.search(r"\.station\s*\{([^}]*)\}", print_css)
            expect(station is not None, "print CSS must style .station")
            expect(re.search(r"opacity:\s*1\s*!important", station.group(1)) is not None,
                   "print stations must be fully opaque")
            expect(re.search(r"@page\s*\{[^}]*size:\s*A4 landscape", html_text) is not None,
                   "print page must be A4 landscape")
            expect(re.search(r"@page\s*\{[^}]*margin:\s*10mm", html_text) is not None,
                   "print page margin must be 10mm")
            expect(re.search(r"\.station-copy small \{ color: #333 !important; \}", print_css) is not None,
                   "print subtitle rule must override the dimmed-station selector")

        def pdf_exists() -> None:
            expect(pdf.is_file(), f"PDF file missing: {pdf}")
            expect(len(data) > 1000, f"PDF is too small: {len(data)} bytes")

        def pdf_valid() -> None:
            expect(data.startswith(b"%PDF-"), "PDF header missing")
            expect(re.search(rb"%PDF-1\.[4-7]", data[:16]) is not None,
                   f"unexpected PDF version: {data[:8]!r}")
            expect(b"%%EOF" in data[-2048:], "PDF trailer %%EOF missing")
            expect(re.search(rb"/Type\s*/Page(?!s)", data) is not None, "no page object in PDF")
            expect(re.search(rb"/Type\s*/Pages", data) is not None, "no pages tree in PDF")

        def pdf_geometry() -> None:
            page_count = len(re.findall(rb"/Type\s*/Page(?!s)", data))
            expect(page_count >= 1, f"expected at least one page, got {page_count}")
            media = re.search(
                rb"/MediaBox\s*\[\s*0(?:\.0+)?\s+0(?:\.0+)?\s+"
                rb"(842(?:\.\d+)?|841\.\d+)\s+(595(?:\.\d+)?|594\.\d+)\s*\]",
                data,
            )
            expect(media is not None, "PDF MediaBox is not A4 landscape (842 x 595 pt)")
            print(f"[INFO] PDF pages={page_count}, size={len(data)} bytes, MediaBox={media.group(0).decode('ascii')}")

        def chrome_invocation() -> None:
            expect(completed is not None, "Chrome print-to-pdf timed out after 120s")
            expect(completed.returncode == 0,
                   f"Chrome exited {completed.returncode}: {completed.stderr.strip()[-1500:]}")

        checker.check("Chrome print-to-pdf invocation succeeds", chrome_invocation)
        checker.check("print CSS uses transform: scale(.8) and no zoom", css_contract)
        checker.check("Chrome produced a non-empty PDF file", pdf_exists)
        checker.check("PDF header, trailer and page tree are valid", pdf_valid)
        checker.check("PDF is A4 landscape with at least one page", pdf_geometry)

        def selected_station_pdf() -> None:
            selected_pdf = workdir / "infra-map-selected.pdf"
            selected_command = command.copy()
            selected_command[command.index(URL)] = URL_SELECTED
            selected_command[command.index(f"--print-to-pdf={pdf}")] = f"--print-to-pdf={selected_pdf}"
            selected = subprocess.run(selected_command, capture_output=True, text=True, timeout=120, cwd=str(ROOT))
            expect(selected.returncode == 0, f"selected-station print failed: {selected.stderr.strip()[-800:]}")
            selected_data = selected_pdf.read_bytes() if selected_pdf.is_file() else b""
            expect(selected_data.startswith(b"%PDF-"), "selected-station PDF header missing")
            expect(len(selected_data) > 1000, "selected-station PDF is empty")
            expect(b"%%EOF" in selected_data[-2048:], "selected-station PDF trailer missing")
            print(f"[INFO] selected-station PDF size={len(selected_data)} bytes")

        checker.check("print after station selection preserves subtitle styling", selected_station_pdf)
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"\nprint checks: {checker.passed} passed, {len(checker.failures)} failed")
    if checker.failures:
        for name, detail in checker.failures:
            print(f"  FAILED {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
