"""Run SLAB once: an input deck in, SLAB's output file out (HB-111 Part A step 3).

SLAB reads its problem from a file named `input` in its working directory and writes
its results to a new file named `predict` there (`SLAB.FOR` lines 177-178:
`open(2,file='input',status='old')`, `open(3,file='predict',status='new')`), as the
distributed `slabbat.bat` runs it. This driver gives each run a fresh temporary
directory, so two runs never share a `predict` and SLAB's `status='new'` never fails on
a stale one, and returns `predict`'s bytes unchanged.

Standard library only. It is the one file of the application the models image holds
(`deploy/models/Dockerfile` copies it to `/opt/slab/slab_driver.py`, its ENTRYPOINT),
and `hazbrief.brief.dense_gas` imports `run_deck` for the local-binary route
(`HAZBRIEF_SLAB_BIN`), so both routes run the same code and return the same bytes
(`test_models_image.py`). It opens no socket.

Usage (the image's entry):  slab_driver.py [DECK]  < deck  > predict
  DECK: a path to the input deck; without it the deck is read from stdin.
  The binary is `SLAB_BIN` and the time limit `SLAB_TIMEOUT_S` (seconds), both from
  the environment (the image sets both; the client passes them on the local route).
  Exit 0 with `predict` on stdout; otherwise exit 2 with one line on stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


class SlabRunError(RuntimeError):
    """SLAB did not produce an output file: the binary is missing, it failed, or it
    timed out. The message is one line."""


def run_deck(binary: str | os.PathLike, deck: bytes, timeout_s: float) -> bytes:
    """SLAB's `predict` for one input deck, run by `binary` in a fresh directory."""
    exe = Path(binary)
    if not exe.is_file() or not os.access(exe, os.X_OK):
        raise SlabRunError(f"the SLAB binary {exe} is not an executable file")
    if not deck.strip():
        raise SlabRunError("the input deck is empty")
    with tempfile.TemporaryDirectory(prefix="slab-") as tmp:
        work = Path(tmp)
        (work / "input").write_bytes(deck)
        try:
            proc = subprocess.run(
                [str(exe.resolve())],
                cwd=work,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SlabRunError(f"SLAB did not finish within {timeout_s:g} s") from exc
        out = work / "predict"
        if proc.returncode != 0 or not out.is_file():
            tail = (proc.stderr or proc.stdout or b"").decode("latin-1").strip()
            tail = tail.splitlines()[-1] if tail else "no message"
            raise SlabRunError(
                f"SLAB exited {proc.returncode} without an output file: {tail}"
            )
        return out.read_bytes()


def main(argv: list[str]) -> int:
    binary = os.environ.get("SLAB_BIN")
    if not binary:
        print("SLAB_BIN is not set: the path of the SLAB binary", file=sys.stderr)
        return 2
    try:
        timeout_s = float(os.environ["SLAB_TIMEOUT_S"])
    except (KeyError, ValueError):
        print("SLAB_TIMEOUT_S is not set to a number of seconds", file=sys.stderr)
        return 2
    deck = Path(argv[1]).read_bytes() if len(argv) > 1 else sys.stdin.buffer.read()
    try:
        sys.stdout.buffer.write(run_deck(binary, deck, timeout_s))
    except SlabRunError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
