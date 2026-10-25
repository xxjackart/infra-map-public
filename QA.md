# QA and sources

**Artifact:** Private AI Infrastructure, System Metro  
**Version:** v6.2  
**Review date:** 2026-10-25  
**Owner:** [xxjackart](https://github.com/xxjackart)  
**Audience:** technical readers evaluating architecture and engineering judgment

## Provenance model

- The published artifact is a capability map, not a C4 context or container diagram.
- Every station is a capability. Product names identify implementations, not deployment boundaries.
- Station order guides reading, not execution. Logical transfers are documented in visible station details and accessible relationship text.
- The detailed LikeC4 development model remains outside this public repository.
- This public repository is a clean release mirror. It is not a dump of internal development history.

## Reproducible verification

Run from the repository root:

```bash
npm test
```

Latest verified result: **80 checks passed, 0 failed**.

| Level | Command | Result | Evidence |
|---|---|---|---|
| Unit | `npm run test:unit` | 16/16 PASS | Station parser, counts, navigation, prototype-key safety, metadata and singular/plural forms |
| Static | `npm run test:static` | 25/25 PASS | HTML, ARIA, unique IDs, local assets, metadata, geometry, security, content and print contracts |
| Print | `npm run test:print` | 6/6 PASS | Valid PDF, 8 pages, A4 landscape, `transform: scale(.8)`, no `zoom`, plus selected-station subtitle coverage |
| Browser | `npm run test:browser` | 33/33 PASS | Real Chrome interactions, deep links, Reset, mobile pan, contrast, icons, overflow and measured pan hints |

No installation or third-party packages are required. Chrome is located through `CHROME_BIN` or standard macOS/Linux paths.

## Measured results

- Dimmed station text contrast: **minimum 5.50:1**, above WCAG AA 4.5:1, for both titles and subtitles
- Pan hint at 1240 px and 1280 px: visible because the canvas overflows
- Pan hint at 1281 px and 1440 px: hidden because the canvas fits
- Deep link `#map-openwebui`: station and tool chips remain correct
- Invalid hashes `#map-toString` and `#map-__proto__`: safe default state, no exception
- Mobile 390 px: selecting Observability pans to the station; Reset returns scroll to zero
- Icons: 8/8 local SVG files decoded; 8 monograms present
- External runtime resources: 0
- Print PDF: 8 pages, A4 landscape, readable dark-on-light content, including after station selection
- Local sensitive-literal guard: optional `tests/local_blocklist.txt` is gitignored and is never included in the public archive

## Review history

- Independent implementation review found and reproduced a deep-link metadata overwrite. Initialization order was corrected and a regression test was added.
- Additional review found subtitle contrast, breakpoint-specific pan hints, missing QA evidence and print coverage. These were corrected and covered by the expanded suite.
- Final independent release review: **PASS**, no remaining BLOCKER or MAJOR findings

## Security checklist

- [x] No addresses, domains, hostnames, physical locations, ports, software versions, infrastructure usernames, exact data volumes, live health data or service-to-host mappings in the current artifact
- [x] No third-party runtime scripts, fonts, trackers or analytics
- [x] External inference and document embeddings disclosed as explicit exceptions to local processing
- [x] Recovery statements describe operating requirements, not universal backup coverage
- [x] Third-party icons pinned to Simple Icons 16.35.0 with CC0 and trademark notes
- [x] Public repository contains only release artifacts and executable tests

## Release checklist

- [x] Reproducible test suite passes
- [x] Final independent release review
- [x] Local scoped commit
- [x] Previous public repository changed to private
- [ ] New public repository created from a fresh archive with exactly one commit
- [ ] GitHub Pages configured for `main /docs`
- [ ] Public URL, social image and `/model/infra.c4` = 404 verified
