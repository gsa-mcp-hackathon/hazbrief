"""`build_ics_201`: a draft FEMA ICS Form 201 (Incident Briefing), the blocks public
data can fill, assembled deterministically from the server's own tools (HB-11; DN-001
section 7; DN-006 section 3.6).

Data source: the server's tools, run here on the incident given: `assess_incident`,
`protective_action_footprint`, `population_at_risk`, `facilities_in_footprint`,
`receiving_hospitals`, `material_response_guidance`, and the flag evaluator over their
`flag_inputs`. The block list is the held FEMA form's (`ics201.yaml`, `ics-201` v3).
Update cadence and as-of: each tool's, carried in each sentence's source tag.

The tools are run here, from the incident, rather than taken from the caller: so every
sentence's receipt is a path into an output this server produced (HB-08 decided the same
for the footprint, which re-derives the assessment). No model writes any sentence: each
is a template filled from a tool output value, or an ERG sentence quoted from a pack.
Every sentence of Blocks 1, 5, 7 and 10 carries at least one receipt, a tool output path
or an ERG locator (Block 1: or the request), or the build fails; every sentence that is
not a marked ERG quotation or Block 1's name is checked by `stylecheck`, and the
findings are returned (`style_findings`; the tests hold them at none).

The form's blocks, numbered as the form numbers them (SB-STR-03): 1 Incident Name (the
TIGERweb place or county and state at the spill, HB-11b); 2 Incident Number (the
Incident Commander's); 3 Date/Time Initiated; 4 Map/Sketch (an SVG sketch of the
footprint GeoJSON over TIGERweb roads, `ics201_map`, then the ERG app link,
SB-STR-09); 5 Situation Summary and Health and Safety Briefing (where the spill is, the
material and its distances, the printed flags each with what it fired on, population,
facilities, and under each the limits that change how its numbers read); 6 Prepared by
(the server and its pack versions; name and signature the Incident Commander's); 7
Current and Planned Objectives (the ERG's protective action sentences); 8 Current and
Planned Actions, Strategies, and Tactics and 9 Current Organization (the Incident
Commander's); 10 Resource Summary (the nearest receiving hospitals as a table). After
the form, Annex A: every limit and every source with its as-of (HB-11b step 1).
"""

from __future__ import annotations

import functools
import re
from datetime import datetime
from typing import Literal

from pydantic import Field

from hazbrief import (
    __version__,
    facilities,
    flags,
    geometry,
    ics201,
    ics201_map,
    nws,
    place,
    stylecheck,
)
from hazbrief.ics201 import (
    Outputs,
    doc_receipt,
    locator_receipt,
    mdy,
    page_of,
    quotation,
    sentence,
    with_page,
)
from hazbrief.incident import assess, candidate_of, placard_words
from hazbrief.models import (
    FacilitiesInput,
    Ics201Input,
    PopulationInput,
    ReceivingInput,
    json_string_notices,
)
from hazbrief.packs import default_packs
from hazbrief.tools import facilities_in_footprint as fif
from hazbrief.tools import population_at_risk as par
from hazbrief.tools import receiving_hospitals as rh
from hazbrief.tools.material_response_guidance import guidance
from hazbrief.tools.protective_action_footprint import (
    GOVERNING_TAG,
    LINK_EDITION_LIMIT,
    LOC_MOST_CONSERVATIVE,
    display_time,
    fired_flags,
    footprint,
    merge_flags,
)
from hazbrief.utils import UpstreamServiceError

A, FP, POP, FAC, REC, MRG, FLAGS = (
    "assess_incident",
    "protective_action_footprint",
    "population_at_risk",
    "facilities_in_footprint",
    "receiving_hospitals",
    "material_response_guidance",
    "flag_evaluator",
)
#: HB-11b: the TIGERweb place at the spill (Block 1, Block 5) and the sketch's basemap
#: (Block 4), kept beside the tool outputs so their sentences carry receipts like any.
PLACE, BASEMAP = "tigerweb_place", "tigerweb_basemap"
#: HB-18 (A-2): the spill point's time zone, from NWS's points endpoint, so Block 3
#: prints local time beside UTC whatever the wind's source.
TZ = "nws_time_zone"
#: The tools whose `limits` the briefing and Annex A read, in print order.
LIMIT_TOOLS = (A, FP, POP, FAC, REC, MRG)
#: The blocks whose every sentence must carry a receipt (HB-11 step 4; Block 1, the
#: incident name, since HB-94, review L5-6).
RECEIPTED_BLOCKS = (1, 5, 7, 10)
#: receiving_hospitals' eight compass points, as words.
DIRECTION_WORDS = {
    "N": "north",
    "NE": "northeast",
    "E": "east",
    "SE": "southeast",
    "S": "south",
    "SW": "southwest",
    "W": "west",
    "NW": "northwest",
}
PREAMBLE = (
    "Draft for the Incident Commander to review, correct and sign. hazbrief assembled "
    "it from public data; no model wrote any sentence."
)


class ReceiptError(RuntimeError):
    """A sentence of Block 1, 5, 7 or 10 carries no receipt: the build fails (HB-11
    step 4)."""


def _num(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.1f}"


@functools.lru_cache(maxsize=1)
def _max_words() -> int:
    """SB-SEN-01's limit, from STYLECHECK.yaml (never restated here)."""
    return stylecheck.load_config().max_sentence_words


def _words(text: str) -> int:
    """Words as stylecheck counts them: tokens with a letter or digit."""
    return sum(1 for w in text.split() if any(c.isalnum() for c in w))


def _name_sentences(names: list[str], cfg: dict, render) -> list[tuple[int, list]]:
    """The names to print (at most `max_names`), grouped into sentences of at most
    `names_per_sentence` names whose rendering stays within SB-SEN-01's limit; a single
    name longer than that is still printed, and stylecheck reports it. Returns (index
    of the group's first name, the names)."""
    shown = names[: cfg["max_names"]]
    groups: list[tuple[int, list]] = []
    for i, name in enumerate(shown):
        if groups:
            first, group = groups[-1]
            trial = [*group, name]
            if (
                len(trial) <= cfg["names_per_sentence"]
                and _words(render(trial)) <= _max_words()
            ):
                group.append(name)
                continue
        groups.append((i, [name]))
    return groups


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


_WORD = re.compile(r"[A-Za-z0-9']+")


def title_case(name: str) -> str:
    """A name the CMS file prints in capitals, in title case (HB-11b step 3): word by
    word, keeping the acronyms ics201.yaml `names.upper` lists, lower-casing its minor
    words after the first, and giving a system its own casing (`names.mixed`). An
    apostrophe does not start a word ("St Luke's", where str.title gives "Luke'S"); a
    word with a digit is an identifier and keeps its letters. A name already in mixed
    case is printed as given."""
    if any(c.islower() for c in name):
        return name
    cfg = ics201.config()["names"]
    upper, lower, mixed = set(cfg["upper"]), set(cfg["lower"]), cfg["mixed"]
    first = True

    def word(m: re.Match) -> str:
        nonlocal first
        w = m.group(0)
        if any(ch.isdigit() for ch in w):
            out = w  # an identifier ("140458L", "60TH" is rare enough to leave)
        elif w in mixed:
            out = mixed[w]
        elif w in upper:
            out = w
        elif not first and w.lower() in lower:
            out = w.lower()
        else:
            out = w.capitalize()
        first = False
        return out

    return _WORD.sub(word, name)


# ── Running the tools ────────────────────────────────────────────────────────


#: What a malformed upstream payload or a corrupt cached file raises past a tool's own
#: `UpstreamServiceError` guard: a feature without `GEOID` (KeyError), a geometry that
#: is not GeoJSON (`geo.GeometryError`, a ValueError), a damaged LODES file (OSError,
#: ValueError). Review L2-4 and LN-05 F-5: one such feature took the whole form down.
#: The F-6 rule applies instead: the failure is a row in `errors` and the tool's block
#: says it is not available. A defect of this module (ReceiptError, ConfigError) is
#: not in the tuple and still stops the build.
TOOL_FAILURES = (KeyError, IndexError, TypeError, ValueError, AttributeError, OSError)


async def _as_row(tool: str, call) -> dict:
    """The tool's output, or the error answer its block prints as not available."""
    try:
        return await call
    except TOOL_FAILURES as exc:
        return {
            "error": f"{tool} failed on its input or an upstream answer: "
            f"{type(exc).__name__}: {exc}",
            "hint": "A defect, not a gap in the data: report it with the incident.",
        }


