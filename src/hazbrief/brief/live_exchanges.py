"""A live brief's exchanges, recorded so its map draws their geometry (HB-208; Issue
8907cf6c).

The map draws a block, a rail line or any other shape only from the upstream exchange
records a tool's record names in its `used` (`layers._Ctx.exchanges`). A recorded
brief has them: HB-140's route records each call into an exchanges directory, migrates
the exchanges into the store, and names each call's reads
(`scripts/record_tool_call_seed.py` `read_by_call`). A live brief had none: the server
fetched in `live` mode, which writes nothing, so every live record's `used` was empty
and the population, residential density and workplaces layers said they could not be
drawn, though their counts were right.

This is the Issue's fix, the recording route run inside the live brief:

1. each live run gets its own exchanges directory under `orchestrator.yaml`
   `entry.exchanges_dir` (git ignores `state`), so nothing a run reads is another run's
   (a forecast from an earlier run is never served to a later one);
2. before each tool call, the tool's body runs in this process inside a
   `utils.recording` scope on that directory (`used_for`): it fetches what the server's
   call will fetch and writes each exchange there, and the scope names every exchange
   it read or wrote;
3. each of those exchanges is written into the run's store as an upstream exchange
   record (`evidence.exchange_records.record_exchange`, the seed migration's own
   construction), and their entity hashes are the call's `used`;
4. the server is started in `record` mode on the same directory (`env`), so its call
   reads the files the pre-run wrote: the counts it returns and the shapes the map draws
   come from the same responses, and no upstream is asked twice.

The pre-run's own failures are not the brief's: an upstream that fails in the pre-run
leaves no file, the server's call asks it again and its record says what happened, as
any live call's does. The pre-run says so on stderr.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hazbrief.config import REPO_ROOT


async def run_tool(name: str, params: dict) -> Any:
    """The tool's body in this process, on the MCP parameters the brief sends it (the
    location recorder's runner, HB-49; `build_ics_201` added by HB-140; moved here from
    `scripts/record_tool_call_seed.py` by HB-208, which the script now imports)."""
    from hazbrief.models import (
        FacilitiesInput,
        Ics201Input,
        IncidentInput,
        PopulationInput,
        ReceivingInput,
        WindObservation,
    )
    from hazbrief.tools import (
        assess_incident,
        build_ics_201,
        facilities_in_footprint,
        material_response_guidance,
        population_at_risk,
        protective_action_footprint,
        receiving_hospitals,
    )

    if name == "protective_action_footprint":
        wind = params.get("wind")
        return await protective_action_footprint.footprint(
            IncidentInput.model_validate(params["incident"]),
            WindObservation.model_validate(wind) if wind else None,
        )
    if name == "assess_incident":
        return assess_incident.run(IncidentInput.model_validate(params["incident"]))
    if name == "material_response_guidance":
        return material_response_guidance.guidance(
            IncidentInput.model_validate(params["incident"])
        )
    if name == "population_at_risk":
        return await population_at_risk.count(
            PopulationInput.model_validate(params["area"])
        )
    if name == "facilities_in_footprint":
        return await facilities_in_footprint.list_facilities(
            FacilitiesInput.model_validate(params["area"])
        )
    if name == "receiving_hospitals":
        return await receiving_hospitals.rank(
            ReceivingInput.model_validate(params["incident"])
        )
    if name == "build_ics_201":
        return await build_ics_201.assemble(
            Ics201Input.model_validate(params["request"])
        )
    raise ValueError(f"no runner for tool {name!r}")


class LiveExchanges:
    """One live run's exchanges: its directory, the server's environment, and the
    `used_for` hook `orchestrator.assemble` calls before each tool call."""

    def __init__(self, store: Path, root: Path, run: str | None = None):
        self.store = Path(store)
        stamp = run or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.dir = Path(root) / stamp

    @classmethod
    def from_config(cls, cfg: dict, store: Path) -> LiveExchanges:
        return cls(store, REPO_ROOT / cfg["entry"]["exchanges_dir"])

    def env(self) -> dict[str, str]:
        """The server's environment: `record` mode on this run's directory."""
        return {"HAZBRIEF_HTTP_MODE": "record", "HAZBRIEF_EXCHANGES_DIR": str(self.dir)}

    async def used_for(self, name: str, params: dict) -> list[str]:
        """The entity hashes of the exchanges `name` reads on `params`, each written
        into the store as an upstream exchange record first."""
        from hazbrief import utils
        from hazbrief.evidence.exchange_records import record_exchange

        with utils.recording(self.dir) as rec:
            try:
                await run_tool(name, params)
            except Exception as exc:  # noqa: BLE001 - reported; the server's call answers
                print(
                    f"live exchanges: {name}'s pre-run raised {type(exc).__name__}: "
                    f"{exc}; the server's call asks again and its record says what "
                    "happened",
                    file=sys.stderr,
                    flush=True,
                )
        shas = set()
        for api, key in sorted(rec.touched):
            path = self.dir / api / f"{key}.json"
            ex = json.loads(path.read_text(encoding="utf-8"))
            shas.add(record_exchange(ex, self.store)["sha256"])
        return sorted(shas)

    def assemble_kw(self) -> dict[str, Any]:
        """What a live `assemble` takes from this run (`env`, `used_for`)."""
        return {"env": self.env(), "used_for": self.used_for}
