#!/usr/bin/env python3
"""Static regression checks for the infra-map v6.2 artifact.

Stdlib only. Parses docs/index.html, validates the DOM contract, local assets,
meta URLs, security-sensitive constructs, and scans the published text for
forbidden infrastructure data and em dashes. Exits 1 on any failed check.
"""

from __future__ import annotations

import re
import struct
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
MAP_JS = DOCS / "map.js"
README = ROOT / "README.md"

EXPECTED_STATIONS = [
    ("sources", "data", 1),
    ("n8n", "data", 2),
    ("openwebui", "data", 3),
    ("qdrant", "data", 4),
    ("records", "data", 5),
    ("human", "agency", 1),
    ("opencode", "agency", 2),
    ("mcp", "agency", 3),
    ("decisions", "agency", 4),
    ("outcomes", "agency", 5),
    ("network", "trust", 1),
    ("caddy", "trust", 2),
    ("infisical", "trust", 3),
    ("recovery", "trust", 4),
    ("observability", "trust", 5),
    ("models", "external", 1),
]

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

RESOURCE_TAGS = {"script", "img", "iframe", "source", "audio", "video", "embed", "object"}


class StationCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.start_tags: list[tuple[str, dict[str, str]]] = []
        self.ids: list[str] = []
        self.id_refs: list[tuple[str, str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.buttons: list[dict[str, str]] = []
        self.stations: list[dict] = []
        self.inline_scripts: list[str] = []
        self.style_chunks: list[str] = []
        self.tag_counts: Counter[str] = Counter()
        self._station: dict | None = None
        self._title_open = False
        self._in_style = False
        self._inline_script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v if v is not None else "") for k, v in attrs}
        self.tag_counts[tag] += 1
        self.start_tags.append((tag, a))

        if "id" in a:
            self.ids.append(a["id"])
        for ref_attr in ("aria-labelledby", "aria-describedby", "aria-controls"):
            if a.get(ref_attr):
                self.id_refs.extend((tag, ref_attr, ref) for ref in a[ref_attr].split())

        if tag == "a":
            self.anchors.append(a)
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        elif tag == "button":
            self.buttons.append(a)
            if "station" in a.get("class", "").split():
                self._station = {"attrs": a, "imgs": [], "monograms": 0, "title": ""}
        elif tag == "script":
            self.scripts.append(a)
            if "src" not in a:
                self._inline_script = []
        elif tag == "style":
            self._in_style = True

        if self._station is not None:
            if tag == "img":
                self._station["imgs"].append(a)
            elif tag == "span" and "monogram" in a.get("class", "").split():
                self._station["monograms"] += 1
            elif tag == "strong" and not self._title_open:
                self._title_open = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
        elif tag == "script":
            if self._inline_script is not None:
                self.inline_scripts.append("".join(self._inline_script))
                self._inline_script = None
        elif tag == "strong":
            self._title_open = False
        elif tag == "button" and self._station is not None:
            self.stations.append(self._station)
            self._station = None

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.style_chunks.append(data)
        if self._inline_script is not None:
            self._inline_script.append(data)
        if self._title_open and self._station is not None:
            self._station["title"] += data

    @property
    def css(self) -> str:
        return "".join(self.style_chunks)


class Checker:
    def __init__(self) -> None:
        self.passed = 0
        self.failures: list[tuple[str, str]] = []
        self.warnings: list[str] = []

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


def css_rule(css: str, selector: str) -> str:
    match = re.search(
        r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}",
        css,
    )
    expect(match is not None, f"missing CSS rule for {selector}")
    return match.group(1)


def css_number(rule: str, prop: str) -> float:
    match = re.search(rf"(?<![\w-]){re.escape(prop)}\s*:\s*(-?\d+(?:\.\d+)?)", rule)
    expect(match is not None, f"missing numeric CSS property {prop}")
    return float(match.group(1))


def braced_block(text: str, marker: str) -> str:
    """Return the contents of the first {...} block following marker."""
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


