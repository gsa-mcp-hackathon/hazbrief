# HB-150 Part B item 7: the FGDC HSWG ERS v2.20 fonts, read

Inputs: `corpus/inbox/ersSymbolsVersion0202/` (11 `ersV2txt/*_txt.ttf`, 11 `ersV2sym/*_sym.ttf`, `readme.txt`,
`readme.htm`; unmodified). The only held glyph-to-name statement is Seldon Issue b1f7dc08 (the Desktop session's
reading, 2026-11-09, of FGDC `Operations_ref.htm`; the page is not held). No other glyph is named anywhere here.

Outputs (all written by `tools/hswg_glyphs.py`, deterministic: two runs gave identical sha1 over the TSV and PNGs):

| file | content |
|---|---|
| `hswg_glyphs.tsv` | 647 rows: every mapped code of the 11 txt fonts; 40 rows carry an Issue name |
| `hswg_fonts.tsv` | 22 rows: name-table strings (family, version, copyright, trademark, licence description and URL) and cmap subtables for every font |
| `hswg_sym_vs_txt.tsv` | 11 rows: sym font against txt font |
| `glyphs/key_check.tsv` | 40 rows: the 10 Issue keys in Operations S1..S4: mapped, glyph name, contour count |
| `glyphs/Operations_S{1..4}_<key>.png` | the 40 keyed glyphs, 96x96, black on white |
| `glyphs/sheet_<font>.png` | 11 contact sheets, every mapped glyph labelled with its character and code point |

`tools/ttf_cmap.py` is standard library only (`cmap_chars(path) -> set[int]`, cmap formats 0, 4, 6, 12; Unicode
subtables plus the Windows Symbol (3,0) subtable; codes mapped to glyph 0 excluded). `hswg_glyphs.py` compares it
with fontTools for all 22 fonts and exits 1 on any difference: no difference.

## Licence and status (the fonts, not the readme)

The readme (txt and htm) says nothing about licence, copyright or status: it covers the txt/sym encodings, a
list-serve, `http://www.fgdc.gov/HSWG` and Microsoft Font Validator. The statements are in every font's name table
(`hswg_fonts.tsv`), identical in all 22:

- nameID 0: "Copyright (c) Homeland Security Working Group, 2003. The symbols, in any form, are considered a
  Government work, and therefore not subject to copyright protection."
- nameID 13 (licence description): "DISCLAIMER: Please be aware these symbols are a draft prototype, provided as is,
  and no warranty is given or implied as to their present usability or their future adoption as a standard. [...] In
  all products that incorporate one or more of the symbols, the user agrees to characterize the symbols as a draft
  prototype. Any redistribution of the symbols individually or as a set carries the same conditions. It is likely
  some of the symbols WILL change as a result of our evaluation process. [...]"
- nameID 5: "Version 2.20 2003" (txt), "Version 2.20 2003 symbol encoding" (sym).

So the Issue's three points (Government work, draft prototype, products must say so) are confirmed from held bytes.
One slip in the fonts: the Damage fonts' trademark string (nameID 7) reads "ERS v2 Incidents is a product of...".

## S1..S4

The fonts name themselves "ERS v2 Operations Stage 01" .. "Stage 04" (likewise Infrastructures); the held material
calls them stages, not levels, and does not say what a stage means. Across S1..S4 the same key draws the same
pictogram; only the frame changes (seen in `sheet_Operations_S1..S4.png`): S1 a single thin circle, S2 a double
circle, S3 a heavy ring broken into four arcs, S4 a dashed (chequered) ring. The contour counts agree: for every one
of the 10 keys, S2 = S1 + 2, S3 = S1 + 4, S4 = S1 + 12 (`glyphs/key_check.tsv`). The Issue's assumption that the
four files are the page's four variants is consistent with this; what each frame signifies is not held. The
Infrastructures stage fonts were not inspected visually beyond S1.

## sym against txt

txt fonts carry Unicode cmaps (0,3) and (3,1) at ASCII codes; sym fonts carry only a Windows Symbol (3,0) cmap at
U+F020..U+F0A4 (U+F000 + byte). Both carry a Mac (1,0) table. Pairing each sym code with the Windows-1252 decoding of
its byte: every sym glyph has a txt counterpart with the same glyph name and outline, except
- the txt fonts add U+00A0 (no-break space, the space glyph); U+20AC (txt) pairs with sym byte 0x80;
- Damage sym: glyph names are `.notdef.N` (no real post names), and its euro-position glyph sits at U+F0AC, not
  U+F080;
- Incidents: six glyphs (A, B, C, F, N, i) have different outline data in txt and sym at equal contour counts; not
  examined further.
The table rows use the txt fonts, as the readme recommends. In every txt font the glyph name equals the character's
PostScript name (`A`, `g`, `exclam`, ...). U+00A4 and U+20AC draw an empty square in every font.

## The Issue's 10 keys

Every key is mapped, to a glyph with outline contours, in all four Operations txt fonts (`glyphs/key_check.tsv`).
Visual reading of the S1 renders (description only; the names are the Issue's):

| key | Issue name | S1 S2 S3 S4 | what it draws | plausible |
|---|---|---|---|---|
| K | Triage | yes yes yes yes | medical bag with caduceus | plausible |
| R | Emergency Staging Areas | yes yes yes yes | building with three bays, boxes in front | plausible |
| N | Emergency Incident Command Center | yes yes yes yes | square split on the diagonal, half black (the ICS command-post mark) | plausible |
| O | Emergency Operations Center | yes yes yes yes | house outline with a triangle inside | plausible |
| Y | Fire Station | yes yes yes yes | fire engine with ladder | plausible (draws the apparatus, not a building) |
| g | Police | yes yes yes yes | police car with light bar | plausible |
| F | Hospital | yes yes yes yes | "H" in a square | plausible |
| M | Emergency Collection Evacuation Point | yes yes yes yes | three figures with an arrow | plausible |
| A | Emergency Medical Operation | yes yes yes yes | star of life | plausible |
| Z | Law Enforcement Operation | yes yes yes yes | six-point sheriff's star | plausible |

Unnamed glyphs seen (descriptions, not names): Operations B house with star of life, C ambulance, D helicopter with
cross, E building with cross, H door with cross, Q tent, T cup with drop, U fork and knife, V fire helmet, W
hydrant, X hose nozzle with drop, b officer at a barrier arm, c officer at a booth, h barred cell; Infrastructures
S1 A book, B mortarboard, = Rx, Z wheelchair, p car at a barrier gate and booth, q traffic cone, r car and officer;
Incidents: a set of diamond hazard pictograms (flame, flame over circle, flask, corrosive, explosive, cylinders,
drop), solid and empty diamonds at `!` and `#`. No glyph seen depicts a decontamination shower or line.

## Commands run (repository root = the worktree)

```
/opt/anaconda3/bin/python3 -I the HB-150 evidence (held privately)     # twice; outputs identical
uv run python -I the HB-150 evidence (held privately) corpus/inbox/ersSymbolsVersion0202/ersV2txt/ERS_v2_Operations_S1_txt.ttf corpus/inbox/ersSymbolsVersion0202/ersV2sym/ERS_v2_Operations_S1_sym.ttf
```

`hswg_glyphs.py` needs fontTools and Pillow: anaconda python (fontTools 4.62, Pillow 12.1). The uv env has Pillow
13.0.0 but no fontTools, so `ttf_cmap.py` (standard library) is what a pytest there can import. Inspection montages
were made with throwaway scripts in /tmp; they are not evidence outputs.
