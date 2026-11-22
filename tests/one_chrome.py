"""HB-164: one headless Chrome at a time, across pytest-xdist workers and across
concurrent test runs on this machine, and a failed Chrome says why.

With the suite in parallel at ten workers, Chrome failed in three of four completed full
runs where it never had serially: a `--dump-dom` that exited 2 (twice) and a
`--print-to-pdf` that hung past its 240 s timeout (11 s serially). Each launch already
had a profile of its own. Exit status 2 is Chromium's `RESULT_CODE_HUNG`
(`content/public/common/result_codes.h`): Chrome's
own hang watchdog, which fires when its processes get no CPU. Those runs had ten workers
and a load average of 40 to 53 on ten cores, because many tests start subprocesses of
their own. Two measures answer it. The gate caps its workers below the core count
(`seldon` `dispatch.gate_command`, `--maxprocesses`), so the machine has headroom.
And every test that launches Chrome does it through `run_chrome`, which holds an
exclusive `flock` on one lock file in the user's temporary directory while Chrome runs,
so two Chromes, each a dozen processes, never compete with each other. Chrome's own
timeout starts after the lock is held, so a wait for the lock never counts against it.
The browser tests take about 150 s serially in all (docs/evidence/hb164/README.md), far
less than the parallel gate's wall clock.

A Chrome that fails raises with its exit status and the tail of its stderr, so the next
failure names its cause instead of a bare `CalledProcessError`.
"""

from __future__ import annotations

import fcntl
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

#: One lock for every checkout and worker of this suite on the machine.
LOCK = Path(tempfile.gettempdir()) / "hazbrief-tests-one-chrome.lock"
#: How much of a failed Chrome's stderr the error carries.
STDERR_TAIL_CHARS = 2000


@contextmanager
def one_chrome():
    """Hold the machine's Chrome lock for the block."""
    with open(LOCK, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _tail(stream) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        stream = stream.decode("utf-8", errors="replace")
    return stream[-STDERR_TAIL_CHARS:]


def run_chrome(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run(args, **kwargs)` for a headless Chrome, under the lock."""
    with one_chrome():
        try:
            return subprocess.run(args, **kwargs)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"headless Chrome exited {e.returncode} (2 is Chromium's "
                f"RESULT_CODE_HUNG); stderr tail:\n{_tail(e.stderr)}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"headless Chrome ran past its {e.timeout} s timeout; stderr tail:\n"
                f"{_tail(e.stderr)}"
            ) from e
