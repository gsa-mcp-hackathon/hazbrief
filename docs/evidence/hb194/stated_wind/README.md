# HB-194 Part A item 3: the stated-wind test, diagnosed

Test: `test_hb139_weather_source.py (a test held privately)::test_a_stated_run_on_the_held_wind_draws_every_consumer_on_its_bearing`.

**What it is, in one sentence:** a bound missed under load, not a stated-wind run whose consumers read
another wind: both gate failures (HB-189 gate 2, HB-193 gate 2) stopped at the test's first check, that
every section rendered, before any bearing is read; a section fails to render only when one of its
channels ends other than `ok` inside its `timeout_s` (`src/hazbrief/brief/orchestrator.yaml`), and in 45
runs here every channel ended `ok`, every drawn consumer read the stated bearing, and the tightest channel
used a third of its budget alone and half of it at a load average of 9 to 13, so a heavier moment of
the gate's load runs it out; no Issue is filed, and the test is in the serial step with the rest.

## The runs

`tools/stated_wind_runs.sh` ran the test as its own pytest process, 20 times alone and then 20 times
with five brief-replay modules (`test_brief.py`, `test_hb130_event_stream.py`, `test_hb132_load_read.py`,
`test_brief_footprint_citation.py`, `test_hb173_two_engines.py`) each running in its own pytest
process beside it, restarted as each finished, from a minute before the first loaded run to the end of
the twentieth (`beside.txt`; `run_times.txt`). Five more alone runs (`margin_alone_runs.tsv`) measured
the channels' own times, which the dump kept from loaded run 13 on (`tools/hb194_brief_dump.py`, which
wraps the assembly and records each channel's state, reason, start and settle).

| Condition | Runs | Failed | Load average (1 min) | Tightest channel's own time (`assess_incident`, budget 15 s) |
|---|--:|--:|---|---|
| alone | 20 + 5 | 0 | 7 to 9 (the machine's other projects) | 4.03 to 4.59 s (the 5 margin runs) |
| beside five brief-replay modules | 20 | 0 | 8.7 to 13.2 (`load.tsv`) | 5.26 to 7.76 s (runs 13 to 20) |

`runs.tsv` has every run: its exit, seconds, the assembly's seconds, each section's state and the
channels not `ok` (none in any run). On a failure it would also carry the assertion line pytest printed
under `-vv`; there was none.

## Why this is load and not the one wind (HB-133)

- The failing assertion in both gates is `test_hb139_weather_source.py:312`,
  `all(state == "rendered" for state in s["sections"].values())`. The `-q` log cut the dict to
  `{'map': 'rendered', 'footprint': 'rendered', 'flags': 'rendered', 'population': 'rendered', ...}`,
  so the section not rendered is one of facilities (115 s budget), hospitals (30 s), guidance
  (`material_response_guidance` and `assess_incident`, 15 s each) or the ICS 201 (120 s). The two 15 s
  channels are the tightest budgets and feed the guidance section.
- A section that does not render is a channel that timed out, erred or found no record. The run is a
  replay of recorded exchanges, so an error or a missing record would recur on every run; the test
  passed on HB-193's `--lf` rerun (20.82 s; `docs/evidence/hb193/gate2_tail.txt`), in HB-189's next
  full gate (gate 3), and in all 45 runs here. A timeout is the one outcome that depends on the machine.
- The checks that a consumer reads the stated wind (`_assert_one_bearing`, the footprint's
  `direction_deg_from`, `wind_record.disagreements`) come after line 312. They passed in all 45 runs, and
  the failing gates never reached them.
- The tightest channel's own time rose from about 4 s alone to nearly 8 s beside five modules. The
  one-step gate ran six workers, a Chrome at a time, and docker runs of the models image beside these
  calls (HB-164 measured load averages of 9 to 15 at six workers; 40 to 53 at ten), so a moment twice as
  loaded as this condition runs it past 15 s.

The failure did not recur in 40 runs here; the classification rests on which assertion failed, the
replay's determinism, and the measured margin. The test is marked `load_sensitive` with the other
tests that start a server (it spawns the MCP server over stdio), so it runs in the serial step.
