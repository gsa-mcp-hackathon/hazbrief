"""The `protective_action_footprint` tool: the ERG zones as GeoJSON, oriented by wind.

Data source: the ERG 2024 tables and guides in the shipped packs, and the wind: the
caller's reading, or the National Weather Service forecast grid for the point
(api.weather.gov). Update cadence: the packs change with a server release; the NWS grid
is revised through the day. As-of: the wind's `as_of` (the grid's update time, or the
caller's observation time) and the NWS response headers, returned with the result.

The zones are the ERG's own shapes (DN-005 section 4): the initial isolation zone, a
circle; for a material ERG Table 1 lists, the protective action zone, a square of the
protective action distance placed downwind with the spill at the midpoint of its upwind
side. For any other material, the guide's immediate precautionary measure as the
isolation circle and no downwind square. With fire, the guide's distance for a tank in
fire is a circle in all directions. Nothing is interpolated between bands or tables;
there is no dispersion model.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hazbrief import flags, geometry, nws
from hazbrief.config import settings
from hazbrief.incident import (
    ERG,
    PLACARD_TABLE,
    AmbiguousLoad,
    AssessmentError,
    assess,
    basis,
    choose_table,
    guide_distances,
    guide_key,
    identify_incident,
    period_word,
    placard_words,
    resolve_container,
    table_distances,
    wind_band,
)
from hazbrief.models import (
    FlagReceipt,
    IncidentInput,
    SpillSize,
    WindObservation,
    with_notices,
)
from hazbrief.packs import default_packs
from hazbrief.utils import UpstreamServiceError

KMH_PER_MPH = 1.609344
#: The 16 compass points, from north clockwise, for the stylebook's "from the west".
COMPASS = (
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
)  # fmt: skip


def compass(deg: float) -> str:
    """The nearest of the 16 compass points to a bearing in degrees; a bearing on a
    sector boundary goes to the next point clockwise (half-up, not Python's
    half-to-even `round`; review L2-8)."""
    return COMPASS[math.floor((deg % 360) / 22.5 + 0.5) % 16]


def display_time(when: datetime, zone: str | None) -> str:
    """month/day/year 24-hour time and zone (SB-NUM-06): the point's zone when NWS
    named one, else UTC."""
    tz = timezone.utc
    if zone:
        try:
            tz = ZoneInfo(zone)
        except ZoneInfoNotFoundError:
            raise RuntimeError(
                f"time zone {zone!r} is not in the zone database (tzdata)"
            ) from None
    local = when.astimezone(tz)
    return f"{local:%m/%d/%Y %H:%M} {local.tzname()}"


def _supplied_wind(w: WindObservation) -> dict:
    return {
        "speed_kmh": w.speed_kmh,
        "direction_deg_from": w.direction_deg_from % 360.0,
        "source": w.source,
        "as_of": w.observed_at.isoformat(),
        "as_of_display": display_time(w.observed_at, None),
        "origin": "caller",
    }


async def _nws_wind(lat: float, lon: float, when: datetime) -> tuple[dict, float]:
    """The NWS wind as printed, and its speed as NWS gave it, which the Table 3 band
    is read from (review L2-2: 9.96 km/h prints 10.0 and is a low wind)."""
    w = await nws.wind_at(lat, lon, when)
    update = datetime.fromisoformat(w.update_time) if w.update_time else None
    return {
        "speed_kmh": round(w.speed_kmh, 1),
        "direction_deg_from": w.direction_deg_from,
        "source": f"NWS api.weather.gov gridpoint forecast {w.grid}",
        "as_of": update.isoformat() if update else None,
        "as_of_display": display_time(update, w.time_zone) if update else None,
        "valid_from": w.valid_from.isoformat(),
        "valid_to": w.valid_to.isoformat(),
        "time_zone": w.time_zone,
        "response_headers": w.gridpoint.as_of_headers,
        "urls": [w.points.url, w.gridpoint.url],
        # "live" (fetched by this call) or "recorded" (a replayed fixture), and when the
        # exchange was fetched from api.weather.gov.
        "origin": w.gridpoint.origin,
        "fetched_at": w.gridpoint.recorded_at,
    }, w.speed_kmh


#: The ERG app link's caveat (HB-08b step 4; HB-01d, corpus/erg2020_datafiles.md
#: section 4). Every `limits` string is written to the commander stylebook (no sentence
#: over 20 words, SB-SEN-01), because build_ics_201 prints it in Block 5 (HB-11). The
#: rows the two editions differ in are LN-02's
#: (LN-02); HB-18 (A-5) took the pointer
#: out of the text, since a client cannot read the repository's lab notes.
LINK_EDITION_LIMIT = (
    "verify_in_erg_app opens PHMSA's ERG app at this material, spill size, period, "
    "surface, wind and point. Compare its drawing with this footprint. Its link "
    "specification is the ERG 2020 app's. The app may draw ERG 2020 distances; this "
    "footprint uses ERG 2024."
)
LINK_CONTAINER_LIMIT = (
    "The container is unknown, so the link names no container. The ERG app then "
    "takes the first container it lists. This footprint takes the container with the "
    "largest distances."
)
#: HB-03c: emitted only when a cell of the table row used carries a unit note. LN-04
#: (LN-04) lists the cells; HB-18 (A-5)
#: took the pointer out of the text.
UNIT_NOTE_LIMIT = (
    "The printed US-unit value of {cells} disagrees with its metric value [ERG 2024]. "
    "The footprint uses the metric value."
)
LINK_NO_WIND_LIMIT = (
    "No wind, so no verify_in_erg_app link: the ERG app needs the wind direction to "
    "draw."
)
#: HB-15: a load known only by its placard or a guide number.
UNIDENTIFIED_TABLE1_LIMIT = (
    "No Table 1 distances: Table 1 needs the material's ID number or name [ERG 2024 "
    "Table 1]."
)
UNIDENTIFIED_SPILL_LIMIT = (
    "Guide {guide} sends a spill to Table 1, which needs the material. The circle is "
    "the guide's immediate precautionary measure [ERG 2024 Guide {guide}]."
)
LINK_UNIDENTIFIED_LIMIT = (
    "No verify_in_erg_app link: the ERG app draws a named material, and none is "
    "identified."
)
UNIDENTIFIED_WATER_LIMIT = (
    "The material is not identified, so ERG Table 2 cannot say whether it gives off "
    "toxic gas in water."
)
#: HB-17: a yellow-index name with no ID number, the explosives (ERG 2024 p. 30,
#: Note 2).
NO_ID_TABLE1_LIMIT = (
    "No Table 1 distances: Table 1 lists materials by ID number, and the ERG lists "
    "explosives by division [ERG 2024 yellow index, Note 2]."
)
LINK_NO_ID_LIMIT = (
    "No verify_in_erg_app link: the ERG app draws a material by ID number, and this "
    "one has none."
)
NO_ID_WATER_LIMIT = (
    "ERG Table 2 lists by ID number, so it cannot say whether this one makes toxic gas "
    "in water."
)
#: HB-18 (A-4): an agent drew its own downwind polygon for UN1203, whose guide gives a
#: downwind distance and no shape (LN-07). The zone's note said so; the limit says it
#: where every client reads the footprint's caveats, and Annex A prints it.
NO_SHAPE_LIMIT = (
    "Guide {guide} gives {text} downwind for a large spill, and no zone shape "
    "[{erg} Guide {guide}]. The footprint draws none; a shape drawn for it is not the "
    "ERG's."
)
WATER_CHANGES_NOTHING_LIMIT = (
    "where_spilled changes nothing for this material. ERG Table 2 does not list it. "
    "Table 1 prints no entry for a spill in water."
)


def erg_app_link(
    material_name: str,
    un: str,
    latitude: float,
    longitude: float,
    wind_from_deg: float,
    spill_size: str,
    period: str,
    where_spilled: str,
    container: str | None,
    wind_band: str,
) -> str:
    """PHMSA's ERG app link for the scenario (`phmsa-erg-api-definition`; the template
    and parameter mapping of corpus/erg2020_datafiles.md section 4): the `material` path
    with `showMap=true`, values percent-encoded ("%20" for a space), `windDir` the
    direction the wind blows from rounded to whole degrees, `spillSize` large for an
    unknown size, `containerType` omitted when the container is unknown."""
    params = [
        ("materialName", material_name),
        ("materialUn", un),
        ("lat", repr(latitude)),
        ("lon", repr(longitude)),
        ("windDir", str(round(wind_from_deg) % 360)),
        ("spillSize", "small" if spill_size == "small" else "large"),
        ("timeOfDay", period),
        ("whereSpilled", where_spilled),
    ]
    if container is not None:
        params.append(("containerType", container))
    params += [("windSpeed", wind_band), ("showMap", "true")]
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params)
    return f"{settings.erg_app_material_url}?{query}"


def fired_flags(packs, assessment: dict, values: dict) -> dict:
    """The flags the footprint's values fire (HB-12b; DN-006): the material's hazard
    class rules and its guide's flags, each a rationalized alarm with its sentence,
    priority, consequence, response, the rules merged into it and its receipts. `all` is
    every fired flag, indications included (structured output); `briefing` is what a
    briefing prints (`hazbrief.flags.for_briefing`: at most ten, high first) and the
    count withheld. Response guidance (fire fighting, first aid) is not a flag; it is
    the guide's sections in the erg pack."""
    data = packs.flag_rules.data
    hc = (assessment.get("hazard_class") or {}).get("class_id")
    by_id = {r.rule_id: r for r in data.rules}
    fired, out = [], []
    for rid in flags.applicable(data, hc, assessment["guide"]["number"]):
        rule = by_id[rid]
        res = flags.evaluate(rule, values)
        if not res["fired"]:
            continue
        fired.append(rule)

        def stmt(st):
            # HB-94 (review L5-7): the text layer the quote was verified against, and
            # what a receipt supports, travel with it, so a consumer can tell a
            # text-layer quote from a Key-A one without opening the pack
            if st is None:
                return None
            out = {"doc_id": st.doc_id, "page": st.page, "quote": st.quote}
            if isinstance(st, FlagReceipt):
                out["supports"] = st.supports
            return out | {"text_layer": st.text_layer}

        out.append(
            {
                "rule_id": rid,
                "kind": rule.kind,
                "priority": rule.priority,
                "indication": rule.indication,
                "sentence": res["sentence"],
                "consequence": stmt(rule.consequence),
                "response": stmt(rule.response),
                "merged": [m.rule_id for m in rule.merged],
                "receipts": [stmt(rc) for rc in rule.receipts],
            }
        )
    shown, withheld = flags.for_briefing(fired)
    return {
        "all": out,
        "briefing": {"rule_ids": [r.rule_id for r in shown], "withheld": withheld},
    }


