"""The location record (DN-013 section 2; HB-48, HB-49).

A location is a shape with a derivation, a source and an accuracy, and every value
computed over it inherits its label. The brief builds one record for the incident's
location, the location every section reads.

**Derivations built** (DN-013 section 3, as DN-013 ADDENDUM-00 corrected it):
* `caller_supplied` (HB-48): the request's bare point. It states no accuracy, so
  `accuracy_m` is null and the label says the footprint is drawn as if the point were
  exact. A view of the footprint's tool-call record (its request and its start time),
  never a second store (DN-010 D4).
* `milepost` (HB-49): a LineString on the named route from one mile to another, in the
  unit the state service answers with. Pennsylvania: PennDOT's RMS state-road segments
  (PASDA), cut where the two interstate mile markers project onto them. Maryland: MDOT
  SHA's 10th-mile milepoints, joined in order. `accuracy_m` is the segment's length,
  `basis: segment_length`: no state LRS states a horizontal accuracy in metres
  (ADDENDUM-00 section 6). Virginia is refused: VDOT's held layer is its mile marker
  signs, which VDOT calls a legacy, unmaintained reference.
* `crossing` (HB-49): the FRA inventory's point, read through BTS NTAD, by crossing ID
  or by state, city and street. `accuracy_m` follows the inventory's own Lat/Long Source
  field, never an assumption (ADDENDUM-00 section 3).

**Pure over held records.** `fetch` makes the GETs a derivation needs through the one
upstream client (`hazbrief.utils`): live or recorded per `settings.hazbrief_http_mode`,
or, with `replay=True`, from the recorded files whatever the mode. `resolve` builds the
record from those exchanges alone, so the tests run it on recorded exchanges with no
network. The record names the exchanges it was read from (`evidence`).
"""

from __future__ import annotations

from typing import Any

import shapely
from shapely.geometry import LineString, MultiLineString, Point, mapping
from shapely.ops import linemerge, substring, unary_union

from hazbrief import facilities
from hazbrief.evidence.store import utc_now
from hazbrief.geometry import COORDINATE_DECIMALS
from hazbrief.lodes import STATE_POSTAL
from hazbrief.utils import Exchange, UpstreamServiceError, fetch_json, recorded_json

FOOTPRINT = "protective_action_footprint"
#: DN-013 section 2's derivations this module builds beside the request's bare point.
DERIVED = ("milepost", "crossing", "address", "intersection")
#: a state's FIPS code from its postal code (TIGERweb's places carry STATE as FIPS)
STATE_FIPS = {postal.upper(): fips for fips, postal in STATE_POSTAL.items()}


class LocationError(ValueError):
    """A location the held services cannot resolve to one shape: no answer, more than
    one answer, or a state with no usable service. The message says which."""


class Unavailable(RuntimeError):
    """The geocoder answered with something that is not its JSON (a redirect off the
    host, a non-JSON body, a 5xx): HB-50 ADDENDUM-00 point 3. Never retried here."""

    def __init__(self, detail: str, at: str):
        super().__init__(detail)
        self.detail, self.at = detail, at


def from_request(record: dict, cfg: dict) -> dict:
    """The record of the point the request gave, from the footprint's tool-call record.
    `as_of` is the call's start, the as-of every value the request gave carries
    (`labels.label_for`, DN-010 ADDENDUM-00)."""
    spec = cfg["location"]["caller_supplied"]
    loc = record["activity"]["params"]["incident"]["location"]
    return {
        "shape": {
            "type": "Point",
            "coordinates": [loc["longitude"], loc["latitude"]],
        },
        "derivation": spec["derivation"],
        "source": spec["source"],
        "accuracy_m": None,
        "basis": spec["basis"],
        "as_of": record["activity"]["startedAtTime"],
        "collapsed_by": None,
        "label": spec["label"],
    }