async def _run_tools(req: Ics201Input) -> tuple[dict, list]:
    """Every tool's output on this incident, and the tools that returned an error."""
    packs = default_packs()
    inc = req.incident
    errors: list[dict] = []
    out: dict = {}
    out[FP] = await footprint(inc, req.wind)
    if "error" in out[FP]:
        return out, errors
    amb = out[FP].get("ambiguity")
    # HB-18: an unresolved load is assessed and guided as its governing candidate, the
    # one whose distances the footprint prints
    gov = candidate_of(inc, packs.erg.data, amb["governing"]) if amb else None
    out[A] = assess(
        packs,
        inc.material,
        inc.container,
        inc.location.latitude,
        inc.location.longitude,
        inc.incident_time,
        inc.fire_involved,
        inc.spill_size,
        inc.where_spilled,
        guide_number=inc.guide_number,
        placard=inc.placard,
        resolved=gov,
    )
    out[MRG] = guidance(inc, resolved=gov)
    fp = out[FP]["footprint"]
    out[POP] = await _as_row(
        POP,
        par.count(
            PopulationInput(
                footprint=fp,
                incident_time=inc.incident_time,
                period=out[FP]["day_night"]["period"],
            )
        ),
    )
    out[FAC] = await _as_row(FAC, fif.list_facilities(FacilitiesInput(footprint=fp)))
    out[REC] = await _as_row(
        REC, rh.rank(ReceivingInput(location=inc.location, footprint=fp))
    )
    # module attribute, not a bound name, so a test can stand a failure in for TIGERweb
    out[PLACE] = await place.locate(inc.location.latitude, inc.location.longitude)
    out[TZ] = await _time_zone(inc, out[FP]["wind"], errors)
    for tool in (POP, FAC, REC):
        r = out[tool]
        if "error" in r:
            errors.append({"tool": tool, "error": r["error"], "hint": r.get("hint")})
        for e in r.get("errors") or []:
            errors.append({"tool": tool, **e})
    for e in out[PLACE]["errors"]:
        errors.append({"tool": PLACE, "error": e})
    # which tool supplied each value: a fired-on line's receipt is a path into it
    values: dict = {}
    value_tools: dict = {}
    for tool in (FP, POP, FAC):
        given = out[tool].get("flag_inputs") or {}
        values |= given
        value_tools |= dict.fromkeys(given, tool)
    parts = [fired_flags(packs, out[FP], values)]
    # HB-18: a non-governing candidate's flags fire on its own guide and table values,
    # read in its `ambiguity` entry; `rule_candidate` names the candidate of each
    rule_candidate: dict = {}
    seen = {f["rule_id"] for f in parts[0]["all"]}
    for i, c in enumerate(amb["candidates"] if amb else []):
        if c["governing"] or "error" in c:
            continue
        part = fired_flags(
            packs, c | {"guide": {"number": c["guide"]}}, values | c["flag_inputs"]
        )
        for f in part["all"]:
            if f["rule_id"] not in seen:
                seen.add(f["rule_id"])
                rule_candidate[f["rule_id"]] = i
        parts.append(part)
    out[FLAGS] = merge_flags(packs, parts) | {
        "values": values,
        "value_tools": value_tools,
        "rule_candidate": rule_candidate,
    }
    return out, errors


async def _time_zone(inc, wind: dict | None, errors: list) -> dict:
    """The spill point's IANA time zone (HB-18, A-2): the one the NWS points response
    gave when the footprint read the NWS grid, else that response read on its own. None,
    with the reason in `error` and in `errors`, when NWS gives none."""
    out = {"time_zone": None, "url": None, "tag": f"[{nws.POINTS_SOURCE}]"}
    if wind and wind.get("time_zone"):
        return out | {"time_zone": wind["time_zone"], "url": wind["urls"][0]}
    try:
        zone, url = await nws.time_zone_at(
            inc.location.latitude, inc.location.longitude
        )
    except UpstreamServiceError as exc:
        errors.append({"tool": TZ, "error": str(exc)})
        return out | {"error": str(exc)}
    return out | {"time_zone": zone, "url": url}


# ── Blocks ───────────────────────────────────────────────────────────────────


def _zone(o: Outputs) -> str | None:
    return o.get(TZ)["time_zone"]


def _when(o: Outputs, iso: str) -> str:
    return display_time(datetime.fromisoformat(iso), _zone(o))


def _beside_utc(o: Outputs, iso: str) -> str:
    """HB-18 (A-2): the local time with its zone, and UTC beside it in parentheses (with
    its date where the UTC date differs): "10/21/2026 07:27 EDT (11:27 UTC)". UTC alone
    when the zone is unknown."""
    local = _when(o, iso)
    if not _zone(o):
        return local
    utc_date, utc_time, _ = display_time(datetime.fromisoformat(iso), None).split()
    same_day = local.split()[0] == utc_date
    return f"{local} ({utc_time if same_day else f'{utc_date} {utc_time}'} UTC)"


#: HB-15: Block 1's name for a load with no ID number or name: the placard as read, or
#: this when there is none (a guide number given, or no placard seen).
UNIDENTIFIED_LABEL = "Unidentified load"
#: HB-16: what `response_format: concise` returns (the registered tool's default).
CONCISE_KEYS = frozenset(
    {"form", "markdown", "geojson", "errors", "pack_versions", "receipt_counts",
     "style_findings"}
)  # fmt: skip


def _material_label(o: Outputs) -> tuple[str | None, str]:
    m = o.get(A)["material"]
    if m is None:  # an unidentified load (HB-15)
        ib = o.get(A)["identified_by"]
        if ib["entry_point"] == "index_name":  # HB-17: a name with no ID number
            return ib["name"], UNIDENTIFIED_LABEL
        if ib["entry_point"] == "placard" and ib["placard"] != "none":
            return f"{placard_words(ib['placard'])} placard", UNIDENTIFIED_LABEL
        return None, UNIDENTIFIED_LABEL
    name = m["matched_name"] or (m["names"][0] if len(m["names"]) == 1 else None)
    return name, m["id_number"]


def _or(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"


def _unresolved_label(amb: dict) -> str:
    """HB-18: Block 1's name for an unresolved load: every candidate, each with its
    guide."""
    short = []
    for c in amb["candidates"]:
        if c["entry_point"] == "placard":
            short.append(f"{placard_words(c['placard'])} (Guide {c['guide']})")
        elif c["id_number"] is None:
            short.append(f"{c['names'][0]} (Guide {c['guide']})")
        elif amb["kind"] == "id_number":
            short.append(f"{c['id_number']} (Guide {c['guide']})")
        else:
            short.append(f"{c['names'][0]} ({c['id_number']}, Guide {c['guide']})")
    return f"Unresolved: {_or(short)}"


def _named_place(o: Outputs) -> bool:
    """TIGERweb named the spill's county and its state, so the name can use them."""
    c = o.get(PLACE)["county"]
    return bool(c and c["state"])


def _material_receipt(o: Outputs) -> dict:
    """The receipt of the material Block 1's name gives (HB-94, review L5-6): the
    candidates of an unresolved load, the ID number of an identified one, else what the
    unidentified load was known by."""
    if o.get(FP).get("ambiguity"):
        return o.receipt(FP, "ambiguity.candidates")
    a = o.get(A)
    if a["material"] is not None:
        return o.receipt(A, "material.id_number")
    ib = a["identified_by"]
    if ib["entry_point"] == "index_name":
        return o.receipt(A, "identified_by.name")
    if ib["entry_point"] == "placard":
        return o.receipt(A, "identified_by.placard")
    return o.receipt(A, "guide.number")


def block_1(req: Ics201Input, o: Outputs, cfg: dict) -> dict:
    """The caller's name, else "<material> release, <place or county>, <state>, <date>"
    from TIGERweb; without a TIGERweb county, the spill point as given (Annex A says
    so). HB-94 (review L5-6): the name is a sentence with receipts, printed as the
    form's field (`field`), so the first line a commander reads is gated and labelled
    like Block 5's: the place, county and state from TIGERweb, the material, and the
    date from the incident. A caller's name carries a `request` receipt: the request
    gave it, and no tool output holds it."""
    field = "Incident Name"
    if req.incident_name:
        rc = {"kind": "request", "path": "incident_name", "value": req.incident_name}
        return _block_1_sentence(sentence(req.incident_name, [rc], field=field))
    label, id_number = _material_label(o)
    amb = o.get(FP).get("ambiguity")
    if amb:
        label = _unresolved_label(amb)
    date = _when(o, req.incident.incident_time.isoformat()).split()[0]
    pl = o.get(PLACE)
    receipts = [_material_receipt(o), o.receipt(A, "incident.incident_time")]
    if _named_place(o):
        name = cfg["form"]["incident_name"].format(
            material=label or id_number,
            where=pl["place"]["basename"] if pl["place"] else pl["county"]["name"],
            state=pl["county"]["state"],
            date=date,
        )
        where = "place.basename" if pl["place"] else "county.name"
        receipts = [
            o.receipt(PLACE, where),
            o.receipt(PLACE, "county.state"),
        ] + receipts
    else:
        loc = req.incident.location
        name = cfg["form"]["incident_name_fallback"].format(
            material=label or id_number,
            latitude=loc.latitude,
            longitude=loc.longitude,
            date=date,
        )
        receipts = [
            o.receipt(PLACE, "county"),
            o.receipt(A, "incident.location.latitude"),
            o.receipt(A, "incident.location.longitude"),
        ] + receipts
    return _block_1_sentence(sentence(name, receipts, field=field))


def _block_1_sentence(s: dict) -> dict:
    return {"fields": {}, "sections": [{"heading": None, "sentences": [s]}]}


def block_3(req: Ics201Input, o: Outputs, cfg: dict) -> dict:
    when = _beside_utc(o, req.incident.incident_time.isoformat())
    date, time = when.split(maxsplit=1)
    dn = o.get(FP)["day_night"]
    label = cfg["guidance"]["erg_label"]
    tz = o.get(TZ)
    zone = (
        sentence(
            f"Local times are in {tz['time_zone']}, the zone NWS gives for the spill "
            f"point {tz['tag']}.",
            [o.receipt(TZ, "time_zone"), o.receipt(TZ, "url")],
        )
        if tz["time_zone"]
        else sentence(
            f"Times are UTC: NWS gave no time zone for the spill point {tz['tag']}.",
            [o.receipt(TZ, "error")],
        )
    )
    if dn["sunrise"] is None:
        # Polar day or night (review L2-1): no sunrise or sunset near the time, and the
        # footprint says how it decided instead (`incident.day_or_night`).
        sun = sentence(
            f"It is {dn['word']} at the spill. {dn['note']} [{label} Table 1 how to "
            "use, the sun's elevation by the NOAA solar equations].",
            [o.receipt(FP, "day_night.word"), o.receipt(FP, "day_night.note")],
        )
    else:
        sun = sentence(
            f"It is {dn['word']} at the spill: sunrise "
            f"{_beside_utc(o, dn['sunrise'])}, sunset "
            f"{_beside_utc(o, dn['sunset'])} [{label} Table 1 how to use, "
            "sunrise and sunset by the NOAA solar equations].",
            [
                o.receipt(FP, "day_night.word"),
                o.receipt(FP, "day_night.sunrise"),
                o.receipt(FP, "day_night.sunset"),
            ],
        )
    return {
        "fields": {
            "Date": date,
            "Time": time,
            "As given": req.incident.incident_time.isoformat(),
        },
        "sections": [{"heading": None, "sentences": [sun, zone]}],
    }


def _point(coords: list, props: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coords},
        "properties": props,
    }