def merge_flags(packs, parts: list[dict]) -> dict:
    """Several `fired_flags` results as one (HB-18: the candidates of an ambiguous
    input): each rule once, the first part's sentence kept, and the briefing selection
    made again over the union (DN-006 section 3.6)."""
    by_id = {r.rule_id: r for r in packs.flag_rules.data.rules}
    seen, out = set(), []
    for p in parts:
        for f in p["all"]:
            if f["rule_id"] not in seen:
                seen.add(f["rule_id"])
                out.append(f)
    shown, withheld = flags.for_briefing([by_id[f["rule_id"]] for f in out])
    return {
        "all": out,
        "briefing": {"rule_ids": [r.rule_id for r in shown], "withheld": withheld},
    }


# ── An ambiguous input (HB-18) ──────────────────────────────────────────────

#: The flag kind an ambiguous input fires (packs/src/flag_rules.yaml FR-AMB-01).
AMBIGUOUS_KIND = "identification.ambiguous_material"
#: ERG 2024 PDF p. 9, the placard table's introduction, step 3: "If multiple placards
#: point to more than one guide, initially use the most conservative guide (i.e., the
#: guide requiring the greatest degree of protective actions)"; p. 290 states the same
#: for Table 1's names ("use the entry with the largest distances"). The degree of
#: protective action is read as the farthest distance a candidate's zones give.
LOC_MOST_CONSERVATIVE = "erg2024-en-pdf#p9"
GOVERNING_TAG = f"{PLACARD_TABLE} introduction"
GOVERNING_RULE = (
    "The governing candidate is the one whose zones give the farthest distance, then "
    "the larger initial isolation distance, then the first printed. A guide that sends "
    "a spill to Table 1 reaches only its own circle here: Table 1 needs the material."
)
AMBIGUOUS_LIMIT = (
    "The load as reported matches {count} candidates [{source}]. The distances shown "
    "are the largest among them, those of {governing} [{tag}]."
)
UNDRAWN_LIMIT = "Candidate {label} has no footprint: {error}"


