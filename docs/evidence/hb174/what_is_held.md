# HB-174 Part A: what is held of EPRI's SourceForge page, established from the bytes

Read on 2026-11-13 in the HB-174 worktree, against the primary checkout's gitignored `corpus/raw/` and
`corpus/inbox/` (the worktree links `corpus/raw`). The test that keeps it true is
`test_hb174_sourceforge_page_held.py (a test held privately)`.

## The answer

**The page was held all along, once, under the key `epri-dispersion-sourceforge`.** HB-69 fetched it through
`scripts/fetch_allowlisted.py` on 2026-10-29 and the build of release `hb01b_45` admitted it to the corpus graph.
HB-170's "not held" (`docs/evidence/hb170/unheld_sources.yaml`; DN-028 ADDENDUM-02 section 1 and row C29) was a miss:
HB-170 looked for the page as a citation of the search report and did not look up the key the NOTICE prints. No fetch
and no ingest was needed (task item 2).

## The five checks

| Check | Finding | How it was read |
|---|---|---|
| A `corpus/sources.yaml` row, under any key | One row, `epri-dispersion-sourceforge` (the HB-69 block), url `https://sourceforge.net/projects/epri-dispersion/`, `reuse: reference-only`. No other row names the url. | `grep -n "sourceforge.net/projects/epri-dispersion" corpus/sources.yaml` |
| The manifest and the graph's current release | Manifest entry `epri-dispersion-sourceforge`: `stage: in_graph`, `disposition: metadata_only` (`metadata_only_reason: no_open_access_text`: the bytes are held, the text is withheld as reference-only), `raw_sha256 99bfc48a…9d7d`, 82,114 bytes, `acquired_by: scripts/fetch_allowlisted.py`, `retrieved_at 2026-10-29T00:54:14Z`. The release export (`the corpus graph (held privately)`, built from the ledger through the latest sealed release `hb01b_61`) holds exactly one node for it, `Work::epri-dispersion-sourceforge`, `status: accepted`, asserted 2026-10-29T00:55:47Z. | `docs/sources/manifest.tsv`; the export's nodes; `ledger/index.json` |
| sha256 of `corpus/raw/epri-dispersion-sourceforge.html` against the NOTICE's | `99bfc48a93dbc9d6695947db21fde382f264398446fe2353e49c6bec1d2f9d7d`, equal to the NOTICE's, the manifest's and the fetch log's (`corpus/fetch_log.jsonl`, the `request` event of 2026-10-29T00:54:14Z). | `shasum -a 256` |
| The operator's markdown copy in `corpus/inbox` or `corpus/inbox/_processed/`, and `corpus/operator_downloads.jsonl` | **Not found.** No file in `corpus/inbox/` or the 50 files of `_processed/` is the page; the only one that mentions it is `ThursNov12PerplexitySearchReport.md` (held as `perplexity-report-dense-gas-and-occupancy-2026-11-12`), which cites it. `operator_downloads.jsonl` (160 lines) registers nothing for the page, and HB-170's inbox account (`the HB-170 evidence (held privately)`) has no row for it. Spotlight finds no file named for the page and none downloaded from its url. | `grep -r -l -i "sourceforge\|BSD License\|EPRI Air Dispersion" corpus/inbox/`; `mdfind` |
| The two lines the NOTICE quotes, verbatim, in the held bytes | **Both found.** `License BSD License` is the text of line 864, `<h3>License</h3>BSD License</section>` (the project-info panel), once its tags are read as spaces. `SCICHEM has been migrated to GitHub: https://github.com/epri-dev/SCICHEM/releases` is in the page's description (line 787, the link's text) and in its `description` and `og:description` meta tags (lines 118 and 133). | the test reads the held bytes with the tags replaced by spaces and the whitespace collapsed |

## Where the operator's copy went

No copy of the page from the operator is on this machine under `corpus/`. It is not needed: the bytes the operator
pointed to (`corpus/raw/epri-dispersion-sourceforge.html`) are the held work, fetched by the allowlisted fetcher and
admitted on 2026-10-29. Nothing was registered by this task and nothing was moved.

## What the other records said, and what HB-174 changes

| Record | Said | Now |
|---|---|---|
| `deploy/models/scichem/NOTICE` (HB-167) | held as `epri-dispersion-sourceforge`, sha256 `99bfc48a…`; "The request to EPRI to add the file is the operator's" | the holding stands (it was true); the request sentence is replaced: no request to EPRI is planned (Issue `4104d9fe`, won't fix); row C29's finding on the manuals is added |
| `docs/evidence/hb170/unheld_sources.yaml` | the page is not held | the entry is removed |
| DN-028 ADDENDUM-02, section 1 and row C29 | "that page is not held" | corrected by DN-028 ADDENDUM-05, with the key and the hash |
| `docs/evidence/hb170/citations_checked.tsv` row C29 (written by `the HB-170 evidence (held privately)`) | "the SourceForge page is not held" | left as HB-170's reading, as ADDENDUM-02 leaves the notes it corrects; ADDENDUM-05 is the correction |
| `docs/SECURITY.md` (SCICHEM's licence) | "the request to EPRI for a licence file is the operator's" | agrees with the NOTICE |

## The models image

The image copies the NOTICE to `/licenses/SCICHEM` (`deploy/models/Dockerfile`, after the engine's build stage). A
rebuild therefore gives the image a new id. Nothing pins the current image's id: every SCICHEM and SLAB run record
(`fixtures/evidence/scichem_runs/`, `scichem_lines/`, `slab_runs/`) states the id of the image that ran it
(`sha256:4ef57fa6…` for SCICHEM), and replay reads a record by its request's sha256, never by the image's id. The engine's
bytes do not change, so no record is re-recorded. The image test (`test_hb167_scichem_image.py (a test held privately)`,
`test_the_image_carries_the_notice`) builds its own tag and compares `/licenses/SCICHEM` with the NOTICE where Docker and
the fetched source are present.
