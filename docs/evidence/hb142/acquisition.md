# HB-142R: the acquisition list for the Desktop inbox

The allowlisted fetcher (`scripts/fetch_allowlisted.py`) was asked for both works below. It refused each at the
allowlist check, because this session's network is HB-142R's Network line alone (`SELDON_NETWORK_ALLOWLIST` =
api.census.gov, tigerweb.geo.census.gov, services.arcgis.com, healthdata.gov). Each refusal names rung 2, the
browser (`fetch.out`, `fetch_log.jsonl`). No browser tools are connected to this headless session, and the Spend line
allows no nested session, so rung 2 is the Desktop thread's. The drafted corpus rows are `deferred_corpus_rows.yaml`.
Issue `1613ac6c` carries both and the ingest that lands them.

| doc_id | Work | Rung-2 URL | Fetcher outcome | Drop the file in |
|---|---|---|---|---|
| `fgdc-hswg-point-symbology` | ANSI INCITS 415-2006, Homeland Security Mapping Standard: Point Symbology for Emergency Management (the FGDC Homeland Security Working Group symbol set: the symbol sheet and the symbol files) | https://www.fgdc.gov/HSWG/index.html | `blocked_host` (www.fgdc.gov), next rung browser | `corpus/inbox/` |
| `fhwa-mutcd-2009-chapter-6i` | FHWA, Manual on Uniform Traffic Control Devices, 2009 edition, Part 6, Chapter 6I, Control of Traffic Through Traffic Incident Management Areas | https://mutcd.fhwa.dot.gov/htm/2009/part6/part6i.htm | `blocked_host` (mutcd.fhwa.dot.gov), next rung browser | `corpus/inbox/` |

After the files are in `corpus/inbox/`, `scripts/register_inbox.py` registers them by content (DN-002 ADDENDUM-00).
The task that lands the symbol sheet:
- checks each `symbol` name in `src/hazbrief/brief/symbols.yaml` against the sheet;
- replaces the placeholder glyphs with the published symbols;
- sets `held: true` and each `verified: true`.

## Not acquisitions: the sources the RESULT names

These are recorded by Issues as sources that would be needed. None of them is an acquisition for this inbox yet:
- **Issue `a539174c`:** the National Structures Dataset stations need carto.nationalmap.gov on a recording task's
  Network line. That is an API call, not a document.
- **Issue `e5e32ff8`:** the trauma and burn-centre lists.
- **Issue `550a34b4`:** the 511 and NPMRDS feeds.
