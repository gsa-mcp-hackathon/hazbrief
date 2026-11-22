"""Build the map's marker symbols as SVG, once, from the held FGDC HSWG fonts.

HB-152 Part A item 2.

**Zero model spend, no network.** Reads `src/hazbrief/brief/symbols.yaml` (each class to
a symbol family and key stroke, or to `own`) and the FGDC HSWG Emergency Response
Symbology v2.20 text-encoded TrueType fonts held in
`corpus/inbox/ersSymbolsVersion0202/ersV2txt/` (gitignored, held in place; HB-150), and
writes one SVG per class into `src/hazbrief/brief/static/symbols/`, plus `manifest.json`
naming each file's sources and sha256. The SVGs are committed; the page embeds them
inline and loads no font.

How a symbol is composed is the reference pages' own scheme
(`docs/evidence/hb152/ref_glyphs.tsv`): each family has a "Background Symbol" (key `!`,
"the background fill shape") and every pictogram glyph carries its own frame. So an SVG
is two paths: the background shape, filled with the layer's colour at render time
(`data-hb="frame"`), and the pictogram glyph, filled with white or black by contrast
(`data-hb="ink"`). A class with no named glyph (`own: true`) is drawn by hazbrief in the
same frame: the family's background, its frame glyph (`#`) and a pictogram hazbrief drew
itself (`own_path`, in the font's units), and is labelled as hazbrief's own wherever it
is shown.

**Why a standard-library TrueType reader, not fontTools.** The task named fontTools,
added to the dev group only. Adding it re-locks `uv.lock`, which needs pypi.org, a host
this task's Network line does not admit (HB-150's glyph table was built with fontTools
under another interpreter for the same reason). The outlines are read here from the
`cmap` (format 4), `head`, `loca` and `glyf` tables as the OpenType specification
defines them ("glyf - Glyph Data", simple and composite glyphs; quadratic B-splines with
implied on-curve midpoints), and `the HB-152 evidence`
compares every point this reader returns with fontTools' for every glyph built (0
differences, `docs/evidence/hb152/cross_check_fonttools.log`). The fonts are gitignored,
so the test suite does not rebuild: it parses every committed SVG and checks it against
`manifest.json`'s sha256; `--check` rebuilds into memory and compares bytes wherever the
fonts are held.

    uv run python scripts/build_symbols.py \
        --fonts-dir corpus/inbox/ersSymbolsVersion0202/ersV2txt
    # rebuild into memory, compare with the committed files
    uv run python scripts/build_symbols.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SYMBOLS_YAML = REPO / "src" / "hazbrief" / "brief" / "symbols.yaml"


class FontError(ValueError):
    """The file is not a TrueType font this reader understands, or a glyph it needs
    is missing."""


# ── the TrueType reader ──────────────────────────────────────────────────────────────


class TrueType:
    """The tables a glyph outline needs: `head` (unitsPerEm, loca format), `maxp`
    (glyph count), `loca`, `glyf`
    and `cmap` (Windows Unicode BMP, format 4)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        (num_tables,) = struct.unpack_from(">H", self.data, 4)
        self.tables: dict[str, tuple[int, int]] = {}
        for i in range(num_tables):
            tag, _check, off, length = struct.unpack_from(
                ">4sIII", self.data, 12 + 16 * i
            )
            self.tables[tag.decode("latin-1")] = (off, length)
        for need in ("head", "maxp", "loca", "glyf", "cmap"):
            if need not in self.tables:
                raise FontError(f"{path.name}: no {need!r} table")
        head = self.tables["head"][0]
        (self.units_per_em,) = struct.unpack_from(">H", self.data, head + 18)
        (self.loca_long,) = struct.unpack_from(">h", self.data, head + 50)
        (self.num_glyphs,) = struct.unpack_from(
            ">H", self.data, self.tables["maxp"][0] + 4
        )
        self.cmap = self._cmap()

    def _cmap(self) -> dict[int, int]:
        base = self.tables["cmap"][0]
        _version, n = struct.unpack_from(">HH", self.data, base)
        for i in range(n):
            plat, enc, off = struct.unpack_from(">HHI", self.data, base + 4 + 8 * i)
            if (plat, enc) == (3, 1):
                return self._cmap4(base + off)
        raise FontError(f"{self.path.name}: no Windows Unicode BMP (3,1) cmap subtable")

    def _cmap4(self, off: int) -> dict[int, int]:
        fmt, _length, _lang, segx2 = struct.unpack_from(">HHHH", self.data, off)
        if fmt != 4:
            raise FontError(f"{self.path.name}: (3,1) cmap is format {fmt}, not 4")
        seg = segx2 // 2
        ends = off + 14
        starts = ends + segx2 + 2
        deltas = starts + segx2
        ranges = deltas + segx2
        out: dict[int, int] = {}
        for s in range(seg):
            (end,) = struct.unpack_from(">H", self.data, ends + 2 * s)
            (start,) = struct.unpack_from(">H", self.data, starts + 2 * s)
            (delta,) = struct.unpack_from(">h", self.data, deltas + 2 * s)
            ro_at = ranges + 2 * s
            (ro,) = struct.unpack_from(">H", self.data, ro_at)
            for code in range(start, end + 1):
                if code == 0xFFFF:
                    continue
                if ro == 0:
                    gid = (code + delta) & 0xFFFF
                else:
                    (gid,) = struct.unpack_from(
                        ">H", self.data, ro_at + ro + 2 * (code - start)
                    )
                    gid = (gid + delta) & 0xFFFF if gid else 0
                if gid:
                    out[code] = gid
        return out

    def _glyph_span(self, gid: int) -> tuple[int, int]:
        loca = self.tables["loca"][0]
        if self.loca_long:
            a, b = struct.unpack_from(">II", self.data, loca + 4 * gid)
        else:
            a, b = (2 * v for v in struct.unpack_from(">HH", self.data, loca + 2 * gid))
        return self.tables["glyf"][0] + a, b - a

    def glyph_id(self, char: str) -> int:
        gid = self.cmap.get(ord(char))
        if not gid:
            raise FontError(
                f"{self.path.name}: {char!r} (U+{ord(char):04X}) is not mapped"
            )
        return gid

    def contours(
        self, gid: int, depth: int = 0
    ) -> list[list[tuple[float, float, bool]]]:
        """The glyph's contours as lists of (x, y, on_curve), in font units, y up."""
        if depth > 8:
            raise FontError(
                f"{self.path.name}: composite glyph nesting deeper than 8 "
                f"at glyph {gid}"
            )
        off, length = self._glyph_span(gid)
        if length == 0:
            return []
        (n,) = struct.unpack_from(">h", self.data, off)
        if n >= 0:
            return self._simple(off, n)
        return self._composite(off, depth)

    def _simple(self, off: int, n: int) -> list[list[tuple[float, float, bool]]]:
        p = off + 10
        ends = list(struct.unpack_from(f">{n}H", self.data, p))
        p += 2 * n
        (ilen,) = struct.unpack_from(">H", self.data, p)
        p += 2 + ilen
        count = ends[-1] + 1 if ends else 0
        flags: list[int] = []
        while len(flags) < count:
            f = self.data[p]
            p += 1
            flags.append(f)
            if f & 0x08:  # REPEAT_FLAG
                r = self.data[p]
                p += 1
                flags.extend([f] * r)
        xs, p = self._coords(flags, p, 0x02, 0x10)
        ys, p = self._coords(flags, p, 0x04, 0x20)
        out, start = [], 0
        for e in ends:
            out.append(
                [
                    (float(xs[i]), float(ys[i]), bool(flags[i] & 0x01))
                    for i in range(start, e + 1)
                ]
            )
            start = e + 1
        return out

    def _coords(
        self, flags: list[int], p: int, short: int, same: int
    ) -> tuple[list[int], int]:
        vals, v = [], 0
        for f in flags:
            if f & short:
                d = self.data[p]
                p += 1
                v += d if f & same else -d
            elif not f & same:
                (d,) = struct.unpack_from(">h", self.data, p)
                p += 2
                v += d
            vals.append(v)
        return vals, p

    def _composite(self, off: int, depth: int) -> list[list[tuple[float, float, bool]]]:
        p = off + 10
        out: list[list[tuple[float, float, bool]]] = []
        while True:
            flags, gid = struct.unpack_from(">HH", self.data, p)
            p += 4
            if flags & 0x0001:  # ARG_1_AND_2_ARE_WORDS
                dx, dy = struct.unpack_from(">hh", self.data, p)
                p += 4
            else:
                dx, dy = struct.unpack_from(">bb", self.data, p)
                p += 2
            if not flags & 0x0002:  # ARGS_ARE_XY_VALUES
                raise FontError(
                    f"{self.path.name}: point-matched composite component (glyph {gid})"
                )
            a, b, c, d = 1.0, 0.0, 0.0, 1.0
            if flags & 0x0008:  # WE_HAVE_A_SCALE
                (s,) = struct.unpack_from(">h", self.data, p)
                p += 2
                a = d = s / 16384
            elif flags & 0x0040:  # WE_HAVE_AN_X_AND_Y_SCALE
                sx, sy = struct.unpack_from(">hh", self.data, p)
                p += 4
                a, d = sx / 16384, sy / 16384
            elif flags & 0x0080:  # WE_HAVE_A_TWO_BY_TWO
                m = struct.unpack_from(">hhhh", self.data, p)
                p += 8
                a, b, c, d = (v / 16384 for v in m)
            for contour in self.contours(gid, depth + 1):
                out.append(
                    [
                        (a * x + c * y + dx, b * x + d * y + dy, on)
                        for x, y, on in contour
                    ]
                )
            if not flags & 0x0020:  # MORE_COMPONENTS
                return out