def candidate_label(mat, kind: str) -> str:
    """How a candidate is named in the briefing: by guide for an ID number whose names
    carry different guides, by name and ID number for a name under several ID numbers,
    by placard for a placard several rows match."""
    if mat.entry_point == "placard":
        return f"{placard_words(mat.placard.placard)} placard, Guide {mat.guide}"
    if mat.entry_point == "index_name":
        return f"{mat.matched_name}, Guide {mat.guide}"
    if kind == "id_number":
        return f"{mat.id_number}, Guide {mat.guide}"
    return f"{mat.matched_name} ({mat.id_number}), Guide {mat.guide}"


def _describe(mat, kind: str) -> dict:
    """A candidate as the flag's receipt names it: name, ID number, guide, placard, and
    the yellow-index or placard-table locator it was read at."""
    if mat.entry_point == "placard":
        loc = mat.placard.locator
    elif mat.entry_point == "index_name":
        loc = mat.unnumbered.locator
    else:
        loc = next(n.locator for n in mat.entry.names if n.name in mat.candidate_names)
    return {
        "label": candidate_label(mat, kind),
        "id_number": mat.id_number,
        "names": list(mat.candidate_names),
        "placard": mat.placard.placard if mat.placard else None,
        "guide": mat.guide,
        "entry_point": mat.entry_point,
        "locator": loc,
    }


