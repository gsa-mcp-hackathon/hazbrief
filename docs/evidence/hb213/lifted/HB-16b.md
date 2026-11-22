# HB-16b: lines lifted from its RESULT

Lifted by `lift_results.py (a build tool held privately)` (HB-213) from HB-16b's RESULT, which is held privately with
the rest of the working record. Each line below is quoted verbatim with its line number; it holds a number a
public document cites.

- line 3: **Task:** `HB-16b` (registered 17cc0b1e).
- line 11: The run measured **`5fa10642437f`** (`5fa10642437ffd9b2e0b7c57fad85a3d1362e302ff56ba31d4184a3d85586c60`),
- line 12: which is HB-18's. It differs from HB-16's `12a20a626237`. It is recorded in
- line 15: After this task's server fix (section 5), the surface is **`fded04ec6c0e`**
- line 16: (`fded04ec6c0e2ec2cc795a9aad679512c1c047b6ab5116390ebc90485ae4a350`), recorded in
- line 23: facts are every candidate and the governing distance, as the frozen form prints them. **32
- line 24: prompts** (18 scenario, 4 ambiguity, 5 out of scope, 5 adversarial).
- line 39: | episodes | 3 x 32 x 3 = **288**, against the task's ceiling 3 x 34 x 3 = 306 (`eval/harness.yaml` `ceilings.episodes: 306`) |
- line 40: | pilot | Opus, HB-16's five pilot prompts, one run: per episode 44,425 tokens, $0.192, 29 s. Projected 12.8 M tokens and $55.25 for 288 (Opus rates for all), 0.8 h. Logged before the rest ran. Cost ceiling $82.87 |
- line 41: | spend | **13,570,575 tokens, $21.06** as the CLI prices them (HB-16's matrix: $18.96). No ceiling crossed |
- line 42: | failures | 0. Two attempts retried, both "529 Overloaded" |
- line 43: | halt | one, at 108 of 288 (section 6, item 4); fixed test-first; the same command resumed |
- line 44: | traces | 33 MB, gitignored as HB-16's (`eval/agent_runs/*/claude-*/`); `traces_sha256.txt` committed, manifest sha256 `36e51a4a4a3cebfee2a6ff0c629851e0cf5f56918b366df5726601af46a80679` |
- line 57: | grounding, pooled | 93.5 to 93.8 | 95.9 to 95.8 | 97.1 to 97.2 |
- line 60: | out-of-scope refusal, strict | 26.7 to 13.3 | 33.3 to 26.7 | 46.7 to 33.3 |
- line 61: | out-of-scope refusal, lenient | 80.0 to 86.7 | 40.0 to 46.7 | 80.0 to 80.0 |
- line 62: | scenario pass | 93.8 to 93.8 | 75.0 to 79.2 | 58.3 to 79.2 |
- line 63: | ambiguity, restated rule | 0.0 to 41.7 | 16.7 to 33.3 | 8.3 to 41.7 |
- line 67: * all 32 prompts;
- line 93:   93.5 %; 93.8 % over the shared prompts).
- line 95:   * strict, **13.3 %** (2 of 15; HB-16: 26.7 %);
- line 96:   * declined the ask, general knowledge added, **86.7 %** (13 of 15; HB-16: 80.0 %).
- line 101: * **The demo model's pass rate on the ambiguity prompts, under the restated rule: 41.7 %**
- line 102:   (5 of 12; 0 of 12 on HB-16's traces).
- line 104: ## 6. A-1 to A-6 against the traces (step 3), and the server fix (step 5)
- line 111: | A-2 | 34 ungrounded clock times to 0 | fixed |
- line 113: | A-4 | 0 to 0 agent-drawn areas in the matrix | fixed. HB-16's case was in its pilots (3 of 4 area calls), not its matrix, as LN-07 part 1 implied |
- line 114: | A-5 | 5 internal ids on the surface to 0; 2 replies to 0 | fixed |
- line 115: | A-6 | 39 `detailed` calls (23 refused by the client's cap) to 0 | fixed by the description; paging never exercised |
- line 118: and Claude Code refused the results (148,721 to 195,440 characters). Its field said only "large",
- line 119: while `detailed`, whose description names the cap, was asked for 0 times. `request.include_map_svg`'s
- line 124: * No output changed: `eval_harness.py regression` reports 0 differences.
- line 131:    among HB-16's 16 scenario prompts. Only HB-18's two were missing, so the set is 32 and the run
- line 132:    288 episodes, under the task's 306.
- line 149:    * `audit` (A-1 to A-6 from the traces);
- line 153:    (`test_the_wind_is_read_from_a_call_that_takes_one`). It changes 6 verdicts, all fail to pass:
- line 155: 6. **"The prompt set never tuned".** It was not, even where the run shows a rule mis-scoring
- line 157:    filed (A-7, A-9, A-10) for a restatement written before the next scoring, as HB-18 did for
- line 161:    part 2. This run has 0.
- line 163: ## 8. Gate (step 6)
- line 166:   8 failed, 5 errors, 12 deselected, 15 xfailed, 1 xpassed, in 540 s.
- line 170:   * Every eval, server and ICS 201 test passes, including the 6 new ones.
- line 171: * **Slow mark** (`-m slow`, `logs/2026-10-23_HB-16b_pytest_slow.log`): 12 passed.
- line 172: * **Regression** (`eval_harness.py regression`): 18 scenarios, 121 outputs, 12 frozen files,
- line 173:   **0 differences**.