def _map(req: Ics201Input, o: Outputs, cfg: dict) -> dict:
    """Block 4's GeoJSON: the footprint, the wind arrow, the facilities and crossings as
    points, the receiving hospitals as points outside."""
    fp = o.get(FP)
    features = [dict(f) for f in fp["footprint"]["features"]]
    w = fp["wind"]
    lat, lon = req.incident.location.latitude, req.incident.location.longitude
    if w:
        up = facilities.destination(
            lat, lon, w["direction_deg_from"], cfg["briefing"]["wind_arrow_m"]
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [up.x, up.y],
                        [
                            round(lon, geometry.COORDINATE_DECIMALS),
                            round(lat, geometry.COORDINATE_DECIMALS),
                        ],
                    ],
                },
                "properties": {
                    "layer": "wind",
                    "from_deg": w["direction_deg_from"],
                    "speed_kmh": w["speed_kmh"],
                    "as_of": w["as_of"],
                    "text": f"from the {w['direction_from_compass']} at "
                    f"{_num(w['speed_kmh'])} km/h",
                },
            }
        )
    fac = o.get(FAC)
    if fac and "error" not in fac:
        for section, layer in (
            ("schools", "school"),
            ("hospitals", "hospital_in_footprint"),
            ("nursing_homes", "nursing_home"),
            ("emergency_services", "emergency_service"),
        ):
            for f in fac.get(section) or []:
                features.append(
                    _point(
                        f["coordinates"],
                        {"layer": layer, "name": f["name"], "zone": f["zone"]},
                    )
                )
        for c in (fac.get("rail") or {}).get("crossings") or []:
            features.append(
                _point(
                    c["coordinates"],
                    {
                        "layer": "grade_crossing",
                        "name": c["crossing_id"],
                        "zone": c["zone"],
                    },
                )
            )
    rec = o.get(REC)
    if rec and "error" not in rec:
        for h in rec["hospitals"]:
            features.append(
                _point(
                    h["coordinates"],
                    {
                        "layer": "receiving_hospital",
                        "name": h["name"],
                        "beds": h["beds"],
                        "distance_km": h["distance_km"],
                        "crosses_footprint": h["crosses_footprint"],
                    },
                )
            )
        for h in rec["inside_footprint"]:
            features.append(
                _point(
                    h["coordinates"],
                    {
                        "layer": "hospital_in_footprint",
                        "name": h["name"],
                        "zone": h["zone"],
                    },
                )
            )
    return {"type": "FeatureCollection", "features": features}


def block_4(o: Outputs, geojson: dict, href: str) -> dict:
    fp = o.get(FP)
    link = fp["verify_in_erg_app"]
    if link:
        lines = [
            sentence(
                f"Check against the PHMSA ERG app: {link}.",
                [o.receipt(FP, "verify_in_erg_app")],
                link=link,
            ),
            sentence(
                "The app may use ERG 2020 distances.",
                [o.receipt(FP, f"limits.{fp['limits'].index(LINK_EDITION_LIMIT)}")],
            ),
            sentence(
                "This footprint uses ERG 2024.", [o.receipt(FP, "pack_versions.erg")]
            ),
        ]
    elif fp["material"] is None:  # HB-15: the app draws a named material
        no_id = (fp.get("identified_by") or {}).get("entry_point") == "index_name"
        lines = [
            sentence(
                "No ERG app link: the app draws a material by ID number, and this one "
                "has none."
                if no_id
                else "No ERG app link: the app draws a named material, and none is "
                "identified.",
                [o.receipt(FP, "verify_in_erg_app")],
            )
        ]
    else:
        lines = [
            sentence(
                "No ERG app link: the footprint has no wind to draw it with.",
                [o.receipt(FP, "verify_in_erg_app")],
            )
        ]
    bm = o.get(BASEMAP)
    if "error" in bm:
        lines.append(
            sentence(
                "The sketch has no basemap; TIGERweb returned no image.",
                [o.receipt(BASEMAP, "error")],
            )
        )
    layers: dict[str, int] = {}
    for f in geojson["features"]:
        p = f["properties"]
        # a facility point carries the zone it is in; it is counted by its layer
        key = p.get("layer") or p.get("zone")
        layers[key] = layers.get(key, 0) + 1
    # the sketch is the picture (HB-11b step 5); the GeoJSON's layer counts stay in the
    # JSON for a client that draws its own
    summary = (
        "The `geojson` output: "
        + "; ".join(f"{k.replace('_', ' ')} {v}" for k, v in layers.items())
        + "."
    )
    return {
        "geojson": "geojson",
        "map_summary": summary,
        "map": {
            "svg": "map_svg",
            "href": href,
            "alt": "Block 4 sketch: the protective action footprint, the wind, the "
            "facilities and the receiving hospitals over TIGERweb roads",
            "basemap": o.receipt(BASEMAP, "error" if "error" in bm else "url"),
        },
        "sections": [{"heading": None, "sentences": lines}],
    }


def _distance_sentences(o: Outputs, cfg: dict) -> list[dict]:
    fp = o.get(FP)
    zones = fp["zones"]
    guide_page = page_of(o.get(MRG)["guide"]["locators"]["public_safety"])
    out = []
    table = "protective_action_zone" in zones
    row_page = page_of(fp["table_row"]["locator"]) if table else guide_page

    def tag(z: str) -> str:
        return with_page(zones[z]["tag"], row_page if table else guide_page)

    iso = zones["initial_isolation_zone"]
    if table:
        out.append(
            sentence(
                f"The initial isolation distance is {iso['distance']['text']} "
                f"{tag('initial_isolation_zone')}.",
                [
                    o.receipt(FP, "zones.initial_isolation_zone.distance.text"),
                    locator_receipt(fp["table_row"]["locator"]),
                ],
            )
        )
        pad = zones["protective_action_zone"]
        out.append(
            sentence(
                f"The protective action distance is {pad['distance']['text']}, "
                f"downwind to the {fp['flag_inputs']['downwind_direction']} "
                f"{tag('protective_action_zone')}.",
                [
                    o.receipt(FP, "zones.protective_action_zone.distance.text"),
                    o.receipt(FP, "flag_inputs.downwind_direction"),
                    locator_receipt(fp["table_row"]["locator"]),
                ],
            )
        )
        if pad.get("note"):
            out.append(
                sentence(
                    pad["note"],
                    [o.receipt(FP, "zones.protective_action_zone.note")],
                )
            )
    else:
        out.append(
            sentence(
                f"The initial isolation distance is {iso['distance']['text']} in all "
                "directions, the guide's immediate precautionary measure "
                f"{tag('initial_isolation_zone')}.",
                [
                    o.receipt(FP, "zones.initial_isolation_zone.distance.text"),
                    doc_receipt(cfg["guidance"]["erg_doc"], guide_page),
                ],
            )
        )
    guide_zones = {
        "large_spill_downwind": "For a large spill, the guide gives {d} downwind for "
        "initial evacuation {t}.",
        "large_spill_evacuation": "For a large spill, the guide gives {d} in all "
        "directions for initial evacuation {t}.",
        "fire_isolation": "With a tank in fire, the guide isolates {d} in all "
        "directions {t}.",
        "fire_evacuation": "With a large fire, the guide gives {d} in all directions "
        "for initial evacuation {t}.",
    }
    for z, template in guide_zones.items():
        if z not in zones:
            continue
        t = with_page(zones[z]["tag"], guide_page)
        out.append(
            sentence(
                template.format(d=zones[z]["distance"]["text"], t=t),
                [
                    o.receipt(FP, f"zones.{z}.distance.text"),
                    doc_receipt(cfg["guidance"]["erg_doc"], guide_page),
                ],
            )
        )
        ce = zones[z].get("consider_evacuation")
        if ce:
            out.append(
                sentence(
                    f"It also gives {ce['text']} in all directions for initial "
                    f"evacuation {t}.",
                    [
                        o.receipt(FP, f"zones.{z}.consider_evacuation.text"),
                        doc_receipt(cfg["guidance"]["erg_doc"], guide_page),
                    ],
                )
            )
    return out


def _place_sentence(o: Outputs) -> dict:
    """Block 5's first sentence (HB-11b step 4): where the spill is, from TIGERweb."""
    pl = o.get(PLACE)
    if not _named_place(o):
        return sentence(
            "TIGERweb names no county at the spill point; Annex A says why.",
            [o.receipt(PLACE, "county")],
        )
    c, p = pl["county"], pl["place"]
    where = f"{c['name']}, {c['state']}"
    receipts = [o.receipt(PLACE, "county.name"), o.receipt(PLACE, "county.state")]
    if p:
        where = f"{p['name']}, {where}"
        receipts.insert(0, o.receipt(PLACE, "place.name"))
    return sentence(f"The spill is in {where} {pl['tag']}.", receipts)