def of_brief(brief, cfg: dict) -> dict | None:
    """The brief's location record: the derived one when the scenario gave a milepost or
    a crossing (HB-49), else the request's bare point, or None while the footprint has
    no record to read the request from (pending, timed out, or missing from the
    store)."""
    if getattr(brief, "location", None):
        return brief.location
    rec = brief.channels.get(FOOTPRINT, {}).get("record")
    return from_request(rec, cfg) if rec else None


# ── the queries ───────────────────────────────────────────────────────────────────────


def _quote(value: Any) -> str:
    """A string literal for an ArcGIS `where` clause (SQL-92: a quote is doubled)."""
    return "'" + str(value).replace("'", "''") + "'"


def _route_number(route: str) -> tuple[str, int]:
    """("I", 81) from "I-81": the class and the number of a route as a scenario names
    it."""
    cls, _, num = str(route).partition("-")
    if not num.isdigit():
        raise LocationError(f"route {route!r} is not written as CLASS-NUMBER (I-81)")
    return cls.upper(), int(num)


def _query(where: str, fields: str, order: str | None = None) -> dict[str, str]:
    q = {
        "where": where,
        "outFields": fields,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    if order:
        q["orderByFields"] = order
    return q


def _miles(given: dict) -> tuple[float, float]:
    lo, hi = float(given["from_mile"]), float(given["to_mile"])
    if not lo < hi:
        raise LocationError(f"from_mile {lo} is not below to_mile {hi}")
    return lo, hi


def _pa_markers(given: dict, spec: dict) -> tuple[str, dict]:
    cls, num = _route_number(given["route"])
    lo, hi = _miles(given)
    where = (
        f"ST_RT_NO={_quote(spec['route_format'].format(num))} "
        f"AND MILE_MARKE IN ({lo:g},{hi:g})"
    )
    return spec["markers"], _query(
        where, "ST_RT_NO,SEG_NO,MILE_MARKE,TY_CODE,GIS_UPDATE", "MILE_MARKE"
    )


def _pa_segments(given: dict, spec: dict, markers: list[dict]) -> tuple[str, dict]:
    _, num = _route_number(given["route"])
    a = markers[0]["attributes"]
    b = markers[-1]["attributes"]
    where = (
        f"T_RT_NO={_quote(spec['route_format'].format(num))} "
        f"AND CTY_CODE={_quote(a['TY_CODE'])} AND SIDE_IND={_quote(spec['side'])} "
        f"AND SEG_NO>={_quote(a['SEG_NO'])} AND SEG_NO<={_quote(b['SEG_NO'])}"
    )
    return spec["segments"], _query(
        where,
        "T_RT_NO,CTY_CODE,SEG_NO,SEG_LNGTH_,CUM_OFFSET,CUM_OFFS_1,SIDE_IND",
        "SEG_NO",
    )


def _md_milepoints(given: dict, spec: dict) -> tuple[str, dict]:
    cls, num = _route_number(given["route"])
    if cls not in spec["prefixes"]:
        raise LocationError(f"MDOT SHA has no ID_PREFIX for route class {cls!r}")
    lo, hi = _miles(given)
    where = (
        f"ID_PREFIX={_quote(spec['prefixes'][cls])} AND ID_RTE_NO={num} "
        f"AND MAIN_LINE=1 AND ID_MP>={lo:g} AND ID_MP<={hi:g}"
    )
    return spec["milepoints"], _query(where, "ROUTEID,ID_MP,MP_DIRECTION", "ID_MP")


def _crossing(given: dict) -> dict[str, str]:
    fields = (
        "CrossingID,StateAbbreviation,CITYNAME,STREET,HighwayName,CrossingPosition,"
        "LatLongSource,LATITUDE,Longitude"
    )
    if given.get("crossing_id"):
        return _query(f"CrossingID={_quote(given['crossing_id'])}", fields)
    for k in ("state", "city", "street"):
        if not given.get(k):
            raise LocationError(f"a crossing by name needs {k!r}, or a crossing_id")
    where = (
        f"StateAbbreviation={_quote(given['state'].upper())} "
        f"AND CITYNAME={_quote(given['city'].upper())}"
    )
    return _query(where, fields, "CrossingID")


async def _get(api: str, path: str, params: dict, replay: bool) -> Exchange:
    return (
        recorded_json(api, path, params)
        if replay
        else await fetch_json(api, path, params)
    )


def _features(ex: Exchange) -> list[dict]:
    body = ex.body if isinstance(ex.body, dict) else {}
    if ex.status != 200 or "error" in body:
        raise LocationError(f"{ex.url} answered {ex.status}: {body.get('error')}")
    return body.get("features") or []


def _geocoder_matches(ex: Exchange) -> list[dict]:
    """The one-line endpoint's candidates, or `Unavailable` when the exchange is not the
    geocoder's JSON (a recorded outage response: a redirect, a 5xx, another body)."""
    body = ex.body if isinstance(ex.body, dict) else None
    result = (body or {}).get("result")
    if (
        ex.status != 200
        or not isinstance(result, dict)
        or "addressMatches" not in result
    ):
        where = ex.as_of_headers.get("Location") or ex.url
        raise Unavailable(f"HTTP {ex.status}, {where}", ex.recorded_at or utc_now())
    return result["addressMatches"]


def _oneline(cfg: dict, address: str) -> tuple[str, dict]:
    spec = cfg["location"]["address"]
    return spec["endpoint"], {
        "address": address,
        "benchmark": spec["benchmark"],
        "format": "json",
    }


def _at_number(match: dict, number: str) -> str:
    """The matched address with its house number replaced: the range's own end."""
    rest = match["matchedAddress"].split(" ", 1)[1]
    return f"{number} {rest}"


def _roads(cfg: dict, where: str, box: tuple[float, float, float, float]) -> list:
    """(path, params) of each road layer's query for `where` inside `box`."""
    w, s_, e, n = box
    out = []
    for layer in cfg["location"]["roads"]["layers"]:
        q = _query(where, "OID,NAME,BASENAME,MTFCC")
        q.update(
            {
                "geometry": f"{w},{s_},{e},{n}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            }
        )
        out.append((layer, q))
    return out


def _box(points: list[tuple[float, float]], margin_m: float) -> tuple:
    g = facilities.buffer(unary_union([Point(p) for p in points]).envelope, margin_m)
    w, s_, e, n = g.bounds
    r = 10**COORDINATE_DECIMALS
    return (
        round(w * r) / r,
        round(s_ * r) / r,
        round(e * r) / r,
        round(n * r) / r,
    )


def _first_point(ex: Exchange) -> tuple[float, float] | None:
    m = _geocoder_matches(ex)
    return (m[0]["coordinates"]["x"], m[0]["coordinates"]["y"]) if m else None


async def _fetch_address(given, cfg, replay) -> list[Exchange]:
    """[the address's answer, then per candidate: its range's from and to ends and
    each road layer's lines of its street around them]."""
    if not given.get("address"):
        raise LocationError("an address location needs `address`")
    spec, roads = cfg["location"]["address"], cfg["location"]["roads"]
    try:
        first = await _get(spec["api"], *_oneline(cfg, given["address"]), replay)
    except UpstreamServiceError as exc:
        raise Unavailable(str(exc), utc_now()) from None
    out = [first]
    for m in _geocoder_matches(first):
        ends = []
        for number in (
            m["addressComponents"]["fromAddress"],
            m["addressComponents"]["toAddress"],
        ):
            try:
                ex = await _get(
                    spec["api"], *_oneline(cfg, _at_number(m, number)), replay
                )
            except UpstreamServiceError as exc:
                raise Unavailable(str(exc), utc_now()) from None
            out.append(ex)
            ends.append(
                _first_point(ex) or (m["coordinates"]["x"], m["coordinates"]["y"])
            )
        name = m["addressComponents"]["streetName"]
        where = f"UPPER(BASENAME)={_quote(name.upper())}"
        for path, q in _roads(cfg, where, _box(ends, roads["margin_m"])):
            out.append(await _get(roads["api"], path, q, replay))
    return out


def _place_query(given: dict) -> dict:
    state = str(given.get("state", "")).upper()
    if state not in STATE_FIPS:
        raise LocationError(f"no state with the postal code {state!r}")
    q = _query(
        f"BASENAME={_quote(given['place'])} AND STATE={_quote(STATE_FIPS[state])}",
        "NAME,BASENAME,STATE",
    )
    q.update({"returnGeometry": "false", "returnExtentOnly": "true"})
    return q


async def _fetch_intersection(given, cfg, replay) -> list[Exchange]:
    """[each places layer's extent query until one holds the place, then each road
    layer's lines of the two streets inside it]."""
    for k in ("street_a", "street_b", "place", "state"):
        if not given.get(k):
            raise LocationError(f"an intersection location needs {k!r}")
    spec = cfg["location"]["intersection"]
    out, ext = [], None
    for layer in spec["places"]:
        ex = await _get(spec["api"], layer, _place_query(given), replay)
        out.append(ex)
        ext = _extent(ex)
        if ext:
            break
    if not ext:
        return out
    names = ",".join(_quote(n.upper()) for n in (given["street_a"], given["street_b"]))
    for path, q in _roads(cfg, f"UPPER(NAME) IN ({names})", ext):
        out.append(await _get(cfg["location"]["roads"]["api"], path, q, replay))
    return out


def _extent(ex: Exchange) -> tuple | None:
    e = (ex.body or {}).get("extent") if isinstance(ex.body, dict) else None
    if not e or e.get("xmin") in (None, "NaN"):
        return None
    return (e["xmin"], e["ymin"], e["xmax"], e["ymax"])


async def fetch(given: dict, cfg: dict, *, replay: bool = False) -> list[Exchange]:
    """The exchanges a derivation reads, in the order `resolve` reads them."""
    loc = cfg["location"]
    kind = given.get("kind")
    if kind == "address":
        return await _fetch_address(given, cfg, replay)
    if kind == "intersection":
        return await _fetch_intersection(given, cfg, replay)
    if kind == "milepost":
        state = str(given.get("state", "")).upper()
        spec = loc["milepost"].get(state)
        if spec is None:
            raise LocationError(f"no milepost service is configured for {state!r}")
        if "refused" in spec:
            raise LocationError(f"{state}: {spec['refused']}")
        if state == "PA":
            m = await _get(spec["api"], *_pa_markers(given, spec), replay)
            markers = _pa_marker_pair(given, _features(m))
            s = await _get(spec["api"], *_pa_segments(given, spec, markers), replay)
            return [m, s]
        return [await _get(spec["api"], *_md_milepoints(given, spec), replay)]
    if kind == "crossing":
        spec = loc["crossing"]
        return [await _get(spec["api"], spec["layer"], _crossing(given), replay)]
    raise LocationError(f"no derivation for a location of kind {kind!r}")


# ── the records ───────────────────────────────────────────────────────────────────────


def _round(g):
    return shapely.set_precision(g, 10**-COORDINATE_DECIMALS)


def _label(cfg: dict, shape_word: str, rec: dict, unit: str) -> str:
    loc = cfg["location"]
    texts = {
        **loc["basis_text"],
        **loc.get("basis_text_by_derivation", {}).get(rec["derivation"], {}),
    }
    accuracy = texts[rec["basis"]].format(accuracy_m=rec["accuracy_m"])
    return loc["label"].format(
        shape=shape_word,
        accuracy=accuracy,
        derivation=rec["derivation"],
        source=rec["source"],
        unit=unit,
    )


def _record(
    cfg, shape, derivation, source, acc, basis, exchanges, unit, word=None
) -> dict:
    rec = {
        "shape": mapping(_round(shape)),
        "derivation": derivation,
        "source": source,
        "accuracy_m": acc,
        "basis": basis,
        # the newest exchange the record was read from: when the source said this
        "as_of": max(ex.recorded_at for ex in exchanges),
        "collapsed_by": None,
        "unit": unit,
        "evidence": [ex.url for ex in exchanges],
    }
    n = len(getattr(shape, "geoms", [shape]))
    word = (
        word
        or {
            "LineString": "a segment",
            "MultiLineString": f"{n} candidate segments",
            "Point": "a point",
            "Polygon": "a disc",
            "MultiPolygon": f"{n} candidate discs",
        }[shape.geom_type]
    )
    rec["label"] = _label(cfg, word, rec, unit)
    # GeoJSON's tuples to lists, so the record compares equal to its JSON round trip
    rec["shape"] = {
        "type": rec["shape"]["type"],
        "coordinates": _lists(rec["shape"]["coordinates"]),
    }
    return rec


def _lists(c):
    return [_lists(x) for x in c] if isinstance(c, (list, tuple)) else c


def _pa_marker_pair(given: dict, feats: list[dict]) -> list[dict]:
    lo, hi = _miles(given)
    by_mile = {}
    for f in feats:
        by_mile.setdefault(float(f["attributes"]["MILE_MARKE"]), []).append(f)
    for m in (lo, hi):
        if len(by_mile.get(m, [])) != 1:
            raise LocationError(
                f"PennDOT holds {len(by_mile.get(m, []))} mile marker(s) {m:g} on "
                f"{given['route']}, not one"
            )
    return [by_mile[lo][0], by_mile[hi][0]]


def _milepost_pa(given, cfg, exchanges) -> dict:
    spec = cfg["location"]["milepost"]["PA"]
    m_ex, s_ex = exchanges
    a, b = _pa_marker_pair(given, _features(m_ex))
    segs = _features(s_ex)
    if not segs:
        raise LocationError(f"PennDOT holds no RMS segment between {a} and {b}")
    line = linemerge([LineString(p) for f in segs for p in f["geometry"]["paths"]])
    if line.geom_type != "LineString":
        raise LocationError(
            "PennDOT's RMS segments between the two markers do not join into one line"
        )
    pa = Point(a["geometry"]["x"], a["geometry"]["y"])
    pb = Point(b["geometry"]["x"], b["geometry"]["y"])
    d0, d1 = sorted((line.project(pa), line.project(pb)))
    cut = substring(line, d0, d1)
    acc = round(facilities.geodesic_length_m(cut), 1)
    at = segs[0]["attributes"]
    nos = [f["attributes"]["SEG_NO"] for f in segs]
    unit = (
        f"PennDOT RMS SR {at['T_RT_NO']} segments {nos[0]} to {nos[-1]} (county "
        f"{at['CTY_CODE']}, side {at['SIDE_IND']}), cut at mile markers "
        f"{a['attributes']['MILE_MARKE']:g} and {b['attributes']['MILE_MARKE']:g}"
    )
    return _record(
        cfg, cut, "milepost", spec["source"], acc, "segment_length", exchanges, unit
    )


def _milepost_md(given, cfg, exchanges) -> dict:
    spec = cfg["location"]["milepost"]["MD"]
    (ex,) = exchanges
    pts = _features(ex)
    lo, hi = _miles(given)
    miles = [float(f["attributes"]["ID_MP"]) for f in pts]
    if len(pts) < 2 or min(miles) > lo or max(miles) < hi:
        raise LocationError(
            f"MDOT SHA holds milepoints {miles} on {given['route']}, which do not span "
            f"{lo:g} to {hi:g}"
        )
    line = LineString([(f["geometry"]["x"], f["geometry"]["y"]) for f in pts])
    acc = round(facilities.geodesic_length_m(line), 1)
    route = pts[0]["attributes"]["ROUTEID"].split()[0]
    unit = (
        f"MDOT SHA milepoints {lo:g} to {hi:g} on {route}, {len(pts)} 10th-mile "
        f"points ({spec['vintage']})"
    )
    return _record(
        cfg, line, "milepost", spec["source"], acc, "segment_length", exchanges, unit
    )


def _crossing_record(given, cfg, exchanges) -> dict:
    spec = cfg["location"]["crossing"]
    (ex,) = exchanges
    feats = _features(ex)
    if not given.get("crossing_id"):
        street = given["street"].upper()
        feats = [
            f for f in feats if (f["attributes"]["STREET"] or "").upper() == street
        ]
    if len(feats) != 1:
        ids = [f["attributes"]["CrossingID"] for f in feats]
        raise LocationError(
            f"the FRA inventory holds {len(feats)} crossing(s) for {given}: {ids}"
        )
    at = feats[0]["attributes"]
    # the inventory's own Lat/Long Source (item 29), never assumed
    src = at.get("LatLongSource")
    rule = cfg["location"]["crossing_accuracy"].get(
        src, {"accuracy_m": None, "basis": "none"}
    )
    unit = (
        f"FRA crossing {at['CrossingID']}, {at['STREET']} ({at['CITYNAME']}, "
        f"{at['StateAbbreviation']}), Lat/Long Source {src!r}"
    )
    return _record(
        cfg,
        Point(at["Longitude"], at["LATITUDE"]),
        "crossing",
        spec["source"],
        rule["accuracy_m"],
        rule["basis"],
        exchanges,
        unit,
    )


def unresolved(given: dict, cfg: dict, source: str, reason: str, exchanges=()) -> dict:
    """A record with no shape (HB-50): the sources answered, and nothing in the answer
    can be drawn. Every section then says why; nothing is guessed."""
    loc = cfg["location"]
    return {
        "shape": None,
        "derivation": given.get("kind"),
        "source": source,
        "accuracy_m": None,
        "basis": "none",
        "as_of": max((ex.recorded_at for ex in exchanges), default=None) or utc_now(),
        "collapsed_by": None,
        "reason": reason,
        "evidence": [ex.url for ex in exchanges],
        "label": loc["unresolved_label"].format(reason=reason),
    }


def _unavailable(given, cfg, exc: Unavailable, exchanges=()) -> dict:
    reason = cfg["location"]["unavailable_reason"].format(at=exc.at, detail=exc.detail)
    return unresolved(
        given, cfg, cfg["location"]["address"]["source"], reason, exchanges
    )


def _lines(exchanges: list[Exchange], keep) -> list[LineString]:
    out = []
    for ex in exchanges:
        for f in _features(ex):
            if keep(f["attributes"]):
                out += [LineString(p) for p in f["geometry"]["paths"]]
    return out


def _address_record(given, cfg, exchanges) -> dict:
    spec, roads = cfg["location"]["address"], cfg["location"]["roads"]
    first, rest = exchanges[0], exchanges[1:]
    try:
        matches = _geocoder_matches(first)
    except Unavailable as exc:
        return _unavailable(given, cfg, exc, exchanges)
    if not matches:
        reason = (
            f"the Census Geocoder ({spec['benchmark']}) found no match for "
            f"{given['address']!r}"
        )
        return unresolved(given, cfg, spec["source"], reason, exchanges)
    per = 2 + len(roads["layers"])
    segs, parts = [], []
    for i, m in enumerate(matches):
        chunk = rest[i * per : (i + 1) * per]
        hint = (m["coordinates"]["x"], m["coordinates"]["y"])
        ends = [_first_point(ex) or hint for ex in chunk[:2]]
        name = m["addressComponents"]["streetName"].upper()
        lines = _lines(chunk[2:], lambda a: (a.get("BASENAME") or "").upper() == name)
        line = linemerge(lines) if lines else None
        if line is not None and line.geom_type == "LineString":
            d = sorted(line.project(Point(p)) for p in ends)
            cut = substring(line, *d)
            how = "the TIGERweb road cut at the range's two ends"
        else:
            cut = LineString(ends)
            how = (
                "the straight line between the range's two ends "
                "(TIGERweb gave no one line)"
            )
        if cut.length == 0:
            cut = LineString([hint, hint])
        segs.append(cut)
        c = m["addressComponents"]
        parts.append(
            f"{m['matchedAddress']}: TIGER line {m['tigerLine']['tigerLineId']} side "
            f"{m['tigerLine']['side']}, address range {c['fromAddress']} to "
            f"{c['toAddress']}, {how}"
        )
    shape = segs[0] if len(segs) == 1 else MultiLineString(segs)
    acc = round(max(facilities.geodesic_length_m(g) for g in segs), 1)
    unit = (
        f"Census Geocoder ({spec['benchmark']}) one-line match, {len(matches)} "
        f"candidate(s), no match type in the response: " + "; ".join(parts)
    )
    word = "a segment" if len(segs) == 1 else f"{len(segs)} candidate segments"
    rec = _record(
        cfg,
        shape,
        "address",
        spec["source"],
        acc,
        "segment_length",
        exchanges,
        unit,
        word=word,
    )
    rec["hint"] = [matches[0]["coordinates"]["x"], matches[0]["coordinates"]["y"]]
    return rec


def _intersection_record(given, cfg, exchanges) -> dict:
    spec = cfg["location"]["intersection"]
    places = [ex for ex in exchanges if "extent" in (ex.body or {})]
    ext = next((e for e in map(_extent, places) if e), None)
    place = f"{given['place']}, {given['state'].upper()}"
    if not ext:
        reason = f"TIGERweb holds no place {place!r}"
        return unresolved(given, cfg, spec["source"], reason, exchanges)
    roads = exchanges[len(places) :]
    a, b = (given["street_a"].upper(), given["street_b"].upper())
    la = unary_union(_lines(roads, lambda t: (t.get("NAME") or "").upper() == a))
    lb = unary_union(_lines(roads, lambda t: (t.get("NAME") or "").upper() == b))
    x = la.intersection(lb) if not (la.is_empty or lb.is_empty) else Point()
    pts = sorted(
        {
            (round(p.x, COORDINATE_DECIMALS), round(p.y, COORDINATE_DECIMALS))
            for p in getattr(x, "geoms", [x])
            if p.geom_type == "Point" and not p.is_empty
        }
    )
    if not pts:
        reason = (
            f"TIGER holds no crossing of {given['street_a']} and "
            f"{given['street_b']} in {place}"
        )
        return unresolved(given, cfg, spec["source"], reason, exchanges)
    acc = spec["accuracy_m"]
    shape = unary_union([facilities.buffer(Point(p), acc) for p in pts])
    unit = (
        f"TIGERweb crossing of {given['street_a']} and {given['street_b']} in {place}, "
        f"{len(pts)} point(s)"
    )
    # the discs of two crossings a few metres apart merge into one polygon; the label
    # counts the crossings, not the polygons
    word = "a disc" if len(pts) == 1 else f"{len(pts)} candidate discs"
    rec = _record(
        cfg,
        shape,
        "intersection",
        spec["source"],
        acc,
        spec["basis"],
        exchanges,
        unit,
        word=word,
    )
    rec["points"] = [list(p) for p in pts]
    rec["hint"] = list(pts[0])
    return rec


def resolve(given: dict, cfg: dict, exchanges: list[Exchange]) -> dict:
    """The location record from the exchanges `fetch` returned for `given`."""
    kind = given.get("kind")
    if kind == "address":
        return _address_record(given, cfg, exchanges)
    if kind == "intersection":
        return _intersection_record(given, cfg, exchanges)
    if kind == "milepost":
        state = str(given["state"]).upper()
        build = _milepost_pa if state == "PA" else _milepost_md
        return build(given, cfg, exchanges)
    if kind == "crossing":
        return _crossing_record(given, cfg, exchanges)
    raise LocationError(f"no derivation for a location of kind {kind!r}")


async def locate(given: dict, cfg: dict, *, replay: bool = False) -> dict:
    """`fetch`, then `resolve`. A geocoder that is unavailable gives an unresolved
    record, not an error: the brief says so (HB-50 ADDENDUM-00 point 3)."""
    try:
        exchanges = await fetch(given, cfg, replay=replay)
    except Unavailable as exc:
        return _unavailable(given, cfg, exc)
    return resolve(given, cfg, exchanges)
