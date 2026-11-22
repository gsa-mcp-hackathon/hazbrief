"""The SCICHEM build's gate (HB-167 Part B item 10), run in the image at build and by
test_hb167_scichem_image.py against the built image. Standard library only.

The case is HB-165's csx day chlorine base project (`case/`: a single-material namelist
project, 885 point sensors at 1.5 m, a 2-hour run). Three checks, each a defect HB-165
found or the reference it measured against:

1. **End of file** (patch 11): a single-material namelist project runs to normal
   termination. Without the patch, gfortran refuses the second read of the `.scn` the
   engine rewrites (IOSTAT 5001) and the run stops at "Error reading SCN namelist".
2. **Sampler** (`-fno-frontend-optimize`): point sensors inside the cloud read above
   zero. Without the flag every sensor reads 0 while the run "ends normally"; EPRI's
   Intel build gives 16,904 non-zero mean and variance values on these inputs
   (measured here from the reference file).
3. **Agreement with EPRI's Intel build**: every sensor value (mean and variance, every
   output time) within `TOLERANCE` of the Intel-built executable's output on the same
   inputs (`intel_reference_csxday_base.smp.gz`, HB-165's run of EPRI's shipped Linux
   `runsci` under amd64 emulation). HB-165 measured every pair within 1 percent (r =
   1.000000, |FB| 1.1e-8; docs/evidence/hb165/compare/cl2_base_gfortran_vs_intel.json),
   so 1 percent is the tolerance: a measured agreement, not a chosen one.

Usage: python -I check_engine.py <check dir> [<driver dir>]
Exit 0 and one summary line when all three hold; exit 1 naming the first that fails.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

#: Every value within 1 percent of the Intel build's (HB-165's measured agreement).
TOLERANCE = 0.01


def table(text: str) -> tuple[list[str], dict[float, list[float]]]:
    body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    names = body[0].split()
    rows = {}
    for ln in body[1:]:
        v = [float(x) for x in ln.split()]
        rows[v[0]] = v
    return names, rows


def check(check_dir: Path, driver_dir: Path) -> dict:
    sys.path.insert(0, str(driver_dir))
    import scichem_driver as D  # noqa: E402

    files = {
        p.name: p.read_text(encoding="ascii")
        for p in sorted((check_dir / "case").iterdir())
    }
    resp = D.run_request(
        {"project": "csxday", "files": files, "extract": []},
        Path(os.environ["SCICHEM_HOME"]),
        float(os.environ["SCICHEM_TIMEOUT_S"]),
    )
    run = resp["runsci"]
    if not run["normal"]:
        raise AssertionError(
            "end of file: the single-material namelist project did not end normally: "
            + " | ".join(run["log_tail"][-3:] + run["err_tail"][-2:])
        )
    ref_text = gzip.decompress(
        (check_dir / "intel_reference_csxday_base.smp.gz").read_bytes()
    ).decode("latin-1")
    out = compare(resp["smp"], ref_text)
    out["normal_termination"] = True
    out["runsci_wall_s"] = run["wall_s"]
    return out


def compare(smp_text: str, ref_text: str) -> dict:
    """Checks 2 and 3 on a sensor file against the Intel reference's text."""
    names, rows = table(smp_text)
    ref_names, ref_rows = table(ref_text)
    if names != ref_names:
        raise AssertionError(
            "the sensor file's columns differ from the Intel reference's"
        )
    cols = [j for j, n in enumerate(names) if n[0] in "CV"]
    nonzero = sum(1 for r in rows.values() for j in cols if r[j] != 0.0)
    ref_nonzero = sum(1 for r in ref_rows.values() for j in cols if r[j] != 0.0)
    if nonzero == 0:
        raise AssertionError(
            "sampler: every point sensor read zero (the front-end optimisation defect)"
        )
    if sorted(rows) != sorted(ref_rows):
        raise AssertionError(
            f"output times differ: {len(rows)} against the reference's {len(ref_rows)}"
        )
    worst, pairs = 0.0, 0
    for t, ref in ref_rows.items():
        got = rows[t]
        for j in cols:
            a, b = ref[j], got[j]
            if a == 0.0 and b == 0.0:
                continue
            pairs += 1
            rel = abs(a - b) / max(abs(a), abs(b))
            worst = max(worst, rel)
    if worst > TOLERANCE:
        raise AssertionError(
            "agreement: the largest relative difference from the Intel build is "
            f"{worst:.3g}, over {TOLERANCE}"
        )
    return {
        "nonzero_values": nonzero,
        "intel_nonzero_values": ref_nonzero,
        "pairs_compared": pairs,
        "largest_relative_difference": worst,
        "tolerance": TOLERANCE,
    }


def main(argv: list[str]) -> int:
    check_dir = Path(argv[1])
    driver_dir = Path(argv[2]) if len(argv) > 2 else check_dir.parent
    try:
        out = check(check_dir, driver_dir)
    except AssertionError as exc:
        print(f"SCICHEM CHECK FAILED: {exc}", file=sys.stderr)
        return 1
    print("SCICHEM CHECK PASSED " + json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