def _load_sentences(o: Outputs, cfg: dict) -> list[dict]:
    """What the load is and how it reached its guide: the material from the yellow
    index, or for an unidentified load (HB-15) the placard and the placard table, or the
    guide number the incident report gave."""
    a = o.get(A)
    label = cfg["guidance"]["erg_label"]
    guide = a["guide"]["number"]
    if a["material"] is not None:
        name, id_number = _material_label(o)
        yellow = a["basis"][0]["locator"]
        what = f"{name} ({id_number})" if name else id_number
        return [
            sentence(
                f"The material is {what}, {label} Guide {guide} "
                f"[{label} yellow index, {id_number}, PDF p. {page_of(yellow)}].",
                [
                    o.receipt(A, "material.id_number"),
                    o.receipt(A, "guide.number"),
                    locator_receipt(yellow),
                ],
            )
        ]
    # The two facts that change how every distance below reads are stated here, as the
    # situation, not as limits: the tools' own limit sentences go to Annex A, which
    # keeps Block 5 within HB-11b's eight printed limits.
    ib = a["identified_by"]
    if ib["entry_point"] == "index_name":
        return _index_name_sentences(o, ib, label, guide)
    table = f"{label} Table of Markings, Labels and Placards"
    if ib["entry_point"] == "guide_number":
        out = [
            sentence(
                f"The material is not identified; the incident report gives {label} "
                f"Guide {guide} [incident report].",
                [
                    o.receipt(A, "identified_by.entry_point"),
                    o.receipt(A, "guide.number"),
                ],
            )
        ]
    else:
        seen = (
            "no placard can be seen"
            if ib["placard"] == "none"
            else f"the placard is {placard_words(ib['placard'])}"
        )
        out = [
            sentence(
                f"The material is not identified, and {seen} [incident report].",
                [o.receipt(A, "identified_by.placard")],
            ),
            sentence(
                f"The placard table gives {label} Guide {guide} "
                f"[{table}, PDF p. {page_of(ib['locator'])}].",
                [
                    o.receipt(A, "identified_by.guide"),
                    locator_receipt(ib["locator"]),
                ],
            ),
        ]
    use = cfg["guidance"]["placard_table_use_locator"]
    return out + [
        sentence(
            f"Table 1 needs the ID number or name, so Guide {guide}'s distances apply "
            f"[{label} Table 1].",
            [o.receipt(A, "erg_table.table"), o.receipt(A, "erg_table.reason")],
        ),
        sentence(
            "Once the ID number is known, use the material's own guide "
            f"[{table}, PDF p. {page_of(use)}].",
            [o.receipt(A, "limits.0"), locator_receipt(use)],
        ),
    ]


#: HB-18: how Block 5 names the zone that gives a candidate's farthest distance.
REACH_WORDS = {
    "initial_isolation_zone": "the initial isolation distance",
    "protective_action_zone": "the protective action distance, downwind",
    "large_spill_downwind": "downwind for a large spill",
    "large_spill_evacuation": "in all directions for a large spill",
    "fire_isolation": "in all directions with a tank in fire",
    "fire_evacuation": "in all directions with a large fire",
}


def _candidate_sentences(o: Outputs, cfg: dict) -> list[dict]:
    """HB-18: Block 5's first lines for an unresolved load: how many candidates, each
    with the farthest distance its guide or table gives, which one governs, and each
    candidate whose guide sends a spill to Table 1, which needs the material."""
    fp = o.get(FP)
    amb = fp["ambiguity"]
    erg = cfg["guidance"]["erg_label"]
    n = amb["candidate_count"]
    source = (
        f"{erg} Table of Markings, Labels and Placards"
        if amb["kind"] == "placard"
        else f"{erg} yellow index"
    )
    out = [
        sentence(
            f"The load is not identified: as reported, it matches {n} candidates "
            f"[{source}].",
            [
                o.receipt(FP, "ambiguity.candidate_count"),
                o.receipt(FP, "ambiguity.input"),
            ],
        )
    ]
    referred = []
    for i, c in enumerate(amb["candidates"]):
        at = f"ambiguity.candidates.{i}"
        if "error" in c:
            out.append(
                sentence(
                    f"{c['label']} has no footprint; the footprint tool's limits say "
                    "why.",
                    [o.receipt(FP, f"{at}.error")],
                )
            )
            continue
        reach = c["reach"]
        loc = next(
            b["locator"]
            for b in c["basis"]
            if b["tag"] == reach["tag"] and b.get("locator")
        )
        out.append(
            sentence(
                f"{c['label']}: up to {reach['text']}, {REACH_WORDS[reach['zone']]} "
                f"{with_page(reach['tag'], page_of(loc))}.",
                [
                    o.receipt(FP, f"{at}.label"),
                    o.receipt(FP, f"{at}.reach.text"),
                    locator_receipt(loc),
                ],
            )
        )
        sends = f"Guide {c['guide']} sends a spill to Table 1"
        k = next((k for k, t in enumerate(c["limits"]) if t.startswith(sends)), None)
        if k is not None:
            referred.append((i, c, k))
    gov = amb["candidates"][amb["governing"]]
    out.append(
        sentence(
            f"The distances below are the largest, those of {gov['label']} "
            f"[{GOVERNING_TAG}, PDF p. {page_of(LOC_MOST_CONSERVATIVE)}].",
            [
                o.receipt(FP, "ambiguity.governing"),
                o.receipt(FP, f"ambiguity.candidates.{amb['governing']}.label"),
                locator_receipt(LOC_MOST_CONSERVATIVE),
            ],
        )
    )
    for i, c, k in referred:
        out.append(
            sentence(
                f"Guide {c['guide']} sends a spill to Table 1, which needs the "
                f"material [{erg} Guide {c['guide']}].",
                [o.receipt(FP, f"ambiguity.candidates.{i}.limits.{k}")],
            )
        )
    return out


def _index_name_sentences(o: Outputs, ib: dict, label: str, guide: str) -> list:
    """HB-17: a name the yellow index prints with no ID number (the explosives): the
    row, the source of an alias the report used, and why the guide's distances apply
    (ERG p. 30, Note 2)."""
    out = [
        sentence(
            f"The material is {ib['name']}, {label} Guide {guide} "
            f"[{label} yellow index, PDF p. {page_of(ib['locator'])}].",
            [
                o.receipt(A, "identified_by.name"),
                o.receipt(A, "guide.number"),
                locator_receipt(ib["locator"]),
            ],
        )
    ]
    if ib["alias"]:
        section = ib["alias_source"]["locator"].split("#")[1]
        out.append(
            sentence(
                f"{ib['alias']}, as reported, is this mixture's abbreviation "
                f"[49 CFR {section}].",
                [
                    o.receipt(A, "identified_by.alias"),
                    o.receipt(A, "identified_by.alias_source.quote"),
                ],
            )
        )
    note = ib["note"]["locator"]
    out.append(
        sentence(
            "The ERG lists explosives by division, not by ID number, so Guide "
            f"{guide}'s distances apply [{label} yellow index, Note 2, PDF p. "
            f"{page_of(note)}].",
            [
                o.receipt(A, "identified_by.note.quote"),
                o.receipt(A, "erg_table.table"),
                locator_receipt(note),
            ],
        )
    )
    return out


def _situation(o: Outputs, cfg: dict) -> list[dict]:
    a, fp = o.get(A), o.get(FP)
    label = cfg["guidance"]["erg_label"]
    guide = a["guide"]["number"]
    mrg = o.get(MRG)
    load = _candidate_sentences if fp.get("ambiguity") else _load_sentences
    out = [_place_sentence(o), *load(o, cfg)]
    if mrg["guide"]["title"]:
        loc = mrg["guide"]["locators"]["potential_hazards"]
        out.append(
            sentence(
                f"Guide {guide} is {mrg['guide']['title']} "
                f"[{label} Guide {guide}, PDF p. {page_of(loc)}].",
                [o.receipt(MRG, "guide.title"), locator_receipt(loc)],
            )
        )
    inc = a["incident"]
    container = inc["container"]
    size = inc["spill_size"]
    out.append(
        sentence(
            (
                "The container is unknown"
                if container == "unknown"
                else f"The container is a {container.lower()}"
            )
            + (
                "; the spill size is unknown [incident report]."
                if size == "unknown"
                else f"; the spill is {size} [incident report]."
            ),
            [o.receipt(A, "incident.container"), o.receipt(A, "incident.spill_size")],
        )
    )
    out.append(
        sentence(
            ("Fire is involved" if inc["fire_involved"] else "No fire is reported")
            + f", and the spill is on {inc['where_spilled']} [incident report].",
            [
                o.receipt(A, "incident.fire_involved"),
                o.receipt(A, "incident.where_spilled"),
            ],
        )
    )
    out += _distance_sentences(o, cfg)
    w = fp["wind"]
    if w:
        out.append(
            sentence(
                f"Wind is from the {w['direction_from_compass']} at "
                f"{_num(w['speed_kmh'])} km/h ({_num(w['speed_mph'])} mph), a "
                f"{w['band_label'].lower()} {mdy(w['tag'])}.",
                [
                    o.receipt(FP, "wind.direction_from_compass"),
                    o.receipt(FP, "wind.speed_kmh"),
                    o.receipt(FP, "wind.band"),
                ],
            )
        )
    else:
        out.append(
            sentence(
                "No wind reading is available for this incident.",
                [o.receipt(FP, "wind_error")],
            )
        )
    return out


def _doc_label(doc_id: str, cfg: dict) -> str:
    return cfg["briefing"]["doc_labels"].get(doc_id, doc_id)


def _value_words(v) -> str:
    """A flag value as printed: the tool's own text for a measured value, a count with
    thousands separators."""
    if isinstance(v, dict) and "text" in v:
        return str(v["text"])
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return _num(v)
    return str(v)


def _basis_tag(o: Outputs, tool: str, supports: str, cfg: dict) -> str:
    """The source tag a tool gives the basis it names `supports`, with the PDF page
    where the basis is an ERG locator; empty when the tool gives none."""
    for b in o.get(tool).get("basis") or []:
        if b["supports"] == supports:
            loc = b.get("locator") or ""
            if loc.startswith(f"{cfg['guidance']['erg_doc']}#p"):
                return with_page(b["tag"], page_of(loc))
            return mdy(b["tag"])
    return ""


