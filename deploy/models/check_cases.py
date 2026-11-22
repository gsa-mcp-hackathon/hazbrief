"""The models image's build gate (HB-111 Part A step 1): SLAB's four distributed test
cases, run through the image's own driver and binary, must reproduce the distributed
outputs.

HB-102 measured the tolerance (`docs/evidence/hb102/inventory.md` section 5): gfortran's
build of SLAB.FOR reproduces OUTPR1..OUTPR4 with every differing number one unit in the
third printed significant figure (`9.21E+01` against `9.20E+01`), signed zeros aside,
and one exception: the downwind distance x printed for x = 0 (`7.63E-06` against
`3.34E-06` in PR1), which SLAB.RME documents as varying between builds. So a value
passes when it is within one unit of the reference's last printed digit; a signed zero
passes; an x (first column) both of whose printings are below `X_ZERO_RESIDUE_M`
passes as that residue. HB-111 found a second residue of the same kind, the
single-precision erf cancellation on the far crosswind tail
(`CANCELLATION_RESIDUE_RATIO`, below). Anything else fails the build, and every
exempted value is listed on stdout, so an exemption is never silent. Line counts must
match exactly.

HB-102's `compare_outputs.py` (copied beside this file) reads the files and writes the
JSON record of every difference, as HB-102 recorded its own runs; this script adds the
pass/fail rule HB-102 stated in prose, over every numeric pair, not only the ten
largest.

Usage: check_cases.py CASES_DIR OUT_DIR   (SLAB_BIN, SLAB_TIMEOUT_S in the environment)
  CASES_DIR holds INPR1..4 and OUTPR1..4; OUT_DIR receives nuoutN and
  compare_OUTPRN.json.
Exit 0 when all four reproduce; 1 with each failing value on stderr otherwise.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_outputs as C  # noqa: E402  (HB-102's, copied beside this file)
import slab_driver as D  # noqa: E402  (the image's entry, copied beside this file)

#: HB-102's tolerance: one unit in the third printed significant figure.
TOLERANCE_UNITS = 1.0
#: A downwind distance (m) printed below this, in both files, is the x = 0 rounding
#: residue SLAB.RME documents ("2.38E-06 vs 7.63E-06 ... 16-bit vs 32-bit programs").
X_ZERO_RESIDUE_M = 1e-4
#: HB-111's second residue, found building on Linux (glibc's libm) where HB-102 built
#: on macOS. In the "concentration in the z = ... plane" tables the crosswind columns
#: are cc(x) * (erf(ya) - erf(yb)), each erf a real*4 near 1 (SLAB.FOR `errint`, line
#: 3016: `real*4 x,erf,erfc`; no other routine declares a precision, so all are
#: default REAL). A value far out on the crosswind tail is the difference of two
#: single-precision numbers and carries only the platform's rounding. The reference's
#: own y/bbc = 2.5 column is not monotone there (OUTPR1 lines 340-343: 4.36E-07,
#: 4.53E-07, 4.50E-07, 4.46E-07). A value printed below this fraction of its row's
#: centreline value (y/bbc = 0), in both files, is that residue: about 100 times
#: real*4's epsilon (1.19E-07). docs/evidence/hb111/README.md section 2.
CANCELLATION_RESIDUE_RATIO = 1e-5
#: Float slack on the unit count (0.01 / 10**k is not exact in binary).
_EPS = 1e-9


def units(ref_tok: str, ref: float, new: float) -> float:
    exp = int(ref_tok.upper().replace("D", "E").split("E")[1])
    return abs(new - ref) / 10.0 ** (exp - 2)


def failures(
    ref_lines: list[str], new_lines: list[str], exempted: list[str] | None = None
) -> list[str]:
    """Every value outside the tolerance; values passed as a residue are appended to
    `exempted` when it is given."""
    exempted = [] if exempted is None else exempted
    if len(ref_lines) != len(new_lines):
        return [f"line count {len(new_lines)} against the reference's {len(ref_lines)}"]
    bad = []
    plane = False  # inside a "concentration in the z = ... plane" table
    for i, (a, b) in enumerate(zip(ref_lines, new_lines), start=1):
        if "concentration in the z" in a:
            plane = True
        elif a.strip() == "1" or "concentration:" in a:
            plane = False  # SLAB's page break, or the next table's title
        if a == b:
            continue
        ta, tb = a.split(), b.split()
        if len(ta) != len(tb):
            bad.append(f"line {i}: token count differs: {a.strip()!r} / {b.strip()!r}")
            continue
        for j, (x, y) in enumerate(zip(ta, tb), start=1):
            if x == y:
                continue
            fx, fy = C.as_float(x), C.as_float(y)
            if fx is None or fy is None:
                bad.append(f"line {i} field {j}: text {x!r} / {y!r}")
                continue
            if fx == 0.0 and fy == 0.0:
                continue  # signed zero
            if j == 1 and abs(fx) < X_ZERO_RESIDUE_M and abs(fy) < X_ZERO_RESIDUE_M:
                exempted.append(f"line {i} field {j}: {x} / {y} (x = 0 residue)")
                continue
            if plane and len(ta) == 10 and j >= 6:
                # x, time of max, duration, bbc, then y/bbc = 0, 0.5, ..., 2.5
                ca, cb = C.as_float(ta[4]), C.as_float(tb[4])
                if (
                    ca
                    and cb
                    and abs(fx) < CANCELLATION_RESIDUE_RATIO * abs(ca)
                    and abs(fy) < CANCELLATION_RESIDUE_RATIO * abs(cb)
                ):
                    exempted.append(
                        f"line {i} field {j}: {x} / {y} (real*4 erf cancellation "
                        f"residue: below {CANCELLATION_RESIDUE_RATIO:g} of {ta[4]})"
                    )
                    continue
            if "E" not in x.upper() and "D" not in x.upper():
                bad.append(f"line {i} field {j}: {x} / {y}")
                continue
            u = units(x, fx, fy)
            if u > TOLERANCE_UNITS + _EPS:
                bad.append(f"line {i} field {j}: {x} / {y} ({u:.2f} units)")
    return bad


def main(argv: list[str]) -> int:
    cases, out = Path(argv[1]), Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    binary = os.environ["SLAB_BIN"]
    timeout_s = float(os.environ["SLAB_TIMEOUT_S"])
    failed = 0
    for n in (1, 2, 3, 4):
        predict = D.run_deck(binary, (cases / f"INPR{n}").read_bytes(), timeout_s)
        (out / f"nuout{n}").write_bytes(predict)
        ref, _ = C.read_lines(cases / f"OUTPR{n}")
        new, _ = C.read_lines(out / f"nuout{n}")
        record = C.compare(ref, new, [])
        (out / f"compare_OUTPR{n}.json").write_text(json.dumps(record, indent=1))
        exempted: list[str] = []
        bad = failures(ref, new, exempted)
        print(
            f"PR{n}: {record.get('numeric_tokens_differing', 0)} numeric tokens "
            "differ, "
            f"max relative {record.get('max_rel_diff', 0.0)}, "
            f"{record.get('signed_zero_pairs', 0)} signed zeros, "
            f"{len(exempted)} residues; "
            f"{'REPRODUCES' if not bad else f'{len(bad)} OUTSIDE TOLERANCE'}"
        )
        for line in exempted:
            print(f"  PR{n} exempted {line}")
        for line in bad:
            print(f"  PR{n} {line}", file=sys.stderr)
        failed += bool(bad)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