def parse_png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    expect(data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def main() -> int:
    checker = Checker()

    for path in (INDEX, MAP_JS, DOCS / "social-preview.png", DOCS / "robots.txt", DOCS / ".nojekyll"):
        expect(path.is_file(), f"missing artifact file: {path.relative_to(ROOT)}")

    raw_html = INDEX.read_text(encoding="utf-8")
    raw_js = MAP_JS.read_text(encoding="utf-8")
    raw_readme = README.read_text(encoding="utf-8") if README.is_file() else ""

    parser = StationCollector()
    parser.feed(raw_html)
    css = parser.css

    meta_by_key: dict[str, str] = {}
    for meta in parser.metas:
        key = meta.get("property") or meta.get("name")
        if key:
            meta_by_key.setdefault(key, meta.get("content", ""))

    links_by_rel: dict[str, list[str]] = {}
    for link in parser.links:
        for rel in link.get("rel", "").split():
            links_by_rel.setdefault(rel, []).append(link.get("href", ""))

    # ---------------------------------------------------------------- shell
    def artifact_files() -> None:
        expect((DOCS / "index.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>"),
               "index.html must start with <!DOCTYPE html>")
        expect((DOCS / ".nojekyll").stat().st_size == 0, ".nojekyll must be empty")
        robots = (DOCS / "robots.txt").read_text(encoding="utf-8").strip().splitlines()
        expect(any(line.strip().lower() == "user-agent: *" for line in robots),
               "robots.txt must allow crawling with User-agent: *")
        expect(any(line.strip().lower() == "allow: /" for line in robots),
               "robots.txt must contain Allow: /")

    checker.check("artifact files and hosting markers exist", artifact_files)

    def document_shell() -> None:
        expect(parser.tag_counts["html"] == 1, "exactly one <html> root")
        expect(parser.tag_counts["body"] == 1, "exactly one <body>")
        expect(parser.tag_counts["main"] == 1, "exactly one <main>")
        expect(parser.tag_counts["header"] >= 1, "header landmark missing")
        expect(parser.tag_counts["footer"] >= 1, "footer landmark missing")
        expect(parser.tag_counts["h1"] == 1, f"expected one h1, got {parser.tag_counts['h1']}")
        expect(parser.tag_counts["h2"] >= 4, "expected at least four section h2 elements")
        expect('lang="en"' in raw_html, "html lang must be en")
        expect('<meta charset="utf-8">' in raw_html, "charset must be utf-8")
        expect(meta_by_key.get("viewport") == "width=device-width, initial-scale=1",
               "viewport meta missing or changed")
        expect(meta_by_key.get("color-scheme") == "light", "color-scheme meta missing")
        expect(len(meta_by_key.get("description", "")) >= 80, "meta description too short")
        title = re.search(r"<title>(.*?)</title>", raw_html, re.S)
        expect(title is not None and title.group(1).strip(), "title element missing")
        expect("No tracking" not in raw_html or "No tracking / no external runtime dependencies" in raw_html,
               "tracking disclaimer mismatch")

    checker.check("document shell, landmarks and metadata", document_shell)

    def unique_ids() -> None:
        duplicates = [key for key, count in Counter(parser.ids).items() if count > 1]
        expect(not duplicates, f"duplicate ids: {duplicates}")
        expect(len(parser.ids) >= 25, f"unexpectedly few ids: {len(parser.ids)}")

    checker.check("all element ids are unique", unique_ids)

    def references_resolve() -> None:
        ids = set(parser.ids)
        missing_refs = [(tag, attr, ref) for tag, attr, ref in parser.id_refs if ref not in ids]
        expect(not missing_refs, f"unresolved ARIA id references: {missing_refs}")
        missing_anchors = [
            a.get("href", "") for a in parser.anchors
            if a.get("href", "").startswith("#") and len(a.get("href", "")) > 1
            and a.get("href", "")[1:] not in ids
        ]
        expect(not missing_anchors, f"anchor targets missing: {missing_anchors}")

    checker.check("anchor and ARIA references resolve to existing ids", references_resolve)

    def script_contract() -> None:
        expect(len(parser.scripts) == 1, f"expected exactly one script tag, got {len(parser.scripts)}")
        expect(parser.scripts[0].get("src") == "map.js", "the only script must be the local map.js")
        expect(not parser.inline_scripts, "inline scripts are not allowed")
        expect(parser.tag_counts["iframe"] == 0, "product page must not embed iframes")
        expect(parser.tag_counts["base"] == 0, "<base> is not allowed")
        expect("http-equiv=\"refresh\"" not in raw_html.lower(), "meta refresh is not allowed")

    checker.check("single local script, no inline code or iframes", script_contract)

    def external_resources() -> None:
        external: list[str] = []
        for tag, attrs in parser.start_tags:
            candidates: list[str] = []
            if tag in RESOURCE_TAGS and attrs.get("src"):
                candidates.append(attrs["src"])
            if tag == "link" and attrs.get("href"):
                rel = attrs.get("rel", "")
                if any(word in rel for word in ("stylesheet", "icon", "preload", "prefetch", "modulepreload")):
                    candidates.append(attrs["href"])
            if tag == "object" and attrs.get("data"):
                candidates.append(attrs["data"])
            for value in candidates:
                if value.startswith(("http://", "https://", "//")):
                    external.append(f"{tag}:{value}")
        expect(not external, f"external runtime resources found: {external}")
        expect("@import" not in css, "CSS @import is not allowed")
        url_refs = re.findall(r"url\(\s*['\"]?([^'\")]+)", css)
        expect(all(ref.startswith(("data:", "#")) for ref in url_refs),
               f"non-local CSS url() resources: {[r for r in url_refs if not r.startswith(('data:', '#'))]}")
        for tag, attrs in parser.start_tags:
            if "style" in attrs and "url(" in attrs["style"]:
                refs = re.findall(r"url\(\s*['\"]?([^'\")]+)", attrs["style"])
                expect(all(r.startswith(("data:", "#")) for r in refs),
                       f"non-local inline style url(): {refs}")

    checker.check("no external runtime resources or remote CSS", external_resources)

    def local_assets() -> None:
        local_refs: list[str] = []
        for tag, attrs in parser.start_tags:
            if tag in RESOURCE_TAGS and attrs.get("src"):
                local_refs.append(attrs["src"])
            if tag == "link" and attrs.get("href"):
                if any(word in attrs.get("rel", "") for word in ("stylesheet", "icon", "preload")):
                    local_refs.append(attrs["href"])
        for href in local_refs:
            if href.startswith(("data:", "http://", "https://", "//", "#")):
                continue
            target = (DOCS / href.split("?", 1)[0].split("#", 1)[0]).resolve()
            expect(target.is_relative_to(DOCS.resolve()), f"asset escapes docs/: {href}")
            expect(target.is_file(), f"referenced asset missing: {href}")
        expect((DOCS / "icons").is_dir(), "docs/icons directory missing")

    checker.check("all referenced local assets exist inside docs", local_assets)

    def meta_urls() -> None:
        canonical_list = links_by_rel.get("canonical", [])
        expect(len(canonical_list) == 1, "expected exactly one canonical link")
        canonical = canonical_list[0]
        expect(canonical.startswith("https://"), f"canonical must be https: {canonical}")
        canonical_url = urlparse(canonical)
        expect(canonical_url.query == "" and canonical_url.fragment == "", "canonical must be a clean URL")

        expect(meta_by_key.get("og:type") == "website", "og:type must be website")
        expect(meta_by_key.get("og:title"), "og:title missing")
        expect(len(meta_by_key.get("og:description", "")) >= 60, "og:description too short")
        expect(meta_by_key.get("og:url") == canonical, "og:url must equal canonical")
        og_image = meta_by_key.get("og:image", "")
        expect(og_image.startswith("https://"), f"og:image must be absolute https: {og_image}")
        image_url = urlparse(og_image)
        expect(image_url.netloc == canonical_url.netloc, "og:image host must match canonical host")
        expect(image_url.path.startswith(canonical_url.path), "og:image must live under the canonical path")
        expect(meta_by_key.get("twitter:card") == "summary_large_image", "twitter card must be summary_large_image")
        expect(meta_by_key.get("og:image:alt"), "og:image:alt missing")

        image_file = DOCS / Path(image_url.path).name
        expect(image_file.is_file(), f"og:image local file missing: {image_file.name}")
        width, height = parse_png_size(image_file)
        expect(str(width) == meta_by_key.get("og:image:width"),
               f"og:image:width mismatch: declared {meta_by_key.get('og:image:width')}, file {width}")
        expect(str(height) == meta_by_key.get("og:image:height"),
               f"og:image:height mismatch: declared {meta_by_key.get('og:image:height')}, file {height}")

        live = re.search(r"\*\*Live:\*\*\s*(https://\S+)", raw_readme)
        if live:
            live_path = urlparse(live.group(1)).path
            if live_path.rstrip("/") != canonical_url.path.rstrip("/"):
                checker.warnings.append(
                    f"README live URL path {live_path} differs from canonical/og:url path "
                    f"{canonical_url.path}; verify the deployed GitHub Pages path"
                )
    checker.check("canonical, OpenGraph and Twitter meta URLs are consistent", meta_urls)

    def security_scan() -> None:
        bad_handlers = [(tag, name) for tag, attrs in parser.start_tags for name in attrs if name.lower().startswith("on")]
        expect(not bad_handlers, f"inline event handlers are forbidden: {bad_handlers}")
        javascript_urls = [a.get("href") for a in parser.anchors if a.get("href", "").lower().startswith("javascript:")]
        expect(not javascript_urls, f"javascript: URLs are forbidden: {javascript_urls}")
        blank = [a for a in parser.anchors if a.get("target") == "_blank"]
        for anchor in blank:
            expect("noopener" in anchor.get("rel", ""), f"target=_blank without rel=noopener: {anchor.get('href')}")
        forbidden_js = [
            "eval(", "new Function", "innerHTML", "outerHTML", "insertAdjacentHTML",
            "document.write", "fetch(", "XMLHttpRequest", "WebSocket(", "localStorage",
            "sessionStorage", "document.cookie", "http://", "https://",
        ]
        hits = [token for token in forbidden_js if token in raw_js]
        expect(not hits, f"map.js contains network/dynamic-code primitives: {hits}")
        expect(parser.tag_counts["form"] == 0, "unexpected form element")
        expect(parser.tag_counts["object"] == 0, "unexpected object element")
        expect(parser.tag_counts["embed"] == 0, "unexpected embed element")

    checker.check("no inline handlers, javascript: URLs or dynamic-code primitives", security_scan)

    # ------------------------------------------------------------- inventory
    def station_inventory() -> None:
        expect(len(parser.stations) == 16, f"expected 16 stations, found {len(parser.stations)}")
        actual = [
            (station["attrs"].get("data-station"), station["attrs"].get("data-line"),
             int(station["attrs"].get("data-position", "0")))
            for station in parser.stations
        ]
        expect(actual == EXPECTED_STATIONS,
               f"station inventory/order mismatch:\nactual   {actual}\nexpected {EXPECTED_STATIONS}")

        for station in parser.stations:
            attrs = station["attrs"]
            name = attrs.get("data-station", "?")
            expect(attrs.get("type") == "button", f"{name}: station must be type=button")
            expect(attrs.get("aria-pressed") == "false", f"{name}: initial aria-pressed must be false")
            expect(station["title"].strip(), f"{name}: visible <strong> label missing")
            expect(attrs.get("data-detail", "").strip(), f"{name}: data-detail missing")
            expect(len(attrs.get("data-description", "")) >= 60, f"{name}: data-description too short")
            tools = [tool for tool in attrs.get("data-tools", "").split("|") if tool.strip()]
            expect(len(tools) >= 1, f"{name}: data-tools missing")
            expect(all(tool == tool.strip() for tool in tools), f"{name}: data-tools contains padding")
        titles = [station["title"].strip() for station in parser.stations]
        expect(len(set(titles)) == len(titles), f"duplicate station titles: {titles}")
        line_counts = Counter(station["attrs"].get("data-line") for station in parser.stations)
        expect(dict(line_counts) == {"data": 5, "agency": 5, "trust": 5, "external": 1},
               f"line distribution changed: {dict(line_counts)}")

    checker.check("16 stations, unique ids, line distribution and positions", station_inventory)

    def station_tokens() -> None:
        icon_refs: list[str] = []
        image_stations = 0
        monogram_stations = 0
        for station in parser.stations:
            name = station["attrs"].get("data-station")
            images = station["imgs"]
            monograms = station["monograms"]
            expect(len(images) + monograms == 1,
                   f"{name}: expected exactly one token (image xor monogram), got {len(images)} img / {monograms} monogram")
            if images:
                image_stations += 1
                expect("alt" in images[0], f"{name}: token image must have an alt attribute")
                src = images[0].get("src", "")
                expect(src.startswith("icons/"), f"{name}: icon must be local under icons/: {src}")
                icon_refs.append(src)
            else:
                monogram_stations += 1
        expect(image_stations == 8 and monogram_stations == 8,
               f"expected 8 image tokens and 8 monograms, got {image_stations}/{monogram_stations}")
        expect(len(set(icon_refs)) == len(icon_refs), f"duplicate icon references: {icon_refs}")

        files = sorted(path.name for path in (DOCS / "icons").glob("*.svg"))
        referenced = sorted(Path(ref).name for ref in icon_refs)
        expect(referenced == files, f"icon files vs references mismatch: files={files} refs={referenced}")
        for path in (DOCS / "icons").glob("*.svg"):
            svg = path.read_text(encoding="utf-8")
            expect("<svg" in svg and "</svg>" in svg, f"{path.name}: not an SVG document")
            expect("<script" not in svg.lower(), f"{path.name}: embedded script")
            expect(not re.search(r'(?:xlink:)?href\s*=\s*["\']https?://', svg), f"{path.name}: external href")

    checker.check("station tokens, local SVG icons and alt attributes", station_tokens)

    def station_geometry() -> None:
        canvas_rule = css_rule(css, ".atlas-canvas")
        canvas_w = css_number(canvas_rule, "width")
        canvas_h = css_number(canvas_rule, "height")
        expect(canvas_w == 1200 and canvas_h == 640, f"canvas must stay 1200x640, got {canvas_w}x{canvas_h}")
        expect("overflow: hidden" in canvas_rule, "canvas must clip its contents")

        station_rule = css_rule(css, ".station")
        station_w = css_number(station_rule, "width")
        station_h = css_number(station_rule, "min-height")
        expect("translate(-50%, -50%)" in station_rule, "station must be centered on its --x/--y anchor")
        expect(station_w > 0 and station_h > 0, "station dimensions must be positive")

        for station in parser.stations:
            attrs = station["attrs"]
            name = attrs.get("data-station")
            style = attrs.get("style", "")
            x_match = re.search(r"--x\s*:\s*(-?\d+(?:\.\d+)?)px", style)
            y_match = re.search(r"--y\s*:\s*(-?\d+(?:\.\d+)?)px", style)
            expect(x_match is not None and y_match is not None, f"{name}: --x/--y missing")
            x, y = float(x_match.group(1)), float(y_match.group(1))
            expect(x - station_w / 2 >= -0.5 and x + station_w / 2 <= canvas_w + 0.5,
                   f"{name}: horizontal box {x - station_w / 2}..{x + station_w / 2} escapes canvas 0..{canvas_w}")
            expect(y - station_h / 2 >= -0.5 and y + station_h / 2 <= canvas_h + 0.5,
                   f"{name}: vertical box {y - station_h / 2}..{y + station_h / 2} escapes canvas 0..{canvas_h}")

    checker.check("station anchors keep every station box inside the 1200x640 canvas", station_geometry)

    def metro_paths() -> None:
        svg = re.search(r"<svg class=\"metro-svg\"[^>]*viewBox=\"([^\"]+)\"", raw_html)
        expect(svg is not None and svg.group(1) == "0 0 1200 640",
               f"metro SVG viewBox mismatch: {svg.group(1) if svg else 'missing'}")
        lines = re.findall(r'<path class="metro-line (line-(?:data|agency|trust))" d="([^"]+)"', raw_html)
        expect(len(lines) == 3, f"expected 3 metro lines, found {len(lines)}")
        expect(sorted(cls for cls, _ in lines) == ["line-agency", "line-data", "line-trust"],
               f"metro line classes: {lines}")
        for cls, path in lines:
            expect(re.fullmatch(r"M40 \d+ H1160", path), f"{cls}: line must span x=40..1160, got {path}")
        ys = sorted(int(re.search(r"M40 (\d+) H1160", path).group(1)) for _, path in lines)
        expect(ys == [170, 360, 550], f"metro line y positions changed: {ys}")

        transfers = re.findall(r'<path class="metro-transfer" d="([^"]+)"', raw_html)
        expect(sorted(transfers) == ["M390 170 V550", "M630 170 V550"],
               f"logical transfer paths changed: {transfers}")

        external = re.findall(r'<path class="metro-external" d="([^"]+)"', raw_html)
        expect(len(external) == 1, f"expected one external path, found {len(external)}")
        expect(external[0].startswith("M630 245") and external[0].endswith("1092 55"),
               f"external boundary path changed: {external[0]}")
        expect(parser.tag_counts["path"] == 6, f"expected 6 SVG paths, found {parser.tag_counts['path']}")

    checker.check("metro SVG geometry: three lines, two transfers, one external boundary", metro_paths)

    # --------------------------------------------------------------- behavior
    def default_state_contract() -> None:
        expect('id="detail-tools"' in raw_html and re.search(
            r'<div class="detail-tools" id="detail-tools"></div>', raw_html) is not None,
            "detail-tools must start empty for default meta chips")
        expect("Choose a station." in raw_html, "default detail title missing")
        expect("Interactive map guide" in raw_html, "default detail kicker missing")
        expect('id="detail-prev" type="button" disabled' in raw_html, "Previous must start disabled")
        expect('id="detail-next" type="button" disabled' in raw_html, "Next must start disabled")
        expect('id="atlas-reset" type="button" disabled' in raw_html, "Reset must start disabled")
        expect("All lines / select a station" in raw_html, "default status text missing")
        expect("defaultMeta" in raw_js, "map.js must expose defaultMeta")
        expect("stationTotal === 1 ? 'station' : 'stations'" in raw_js, "defaultMeta station pluralisation changed")
        expect("external === 1 ? 'boundary' : 'boundaries'" in raw_js,
               "defaultMeta external pluralisation changed")
        expect(parser.tag_counts["button"] == 19,
               f"expected 19 buttons (16 stations + reset + prev + next), got {parser.tag_counts['button']}")

    checker.check("initial UI state and default 3-line metadata contract", default_state_contract)

    def responsive_contract() -> None:
        viewport_rule = css_rule(css, ".atlas-viewport")
        expect("overflow-x: auto" in viewport_rule, "atlas viewport must scroll horizontally")
        hint = css_rule(css, ".map-pan-hint")
        expect("display: none" in hint, "pan hint must be hidden by default")
        expect("updatePanHint" in raw_js and "scrollWidth > viewport.clientWidth" in raw_js,
               "pan hint must be driven by measured overflow, not a viewport breakpoint")
        expect("ResizeObserver" in raw_js, "pan hint must react to viewport size changes")
        expect(re.search(r"\.atlas-shell\.has-focus \.station small \{ color: var\(--dark-text\)", css)
               is not None, "dimmed subtitles must use the high-contrast text token")
        for breakpoint in (1120, 860, 640):
            expect(re.search(rf"@media \(max-width: {breakpoint}px\)", css) is not None,
                   f"missing responsive breakpoint {breakpoint}px")
        expect(re.search(r"prefers-reduced-motion:\s*reduce", css) is not None,
               "missing prefers-reduced-motion handling")
        dim = re.search(r"\.atlas-shell\.has-focus \.station\s*\{[^}]*opacity:\s*(0?\.\d+|1)\s*;", css)
        expect(dim is not None, "missing dimmed-station opacity rule")
        expect(float(dim.group(1)) >= 0.55, f"dimmed opacity below 0.55: {dim.group(1)}")
        active = re.search(r"\.atlas-shell\.has-focus \.station\.is-active-line\s*\{[^}]*opacity:\s*1\s*;", css)
        expect(active is not None, "active-line stations must return to opacity 1")
        external = re.search(r'\.station\[data-line="external"\]\s*\{[^}]*border-style:\s*dashed', css)
        expect(external is not None, "external station must use a dashed border")

    checker.check("responsive pan hint, breakpoints and dimming contract", responsive_contract)

    def accessibility_contract() -> None:
        expect(parser.tag_counts["button"] == len(parser.buttons), "button parse mismatch")
        expect(all(button.get("type") == "button" for button in parser.buttons),
               "every button must declare type=button")
        expect(all("aria-pressed" in station["attrs"] for station in parser.stations),
               "every station needs aria-pressed")
        region = [attrs for tag, attrs in parser.start_tags
                  if attrs.get("role") == "region" and attrs.get("id") == "atlas-viewport"]
        expect(len(region) == 1, "atlas viewport must be a labelled region")
        expect(region[0].get("tabindex") == "0", "atlas viewport must be keyboard focusable")
        expect(region[0].get("aria-label"), "atlas viewport needs an aria-label")
        images = [attrs for tag, attrs in parser.start_tags if tag == "img"]
        expect(all("alt" in image for image in images), "every img needs an alt attribute")
        expect(any(attrs.get("aria-live") == "polite" for tag, attrs in parser.start_tags),
               "detail region needs aria-live=polite")
        skip_link = [a for a in parser.anchors if "skip" in a.get("class", "").split()]
        expect(len(skip_link) == 1, "skip link missing")
        expect(skip_link[0].get("href") == "#top", "skip link must target #top")
        expect('id="top"' in raw_html, "skip-link target #top missing")
        expect(re.search(r'<nav aria-label="[^"]+"', raw_html) is not None, "nav landmark needs a label")

    checker.check("keyboard, ARIA and landmark accessibility contract", accessibility_contract)

    # --------------------------------------------------------------- hygiene
    def em_dash_scan() -> None:
        text_files = [INDEX, MAP_JS, README, DOCS / "robots.txt", *sorted((DOCS / "icons").glob("*.svg"))]
        offenders = []
        for path in text_files:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            count = text.count("\u2014")
            if count:
                offenders.append(f"{path.relative_to(ROOT)}={count}")
        expect(not offenders, f"em dash (U+2014) found: {offenders}")

    checker.check("no em dash (U+2014) in published text", em_dash_scan)

    def forbidden_infra_data() -> None:
        patterns: list[tuple[str, re.Pattern[str]]] = [
            ("private IPv4", re.compile(
                r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|"
                r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))(?:\.\d{1,3}){2}(?![\d.])")),
            ("loopback address", re.compile(r"\b127\.0\.0\.1\b")),
            ("localhost", re.compile(r"\blocalhost\b", re.I)),
            ("private hostname suffix", re.compile(r"\.(?:local|lan|internal|home\.arpa|ts\.net)\b", re.I)),
            ("host and port", re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}:\d{2,5}\b", re.I)),
            ("MAC address", re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.I)),
            ("IPv6 address", re.compile(r"\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b", re.I)),
            ("absolute home path", re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")),
            ("ssh-like command", re.compile(r"\b(?:ssh|scp|rsync)\s+-")),
            ("secret assignment", re.compile(
                r"(?i)\b(?:api[_-]?key|apikey|password|passwd|client[_-]?secret|access[_-]?token)\b"
                r"\s*[:=]\s*[^\s<]+")),
            ("bearer token", re.compile(r"(?i)\bbearer\s+[a-z0-9._-]{8,}")),
            ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        ]
        scanned = [INDEX, MAP_JS, DOCS / "robots.txt", *sorted((DOCS / "icons").glob("*.svg"))]
        findings: list[str] = []
        for path in scanned:
            text = path.read_text(encoding="utf-8", errors="replace")
            for label, pattern in patterns:
                for match in pattern.finditer(text):
                    findings.append(f"{path.relative_to(ROOT)}: {label} -> {match.group(0)!r}")
        expect(not findings, "forbidden infrastructure data:\n  " + "\n  ".join(findings[:12]))

    checker.check("no addresses, hostnames, ports, credentials or codenames in docs", forbidden_infra_data)

    def local_sensitive_scan() -> None:
        blocklist = ROOT / "tests" / "local_blocklist.txt"
        if not blocklist.is_file():
            return
        terms = [line.strip() for line in blocklist.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not terms:
            return
        text_files = [
            INDEX, MAP_JS, README, ROOT / "QA.md", ROOT / "THIRD_PARTY_NOTICES.md", ROOT / "package.json",
            *sorted((ROOT / "tests").glob("*.py")), *sorted((ROOT / "tests").glob("*.html")),
        ]
        findings = []
        for path in text_files:
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(re.search(rf"\b{re.escape(term)}\b", text, re.I) for term in terms):
                findings.append(str(path.relative_to(ROOT)))
        expect(not findings, f"local sensitive literals found in public files: {sorted(set(findings))}")

    checker.check("no local sensitive literals in public files", local_sensitive_scan)

    def tracking_scan() -> None:
        needles = [
            "gtag(", "googletagmanager", "google-analytics", "analytics.js", "plausible",
            "umami", "matomo", "hotjar", "connect.facebook", "doubleclick", "mixpanel",
            "segment.com", "clarity.ms",
        ]
        hits = [needle for needle in needles if needle in raw_html.lower()]
        expect(not hits, f"tracking/analytics references found: {hits}")
        expect(not re.search(r"<iframe", raw_html, re.I), "iframes are not allowed in the product page")

    checker.check("no trackers, analytics or third-party embeds", tracking_scan)

    def release_metadata() -> None:
        expect("Version: v6.2" in raw_html, "footer version must be v6.2")
        expect('datetime="2026-10-25"' in raw_html, "review date meta missing")
        expect("Reviewed:" in raw_html, "review label missing")
        expect("infra-map-public/blob/main/QA.md" in raw_html, "QA.md link missing")
        expect("No tracking / no external runtime dependencies" in raw_html,
               "runtime dependency disclaimer missing")

    checker.check("release metadata matches v6.2", release_metadata)

    def no_leaky_artifacts() -> None:
        forbidden_suffixes = {".map", ".env", ".pem", ".key", ".p12", ".pfx", ".bak", ".log", ".sql", ".sqlite"}
        forbidden_names = {"id_rsa", "id_ed25519", ".DS_Store", "package.json", "package-lock.json"}
        found = []
        for path in DOCS.rglob("*"):
            if path.is_dir():
                continue
            if path.suffix.lower() in forbidden_suffixes or path.name in forbidden_names:
                found.append(str(path.relative_to(ROOT)))
        expect(not found, f"unexpected files in published artifact: {found}")
        expect("node_modules" not in [p.name for p in DOCS.iterdir()], "node_modules leaked into docs")

    checker.check("no source maps, secrets, logs or build residue in docs", no_leaky_artifacts)

    def print_contract() -> None:
        print_css = braced_block(css, "@media print")
        canvas = re.search(r"\.atlas-canvas\s*\{([^}]*)\}", print_css)
        expect(canvas is not None, "print CSS must style .atlas-canvas")
        expect(re.search(r"transform:\s*scale\(\s*(?:\.8|0\.8)\s*\)", canvas.group(1)) is not None,
               "print CSS must scale the canvas with transform: scale(.8)")
        expect("transform-origin: top left" in canvas.group(1),
               "print canvas transform must anchor at top left")
        expect(not re.search(r"(?<![\w-])zoom\s*:", print_css),
               "print CSS must not use zoom")
        expect("zoom" not in print_css, "print CSS must not contain the zoom keyword")

        viewport = re.search(r"\.atlas-viewport\s*\{([^}]*)\}", print_css)
        expect(viewport is not None, "print CSS must style .atlas-viewport")
        expect("overflow: visible" in viewport.group(1), "print viewport must not clip the scaled canvas")
        expect(re.search(r"height:\s*512px", viewport.group(1)) is not None,
               "print viewport height must match 640 * 0.8")

        station = re.search(r"\.station\s*\{([^}]*)\}", print_css)
        expect(station is not None, "print CSS must style .station")
        expect(re.search(r"opacity:\s*1\s*!important", station.group(1)) is not None,
               "print stations must be fully opaque")
        expect(re.search(r"@page\s*\{[^}]*size:\s*A4 landscape", css) is not None,
               "print page must be A4 landscape")
        expect(re.search(r"@page\s*\{[^}]*margin:\s*10mm", css) is not None,
               "print page margin must be 10mm")

    checker.check("print CSS uses transform scale(.8), not zoom", print_contract)

    def third_party_contract() -> None:
        notices_path = ROOT / "THIRD_PARTY_NOTICES.md"
        expect(notices_path.is_file(), "THIRD_PARTY_NOTICES.md missing from repo root")
        notices = notices_path.read_text(encoding="utf-8")
        expect("16.35.0" in notices, "Simple Icons version must be pinned to 16.35.0")
        expect("CC0 1.0" in notices, "Simple Icons license reference missing")
        expect("simple-icons/simple-icons" in notices, "Simple Icons upstream reference missing")
        for icon in sorted(path.name for path in (DOCS / "icons").glob("*.svg")):
            expect(f"`{icon}`" in notices, f"THIRD_PARTY_NOTICES.md must list {icon}")
        expect("16.35.0" in raw_readme, "README must pin the vendored icon version")

    checker.check("third-party icon provenance is pinned to Simple Icons 16.35.0", third_party_contract)

    def readme_contract() -> None:
        expect("16 interactive stations" in raw_readme, "README must document 16 stations")
        expect("python3 -m http.server 4174 --directory docs" in raw_readme,
               "README local preview command changed")
        expect("no external runtime dependencies" in raw_readme.lower(),
               "README dependency claim changed")
        expect("**Live:** https://" in raw_readme, "README live URL missing")

    checker.check("README contract matches the artifact", readme_contract)

    # ---------------------------------------------------------------- summary
    for warning in checker.warnings:
        print(f"[WARN] {warning}")
    print(f"\nstatic checks: {checker.passed} passed, {len(checker.failures)} failed")
    if checker.failures:
        for name, detail in checker.failures:
            print(f"  FAILED {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