def _rule_values(o: Outputs, rid: str) -> tuple[dict, dict]:
    """The values a fired rule read and, for each, the (tool, path) it was read at: the
    tools' `flag_inputs`, or (HB-18) for a rule a non-governing candidate fired, that
    candidate's own `flag_inputs` over them."""
    ev = o.get(FLAGS)
    values = dict(ev["values"])
    paths = {k: [t, f"flag_inputs.{k}"] for k, t in ev["value_tools"].items()}
    i = ev["rule_candidate"].get(rid)
    if i is not None:
        mine = o.get(FP)["ambiguity"]["candidates"][i]["flag_inputs"]
        values |= mine
        paths |= {k: [FP, f"ambiguity.candidates.{i}.flag_inputs.{k}"] for k in mine}
    return values, paths


def _fired_on(o: Outputs, rule, f: dict, cfg: dict) -> dict:
    """The cause line of a printed flag (HB-11b step 2): each input the rule read, with
    the value that satisfied it and its receipt, from the first cause that held. A
    guide_page term is printed only when it is the cause's only term."""
    values, paths = _rule_values(o, f["rule_id"])
    words = cfg["briefing"]["fired_on"]
    cause = flags.cause_that_held(rule, values)
    terms = [t for t in cause.terms if t.input != "guide_page" or len(cause.terms) == 1]
    clauses, receipts, records = [], [], []
    for t in terms:
        spec = words[t.input]
        rc = o.receipt(*paths[t.input])
        receipts.append(rc)
        records.append({"input": t.input, "receipt": rc})
        v = values[t.input]
        number = v["value"] if isinstance(v, dict) and "value" in v else v
        template = spec["text"]
        if isinstance(template, list):
            template = template[0] if number == 1 else template[1]
        fill = {"value": _value_words(v)}
        if t.ref:
            receipts.append(o.receipt(*paths[t.ref]))
            fill["ref"] = _value_words(values[t.ref])
        clause = template.format(**fill)
        if spec.get("moe"):
            tool, path, (one, many) = spec["moe"]
            receipts.append(o.receipt(tool, path))
            moe = o.value(tool, path)
            clause += f" (margin of error {_num(moe)} {one if moe == 1 else many})"
        tag = spec.get("tag") or (
            _basis_tag(o, spec["basis"][0], spec["basis"][1], cfg)
            if spec.get("basis")
            else ""
        )
        clauses.append(f"{clause} {tag}" if tag else clause)
    label = cfg["briefing"]["flag_kinds"][f["kind"]]
    return sentence(
        f"Fired on: {'; '.join(clauses)}.",
        receipts,
        flag=f["rule_id"],
        role="fired_on",
        priority=f["priority"],
        # HB-18 (A-5): the rule id stays in the sentence's `flag`, not in the words
        heading=f"{f['priority'].capitalize()}: {label}",
        terms=records,
    )


def _flag_sentences(o: Outputs, cfg: dict) -> list[dict]:
    ev = o.get(FLAGS)
    by_id = {f["rule_id"]: (i, f) for i, f in enumerate(ev["all"])}
    rules = {r.rule_id: r for r in default_packs().flag_rules.data.rules}
    out = []
    for rid in ev["briefing"]["rule_ids"]:
        i, f = by_id[rid]
        out.append(_fired_on(o, rules[rid], f, cfg))
        for role in ("consequence", "response"):
            st = f[role]
            if st is None:
                continue
            tag = f"[{_doc_label(st['doc_id'], cfg)}, PDF p. {st['page']}]"
            out.append(
                quotation(
                    st["quote"],
                    tag,
                    [
                        o.receipt(FLAGS, f"all.{i}.{role}.quote"),
                        doc_receipt(st["doc_id"], st["page"]),
                    ],
                    flag=rid,
                    role=role,
                    priority=f["priority"],
                )
            )
    withheld = ev["briefing"]["withheld"]
    if withheld:
        out.append(
            sentence(
                f"The briefing withholds {_plural(withheld, 'flag', 'flags')}; the "
                "`flags` output lists every one [hazbrief flag rules].",
                [o.receipt(FLAGS, "briefing.withheld")],
            )
        )
    if not ev["briefing"]["rule_ids"]:
        out.append(
            sentence(
                "No flag rule fired for this incident.",
                [o.receipt(FLAGS, "briefing.rule_ids")],
            )
        )
    return out


def _tag(basis: list, supports: str) -> str:
    return mdy(next(b["tag"] for b in basis if b["supports"] == supports))


def _population(o: Outputs) -> list[dict]:
    p = o.get(POP)
    if "error" in p:
        return [
            sentence(
                "Population counts are not available; population_at_risk returned an "
                "error.",
                [o.receipt(POP, "error")],
            )
        ]
    if p.get("reason"):
        return [
            sentence(
                "No census block overlaps the footprint, so nobody is counted there.",
                [o.receipt(POP, "reason")],
            )
        ]
    b = p["basis"]
    night = sentence(
        f"{_plural(p['nighttime']['total'], 'resident lives', 'residents live')} in "
        f"the footprint {_tag(b, 'nighttime residents')}.",
        [o.receipt(POP, "nighttime.total")],
    )
    day = sentence(
        f"{_plural(p['daytime']['workers'], 'job is', 'jobs are')} located in the "
        f"footprint {_tag(b, 'daytime workforce')}.",
        [o.receipt(POP, "daytime.workers")],
    )
    out = [day, night] if p["primary"] == "day" else [night, day]
    out.append(
        sentence(
            f"It is {'daytime' if p['primary'] == 'day' else 'nighttime'}, so the "
            f"{'daytime' if p['primary'] == 'day' else 'nighttime'} count comes first.",
            [o.receipt(POP, "primary")],
        )
    )
    gq = p["nighttime"]["group_quarters"]["total"]
    out.append(
        sentence(
            f"{_plural(gq, 'resident lives', 'residents live')} in group quarters in "
            f"the footprint {_tag(b, 'group quarters by type')}.",
            [o.receipt(POP, "nighttime.group_quarters.total")],
        )
    )
    # (one, many, the counted noun of the margin of error, one and many): ACS
    # estimates, each with its derived margin of error in the same sentence (SB-NUM-02)
    phrases = {
        "age_65_and_over": (
            "{n} person aged 65 years and over lives in the footprint",
            "{n} people aged 65 years and over live in the footprint",
            ("person", "people"),
        ),
        "disability": (
            "{n} person with a disability lives in the footprint",
            "{n} people with a disability live in the footprint",
            ("person", "people"),
        ),
        "no_vehicle_households": (
            "{n} household in the footprint has no vehicle",
            "{n} households in the footprint have no vehicle",
            ("household", "households"),
        ),
        "limited_english_households": (
            "{n} household in the footprint is limited English speaking",
            "{n} households in the footprint are limited English speaking",
            ("household", "households"),
        ),
        "group_quarters_population": (
            "{n} person in the footprint lives in group quarters",
            "{n} people in the footprint live in group quarters",
            ("person", "people"),
        ),
    }
    for key, (one, many, unit) in phrases.items():
        c = p["characteristics"].get(key)
        if c is None:
            continue
        lead = (one if c["estimate"] == 1 else many).format(n=f"{c['estimate']:,}")
        noun = unit[0] if c["moe"] == 1 else unit[1]
        out.append(
            sentence(
                f"{lead} (margin of error {c['moe']:,} {noun}) {_tag(b, key)}.",
                [
                    o.receipt(POP, f"characteristics.{key}.estimate"),
                    o.receipt(POP, f"characteristics.{key}.moe"),
                ],
            )
        )
    r = p["resilience"]
    t = _tag(b, "resilience")
    out.append(
        sentence(
            f"{_plural(r['count'], 'person', 'people')} in the footprint "
            f"{'has' if r['count'] == 1 else 'have'} three or more components of "
            "social "
            f"vulnerability {t}.",
            [o.receipt(POP, "resilience.count")],
        )
    )
    if r.get("rate") is not None:
        out.append(
            sentence(
                f"That is {r['rate']} % of "
                f"{_plural(r['universe'], 'person', 'people')}, "
                f"against {r['national_rate']} % nationally {t}.",
                [
                    o.receipt(POP, "resilience.rate"),
                    o.receipt(POP, "resilience.universe"),
                    o.receipt(POP, "resilience.national_rate"),
                ],
            )
        )
    return out


_ZONE_WORDS = {
    "isolation": "initial isolation zone",
    "protective_action": "protective action zone",
    # HB-15 (F-5b): a guide's circles, named as the footprint's zones are
    # (facilities.zone_of; HB-05 part C found a school in UN1075's fire circle, live)
    "large_spill_evacuation": "large spill evacuation zone",
    "fire_isolation": "fire isolation zone",
    "fire_evacuation": "fire evacuation zone",
    # a polygon that carries no zone name (a footprint not drawn by this server)
    "footprint": "footprint",
}