def _reach_m(r: dict) -> int:
    """The farthest distance a footprint's zones give, drawn or not."""
    out = 0
    for z in r["zones"].values():
        out = max(out, z["distance"]["metres"])
        ce = z.get("consider_evacuation")
        if ce:
            out = max(out, ce["metres"])
    return out


def _reach_zone(r: dict, metres: int) -> dict:
    """The zone that gives a footprint's farthest distance, and that distance as the
    ERG prints it."""
    for name, z in r["zones"].items():
        for d in (z["distance"], z.get("consider_evacuation")):
            if d and d["metres"] == metres:
                return {"zone": name, "text": d["text"], "tag": z["tag"]}
    raise ValueError(f"no zone gives {metres} m")


def ambiguous_footprint(packs, amb, results: list[dict]) -> dict:
    """The answer to an ambiguous input: one footprint per candidate, the largest
    marked governing (`GOVERNING_RULE`). The top level is the governing candidate's
    answer, so a caller that reads one footprint reads the largest, except that
    `footprint` holds
    every candidate's polygons (the union is the envelope; each polygon carries its
    `candidate` and whether it is `governing`), `flags` every candidate's fired flags
    and `ambiguous_material`, and `limits` every candidate's. `ambiguity` holds each
    candidate's own zones, table, guide and locators. Nothing is averaged, and no
    candidate is chosen by how likely it is."""
    kind = amb.kind
    mats = amb.materials
    described = [_describe(m, kind) for m in mats]
    drawn = [i for i, r in enumerate(results) if "error" not in r]
    if not drawn:  # no candidate can be drawn: the first one's reason, as for one input
        return results[0]
    reach = {i: _reach_m(results[i]) for i in drawn}

    def size(i):
        iso = results[i]["zones"]["initial_isolation_zone"]["distance"]["metres"]
        return (reach[i], iso, -i)

    g = max(drawn, key=size)
    gov = results[g]
    label = described[g]["label"]
    features = [gov["footprint"]["features"][0]]  # the spill point, once
    for i in drawn:
        for f in results[i]["footprint"]["features"][1:]:
            props = f["properties"] | {
                "candidate": i,
                "candidate_label": described[i]["label"],
                "governing": i == g,
            }
            features.append(f | {"properties": props})
    candidates = []
    for i, r in enumerate(results):
        c = described[i] | {"governing": i == g}
        if i in drawn:
            c |= {
                "reach_m": reach[i],
                "reach": _reach_zone(r, reach[i]),
                "guide_title": r["guide"]["title"],
                "hazard_class": r["hazard_class"],
                "flag_inputs": r["flag_inputs"],
                **{
                    k: r[k]
                    for k in (
                        "material",
                        "identified_by",
                        "tih",
                        "erg_table",
                        "table_row",
                        "zones",
                        "basis",
                        "verify_in_erg_app",
                        "limits",
                    )
                },  # fmt: skip
                "flags": [f["rule_id"] for f in r["flags"]["all"]],
            }
        else:
            c |= {"error": r["error"], "hint": r.get("hint")}
        candidates.append(c)
    source = PLACARD_TABLE if kind == "placard" else f"{ERG} yellow index"
    limits = [
        AMBIGUOUS_LIMIT.format(
            count=len(mats), source=source, governing=label, tag=GOVERNING_TAG
        )
    ]
    for i, r in enumerate(results):
        if i not in drawn:
            limits.append(
                UNDRAWN_LIMIT.format(label=described[i]["label"], error=r["error"])
            )
    for i in [g, *[i for i in drawn if i != g]]:
        limits += [t for t in results[i]["limits"] if t not in limits]
    values = gov["flag_inputs"] | {
        "candidate_count": len(mats),
        "governing_candidate": label,
    }
    own = fired_flags(packs, gov, values)
    for f in own["all"]:
        if f["kind"] == AMBIGUOUS_KIND:
            f["candidates"] = described
    merged = merge_flags(packs, [own] + [results[i]["flags"] for i in drawn if i != g])
    basis_ = list(gov["basis"]) + [
        basis("candidates", source, described[0]["locator"]),
        basis("governing candidate", GOVERNING_TAG, LOC_MOST_CONSERVATIVE),
    ]
    return gov | {
        "footprint": {"type": "FeatureCollection", "features": features},
        "basis": basis_,
        "flag_inputs": values,
        "flags": merged,
        "limits": limits,
        "ambiguity": {
            "input": amb.error,
            "kind": kind,
            "candidate_count": len(mats),
            "governing": g,
            "rule": GOVERNING_RULE,
            "candidates": candidates,
        },
    }


