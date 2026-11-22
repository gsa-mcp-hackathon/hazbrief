# HB-115 load read: the rule set (ADDENDUM-01 section 3)

**What is read:** for each of the five briefs to be served, the text a reader sees in the committed
`brief.html`: the map panel (the first screen), the sections below it and the commander's report (ICS 201,
`section-ics201`). Script, style and SVG bodies and attribute values are not read.
**Who reads:** this session, once, with `the HB-115 evidence (held privately)` as the mechanical first pass
and a reading of each flagged item. No model API call and no nested session (the task's Spend line).
**Prior art:** the rules are ADDENDUM-01's own four, which follow DN-019 section 2's two consequences of HB-83's
held standards on cognitive load ("fewer things on by default than can be shown"; Sweller 1988, cited by
DN-019's library receipts) and the redundancy principle of the same literature: text that restates text a reader
already has adds load and no information.

## The rules

| Rule | What it finds | Mechanical test (`load_read.py`) |
|---|---|---|
| R1 | a duplicated sentence | the same sentence, case and whitespace folded, of at least 6 words, printed more than once on the page |
| R2 | a sentence followed by a sentence about that sentence | a sentence opening "This line", "This value", "That is", "In other words", "i.e." and the like, after another in the same block |
| R3 | a label that restates its value | a two-cell table row, or a "Label: value" block, whose value begins with its own label's words |
| R4 | three receipts where one carries the fact | a list item, cell or paragraph with three or more receipts: a bracketed ERG/CFR/NWS tag, a "p. N" page, a 12-hex record hash |

## What a cut may do

A cut is **applied** only when it changes no number and no receipt on the page, and moves no text this task
may not move. Three classes are not applied, whatever their load:
1. **the ICS 201's text**, which is the server's `build_ics_201` output, not the application's ("the frozen
   ICS 201", DN-013 section 6, as the scenario manifest's `not_run` cells quote it); a cut there is a server
   change, and this task changes no tool;
2. **a modelled layer's label**, whose sentences DN-018, DN-020 and the the instructions of the coding sessions (held privately) paragraph require ("the ERG
   footprint is the protective action distance");
3. **a sentence another task's test pins** (it moves with that task's rule, by addendum).

Every proposal not applied is filed as an Issue for the review (ADDENDUM-01 section 3).

## Outputs

- `before/` and `after/`: one JSON per brief (every R1 to R4 candidate, words by section) and
  `word_counts.tsv`. `before/` is HEAD's committed pages; `after/` is the pages as served.
- `proposals.md`: the reading of every candidate, the cut proposed, and whether it was applied.
