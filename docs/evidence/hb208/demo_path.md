# HB-208 item 15: the demo path from the start page, as it worked live on 2026-11-19

The successor of `docs/evidence/hb207/demo_lines.md`. Driven in headless Chrome by
`the HB-208 evidence (held privately)` against the server `uv run hazbrief brief --serve` starts, run behind this
task's network gate (`the HB-208 evidence (held privately)`, the same `cli.main` on ports 8791 to 8794), one server
per run, each stopped when its run was done. Each run's record, timeline and screenshots are in
`docs/evidence/hb208/live/<run>/`; the three runs are `docs/evidence/hb208/live/runs.tsv`.

1. Start the server: `uv run hazbrief brief --serve`. It prints `serving the start page at http://127.0.0.1:8790/` and
   opens the page: "Enter a new incident" at the top, then the 22 prepared scenarios, each with its place, material
   (ERG name and ID number), container, the time its recorded run is for, and day or night.
2. A recorded run: on the row "State Line CDP, Franklin County, PA | Ammonia, anhydrous, UN1005", press "Open the
   recorded run". The brief replays in about 6 s under the banner "Replay of a brief recorded 11/13/2026; it makes no
   call to any source; every as-of is the recording's." Its page is the committed `docs/briefs/un1005-i81/brief.html`
   byte for byte. Play steps the cloud. Stop the server (Ctrl-C) and start it again for the next brief.
3. Today's conditions, nothing changed: first look at the wind. At 21:29 EST the forecast at Point of Rocks was calm
   (0 km/h), and a calm forecast draws no cloud by design (the page says "calm forecast: the puff needs a wind above
   0 m/s", Issue 473bdfeb). The I-83 point had 3.7 km/h from 250 degrees
   (`the HB-208 evidence (held privately)` prints the forecast wind now at each prepared point). On the row
   "York County, PA | Chlorine, UN1017 | Highway tank truck or trailer | 10/21/2026 14:00 EDT | day", press "Run it
   with today's conditions". The form opens filled: Chlorine, UN1017 (ERG Guide 124), already confirmed; the tank
   truck; leaking; 20,000 kg, the scenario's quantity; the start time now; weather forecast. Press "Build the brief".
   The first frame of the moving cloud is on the page at 136 s, the 24 frames to H+6 h by 198 s, and the last section
   at 802 s (13 min 22 s). Play steps H+15 min to H+1 h. The population, residential density and workplaces layers
   draw 160 census blocks each.
4. Today's conditions at another place: on the row "State Line CDP, Franklin County, PA | Ammonia, anhydrous,
   UN1005", press "Run it with today's conditions", then click the map at 39.3745, -76.4543 (I-95 at White Marsh,
   MD); the point line reads "Point 39.3745, -76.4543". Press "Build the brief". The brief is for the new point (its
   header reads 39.3745° N, 76.4543° W), wind from 250 degrees at 1.9 km/h. The first frame is on the page at 83 s,
   the 24 frames to H+6 h by 135 s, the last section at 848 s (14 min 8 s). The AEGL-3, -2 and -1 cloud is drawn
   (SCICHEM at the 1.25 m setting); Play steps H+15 min to H+1 h; the three block layers draw 38 census blocks each.
5. After each run, stop the server with Ctrl-C; check `docker ps` lists no `hazbrief-models` container (none was
   left after any run here).

What did not work, and how to avoid it in a demo: a calm forecast (0 km/h, as at Point of Rocks and the I-81 point at
21:29 EST) draws no cloud, by design. Before a live demo, run `uv run python the HB-208 evidence (held privately)`
and pick a row whose point has wind, or move the point (step 4), or choose `stated` under Weather source with a
direction, speed and basis.