class _Wind:
    """The wind for the incident, read once however many candidates are drawn (HB-18):
    the caller's reading, else the NWS grid's, fetched on first use, so an input the ERG
    cannot answer costs no call."""

    def __init__(self, incident: IncidentInput, wind: WindObservation | None):
        self.incident, self.wind = incident, wind
        self.read, self.used, self.error = False, None, None
        #: the speed the Table 3 band is read from: the reading as given, not the
        #: printed `speed_kmh` (review L2-2)
        self.band_speed_kmh: float | None = None

    async def get(self) -> tuple[dict | None, str | None]:
        if not self.read:
            self.read = True
            if self.wind is not None:
                self.used = _supplied_wind(self.wind)
                self.band_speed_kmh = self.wind.speed_kmh
            else:
                inc = self.incident
                try:
                    self.used, self.band_speed_kmh = await _nws_wind(
                        inc.location.latitude,
                        inc.location.longitude,
                        inc.incident_time,
                    )
                except (UpstreamServiceError, nws.WindUnavailable) as exc:
                    self.error = str(exc)
        # each candidate adds its own band and tag to its copy
        return (dict(self.used) if self.used else None), self.error


async def footprint(incident: IncidentInput, wind: WindObservation | None) -> dict:
    """The tool body, apart from registration so tests can call it directly. An input
    the ERG answers with several candidates (HB-18) is drawn once per candidate and
    answered by `ambiguous_footprint`."""
    packs = default_packs()
    try:
        mats, ambiguous = [identify_incident(incident, packs.erg.data)], None
    except AmbiguousLoad as exc:
        mats, ambiguous = exc.materials, exc
    except AssessmentError as exc:
        return exc.as_dict()
    winds = _Wind(incident, wind)
    results = [await _drawn(packs, incident, mat, winds) for mat in mats]
    if ambiguous is None:
        return results[0]
    return ambiguous_footprint(packs, ambiguous, results)


async def _drawn(packs, incident: IncidentInput, mat, winds: _Wind) -> dict:
    """One material's footprint: the whole answer for a resolved input, one candidate's
    for an ambiguous one. A zone the geometry cannot draw (one crossing the
    antimeridian) is returned as `error` and `hint`, not raised: a raised error leaves
    the tool's contract (HB-89; review L3-5)."""
    try:
        return await _draw(packs, incident, mat, winds)
    except geometry.GeometryError as exc:
        return {
            "error": f"The footprint cannot be drawn here: {exc}",
            "hint": "The footprint is drawn on a local plane around the spill; a zone "
            "that crosses the antimeridian is not supported. Use the "
            "ERG distances in material_response_guidance.",
        }


