# HB-202: the disk measured, this project's finished scratch removed, then the gate

Tool: `tools/disk_survey.py` (`survey`, `candidates`, `remove`), run with `/opt/anaconda3/bin/python` (seldon's
interpreter) from the repository root. Sizes are size on disk (`du -sk`). Free bytes and the dispatcher's need are
seldon's own `free_bytes` and `tree_bytes(main) x 2`, as HB-198's `disk.py` reads them.

Files: `disk_before.tsv`, `candidates.tsv` (every entry and the rule's verdict on it), `removed.tsv` (each row written
and fsynced before its removal, then a second row with the outcome), `disk_after.tsv`.

## Part A: where the space was, what was removed, what is left

Three readings of free disk on `/System/Volumes/Data`, 2026-11-18:

| when | free bytes | what changed before it |
|---|---:|---|
| session's first survey, about 12:46 EST | 9,354,526,720 | nothing |
| `disk_before.tsv`, 12:52:50 EST | 26,686,898,176 | 16,713,465,856 bytes under `/private/tmp` removed **outside this session** (below) |
| `disk_after.tsv`, 12:56:20 EST | 33,882,288,128 | this session's 199 removals, 7,297,998,848 bytes |

The session's first survey was written to `disk_before.tsv` and then overwritten by the second when the tool was
corrected (it had counted Docker's directory handles as use; below). Its figures above and here are from that run's
printed output: `/private/tmp` held 24,842,653,696 bytes, among them `hb192_base` 2,747,936,768, `hb196_head`
2,550,841,344, `hb196_main` 2,550,464,512, `hb196_head.tar` 2,513,113,088, `hb196_main.tar` 2,512,793,600,
`hb186_red` 1,920,409,600 and `hb185_base` 1,917,906,944 (16,713,465,856 in all). By the second survey those seven
were gone and `/private/tmp` held 8,129,294,336; no dispatched session but this one was running (`ps`), so they were
removed by hand outside it. This session did not remove them and has no record of who did.

| place | before (second reading) | removed here | after | left for the operator |
|---|---:|---:|---:|---|
| `/private/tmp`, this project's completed tasks (`hb<n>`, nothing open) | 7,122,513,920 | 7,122,513,920 (188 entries) | 0 | — |
| `/private/tmp`, `hb<n>` files Docker's VM holds open (regular-file handles) | 61,739,008 | 0 | 61,739,008 | 110 small files; free once Docker Desktop restarts and they are deleted |
| `/private/tmp`, `hb158_base` and its log (HB-158's `serve.py`, pid 29898, 7 days, has its cwd there) | in the row above | 0 | listed | stop pid 29898, then the folder is removable |
| `/private/tmp`, the operator's own `hb190_dup_*` | 13,602,816 | 0 | 13,602,816 | never touched |
| `/private/tmp`, other projects (`sel*`, `sq*`, `arnold*`, ...: 96 entries) | 931,524,608 | 0 | 931,524,608 | `sel012` 504,938,496; `sq142_c3` 296,882,176; `sel040` 64,212,992 |
| pytest's temporary root, `$TMPDIR/pytest-of-brock` (11 run folders) | 175,484,928 | 175,484,928 | 0 | — |
| `$TMPDIR` (the user temporary root, pytest's parent), `hb*` entries | 33,183,080,448 | 0 | 33,183,080,448 | **the largest single holder**; see 1 below |
| `$TMPDIR`, `com.docker.install` (505 h old) | 2,335,080,448 | 0 | 2,335,080,448 | Docker's own installer scratch |
| uv's cache, `~/.cache/uv` | 10,251,935,744 | 0 | same | `uv cache prune` keeps what is in use |
| Docker's disk image `Docker.raw` | 20,043,325,440 allocated (63,999,836,160 apparent) | 0 | same | images 12.35 GB (3.607 GB reclaimable), build cache 6.033 GB (2.755 GB reclaimable), volumes 1.592 GB |
| worktree `.claude/worktrees/sunny-shimmying-pebble` | 1,041,813,504 | 0 | same | see 3 below |
| this repository's `logs/` | 672,833,536 | 0 | same | gitignored run logs |
| this repository's `.venv`, `.pytest_cache`, `.ruff_cache` | 201,850,880 | 0 | same | in use |

No orphaned pytest or headless Chrome process was running (parent pid 1), and no exited container was made from
this project's two images (`hazbrief-mcp`, `hazbrief-models`); the five exited containers are other projects'
(`docker ps -a` in `disk_before.tsv`). Nothing was ended.

**Docker's directory handles.** Docker Desktop's VM process (pid 63073) holds a read-only directory handle on
every directory under `/private/tmp` it has seen (9,663 of them, as many on HB-64's two-week-old scratch as on any
other) and 110 regular-file handles. The first candidate run counted the directory handles as use and found nothing
removable; the tool now ignores that process's directory handles only (they hold no file's bytes) and still counts
its file handles and every other process's (`open_paths` in the tool). A transient holder at the second run
(gone a minute later, unnamed then) is why the tool now names each holder in `candidates.tsv`.

### For the operator, with sizes (nothing below was touched)

Run in a Terminal, in this order if you want all of it; each line is independent.

1. **This project's finished scratch in `$TMPDIR`, 33.18 GB** (item 2's rule names `/private/tmp` only, so it was
   not applied here). Seven clones from HB-196, HB-197 and HB-201, all completed in the graph: `hb196_judge_*` (3 x
   5.15 GB), `hb197_clean_*` (5.06 GB), `hb201_clean_*` (2 x 5.06 GB), `hb201_copy_*` (2.55 GB); and 660 empty
   `hb16-*` folders `scripts/agent_eval.py` leaves (0 bytes):

   ```
   rm -rf "$TMPDIR"/hb196_judge_* "$TMPDIR"/hb197_clean_* "$TMPDIR"/hb201_clean_* "$TMPDIR"/hb201_copy_* "$TMPDIR"/hb16-*
   ```

2. **HB-158's evidence server**, 7 days old, holding `/private/tmp/hb158_base`: `kill 29898`
3. **The kept worktree `sunny-shimmying-pebble`, 1.04 GB**, branch `worktree-sunny-shimmying-pebble` at 4d97f03a.
   The dispatcher kept it on 2026-11-09 06:39Z for HB-140 (`worktree_kept`, outcome `session_failed`); HB-140 was
   withdrawn and its 20 events discarded on record the same day 17:57Z (`events_discarded`). In
   `/Users/brock/GitHub/hazbrief-mcp`:

   ```
   git worktree remove --force .claude/worktrees/sunny-shimmying-pebble
   git branch -D worktree-sunny-shimmying-pebble
   ```

4. **uv's cache, 10.25 GB:** `uv cache prune` (removes only entries no environment uses).
5. **Docker, not recommended before submission:** pruning the build cache (6.03 GB) or images makes the models image
   and the server image need the network to rebuild. `docker system df -v` is in `disk_after.tsv`.
6. **Other projects' `/private/tmp` scratch, 0.93 GB**, and `$TMPDIR/com.docker.install`, 2.34 GB: each owner's call.

## Part B: the gate, with the disk watched

**Before (item 4, `disk.txt`).** No iCloud placeholders under the linked corpus paths (`placeholders.txt`). The
dispatcher's need was 4,994,478,346 bytes (2 x the tree). ADDENDUM-01's threshold is the need plus the larger measured
draw: HB-197's RESULT records only its stop (4.07 GB free against 4.98 GB needed, the parallel step at 96 percent;
item 4 reads its draw as about 6 GB); HB-199 measured 9,451,827,200 bytes (`docs/evidence/hb199/gate_failure_1.txt`).
Threshold 14,446,305,546; free 33,835,036,672: started.

