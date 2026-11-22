"""A test helper (HB-133): pin a brief's one wind record to its scenario's stated wind.

The tool-call seed (`evidence/seed_calls`) and the derivations recorded before HB-133
were made on each fixture's stated wind (the "worked example wind"). A brief now asks
the server about its one wind record, the held forecast cell, so those calls are not
the brief's (`hazbrief.brief.wind_record`). Tests of the orchestrator's mechanics
(DN-011 D7) and of the derivations' algorithms on that recorded data pin the record to
the stated wind, as a brief with no forecast held for its hour would resolve it: the
request is then the seed's own, every held call and exchange replays, and the brief
reads one wind. Tests of the committed briefs read them as built, unpinned.
"""

from __future__ import annotations

import contextlib

import pytest

from hazbrief.brief import wind_record


async def _stated_only(scenario, point, cfg, *, now, replay, weather=None):
    return wind_record.from_forecast(None, scenario, cfg), None


@contextlib.contextmanager
def stated_wind_pinned():
    """Inside: every assembly resolves its record from the stated wind alone."""
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(wind_record, "resolve", _stated_only)
        yield
    finally:
        mp.undo()
