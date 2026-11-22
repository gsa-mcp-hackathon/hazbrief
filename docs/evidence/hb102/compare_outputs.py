"""HB-102: compare a model's fresh output with its distributed reference output, number
by number.

Why: a text diff of Fortran E-format output flags every last-digit change; the question
for DN-020 is how large the differences are.  Lines are paired by position (the files
must have the same line count; a different count is reported and the comparison stops).
Within a differing line, tokens are paired by position; numeric pairs report their
relative difference |a-b|/max(|a|,|b|); non-numeric differing tokens are listed
verbatim.

Signed zeros (0.00E+00 vs -0.00E+00) are counted separately as signed_zero_pairs; every
other differing numeric pair is reported, including a value printed at its rounding
floor (SLAB.RME documents 2.38E-06 vs 7.63E-06 on the source-plane coordinate as a
16-bit/32-bit artefact), so a large relative difference is listed and must be read
against its line, never dropped.

Usage: python -I compare_outputs.py REF NEW [--ignore-line REGEX ...]   (prints JSON)
  --ignore-line: lines of the reference matching REGEX (a run date or time stamp) are
  listed under ignored_lines instead of compared.
"""

import argparse
import json
import re

NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([EeDd][-+]?\d+)?$")


def as_float(tok):
    if NUM.match(tok):
        return float(tok.replace("D", "E").replace("d", "e"))
    return None


def read_lines(path):
    """Lines without CR/LF.  A last line that is only the DOS end-of-file byte (0x1A,
    which DOS 'copy a+b c' appends to the concatenated .lis files) is dropped and
    counted."""
    with open(path, encoding="latin-1") as f:
        lines = [ln.rstrip("\r\n") for ln in f]
    eof = 0
    if lines and lines[-1].strip() == "\x1a":
        lines.pop()
        eof = 1
    return lines, eof


def compare_flat(ref, new):
    """List-directed output (the .PSD files) wraps records at a compiler-chosen width
    and prints a compiler-chosen number of digits, so compare the flattened number
    streams."""
    fa = [as_float(t) for ln in ref for t in ln.split()]
    fb = [as_float(t) for ln in new for t in ln.split()]
    out = {"mode": "flattened", "ref_tokens": len(fa), "new_tokens": len(fb)}
    if len(fa) != len(fb) or None in fa or None in fb:
        out["verdict"] = "token_count_differs_or_non_numeric"
        return out
    rels = [
        abs(a - b) / max(abs(a), abs(b)) for a, b in zip(fa, fb) if max(abs(a), abs(b))
    ]
    out.update(
        max_rel_diff=max(rels) if rels else 0.0,
        tokens_rel_over_1e6=sum(r > 1e-6 for r in rels),
        tokens_rel_over_1pct=sum(r > 0.01 for r in rels),
    )
    return out


def compare(ref, new, ignore):
    out = {"ref_lines": len(ref), "new_lines": len(new)}
    if len(ref) != len(new):
        out["verdict"] = "line_count_differs"
        return out
    lines_differing, numeric, signed_zero, text_diffs, ignored = 0, [], [], [], []
    for i, (a, b) in enumerate(zip(ref, new), start=1):
        if a == b:
            continue
        if any(rx.search(a) for rx in ignore):
            ignored.append({"line": i, "ref": a.strip(), "new": b.strip()})
            continue
        lines_differing += 1
        ta, tb = a.split(), b.split()
        if len(ta) != len(tb):
            text_diffs.append({"line": i, "ref": a.strip(), "new": b.strip()})
            continue
        for j, (x, y) in enumerate(zip(ta, tb)):
            if x == y:
                continue
            fx, fy = as_float(x), as_float(y)
            if fx is None or fy is None:
                text_diffs.append({"line": i, "field": j + 1, "ref": x, "new": y})
                continue
            big = max(abs(fx), abs(fy))
            rec = {"line": i, "field": j + 1, "ref": x, "new": y}
            if big == 0.0:
                signed_zero.append(rec)
                continue
            # Three significant figures, so a 1E-07 difference is not printed as 0.0.
            rec["rel"] = float(f"{abs(fx - fy) / big:.3g}")
            numeric.append(rec)
    numeric.sort(key=lambda r: -r["rel"])
    out.update(
        lines_differing=lines_differing,
        numeric_tokens_differing=len(numeric),
        max_rel_diff=numeric[0]["rel"] if numeric else 0.0,
        tokens_rel_over_1pct=sum(r["rel"] > 0.01 for r in numeric),
        tokens_rel_over_5pct=sum(r["rel"] > 0.05 for r in numeric),
        largest_10=numeric[:10],
        signed_zero_pairs=len(signed_zero),
        text_diffs=text_diffs,
        ignored_lines=ignored,
    )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("new")
    ap.add_argument("--ignore-line", action="append", default=[])
    ap.add_argument(
        "--flatten",
        action="store_true",
        help="compare the flattened number streams (list-directed output)",
    )
    args = ap.parse_args()
    (ref, ref_eof), (new, new_eof) = read_lines(args.ref), read_lines(args.new)
    out = {
        "ref": args.ref,
        "new": args.new,
        "dos_eof_dropped": {"ref": ref_eof, "new": new_eof},
    }
    if args.flatten:
        out.update(compare_flat(ref, new))
    else:
        out.update(compare(ref, new, [re.compile(r) for r in args.ignore_line]))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