**What the gate draws (item 5).** Sampled every 60 s from the first minute (`tools/gate_disk.py` to
`gate_disk.tsv` and `gate2_disk.tsv`; `tools/gate_swap.py` to `gate_swap.tsv` and `gate2_swap.tsv`, started three
minutes into gate 1 when free bytes fell with no directory growing):

| | gate 1 (13:00 to 14:26) | gate 2 (14:31 to 15:45) |
|---|---:|---:|
| free at start | 33,822,867,456 | 32,263,987,200 |
| lowest free, and when | 25,739,071,488 at 14:04:59 (64 min in) | 23,670,824,960 at 14:32:04 (1 min in) |
| draw (start minus lowest) | 8,083,795,968 | 8,593,162,240 |
| swapfiles (1 GiB each, `/System/Volumes/VM`), start to peak | about 27 to 34 | 28 to 36 (in the first minute) |
| correlation of swapfile bytes with free bytes | -0.986 | -0.940 |
| pytest's temporary root, peak | 1,273,987,072 | 1,383,088,128 |
| new entries in `$TMPDIR` outside pytest's root, peak | 4,792,320 | 0 |
| `/private/tmp`, the worktree, Docker's image | flat (under 25 MB of change each) | flat |
| free at the end, after the workers exit | 32,285,454,336 | 30,436,864,000 |

