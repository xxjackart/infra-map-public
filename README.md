# Private AI Infrastructure · system metro

An interactive, security-conscious capability map of a local-first AI platform: knowledge, agents, automation, operations and the engineering rules connecting them.

**Live:** https://xxjackart.github.io/infra-map-public/

**Version:** v6.2 · **Review:** 2026-10-25 · **Owner:** [xxjackart](https://github.com/xxjackart)

Static HTML + CSS + vanilla JS. No external runtime dependencies, tracking or build step.

## Explore the map

- **16 interactive stations**: 15 across DATA, AGENCY and TRUST, plus **1 external AI boundary**
- Station selection focuses the whole line and opens its role, tools and engineering rationale
- Previous and Next traverse the whole system without returning to the menu
- Deep links such as `#map-openwebui` share a specific station
- Logical transfers show only meaningful dependencies, never physical network routes
- External inference and document embeddings are explicit exceptions to local processing
- Small screens pan horizontally without shrinking labels; Reset restores both selection and pan

The map is a capability map for technical readers, not a C4 context or container diagram. Every station is a capability; product names identify implementations, not deployment boundaries. Station order guides reading, not execution.

## Public artifact

Only `docs/` belongs to the published site. The detailed LikeC4 development model is maintained outside this public repository and is not part of the artifact.

- `docs/index.html`: page, responsive and print styles, station definitions and accessible relationship text
- `docs/map.js`: UMD interaction module used by the browser and Node tests
- `docs/icons/`: local SVG brand icons, pinned to Simple Icons 16.35.0; monogram fallbacks are inline in the HTML
- `docs/social-preview.png`: current system metro sharing image
- `docs/robots.txt` and `docs/.nojekyll`: GitHub Pages support
- `tests/`: unit, static, print and real-browser regression harness
- `QA.md`: review evidence and release checklist
- `THIRD_PARTY_NOTICES.md`: icon provenance and licensing

GitHub Pages source: `main` branch, `/docs` folder. This public repository is a clean release mirror, not a dump of internal development history.

## Local preview

```bash
python3 -m http.server 4174 --directory docs
```

Open `http://127.0.0.1:4174/`.

## Regression tests

No installation or third-party packages are required.

```bash
npm test
```

The suite runs four levels:

1. **Unit:** Node's built-in test runner for station parsing, counts, navigation, prototype-key safety and metadata
2. **Static:** HTML, ARIA, local assets, geometry, metadata, security and content checks
3. **Print:** headless Chrome PDF generation, page geometry and readable print CSS
4. **Browser:** real Chrome interactions for clicks, Next/Previous, Reset, valid and invalid deep links, mobile pan and overflow

Individual commands:

```bash
npm run test:unit
npm run test:static
npm run test:print
npm run test:browser
```

Set `CHROME_BIN` if Chrome is not installed in a standard location.

## Changelog

### v6.2 · 2026-10-25

- Full standards audit remediation across UX, accessibility, C4 semantics, provenance, code quality and tests
- Readable focus contrast, persistent line identification and pan guidance on all overflowing viewports
- Explicit capability-map audience and semantics, accessible relationship text and print output
- Single source of truth for stations, derived counters and reset content, no duplicated station model
- Executable four-level regression suite and public QA evidence
- Pinned third-party icon provenance and refreshed social preview

### v6.1 · 2026-10-25

- First interactive system metro with 16 stations, local brand icons, detail panel and deep links

### v6.0 · 2026-10-25

- Editorial capability brief with isolated `docs/` artifact

## Security boundary

The public presentation intentionally includes tool names, responsibilities and architectural patterns only. It omits addresses, domains, hostnames, locations, ports, software versions, infrastructure usernames, exact data volumes, live health data and service-to-host mappings.

Recovery statements are operating requirements, not claims that every workload has a tested backup. The public GitHub author identity is intentional project identity, not an infrastructure credential or deployment identifier.

This is a capability map, not a network map.