# ── outline to SVG path ──────────────────────────────────────────────────────────────


def _n(v: float) -> str:
    """A coordinate as the shortest exact text: integers stay integers, implied
    midpoints keep one decimal."""
    r = round(v, 1)
    return str(int(r)) if r == int(r) else f"{r:.1f}"


def path_data(
    contours: list[list[tuple[float, float, bool]]], dx: float = 0, dy: float = 0
) -> str:
    """SVG path data for TrueType contours, y flipped (SVG's y runs down), shifted by
    (dx, dy) after the flip.

    TrueType contours are quadratic B-splines: two consecutive off-curve points imply
    an on-curve point at their midpoint; a contour may start off-curve (OpenType spec,
    "glyf", and Apple's TrueType Reference Manual, "Digitizing Letterform Designs").
    Each contour is closed. Fill rule is SVG's default, nonzero, as TrueType's."""

    def pt(x: float, y: float) -> str:
        return f"{_n(x + dx)} {_n(-y + dy)}"

    parts: list[str] = []
    for c in contours:
        if not c:
            continue
        n = len(c)
        first_on = next((i for i, q in enumerate(c) if q[2]), None)
        if first_on is None:
            # every point off-curve: start at the midpoint of the first two
            sx, sy = (c[0][0] + c[1 % n][0]) / 2, (c[0][1] + c[1 % n][1]) / 2
            seq = c[1:] + c[:1]
        else:
            sx, sy = c[first_on][0], c[first_on][1]
            seq = c[first_on + 1 :] + c[: first_on + 1]
        parts.append(f"M{pt(sx, sy)}")
        ctrl: tuple[float, float] | None = None
        for x, y, on in seq:
            if on:
                if ctrl is None:
                    parts.append(f"L{pt(x, y)}")
                else:
                    parts.append(f"Q{pt(*ctrl)} {pt(x, y)}")
                    ctrl = None
            else:
                if ctrl is not None:
                    mx, my = (ctrl[0] + x) / 2, (ctrl[1] + y) / 2
                    parts.append(f"Q{pt(*ctrl)} {pt(mx, my)}")
                ctrl = (x, y)
        if ctrl is not None:
            parts.append(f"Q{pt(*ctrl)} {pt(sx, sy)}")
        parts.append("Z")
    return "".join(parts)