**What it writes most of: no file.** The draw is swap. macOS keeps swap in 1 GiB files on the VM volume of the same
APFS container, so each new swapfile takes free space the dispatcher reads; the six workers' memory pushes the system
into new swapfiles (twice at once, as the workers collect about 8,000 tests: gate 2's whole draw came in its first
minute, as HB-199's did in its first six), and they are released when the workers exit. Files the gate writes peak at
1.27 to 1.38 GB under pytest's own root, of mixed kinds (git copies of the repository, Chrome profiles, staged
stores, `pytest-3` after gate 1 by folder: `test_start_changes_nothing_git0` 49 MB, `ibm_stage0` 16 MB, Chrome-page
folders 4 to 6 MB each), and pytest's three-folder rotation removes the oldest. Not one kind of file, so item 5's rule
holds: reported, nothing changed.

**Why the system swaps so much before the gate starts** (`memory_top.txt`, 13:06): 32 GiB of memory, about 28 GiB in
swap before either gate. `fseventsd` (pid 340, up 47 days) holds 22 GB, 20 GB of it compressed or swapped; Docker's
VM 3.4 GB plus 5.2 GB compressed; a second VM process (pid 48871, launched by launchd, 6 hours old) 2.9 GB plus 4.6
GB; Neo4j Desktop's Java 3.1 GB. This session did not end or restart any of them: they are not this project's.

**How much disk a gate needs.** The dispatcher stops a running gate when free bytes fall under its need (2 x the
tree, 4.99 GB here). Three measured draws: 8.08 GB (gate 1), 8.59 GB (gate 2), 9.45 GB (HB-199). A gate finishes
only if it starts with at least the need plus about 9.5 GB free, about 14.5 GB, while swap starts where it is now.
Swap released by `fseventsd` would lower the draw's starting point, not the draw itself.

### For the operator: swap (nothing done here)

7. **`fseventsd`'s 22 GB** is the largest single holder of swap. Restarting it, or the machine (up 47 days), returns
   most of the 28 to 30 GB of swapfiles to free space. A restart is the cleaner of the two; do it when no session or
   gate is running.

## Part B, items 6 and 7: the gate's results

Gate 1 (commit e6a7cb9b): parallel step 2 failed, 8056 passed; load_sensitive 85 passed; ruff 31 errors; format 5
files (`gate1_tail.txt`; `gate_failure_1.txt`, `gate_failure_2.txt`). All four failures were in what HB-198 and HB-199
added and reached main with no gate; each was fixed by its own route:

| failure | cause | fixed by |
|---|---|---|
| `test_hb178_material_keyed_and_off_pair.py::test_the_audit_re_derives_and_every_hit_has_a_verdict` | HB-199 reworded the TEVV T60 status line (`orchestrator.yaml:3230`, "On Jack Rabbit II Trial 7 ... names no engine"); HB-178's audit verdict A24 still matched the replaced words | A24's match, `says` and `now` follow HB-199's wording; `material_keyed_audit.tsv` re-derived by `the HB-178 evidence (held privately)` (one row) |
| `test_hb199_trial7.py::test_the_protocol_was_committed_before_every_record_and_not_changed_after` | the record names the protocol commit as it was on HB-199's branch (f132d716); the dispatcher's rebase landed it on main as 0a64ca63, same author date and the same 11-file change | the test joins the record to the protocol by author date, as HB-187's test has since HB-189, and where the branch's commit is still held, by `git patch-id` too |
| ruff check, 31 E501 | three HB-198 evidence tools | a file-level `# ruff: noqa: E501`, as HB-199's and HB-176's evidence tools carry |
| ruff format, 5 files | four HB-198 evidence tools and `gate_ledger.py (a build tool held privately)` | `ruff format` (layout only); `gate_ledger.py --check` still exits 0 |

Nothing under `src/` changed; no test was deleted, skipped or marked to fail, and no bound moved.

Gate 2 (commit 54c2491c): green, every step (`gate_tail.txt`), covering HB-197's, HB-198's and HB-199's merges.
