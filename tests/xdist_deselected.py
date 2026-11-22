"""HB-164: a parallel run's summary line counts the deselected tests, as a serial run's
does.

Under pytest-xdist the controller collects nothing; each worker collects the whole
suite and applies `-m` itself, so the controller's terminal reporter never sees a
deselected item and its summary drops the `N deselected` field. Every worker collects
and deselects the same items, so the first worker to finish reports its deselected
node ids (in its `workeroutput`, xdist's channel for a worker's results), and the
controller adds them to its terminal reporter's `deselected` stats once. A serial run
is untouched: it never has a worker, and its own reporter counts the deselection.

`tests/conftest.py` imports the two hooks, so every run of the suite has them;
`test_hb164_parallel_gate.py` loads this module with `-p` on a scratch suite.
"""

from __future__ import annotations

import pytest

KEY = "hb164_deselected"
_added = pytest.StashKey[bool]()


def pytest_deselected(items):
    """On a worker, keep the ids this worker deselected for the controller."""
    if not items:
        return
    config = items[0].config
    out = getattr(config, "workeroutput", None)
    if out is not None:
        out.setdefault(KEY, []).extend(item.nodeid for item in items)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    """On the controller, count one worker's deselected ids, once."""
    config = node.config
    ids = getattr(node, "workeroutput", {}).get(KEY)
    if ids is None or config.stash.get(_added, False):
        return
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    reporter.stats.setdefault("deselected", []).extend(ids)
    config.stash[_added] = True