def _facilities(o: Outputs, cfg: dict) -> list[dict]:
    f = o.get(FAC)
    bc = cfg["briefing"]
    if "error" in f:
        return [
            sentence(
                "Facility lists are not available; facilities_in_footprint returned "
                "an error.",
                [o.receipt(FAC, "error")],
            )
        ]
    b = f["basis"]
    out = []
    lists = (
        ("schools", "school is", "schools are", "schools"),
        ("hospitals", "hospital is", "hospitals are", "hospitals"),
        ("nursing_homes", "nursing home is", "nursing homes are", "nursing_homes"),
        (
            "emergency_services",
            "emergency service is",
            "emergency services are",
            "emergency_services",
        ),
    )
    for section, one, many, supports in lists:
        items = f[section]
        if items is None:
            out.append(
                sentence(
                    f"The {section.replace('_', ' ')} list is not available; its "
                    "source returned an error.",
                    [o.receipt(FAC, f"counts.{section}")],
                )
            )
            continue
        t = _tag(b, supports)
        out.append(
            sentence(
                f"{_plural(len(items), one, many)} inside the footprint {t}.",
                [o.receipt(FAC, f"counts.{section}")],
            )
        )

        def inside(group, first=0, items=items):
            zones = sorted(
                {_ZONE_WORDS[items[first + k]["zone"]] for k in range(len(group))}
            )
            verb = "is" if len(group) == 1 else "are"
            return f"{_join(group)} {verb} inside the {' and the '.join(zones)}."

        for first, group in _name_sentences([i["name"] for i in items], bc, inside):
            out.append(
                sentence(
                    inside(group, first),
                    [
                        o.receipt(FAC, f"{section}.{first + k}.name")
                        for k in range(len(group))
                    ],
                )
            )
        if len(items) > bc["max_names"]:
            rest = len(items) - bc["max_names"]
            out.append(
                sentence(
                    f"The {section.replace('_', ' ')} list in the facilities output "
                    f"names the other {rest:,} [facilities_in_footprint].",
                    [o.receipt(FAC, f"counts.{section}")],
                )
            )
    w = f["waterways"]
    if w is None:
        out.append(
            sentence(
                "The waterway list is not available; its source returned an error.",
                [o.receipt(FAC, "counts.waterways")],
            )
        )
    else:
        t = _tag(b, "waterways")
        out.append(
            sentence(
                f"{_plural(w['count'], 'waterway is', 'waterways are')} inside the "
                f"footprint {t}.",
                [o.receipt(FAC, "waterways.count")],
            )
        )
        if w["count"]:
            out.append(
                sentence(
                    "A waterway touches the initial isolation zone."
                    if w["in_isolation_zone"]
                    else "No waterway touches the initial isolation zone.",
                    [o.receipt(FAC, "waterways.in_isolation_zone")],
                )
            )

        def named(group):
            return f"Named waterways inside include {_join(group)}."

        for first, group in _name_sentences(w["named"], bc, named):
            out.append(
                sentence(
                    named(group),
                    [
                        o.receipt(FAC, f"waterways.named.{first + k}")
                        for k in range(len(group))
                    ],
                )
            )
    r = f["rail"]
    if r is None:
        out.append(
            sentence(
                "The rail list is not available; its source returned an error.",
                [o.receipt(FAC, "counts.rail_segments")],
            )
        )
    else:
        t = _tag(b, "rail lines")
        segs = len(r["segments"])
        owners = f" of {_join(r['owners'])}" if r["owners"] else ""
        out.append(
            sentence(
                f"{_plural(segs, 'rail segment', 'rail segments')}{owners} "
                f"{'is' if segs == 1 else 'are'} inside the footprint, "
                f"{r['length_inside_m']:,} m of line {t}.",
                [
                    o.receipt(FAC, "counts.rail_segments"),
                    o.receipt(FAC, "rail.length_inside_m"),
                ],
            )
        )
        t = _tag(b, "grade crossings")
        xs = r["crossings"]
        out.append(
            sentence(
                f"{_plural(len(xs), 'grade crossing is', 'grade crossings are')} "
                f"inside the footprint {t}.",
                [o.receipt(FAC, "counts.grade_crossings")],
            )
        )

        def crossing(group):
            one = len(group) == 1
            return (
                f"Crossing {'number' if one else 'numbers'} {_join(group)} "
                f"{'is' if one else 'are'} inside."
            )

        for first, group in _name_sentences(
            [x["crossing_id"] for x in xs], bc, crossing
        ):
            out.append(
                sentence(
                    crossing(group),
                    [
                        o.receipt(FAC, f"rail.crossings.{first + k}.crossing_id")
                        for k in range(len(group))
                    ],
                )
            )
    rec = o.get(REC)
    if rec and "error" not in rec:
        for i, h in enumerate(rec["inside_footprint"]):
            out.append(
                sentence(
                    f"{title_case(h['name'])} is inside the "
                    f"{_ZONE_WORDS[h['zone']]}: a casualty site, not a receiving "
                    "hospital.",
                    [o.receipt(REC, f"inside_footprint.{i}.name")],
                )
            )
    return out


def _limit_class(tool: str, text: str, cfg: dict) -> dict | None:
    """The briefing entry of ics201.yaml that classes this limit, or None (annex)."""
    for e in cfg["briefing"]["limits"]["briefing"]:
        if e["tool"] == tool and re.search(e["match"], text):
            return e
    return None


def _limits(o: Outputs, cfg: dict, where: str | None = None) -> list[dict]:
    """Every tool's limits, deduplicated, in the tools' order (Annex A); with `where`,
    only the briefing-class limits that print there (HB-11b step 1)."""
    seen, out = set(), []
    for tool in LIMIT_TOOLS:
        r = o.get(tool) or {}
        for i, text in enumerate(r.get("limits") or []):
            e = _limit_class(tool, text, cfg)
            if text in seen or (where and (e is None or e["place"] != where)):
                continue
            seen.add(text)
            # the tool's words; only its ISO dates are written month/day/year
            out.append(
                sentence(
                    mdy(text),
                    [o.receipt(tool, f"limits.{i}")],
                    limit="briefing" if e else "annex",
                )
            )
    return out


def block_5(o: Outputs, cfg: dict) -> dict:
    return {
        "sections": [
            {
                "heading": "Material and protective distances",
                "sentences": _situation(o, cfg),
            },
            {"heading": "Flags", "sentences": _flag_sentences(o, cfg)},
            {
                "heading": "Population at risk",
                "sentences": _population(o) + _limits(o, cfg, "population"),
            },
            {
                "heading": "Facilities",
                "sentences": _facilities(o, cfg) + _limits(o, cfg, "facilities"),
            },
        ]
    }


def annex(o: Outputs, cfg: dict) -> dict:
    """Annex A (HB-11b step 1): every limit, every source with its as-of, each once,
    and what the briefing could not get from TIGERweb."""
    sources, seen = [], set()
    for tool in (*LIMIT_TOOLS, PLACE, BASEMAP, TZ):
        r = o.get(tool) or {}
        basis = list(enumerate(r.get("basis") or []))
        if tool in (PLACE, BASEMAP, TZ) and r.get("tag"):
            what = {
                PLACE: "place and county at the spill",
                BASEMAP: "Block 4 sketch roads and railroads",
                TZ: "the spill point's time zone",
            }[tool]
            basis = [(None, {"tag": r["tag"], "supports": what})]
        for i, b in basis:
            tag = mdy(b["tag"])
            if tag in seen:
                continue
            seen.add(tag)
            path = "tag" if i is None else f"basis.{i}.tag"
            sources.append(
                {
                    "tag": tag,
                    "supports": b["supports"],
                    "tool": tool,
                    "receipts": [o.receipt(tool, path)],
                }
            )
    notes = []
    if not _named_place(o):
        notes.append(
            sentence(
                "TIGERweb named no county at the spill point, so the incident name "
                "uses the coordinates.",
                [o.receipt(PLACE, "errors"), o.receipt(PLACE, "county")],
            )
        )
    if "error" in o.get(BASEMAP):
        notes.append(
            sentence(
                "TIGERweb returned no basemap image, so the sketch draws no roads.",
                [o.receipt(BASEMAP, "error")],
            )
        )
    return {
        "title": cfg["form"]["annex_title"],
        "limits": _limits(o, cfg),
        "notes": notes,
        "sources": sources,
    }


def block_6(o: Outputs, cfg: dict) -> dict:
    pb = cfg["form"]["prepared_by"]
    packs = default_packs()
    return {
        "fields": {
            "draft_source": pb["statement"].format(version=__version__),
            "pack_versions": {
                k: getattr(packs, k).version
                for k in ("erg", "flag_rules", "cfr172", "cameo", "hazard_classes")
            },
        },
        "sections": [],
        "blank": [
            {"field": f, "label": cfg["form"]["blank_label"]}
            for f in pb["blank_fields"]
        ],
    }


def _objective_quote(key: str, cfg: dict) -> dict:
    """An objectives sentence from ics201.yaml, found among the flag pack's ERG
    sentences; one the pack does not hold is a configuration error."""
    spec = cfg["briefing"]["objectives"][key]
    for r in default_packs().flag_rules.data.rules:
        for st in (r.consequence, r.response, *r.receipts):
            if (
                st is not None
                and st.doc_id == spec["doc_id"]
                and st.page == spec["page"]
                and st.quote == spec["quote"]
            ):
                return spec
    raise ics201.ConfigError(
        f"ics201.yaml briefing.objectives.{key}: the flag pack holds no such sentence "
        f"on {spec['doc_id']} p. {spec['page']}"
    )


def _guide_lines(o: Outputs, label: str, heading_match) -> list[dict]:
    """Quotations of the public safety lines under a matching EVACUATION
    sub-heading, from material_response_guidance's selection."""
    ps = o.get(MRG)["public_safety"]
    guide = o.get(MRG)["guide"]["number"]
    out, inside = [], False
    for i, item in enumerate(ps):
        if item["kind"] == "heading":
            inside = heading_match(item["text"])
            continue
        if inside:
            out.append(
                quotation(
                    item["text"],
                    f"[{label} Guide {guide}, PDF p. {item['page']}]",
                    [
                        o.receipt(MRG, f"public_safety.{i}.text"),
                        locator_receipt(item["locator"]),
                    ],
                )
            )
    return out