async def _draw(packs, incident: IncidentInput, mat, winds: _Wind) -> dict:
    """`_drawn`'s body; a `GeometryError` raised here is returned there."""
    erg = packs.erg.data
    lat, lon = incident.location.latitude, incident.location.longitude
    try:
        assessment = assess(
            packs,
            incident.material,
            incident.container,
            lat,
            lon,
            incident.incident_time,
            incident.fire_involved,
            incident.spill_size,
            incident.where_spilled,
            guide_number=incident.guide_number,
            placard=incident.placard,
            resolved=mat,
        )
    except AssessmentError as exc:
        return exc.as_dict()
    if assessment["coverage"] == "index_only":
        return {
            "error": f"The packs carry no ERG distances for "
            f"{assessment['material']['id_number']}.",
            "hint": assessment["hint"],
            "assessment": assessment,
        }
    choice = choose_table(
        mat,
        incident.spill_size,
        resolve_container(incident.container, erg),
        incident.fire_involved,
        incident.where_spilled,
    )
    period = assessment["day_night"]["period"]
    needs_direction = choice.table in ("Table 1", "Table 3")

    wind_used, wind_error = await winds.get()
    if wind_used is None and needs_direction:
        return {
            "error": f"No wind to orient the protective action zone: {wind_error}",
            "hint": "Supply `wind` (speed in km/h, the direction it blows from in "
            "degrees, when and by whom it was observed).",
            "assessment": assessment,
        }

    out_basis = list(assessment["basis"])
    zones: dict = {}
    features = [geometry.point_feature(lat, lon, {"zone": "spill"})]
    band = None
    if wind_used is not None:
        band = wind_band(winds.band_speed_kmh, erg.table3_wind_bands)
        downwind = (wind_used["direction_deg_from"] + 180.0) % 360.0
        wind_used.update(
            speed_mph=round(wind_used["speed_kmh"] / KMH_PER_MPH, 1),
            direction_from_compass=compass(wind_used["direction_deg_from"]),
            downwind_bearing_deg=downwind,
            band=band.band,
            band_label=band.label,
        )
        tag = wind_used["source"] + (
            f", as of {wind_used['as_of_display']}"
            if wind_used["as_of_display"]
            else ""
        )
        wind_used["tag"] = f"[{tag}]"
        out_basis.append(basis("wind speed and direction", tag, None))
        out_basis.append(
            basis("wind band", f"{ERG} Table 3 wind categories", band.locator)
        )

    vertices = settings.footprint_circle_vertices
    receipt = None
    unit_noted: list = []
    if needs_direction:
        dist = table_distances(mat, choice, period, band)
        receipt = dist["row"]
        unit_noted = [
            name
            for name, d in (
                ("the initial isolation distance", dist["initial_isolation_distance"]),
                ("the protective action distance", dist["protective_action_distance"]),
            )
            if d["erg_units"].get("unit_note")
        ]
        iso, pad = (
            dist["initial_isolation_distance"],
            dist["protective_action_distance"],
        )
        tag = dist["basis"][0]["tag"]
        zones["initial_isolation_zone"] = {"distance": iso, "tag": tag}
        zones["protective_action_zone"] = {
            "distance": pad,
            "shape": "square, side equal to the protective action distance, downwind, "
            "the spill at the midpoint of its upwind side",
            "downwind_bearing_deg": wind_used["downwind_bearing_deg"],
            "tag": dist["basis"][1]["tag"],
        }
        if dist.get("container_chosen_as_largest"):
            zones["protective_action_zone"]["note"] = (
                f"Container unknown: the {receipt['container'].lower()} row, the "
                "largest distances in this material's Table 3."
            )
        features.append(
            geometry.polygon_feature(
                geometry.circle(lat, lon, iso["metres"], vertices),
                {
                    "zone": "initial_isolation_zone",
                    "radius_m": iso["metres"],
                    "text": iso["text"],
                    "tag": tag,
                },
            )
        )
        features.append(
            geometry.polygon_feature(
                geometry.downwind_square(
                    lat, lon, pad["metres"], wind_used["downwind_bearing_deg"]
                ),
                {
                    "zone": "protective_action_zone",
                    "side_m": pad["metres"],
                    "downwind_bearing_deg": wind_used["downwind_bearing_deg"],
                    "text": pad["text"],
                    "tag": dist["basis"][1]["tag"],
                },
            )
        )
        out_basis += dist["basis"]

    gd = guide_distances(erg.guides[guide_key(mat.guide)], incident.fire_involved)
    gtag = f"[{ERG} Guide {mat.guide}]"
    if not needs_direction:
        ipm = gd["immediate_precautionary"]
        zones["initial_isolation_zone"] = {
            "distance": ipm,
            "tag": gtag,
            "note": "The guide's immediate precautionary measure: isolate in all "
            "directions.",
        }
        out_basis.append(gd["basis"]["immediate_precautionary"])
        if "immediate_precautionary_solids" in gd:
            # The guide prints one distance for liquids and one for solids; the circle
            # is the liquids distance, the larger.
            zones["initial_isolation_zone"]["note"] += (
                f" The guide gives {ipm['text']} for liquids and "
                f"{gd['immediate_precautionary_solids']['text']} for solids {gtag}. "
                "The circle is the distance for liquids."
            )
            out_basis.append(gd["basis"]["immediate_precautionary_solids"])
        features.append(
            geometry.polygon_feature(
                geometry.circle(lat, lon, ipm["metres"], vertices),
                {
                    "zone": "initial_isolation_zone",
                    "radius_m": ipm["metres"],
                    "text": ipm["text"],
                    "tag": gtag,
                },
            )
        )
        if incident.spill_size != SpillSize.SMALL and "large_spill_downwind" in gd:
            zones["large_spill_downwind"] = {
                "distance": gd["large_spill_downwind"],
                "tag": gtag,
                "note": "The guide gives this downwind distance for initial "
                "evacuation but no zone shape, so none is drawn.",
            }
            out_basis.append(gd["basis"]["large_spill_downwind"])
        if (
            incident.spill_size != SpillSize.SMALL
            and "large_spill_all_directions" in gd
        ):
            le = gd["large_spill_all_directions"]
            zones["large_spill_evacuation"] = {
                "distance": le,
                "tag": gtag,
                "note": "The guide's large spill distance: consider initial evacuation "
                "in all directions.",
            }
            out_basis.append(gd["basis"]["large_spill_all_directions"])
            features.append(
                geometry.polygon_feature(
                    geometry.circle(lat, lon, le["metres"], vertices),
                    {
                        "zone": "large_spill_evacuation",
                        "radius_m": le["metres"],
                        "text": le["text"],
                        "tag": gtag,
                    },
                )
            )
    if incident.fire_involved and "fire_isolate" not in gd and "fire_evacuate" in gd:
        # Guides 161 to 166 and 172 print no fire isolation distance, only "consider an
        # initial evacuation distance of ... in all directions" for a major fire.
        fe = gd["fire_evacuate"]
        zones["fire_evacuation"] = {
            "distance": fe,
            "tag": gtag,
            "note": "The guide's distance when a large quantity or container is "
            "involved in a fire: consider initial evacuation in all directions.",
        }
        out_basis.append(gd["basis"]["fire_evacuate"])
        features.append(
            geometry.polygon_feature(
                geometry.circle(lat, lon, fe["metres"], vertices),
                {
                    "zone": "fire_evacuation",
                    "radius_m": fe["metres"],
                    "text": fe["text"],
                    "tag": gtag,
                },
            )
        )
    if incident.fire_involved and "fire_isolate" in gd:
        fi = gd["fire_isolate"]
        zones["fire_isolation"] = {
            "distance": fi,
            "tag": gtag,
            "note": "The guide's distance for a tank, rail tank car or highway tank "
            "in a fire: isolate in all directions.",
        }
        out_basis.append(gd["basis"]["fire_isolate"])
        if "fire_evacuate" in gd:
            zones["fire_isolation"]["consider_evacuation"] = gd["fire_evacuate"]
            out_basis.append(gd["basis"]["fire_evacuate"])
        features.append(
            geometry.polygon_feature(
                geometry.circle(lat, lon, fi["metres"], vertices),
                {
                    "zone": "fire_isolation",
                    "radius_m": fi["metres"],
                    "text": fi["text"],
                    "tag": gtag,
                },
            )
        )
    limits = []
    if "large_spill_downwind" in zones:
        limits.append(
            NO_SHAPE_LIMIT.format(
                guide=mat.guide,
                text=zones["large_spill_downwind"]["distance"]["text"],
                erg=ERG,
            )
        )
    if unit_noted:
        limits.append(UNIT_NOTE_LIMIT.format(cells=" and ".join(unit_noted)))
    no_id = mat.entry_point == "index_name"
    if not mat.identified:
        limits.append(NO_ID_TABLE1_LIMIT if no_id else UNIDENTIFIED_TABLE1_LIMIT)
        if erg.guides[guide_key(mat.guide)].evacuation.spill_refers_to_table1:
            limits.append(UNIDENTIFIED_SPILL_LIMIT.format(guide=mat.guide))
    mat_rows = mat.material
    water_matters = bool(mat_rows and mat_rows.where_spilled_matters) or any(
        e.spilled_in for e in (mat_rows.table1 if mat_rows else [])
    )
    if incident.where_spilled == "water" and not mat.identified:
        limits.append(NO_ID_WATER_LIMIT if no_id else UNIDENTIFIED_WATER_LIMIT)
    elif incident.where_spilled == "water" and not water_matters:
        limits.append(WATER_CHANGES_NOTHING_LIMIT)
    link = None
    if not mat.identified:
        limits.append(LINK_NO_ID_LIMIT if no_id else LINK_UNIDENTIFIED_LIMIT)
    elif wind_used is not None:
        name = (
            assessment["material"]["matched_name"] or assessment["material"]["names"][0]
        )
        link = erg_app_link(
            name,
            mat.un,
            lat,
            lon,
            wind_used["direction_deg_from"],
            choice.spill_size_used,
            period,
            incident.where_spilled,
            choice.container,
            band.band,
        )
        limits.append(LINK_EDITION_LIMIT)
        if choice.container is None:
            limits.append(LINK_CONTAINER_LIMIT)
    else:
        limits.append(LINK_NO_WIND_LIMIT)
    values = {
        "guide_page": mat.guide.rstrip("P"),
        "guide_designated_p": mat.guide.endswith("P"),
        "fire_involved": incident.fire_involved,
        "spill_size": incident.spill_size.value,
        "tih": assessment["tih"],
        "where_spilled": incident.where_spilled,
        # not known for an unidentified load: None, so no rule reads a guess
        "where_spilled_matters": bool(mat_rows and mat_rows.where_spilled_matters)
        if mat.identified
        else None,
        "table3_listed": bool(mat_rows and mat_rows.table3) if mat.identified else None,
        "footprint_present": True,
        "period": period_word(period),
    }
    if "protective_action_zone" in zones:
        pad = zones["protective_action_zone"]
        values["protective_action_distance"] = {
            "value": pad["distance"]["metres"],
            "text": pad["distance"]["text"],
        }
        values["downwind_direction"] = compass(pad["downwind_bearing_deg"])
    if "fire_isolation" in zones:
        values["fire_isolate"] = zones["fire_isolation"]["distance"]["text"]
        ce = zones["fire_isolation"].get("consider_evacuation")
        if ce:
            values["fire_evacuate"] = ce["text"]
    return {
        "material": assessment["material"],
        "identified_by": assessment.get("identified_by"),
        "guide": assessment["guide"],
        "tih": assessment["tih"],
        "erg_table": assessment["erg_table"],
        "table_row": receipt,
        "day_night": assessment["day_night"] | {"word": period_word(period)},
        "wind": wind_used,
        "wind_error": wind_error,
        "zones": zones,
        "footprint": {"type": "FeatureCollection", "features": features},
        "basis": out_basis,
        "hazard_class": assessment.get("hazard_class"),
        # the values the flag rules read, by their rule names (as population_at_risk's
        # `flag_inputs`), so a caller can evaluate rules over several tools' outputs
        "flag_inputs": values,
        "flags": fired_flags(packs, assessment, values),
        "verify_in_erg_app": link,
        "limits": limits,
        "pack_versions": assessment["pack_versions"],
    }


