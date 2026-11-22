# HB-215 Part B item 10: the display prior art for the Sources view's marks

The operator asked for "a nice graphical stoplight chart of the servers and what was on, what was not". A stoplight
chart is a colour code. The held human-factors standards say a colour code must not stand alone; each mark carries
a second cue. The view does what they say: each mark has a shape that differs by state (● answered, ○ not called,
✕ failed, ◌ waiting) and the state's word beside it, and the colour adds to both. A source that was not called gets
its own mark and word. It is never shown by a blank.

Searched: the held texts of the three human-factors standards in `corpus/sources.yaml` (rows 6489 to 6560, "the
public human-factors standards ... a display design note"), read with `pdftotext -layout` and searched for
"redundant" beside "colo(u)r" and for "status". Tufte's *Visual Display of Quantitative Information*
(`tufte-2001-visual-display-quantitative-information`) is metadata only (a closed row, not public), so it is cited by
row only and not quoted.

| Held row | sha256 (first 16) | Block read | PDF page | Text |
|---|---|---|---|---|
| `nrc-nureg-0700-r4` (NUREG-0700 Rev. 4) | 9aa099f258702ef8 | 1.3.8-10 Redundant Color Coding | 83 | "Color coding should be redundant with some other display feature." Additional information: "Displayed information should be sufficient even when viewed on a monochromatic display terminal or hardcopy printout, or when viewed by a user with color vision impairment." |
| `nrc-nureg-0700-r4` | 9aa099f258702ef8 | 3.2.2-3 Positive Status Indication | 226 | "System and equipment status should be conveyed by illuminated indicators, never by the absence of illumination." |
| `faa-hf-std-001b` (DOT/FAA/HF-STD-001B) | bcbbe0276186f204 | 5.6.6.2.1.5 Redundant use | 306 | "Color-coding should be redundant to some other means of coding, indicating an action, prompting a response, or distinguishing a visual element, not as the only means of conveying information." |
| `dod-mil-std-1472h` (MIL-STD-1472H) | 20dae60ff4451f27 | 5.1.3.1.16 Target shape and color | 63 | "If color coding is used, it shall be redundant to another form of coding." |

How the view applies them (`src/hazbrief/brief/orchestrator.yaml` `data_sources.board`; `data_sources.board_mark`):

- **Redundant coding** (NUREG 1.3.8-10; FAA 5.6.6.2.1.5; MIL-STD-1472H 5.1.3.1.16): each state has its own shape
  and its own word, so the board still reads in greyscale or in print. The word is the part a screen reader reads;
  the shape is `aria-hidden`. `tests/test_hb215_sources_board.py` checks that no row's state is given by colour alone.
- **Positive status** (NUREG 3.2.2-3): "not called" is a mark and a word of its own. A source the brief did not
  call is never shown by a missing row.
- The page's three states for sections (`page.states`, HB-158) already follow this rule (WCAG 2.2 SC 1.4.1 is named
  there). The board uses the same shapes for answered, failed and waiting, and adds ○ for not called.