#: The areas Block 7's decision-factors sentence can name, in the order it names them:
#: the table's protective action zone, else the guide's evacuation areas (HB-17: a
#: guide-only form has no protective action zone). The fire isolation zone counts only
#: where the guide also gives an evacuation distance for it.
_DECISION_ZONES = {
    "protective_action_zone": "the protective action zone",
    "large_spill_evacuation": "the large spill evacuation zone",
    "large_spill_downwind": "the downwind evacuation area",
    "fire_isolation": "the fire isolation zone",
    "fire_evacuation": "the fire evacuation zone",
}


def _decision_zones(zones: dict) -> dict[str, str]:
    """What the ERG's evacuate-or-shelter decision is for, on this form, by zone: the
    protective action zone; else the guide's evacuation areas; else, for a guide that
    gives only its immediate precautionary measure, the initial isolation zone."""
    if "protective_action_zone" in zones:
        return {"protective_action_zone": _DECISION_ZONES["protective_action_zone"]}
    named = {
        z: words
        for z, words in _DECISION_ZONES.items()
        if z in zones and (z != "fire_isolation" or zones[z].get("consider_evacuation"))
    }
    return named or {"initial_isolation_zone": "the initial isolation zone"}


def block_7(o: Outputs, cfg: dict) -> dict:
    fp = o.get(FP)
    zones = fp["zones"]
    g = cfg["guidance"]
    label = g["erg_label"]
    out = []
    if "protective_action_zone" in zones:
        page = page_of(fp["table_row"]["locator"])
        iso, pad = zones["initial_isolation_zone"], zones["protective_action_zone"]
        out.append(
            sentence(
                f"Isolate the initial isolation zone: {iso['distance']['text']} in all "
                f"directions from the spill {with_page(iso['tag'], page)}.",
                [
                    o.receipt(FP, "zones.initial_isolation_zone.distance.text"),
                    locator_receipt(fp["table_row"]["locator"]),
                ],
            )
        )
        out.append(
            sentence(
                f"Protect people in the protective action zone: "
                f"{pad['distance']['text']} downwind, "
                f"{fp['flag_inputs']['downwind_direction']} of the spill "
                f"{with_page(pad['tag'], page)}.",
                [
                    o.receipt(FP, "zones.protective_action_zone.distance.text"),
                    o.receipt(FP, "flag_inputs.downwind_direction"),
                    locator_receipt(fp["table_row"]["locator"]),
                ],
            )
        )
        cw = _objective_quote("crosswind", cfg)
        out.append(
            quotation(
                cw["quote"],
                f"[{label}, PDF p. {cw['page']}]",
                [doc_receipt(cw["doc_id"], cw["page"])],
            )
        )
    else:
        imm = g["immediate_precautionary_heading"]
        out += _guide_lines(o, label, lambda t: t == imm)
        large = re.compile(g["spill_headings"]["large"], re.I)
        out += _guide_lines(o, label, lambda t: bool(large.search(t)))
    if fp["flag_inputs"]["fire_involved"]:
        fe = g["fire_evacuation"]["heading"]
        out += _guide_lines(o, label, lambda t: t == fe)
    page = cfg["briefing"]["objectives"]["decision_factors_page"]
    decide = _decision_zones(zones)
    out.append(
        sentence(
            f"Choose evacuation or shelter-in-place for {_join(list(decide.values()))} "
            f"from the ERG decision factors [{label} Protective Actions, "
            f"PDF p. {page}].",
            [doc_receipt(g["erg_doc"], page)]
            + [o.receipt(FP, f"zones.{z}.distance.text") for z in decide],
        )
    )
    ev = o.get(FLAGS)
    kinds = {f["rule_id"]: f["kind"] for f in ev["all"]}
    if any(
        kinds[rid].startswith(tuple(cfg["briefing"]["decision_flag_kinds"]))
        for rid in ev["briefing"]["rule_ids"]
    ):
        df = _objective_quote("decision_factors", cfg)
        out.append(
            quotation(
                df["quote"],
                f"[{label}, PDF p. {df['page']}]",
                [doc_receipt(df["doc_id"], df["page"])],
            )
        )
    return {"sections": [{"heading": None, "sentences": out}]}


def _hospital_row(o: Outputs, i: int, h: dict) -> dict:
    """One Block 10 row: hospital, beds, km, bearing, crosses zone; each cell's value
    has its receipt."""
    receipts = [
        o.receipt(REC, f"hospitals.{i}.{k}")
        for k in ("name", "beds", "distance_km", "bearing_deg", "direction")
    ]
    receipts.append(o.receipt(REC, f"hospitals.{i}.crosses_footprint"))
    crosses = h["crosses_footprint"]
    if crosses is None:
        cross = "not assessed"
    elif crosses:
        cross = f"yes, {h['line_in_protective_action_zone_m']:,} m"
        receipts.append(
            o.receipt(REC, f"hospitals.{i}.line_in_protective_action_zone_m")
        )
    else:
        cross = "no"
    return {
        "hospital": h["name"],
        "cells": [
            title_case(h["name"]),
            f"{h['beds']:,}" if h["beds"] is not None else "not reported",
            _num(h["distance_km"]),
            f"{h['bearing_deg']}° ({h['direction']})",
            cross,
        ],
        "receipts": receipts,
    }


def block_10(o: Outputs, cfg: dict) -> dict:
    """The nearest receiving hospitals as a table (HB-11b step 3): one sentence above
    it says how many were ranked and that the full list is the structured output's;
    the hospital limits print below it."""
    rec = o.get(REC)
    rs = cfg["form"]["resource_summary"]
    blank = [
        {"field": f, "label": cfg["form"]["blank_label"]} for f in rs["blank_fields"]
    ]
    if "error" in rec:
        lines = [
            sentence(
                "Receiving hospitals are not available; receiving_hospitals returned "
                "an error.",
                [o.receipt(REC, "error")],
            )
        ]
        return {"sections": [{"heading": None, "sentences": lines}], "blank": blank}
    origin = (
        "the upwind edge"
        if rec["measured_from"]["kind"] == "upwind_edge"
        else "the spill"
    )
    tag = _tag(rec["basis"], "hospitals and emergency services")
    n = len(rec["hospitals"])
    if not n:
        lines = [
            sentence(
                f"No hospital with emergency services is within {_num(rec['max_km'])} "
                f"km of {origin} {tag}.",
                [o.receipt(REC, "max_km")],
            )
        ]
        return {
            "sections": [
                {"heading": None, "sentences": lines + _limits(o, cfg, "hospitals")}
            ],
            "blank": blank,
        }
    ranked = sentence(
        f"{_plural(n, 'hospital', 'hospitals')} with emergency services "
        f"{'is' if n == 1 else 'are'} ranked within {_num(rec['max_km'])} km of "
        f"{origin}; receiving_hospitals lists every one {tag}.",
        [o.receipt(REC, "max_km")]
        + [o.receipt(REC, f"hospitals.{i}.name") for i in range(n)],
    )
    rows = [
        _hospital_row(o, i, h) for i, h in enumerate(rec["hospitals"][: rs["nearest"]])
    ]
    beds = next(i for i, b in enumerate(rec["basis"]) if b["supports"] == "beds")
    below = [
        sentence(
            "Beds come from the CMS Provider of Services file "
            f"{_tag(rec['basis'], 'beds')}.",
            [o.receipt(REC, f"basis.{beds}.tag")],
        ),
        *_limits(o, cfg, "hospitals"),
    ]
    return {
        "sections": [
            {
                "heading": None,
                "sentences": [ranked],
                "table": {"columns": rs["columns"], "rows": rows},
            },
            {"heading": None, "sentences": below},
        ],
        "blank": blank,
    }


# ── Assembly ─────────────────────────────────────────────────────────────────


def _style_text(s: dict) -> str:
    """The text stylecheck reads: SB-STR-09 prints the link itself, and the rule writes
    the sentence with "<link>" in its place, so that form is checked."""
    return s["text"].replace(s["link"], "<link>") if s.get("link") else s["text"]


async def _sketch(outputs: dict, geojson: dict, cfg: dict, errors: list) -> str:
    """Block 4's SVG (HB-11b step 5): the frame is every footprint, wind and facility
    feature and the nearest receiving hospital; the basemap is one TIGERweb export of
    it, recorded under `tigerweb_basemap`."""
    pts: list[tuple[float, float]] = []
    for f in geojson["features"]:
        g = f["geometry"]
        if f["properties"].get("layer") == "receiving_hospital":
            continue
        if g["type"] == "Point":
            pts.append(tuple(g["coordinates"]))
        elif g["type"] == "LineString":
            pts += [tuple(c) for c in g["coordinates"]]
        elif g["type"] == "Polygon":
            pts += [tuple(c) for c in g["coordinates"][0]]
    rec = outputs[REC]
    if "error" not in rec and rec["hospitals"]:
        pts.append(tuple(rec["hospitals"][0]["coordinates"]))
    fr = ics201_map.frame(pts, cfg["map"])
    bm, png = await ics201_map.basemap(fr, cfg["map"])
    outputs[BASEMAP] = bm
    if "error" in bm:
        errors.append({"tool": BASEMAP, "error": bm["error"]})
        credit = "No basemap: TIGERweb returned no image."
    else:
        credit = f"Roads: U.S. Census Bureau, {bm['tag'][1:-1]}."
    erg = cfg["guidance"]["erg_label"]
    c = outputs[PLACE]["county"]
    # HB-18 (A-4): a guide's downwind distance has no shape; the legend says so
    zones = outputs[FP]["zones"]
    notes = (
        (
            f"Downwind {zones['large_spill_downwind']['distance']['text']} (guide): "
            "no shape, none drawn",
        )
        if "large_spill_downwind" in zones
        else ()
    )
    return ics201_map.render_svg(
        geojson,
        fr,
        png,
        outputs[PLACE]["outline"],
        cfg["map"],
        label=title_case,
        attribution=f"{credit} Zones: {erg}. A sketch, not for navigation.",
        county=f"{c['name']}, {c['state']}" if c and c["state"] else "",
        notes=notes,
    )


