# HB-207 resume

Kept current through the session (task: "Write docs/evidence/hb207/resume.md first and keep it
current; commit after each item").

## State

- [x] A1 live run writes to an ignored path; kept fixtures copied in (6d7f316e)
- [x] A2 hosts.tsv
- [x] B3-B7 a common name resolves; confirmation; server lookup candidates (b418eff1)
- [x] C8-C11 storage state and quantity proposed; past time message (b418eff1)
- [x] D12-D14 errors on their section; working state; item 4 explained (7f9b7095)
- [x] E15-E18 suggested actions pack; decision support prompt; register; docs (7f9b7095, c50ac174)
- [x] F19-F25 live runs (docs/evidence/hb207/live/runs.tsv: ammonia run 3 and chlorine run 4 drew the cloud and
      Play stepped it; nitrogen and the no-material line in run 2); demo_lines.md; gate 3 green at 982ed509; verify;
      RESULT written. Not run here, by the session's instruction: `seldon cc complete` (the dispatcher completes).

## Notes

- A1 done (commit 6d7f316e): `entry.transcripts_dir` and `entry.fixtures_dir` are under `state/entry/`
  (ignored); committed transcripts are read from `entry.held_transcripts`. Kept: the "Liquid nitrogen"
  record (`fixtures/entry/entry-8f196dc3cd2f.json`, transcript `b2bade64...`) and one UN1005 record
  (`fixtures/entry/entry-76c25a2979a0.json`, transcript `b72f9393...`). The ammonia transcript
  (`116ff8ee...`) stays in the primary's ignored `the session state (held privately)`.
- A2 done: `hosts.tsv`. Four hosts the live path calls are off the Network line (3DEP, EPQS, the NLCD COG
  mirror, NLDI); none feeds the modelled cloud. No Google key is configured: no traffic layer can draw.
- B3 measured: the whole index is 2,767 rows, 237,835 JSON characters (about 59,000 tokens by chars/4, an
  estimate, not a metered count); a 25-row shortlist is a few hundred. Shortlist kept
  (`src/hazbrief/index_candidates.py`, entity-linking candidate generation, Shen, Wang and Han 2015).
  The chooser is a second recorded call (`prompts/entry_choose.md`), made only when the index does not
  print the typed name: the parse prompt is unchanged, so the 39 committed parse transcripts still replay.
- B7: the tool surface is frozen to 2026-11-20 (DN-009 section 2; pinned `fded04ec6c0e`), so the tool
  description is not changed; the not-found error carries `index_candidates` and its hint says so; the
  `assess_incident` module docstring records it.
- C8: ERG 2024 methodology Table 2.3 (gases, PDF p. 22, block 203) and Table 2.2 (liquids, PDF p. 21,
  block 198): rail 80,000 kg, highway 20,000 kg, each an example profile (UN 1749; UN 1244).
- C11: NWS gridpoint layers begin at the grid's `validTimes` start, not at now: 12:00Z for a 19:37Z read
  on 2026-11-19 (LWX/102,74). The form asks `nws.wind_at` for the start time; WindUnavailable is the
  one past-time message.

## Checkpoint plan: the recordings of HB-207's test lines (standards section 15)

- Unit: one model call (the parse, or the choice), keyed by sha256 of the request (prompt sha, entry,
  input) and the model (`ModelAuthor.key`); written atomically to its transcript file before the next
  call is made. Resume: re-run the same command; a held key is read, not called.
- Checkpoint files: `the HB-207 evidence (held privately)<key>.json`.
- Pilot: the first line alone, then the rest. Ceiling: `--max-calls` (12 for the test lines); the task's
  ceiling is 40 calls in all. A failed call is a transcript row with `ok: false`, retried up to
  `model.max_attempts`.
- Progress: one line per unit to stdout and `logs/hb207_record_lines.log`.

- Live run 1 (14:52 EST, ammonia, I-95) failed whole at 963.6 s on SLAB's unrecorded run (fixed, failures.tsv) and
  left three engine records in fixtures/evidence (fixed: brief/live_records.py). Run 2 started 15:13 EST on four
  ports (8791 to 8794; 8790 is held by an operator's served replay of un1005-i81 from the primary checkout, not
  stopped): `uv run python the HB-207 evidence (held privately) state/entry/live2`.
- Model calls: 12 of the 40 allowed (10 for the test lines, 2 for the ammonia demo line).
- Done 2026-11-19 20:20 EST. Model calls 12 of 40. Tokens 751,593 of 5,000,000 at Part F.