def bbox(
    contours: list[list[tuple[float, float, bool]]],
) -> tuple[float, float, float, float]:
    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    if not xs:
        raise FontError("an empty glyph has no box")
    return min(xs), min(ys), max(xs), max(ys)


# ── building ─────────────────────────────────────────────────────────────────────────


def load_table(path: Path = SYMBOLS_YAML) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def font_file(table: dict, family: str) -> str:
    fam = table["families"][family]
    return fam["font"].format(stage=table["standard"]["stage"])


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_one(table: dict, cls: str, fonts: dict[str, TrueType]) -> tuple[str, dict]:
    """One class's SVG text and its manifest row."""
    std = table["standard"]
    entry = table["classes"][cls]
    family = entry["family"]
    fam = table["families"][family]
    font = fonts[family]
    background = font.contours(font.glyph_id(fam["background"]))
    x0, y0, x1, y1 = bbox(background)
    pad = std["svg_pad_units"]
    # the viewBox is the background's box, padded; SVG y = -font y, so the top is -y1
    vb = (x0 - pad, -y1 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad)
    if entry.get("own"):
        frame = font.contours(font.glyph_id(fam["frame"]))
        ink = path_data(frame) + entry["own_path"]
        title = f"{entry['name']} (hazbrief's own symbol in the FGDC {family} frame)"
        glyph_row = {"own": True, "frame_key": fam["frame"]}
    else:
        ink = path_data(font.contours(font.glyph_id(entry["key"])))
        title = (
            f"{entry['name']} (FGDC HSWG ERS v2.20 {family}, key {entry['key']}; "
            "draft prototype)"
        )
        glyph_row = {"own": False, "key": entry["key"]}
    size = std["size_px"]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{" ".join(_n(v) for v in vb)}" '
        f'width="{size}" height="{size}" role="img" data-hb-class="{cls}">'
        f"<title>{_esc(title)}</title>"
        f'<path data-hb="frame" fill="{std["frame_default"]}" '
        f'd="{path_data(background)}"/>'
        f'<path data-hb="ink" fill="{std["ink_default"]}" d="{ink}"/>'
        "</svg>\n"
    )
    row = {
        "class": cls,
        "file": f"{cls}.svg",
        "sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
        "name": entry["name"],
        "family": family,
        "font": font.path.name,
        "font_sha256": font.sha256,
        "background_key": fam["background"],
        **glyph_row,
        "reference_page": fam["page"],
    }
    return svg, row