async def assemble(req: Ics201Input, map_href: str | None = None) -> dict:
    """The form, its Markdown, its GeoJSON, its Block 4 sketch (`map_svg`, which the
    Markdown embeds as `map_href`, default ics201.yaml `map.href`), Annex A, and every
    tool output its receipts point into (`tool_outputs`; the registered tool returns
    it only when asked)."""
    cfg = ics201.config()
    outputs, errors = await _run_tools(req)
    if "error" in outputs[FP]:
        return {
            "error": outputs[FP]["error"],
            "hint": outputs[FP].get("hint"),
            "tool": FP,
        }
    o = Outputs(outputs)
    geojson = _map(req, o, cfg)
    svg = await _sketch(outputs, geojson, cfg, errors)
    label = cfg["form"]["blank_label"]
    parts = {
        1: block_1(req, o, cfg),
        3: block_3(req, o, cfg),
        4: block_4(o, geojson, map_href or cfg["map"]["href"]),
        5: block_5(o, cfg),
        6: block_6(o, cfg),
        7: block_7(o, cfg),
        10: block_10(o, cfg),
    }
    blocks = []
    for spec in cfg["form"]["blocks"]:
        n = spec["number"]
        if n in cfg["form"]["blank_blocks"]:
            b = {
                "filled_by": label,
                "sections": [],
                "blank": [{"field": spec["title"], "label": label}],
            }
        else:
            b = {"blank": [], **parts[n]}
            b["filled_by"] = "partly" if b["blank"] else "hazbrief"
        blocks.append(
            {"number": n, "title": spec["title"], "receipt": spec["receipt"], **b}
        )

    ann = annex(o, cfg)
    counts = {}
    for b in blocks:
        if b["number"] not in RECEIPTED_BLOCKS:
            continue
        ss = [s for sec in b["sections"] for s in sec["sentences"]]
        rows = [
            r for sec in b["sections"] if sec.get("table") for r in sec["table"]["rows"]
        ]
        missing = [s["text"] for s in ss if not _receipted(s, b["number"])]
        missing += [r["cells"] for r in rows if not _receipted(r, b["number"])]
        if missing:
            raise ReceiptError(f"Block {b['number']}: no receipt for {missing!r}")
        counts[str(b["number"])] = {
            "sentences": len(ss),
            "table_rows": len(rows),
            "quotations": sum(s["quotation"] for s in ss),
            "tool_receipts": sum(
                r["kind"] == "tool" for s in ss for r in s["receipts"]
            ),
            "document_receipts": sum(
                r["kind"] == "document" for s in ss for r in s["receipts"]
            ),
            "without_receipt": 0,
        }
    # Block 1's sentence is the incident name, a form field the template or the caller
    # writes, not prose: stylecheck reads prose (HB-94 made it a sentence only to carry
    # its receipts, review L5-6)
    printed = [
        (b["number"], s)
        for b in blocks
        if b["number"] != 1
        for sec in b["sections"]
        for s in sec["sentences"]
    ] + [("annex", s) for s in ann["limits"] + ann["notes"]]
    findings = [
        {
            "block": where,
            "text": s["text"],
            "rule": f.rule,
            "message": f.message,
        }
        for where, s in printed
        if not s["quotation"]
        for f in stylecheck.check(_style_text(s))
    ]
    form = {"preamble": PREAMBLE, "blocks": blocks, "annex": ann}
    ev = outputs[FLAGS]
    return {
        "form": cfg["form"]["name"],
        "blocks": blocks,
        "annex": ann,
        "geojson": geojson,
        "map_svg": svg,
        "markdown": ics201.render_markdown(form),
        "flags": {"all": ev["all"], "briefing": ev["briefing"]},
        "receipt_counts": counts,
        "style_findings": findings,
        "errors": errors,
        "pack_versions": parts[6]["fields"]["pack_versions"],
        "tool_outputs": outputs,
    }


#: HB-18 (A-6): what a detailed page carries besides its part.
PAGE_KEYS = ("form", "errors", "pack_versions", "receipt_counts", "style_findings")
BLOCK_NOTICE = {
    "notice": "block pages the detailed form; with concise it is ignored and the "
    "whole concise form is returned.",
    "parameter": "request.block",
}


def page(r: dict, part: int | str) -> dict:
    """One page of the detailed form (HB-18, A-6): a block by its number, `annex` or
    `flags`, with the keys every page carries. The pages together are the whole."""
    out = {k: r[k] for k in PAGE_KEYS if k in r} | {"block": part}
    if part in ("annex", "flags"):
        return out | {part: r[part]}
    return out | {"blocks": [b for b in r["blocks"] if b["number"] == part]}


def _receipted(s: dict, block: int) -> bool:
    """A tool output path or an ERG locator; in Block 1, also the request (a caller's
    incident name, HB-94)."""
    erg = ics201.config()["guidance"]["erg_doc"]
    return any(
        r["kind"] == "tool"
        or (r["kind"] == "document" and r["doc_id"] == erg)
        or (r["kind"] == "request" and block == 1)
        for r in s["receipts"]
    )


def register(mcp) -> None:
    default_packs()
    cfg = ics201.config()  # a malformed ics201.yaml stops the server at startup
    for key in cfg["briefing"]["objectives"]:
        if key != "decision_factors_page":
            _objective_quote(key, cfg)

    @mcp.tool(
        name="build_ics_201",
        annotations={
            "title": "Build ICS 201 Incident Briefing",
            "readOnlyHint": True,
            "openWorldHint": True,
        },
    )
    async def build_ics_201(
        request: Ics201Input,
        response_format: Literal["concise", "detailed"] | None = Field(
            default=None,
            description=(
                "As `request.response_format`, given beside the request; it wins when "
                "both are given. The whole detailed form is larger than Claude Code's "
                "default cap on a tool result (25,000 tokens); `request.block` returns "
                "it a part at a time."
            ),
        ),
        include_map_svg: bool | None = Field(
            default=None,
            description="As `request.include_map_svg`, given beside the request.",
        ),
    ) -> dict:
        """A draft ICS 201 Incident Briefing (FEMA ICS Form 201) for the incident: the
        blocks public data can fill, block by block, every sentence with its receipts,
        plus a Markdown rendering and a GeoJSON map for Block 4. The blocks that are the
        Incident Commander's (2 Incident Number, 8 Current and Planned Actions,
        Strategies, and Tactics, 9 Current Organization, and the names and signature of
        Block 6) are blank and labelled.

        Pass `request.incident` (as for protective_action_footprint), optionally `wind`
        and `incident_name`. The server runs assess_incident,
        protective_action_footprint, population_at_risk, facilities_in_footprint,
        receiving_hospitals and material_response_guidance on it and fires the flag
        rules over their outputs; Block 5 prints at most ten fired flags, high priority
        first, each as the value it fired on, then its ERG consequence and its ERG
        response. A load the ERG answers with several candidates is briefed as
        protective_action_footprint draws it: Block 1 and Block 5 name every candidate,
        the distances are the governing (largest) candidate's, and the sketch dashes
        the others. Block 10 tables the nearest five receiving hospitals. Annex A,
        after the form, lists every limit and every source with its as-of. A tool that
        fails is listed in `errors`, its lines say so, and the other blocks still fill.
        `response_format` concise (the default) returns the Markdown form, every
        sentence with its source tag, the GeoJSON, `errors` and `pack_versions`;
        detailed adds `blocks` (each sentence with its receipts), `annex` and `flags`,
        60,000 to 100,000 characters in all, above Claude Code's default cap on a tool
        result. With detailed, `request.block` returns one part (a block by number,
        annex or flags), at most about 28,000 characters; ask for each part in turn.
        `include_tool_outputs` returns the outputs the receipts point into.

        Block 4's sketch, with `include_map_svg`, is `map_svg`, an SVG the Markdown
        embeds as `ics201_block4.svg`: save it beside the Markdown under that name to
        view the two together. With it the result is over 100,000 characters, above
        Claude Code's default cap on a tool result. `geojson` carries the same
        features for a client that draws.

        Data sources: those tools' (ERG 2024 packs; NWS wind; Census DHC, ACS, LODES,
        CRE; USGS Structures and 3DHP; CMS; NTAD rail), and TIGERweb (the place and
        county at the spill, January 1, 2026 vintage; the roads image, as of the day it
        is retrieved). Update cadence and as-of: each sentence's source tag and Annex
        A. No model writes any sentence; nothing is interpolated.
        """
        # HB-16: agents put these beside the request as often as inside it
        if response_format is not None:
            request = request.model_copy(update={"response_format": response_format})
        if include_map_svg is not None:
            request = request.model_copy(update={"include_map_svg": include_map_svg})
        r = await assemble(request)
        # HB-18 (A-1): an argument sent as a JSON string, parsed once, is a notice
        r["errors"] = list(r.get("errors") or []) + json_string_notices(request=request)
        if not request.include_tool_outputs:
            r.pop("tool_outputs", None)
        # HB-16: an MCP client caps a tool result (Claude Code: 25,000 tokens by
        # default; it refused 255,690 characters, then 64,543). The sketch is opt-in,
        # and the default is the concise form (Anthropic, "Writing effective tools for
        # agents": a `response_format` enum, concise or detailed).
        if not request.include_map_svg:
            r.pop("map_svg", None)
        if request.response_format == "concise":
            r = {k: v for k, v in r.items() if k in CONCISE_KEYS | {"map_svg"}}
            r.pop("tool_outputs", None)
            if request.block is not None and "error" not in r:
                r["errors"] = r["errors"] + [BLOCK_NOTICE]
        elif request.block is not None and "error" not in r:
            r = page(r, request.block)
        r["response_format"] = request.response_format
        return r