def register(mcp) -> None:
    default_packs()  # a missing or altered pack stops the server at startup

    @mcp.tool(
        name="protective_action_footprint",
        annotations={
            "title": "Protective Action Footprint",
            "readOnlyHint": True,
            "openWorldHint": True,
        },
    )
    async def protective_action_footprint(
        incident: IncidentInput, wind: WindObservation | None = None
    ) -> dict:
        """The ERG zones for an incident, as GeoJSON with their distances and sources.

        For a material ERG Table 1 lists: the initial isolation zone (a circle) and the
        protective action zone, the ERG's own square (its side is the protective action
        distance, downwind, the spill at the midpoint of its upwind side), from the
        Table 1 or Table 3 row for the spill size, day or night and wind band. That
        square is the only downwind shape the ERG gives. For any other material: the
        guide's immediate precautionary distance as a circle. A guide's downwind
        evacuation distance for a large spill (`zones.large_spill_downwind`) has no
        shape in the ERG, so none is drawn; do not draw one. With fire, the guide's
        isolation distance for a tank in fire, as a circle. Returns the distances in
        metres and as the ERG prints them, the table row used, the wind used (value,
        band, as-of, source), day or night, and `basis` source tags.
        `incident.where_spilled` (land, the default, or water) selects a water-reactive
        material's Table 1 entry for a spill in water (ERG Table 2). `flags` are the
        fired flag rules, each with its sentence and receipts. A load known only by its
        placard or a guide number (`placard` or `guide_number` instead of `material`)
        gets that guide's circles and no Table 1 zone, which `limits` says.

        A load the ERG answers with several candidates (a name under several ID
        numbers, an ID number whose names carry different guides, a placard that
        matches several rows) is drawn once per candidate: `ambiguity.candidates` holds
        each candidate's zones, guide and locators, and the one with the largest
        distances is `governing` (the ERG's rule: the most conservative guide). The top
        level is the governing candidate's answer, except that `footprint` holds every
        candidate's polygons (each with its `candidate` and `governing`), `flags` adds
        `ambiguous_material`, and `limits` holds every candidate's. Nothing is
        averaged. Name every candidate, and identify the material to settle it.

        `verify_in_erg_app` is PHMSA's ERG app link for the same scenario; `limits` says
        what it and the inputs cannot do (the app may draw ERG 2020 distances).

        Data source: ERG 2024 (the server's packs); wind from `wind` if given, else the
        National Weather Service forecast grid for the point (api.weather.gov), the
        period holding the incident time. Update cadence: NWS revises the grid through
        the day. As-of: `wind.as_of` and the NWS response headers. No dispersion model;
        nothing is interpolated. An input the ERG cannot answer returns `error` and a
        `hint`.
        """
        return with_notices(
            await footprint(incident, wind), incident=incident, wind=wind
        )