def build(table: dict, fonts_dir: Path) -> dict[str, str]:
    """Every class's SVG text, plus `manifest.json`, keyed by file name."""
    fonts: dict[str, TrueType] = {}
    for family in table["families"]:
        path = fonts_dir / font_file(table, family)
        if not path.is_file():
            raise FontError(
                f"font not found: {path} "
                "(the fonts are held in corpus/inbox/, gitignored; HB-150)"
            )
        fonts[family] = TrueType(path)
    out: dict[str, str] = {}
    rows = []
    for cls in table["classes"]:
        svg, row = build_one(table, cls, fonts)
        out[row["file"]] = svg
        rows.append(row)
    manifest = {
        "built_by": "scripts/build_symbols.py",
        "standard": table["standard"]["title"],
        "stage": table["standard"]["stage"],
        "classes": rows,
    }
    out["manifest.json"] = json.dumps(manifest, indent=1, sort_keys=False) + "\n"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--table", type=Path, default=SYMBOLS_YAML)
    ap.add_argument(
        "--fonts-dir",
        type=Path,
        default=None,
        help="default: the table's standard.fonts_dir",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="default: the table's standard.svg_dir",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="compare a fresh build with the committed files",
    )
    args = ap.parse_args(argv)
    table = load_table(args.table)
    std = table["standard"]
    fonts_dir = args.fonts_dir or REPO / std["fonts_dir"]
    out_dir = args.out_dir or REPO / std["svg_dir"]
    try:
        built = build(table, fonts_dir)
    except FontError as e:
        print(f"build_symbols: {e}", file=sys.stderr)
        return 2
    if args.check:
        differ = [
            n
            for n, t in built.items()
            if not (out_dir / n).is_file() or (out_dir / n).read_text() != t
        ]
        extra = sorted({p.name for p in out_dir.glob("*")} - set(built))
        print(
            f"build_symbols --check: {len(built)} files; "
            f"differ: {', '.join(differ) or 'none'}; "
            f"not built: {', '.join(extra) or 'none'}"
        )
        return 1 if differ or extra else 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in built.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    print(f"build_symbols: wrote {len(built)} files to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
