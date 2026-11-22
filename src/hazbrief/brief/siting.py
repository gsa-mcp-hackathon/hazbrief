"""The command post, triage and staging suggested from held criteria (HB-155; DN-023).

Pure functions over what the derivations already hold: the footprint, the drawn hazard
layers (`derive.drawn_hazards`), the wind record, the terrain points, the downstream
path, the services in the area (stage one) and the candidate places read in the area
(the National Structures Dataset's public buildings, TIGER parking lot roads, NTAD's
truck
parking). Every rule is a row of `packs/siting_rules.json`, named on each point's
reason;
every value no source gives is `orchestrator.yaml` `derive.siting`'s, marked NO
PUBLISHED
BASIS there and printed on the label (DN-023 section 4).

- `exclusion`: the union a suggested point must lie outside (section 4.1).
- `derive`: the candidates, which survive, the three points and the routes (sections
  4.2 to 4.4).
- `move`: a point the operator moved, its Warning and its routes recomputed
  (section 4.5); the live page's server calls it and appends the result to the stream.

A suggested point is a suggestion; every label says the incident commander sets it.
"""

from __future__ import annotations

import heapq
import math
from typing import Any

import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import unary_union

from hazbrief.brief import derive as D

POINTS = ("command_post", "triage", "staging")
SERVICE_KINDS = ("fire", "ems", "police", "hospital")


def _gj(g) -> dict | None:
    """A shape as GeoJSON with rounded coordinates; a collection keeps its polygonal
    parts (an exclusion area) or its lines (a route), whichever it holds."""
    if g is None or g.is_empty:
        return None
    if g.geom_type == "GeometryCollection":
        polys = [x for x in g.geoms if x.geom_type in ("Polygon", "MultiPolygon")]
        lines = [x for x in g.geoms if x.geom_type in ("LineString", "MultiLineString")]
        g = unary_union(polys) if polys else unary_union(lines)
        if g.is_empty:
            return None
    m = mapping(g)
    return {"type": m["type"], "coordinates": D._round_coords(m["coordinates"])}


def rules() -> dict:
    """The siting rules (`packs/siting_rules.json`), by id."""
    from hazbrief import packs as P

    return P.load_app_pack("siting_rules").data.model_dump(mode="json")["rules"]


def rule_sources(rid: str, un: str | None = None) -> str:
    """One rule's sources as a popup prints them: each quote's document and page, or
    the operator's record. HB-178 (Issue 1f99f2f8): a source about one material is the
    brief's own material's (`un`), or the rule's words for none held; a general source
    drawn from one material's incident carries its note."""
    r = rules()[rid]
    notes = r.get("source_notes") or {}

    def cite(s: dict) -> str:
        n = notes.get(s["doc_id"])
        return f"{s['doc_id']} p. {s['page']}" + (f", {n['note']}" if n else "")

    parts = [cite(s) for s in r["sources"]]
    if r.get("material_sources"):
        own = r["material_sources"].get(str(un or ""))
        if own:
            parts += [cite(s) for s in own["sources"]]
        else:
            parts.append(r["material_none"])
    if r.get("operator_stated"):
        parts.append(f"operator record {r['operator_stated']['record'].split(':')[-1]}")
    return f"{rid} ({'; '.join(parts)})"


# ── the exclusion area (DN-023 section 4.1; ADDENDUM-04 item 1) ──────────────────────


def _spread_half(brief, derived: dict, cfg: dict) -> tuple[float, str]:
    """The half-angle the protective action zone is swept through, and its basis:
    HB-143's
    station spread for an observed record, the forecast's direction range over the
    window
    for a forecast record, never under the configured minimum."""
    from hazbrief.brief import observed_wind

    spec = cfg["derive"]["siting"]["sweep"]
    floor = float(spec["min_half_angle_deg"])
    rec = brief.wind_record or {}
    half, basis = None, "configured"
    if rec.get("kind") == "observed":
        a = (rec.get("spread") or {}).get("arc")
        if a is not None:
            half, basis = float(a["width_deg"]) / 2.0, "observed"
    elif rec.get("kind") == "forecast":
        rows = (derived.get("forecast") or {}).get("rows") or []
        a = observed_wind.arc(
            [r["windDirection"] for r in rows if r.get("windDirection") is not None]
        )
        if a is not None:
            half, basis = float(a["width_deg"]) / 2.0, "forecast"
    if half is None or half < floor:
        return floor, "configured"
    return round(half, 1), basis


def _swept(zone, incident: Point, half: float, step: float):
    """`zone` rotated about `incident` through -half to +half degrees, on the local
    plane; the union, in longitude and latitude."""
    plane = D._plane(zone, incident)
    n = max(1, math.ceil(half / step))
    angles = sorted(
        {round(-half + 2 * half * i / (2 * n), 6) for i in range(2 * n + 1)}
    )
    rotated = [affinity.rotate(plane, a, origin=(0.0, 0.0)) for a in angles]
    return D._unplane(shapely.make_valid(unary_union(rotated)), incident)


def _dense_class(derived: dict, cfg: dict) -> str | None:
    """The dense-gas channel's class when it is one of the low-ground classes."""
    cls = (derived.get("dense_gas") or {}).get("class")
    return cls if cls in cfg["derive"]["siting"]["low_ground"]["classes"] else None


def exclusion(brief, fp: dict, derived: dict, cfg: dict) -> dict:
    """The exclusion area's parts, each (id, words, shape in longitude and latitude):
    every drawn hazard layer, the protective action zone swept across the wind's spread,
    the downstream path's corridor, and held ground lower than the spill near it for a
    dense-gas class; with what each part rested on, for the label."""
    spec = cfg["derive"]["siting"]
    words = spec["words"]
    incident = D.incident_point(brief, fp)
    # HB-173 (DN-028 ADDENDUM-04 decision 5): the planning shape is read by the
    # population, the named places and the cordons; the siting reads the cloud alone
    parts = list(D.drawn_hazards(fp, derived, cfg, what="cloud"))
    notes = []
    half, basis = _spread_half(brief, derived, cfg)
    paz = next(
        (g for z, g in D.zone_polygons(fp) if z == "protective_action_zone"), None
    )
    if paz is not None:
        swept = _swept(paz, incident, half, float(spec["sweep"]["step_deg"]))
        parts.append(
            (
                "paz_sweep",
                "protective action zone swept across the wind's spread",
                swept,
            )
        )
    notes.append(
        words["parts_sweep"].format(half=half, basis=words["sweep_basis"][basis])
    )
    path = (derived.get("downstream") or {}).get("path")
    if path and path.get("geometry"):
        line = shape(path["geometry"])
        corridor = D._unplane(
            D._plane(line, incident).buffer(float(spec["corridor_m"])), incident
        )
        parts.append(("downstream_corridor", "downstream path's corridor", corridor))
        notes.append(words["parts_corridor"].format(m=float(spec["corridor_m"])))
    cls = _dense_class(derived, cfg)
    low_held = False
    if cls is not None:
        t = derived.get("terrain") or {}
        spill_m = t.get("spill_m")
        within = float(spec["low_ground"]["within_m"])
        spacing = float(t.get("spacing_m") or 0)
        if spill_m is not None and spacing:
            discs = []
            for lon, lat, v in t.get("points") or []:
                p = Point(lon, lat)
                if v < spill_m and D._metres(incident, p, incident) <= within:
                    discs.append(D._plane(p, incident).buffer(spacing / 2))
            if discs:
                low = D._unplane(unary_union(discs), incident)
                parts.append(("lower_ground", "lower ground near the spill", low))
                low_held = True
        notes.append(
            words["parts_low"].format(m=within, cls=cls)
            if t.get("points")
            else words["parts_low_unheld"].format(
                cls=cls, why=t.get("reason") or "no terrain point held"
            )
        )
    union = shapely.make_valid(unary_union([g for _, _, g in parts])) if parts else None
    return {
        "parts": parts,
        "union": union,
        "sweep": {"half_deg": half, "basis": basis},
        "dense_class": cls,
        "low_ground_held": low_held,
        "notes": notes,
    }


def inside(pt: Point, parts: list) -> list[str]:
    """The words of every exclusion part that holds `pt`, in the parts' order."""
    return [w for _, w, g in parts if g.covers(pt)]


# ── the candidates (DN-023 section 4.2) ──────────────────────────────────────────────


def _cid(kind: str, key: Any, coords: list) -> str:
    k = key if key not in (None, "") else f"{coords[0]:.5f},{coords[1]:.5f}"
    return f"{kind}:{k}"


def service_candidates(nearby: dict) -> list[dict]:
    """The services in the area (stage one), each a candidate of its class."""
    out = []
    for cls in SERVICE_KINDS:
        for r in (nearby.get("classes") or {}).get(cls) or []:
            key = r.get("source_id") or r.get("ccn")
            out.append(
                {
                    "id": _cid(cls, key, r["coordinates"]),
                    "kind": cls,
                    "name": r.get("name") or "Unnamed",
                    "coordinates": list(r["coordinates"]),
                }
            )
    return out


def structure_candidates(features: dict[str, list[dict]], cfg: dict) -> list[dict]:
    """The National Structures Dataset's public buildings by layer id (GeoJSON
    features as `facilities.arcgis_features` reads them)."""
    names = cfg["derive"]["siting"]["candidates"]["nsd_layers"]
    out = []
    for layer, feats in sorted(features.items(), key=lambda kv: int(kv[0])):
        kind = "school" if int(layer) in (21, 22, 23) else "public"
        for f in feats:
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            p = {k.lower(): v for k, v in (f.get("properties") or {}).items()}
            xy = [D._rnd(g["coordinates"][0]), D._rnd(g["coordinates"][1])]
            out.append(
                {
                    "id": _cid(kind, p.get("permanent_identifier"), xy),
                    "kind": kind,
                    "name": p.get("name") or names[int(layer)],
                    "type": names[int(layer)],
                    "coordinates": xy,
                }
            )
    return out


def parking_candidates(features: list[dict], incident: Point, cfg: dict) -> list[dict]:
    """TIGER parking lot roads (MTFCC S1780; esri JSON lines) as lots: lines within
    `merge_m` of each other are one lot; a lot with less than `min_length_m` of road is
    not offered. The lot's point is its road's point nearest the lot's centroid."""
    spec = cfg["derive"]["siting"]["candidates"]["parking"]
    lines = []
    for f in features:
        g = D.esri_line(f.get("geometry") or {})
        if g is None or g.is_empty:
            continue
        lines.append(
            (int((f.get("attributes") or {}).get("OID") or 0), D._plane(g, incident))
        )
    if not lines:
        return []
    lines.sort(key=lambda t: t[0])
    merge = float(spec["merge_m"]) / 2
    blobs = unary_union([g.buffer(merge) for _, g in lines])
    groups = list(blobs.geoms) if hasattr(blobs, "geoms") else [blobs]
    tree = shapely.STRtree([g for _, g in lines])
    out = []
    for blob in groups:
        idx = sorted(int(i) for i in tree.query(blob, predicate="intersects"))
        members = [lines[i] for i in idx]
        length = sum(g.length for _, g in members)
        if length < float(spec["min_length_m"]):
            continue
        road = unary_union([g for _, g in members])
        c = road.centroid
        p = (
            road.interpolate(road.project(c))
            if road.geom_type != "MultiLineString"
            else min(
                (part.interpolate(part.project(c)) for part in road.geoms),
                key=lambda q: q.distance(c),
            )
        )
        xy = D._unplane(p, incident)
        coords = [D._rnd(xy.x), D._rnd(xy.y)]
        oid = min(o for o, _ in members)
        out.append(
            {
                "id": _cid("parking", oid, coords),
                "kind": "parking",
                "name": f"Parking lot ({length:,.0f} m of lot road, TIGER OID {oid})",
                "coordinates": coords,
            }
        )
    return out


def rest_area_candidates(features: list[dict]) -> list[dict]:
    """NTAD Truck Stop Parking points (rest areas and truck stops on the NHS)."""
    out = []
    for f in features:
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        p = f.get("properties") or {}
        xy = [D._rnd(g["coordinates"][0]), D._rnd(g["coordinates"][1])]
        where = ", ".join(
            str(x)
            for x in (
                p.get("highway_route"),
                f"mile {p['mile_post']}"
                if p.get("mile_post") not in (None, "")
                else None,
                p.get("municipality"),
            )
            if x not in (None, "")
        )
        rest = str(p.get("nhs_rest_stop") or "").strip()
        name = ("Rest area" if rest.lower().startswith("y") else "Truck stop") + (
            f", {where}" if where else ""
        )
        out.append(
            {
                "id": _cid("rest_area", p.get("OBJECTID"), xy),
                "kind": "rest_area",
                "name": name,
                "coordinates": xy,
                "spots": p.get("number_of_spots"),
            }
        )
    return out


# ── the road graph, its routes and their crossings ───────────────────────────────────


class Graph:
    """HB-142R's road graph (`derive._RoadGraph`) around the incident, with the segments
    that meet the exclusion area marked, so a route can avoid them."""

    def __init__(self, lines: list, spec: dict, incident: Point, excl_plane):
        self.c = incident
        self.g = D._RoadGraph(
            lines, spec["speed_kmh"], float(spec["junction_m"]), incident
        )
        self.conn = float(spec["connector_kmh"])
        self.excl = excl_plane
        self.blocked: set[tuple[int, int]] = set()
        if excl_plane is not None and len(self.g.segs):
            hit = self.g.tree.query(excl_plane, predicate="intersects")
            for k in hit:
                i, j, _ = self.g.seg_ij[int(k)]
                self.blocked.add((min(i, j), max(i, j)))

    def snap(self, lonlat: list) -> tuple[int, float, Point] | None:
        """`lonlat` joined to the graph at its nearest segment (`_RoadGraph.snap`): a
        new
        node, whose two edges are blocked where the segment it splits is."""
        p = D._plane(Point(lonlat), self.c)
        s = self.g.snap(p)
        if s is None:
            return None
        n = s[0]
        ends = [j for j, _ in self.g.edges.get(n, [])]
        if len(ends) == 2 and (min(ends), max(ends)) in self.blocked:
            for j in ends:
                self.blocked.add((min(n, j), max(n, j)))
        return n, s[1], p

    def via(self, n: int, best: dict) -> tuple[float, int | None]:
        """A snapped node's cost through its two edges to a node `best` already holds
        (a search run before it was snapped), and the neighbour it goes through."""
        out = (math.inf, None)
        for j, w in self.g.edges.get(n, []):
            if j in best and best[j] + w < out[0]:
                out = (best[j] + w, j)
        return out

    def dijkstra(self, sources: dict[int, float], avoid: bool):
        best = dict(sources)
        prev: dict[int, int] = {}
        heap = [(t, i) for i, t in sources.items()]
        heapq.heapify(heap)
        while heap:
            t, i = heapq.heappop(heap)
            if t > best.get(i, math.inf):
                continue
            for j, w in self.g.edges.get(i, []):
                if avoid and (min(i, j), max(i, j)) in self.blocked:
                    continue
                if t + w < best.get(j, math.inf):
                    best[j] = t + w
                    prev[j] = i
                    heapq.heappush(heap, (t + w, j))
        return best, prev

    def path(self, prev: dict, start: int) -> list[int]:
        out = [start]
        while out[-1] in prev:
            out.append(prev[out[-1]])
        return out

    def line(self, nodes: list[int], a: Point | None, b: Point | None):
        pts = ([a] if a is not None else []) + [Point(self.g.nodes[i]) for i in nodes]
        pts += [b] if b is not None else []
        coords = [(p.x, p.y) for p in pts]
        return LineString(coords) if len(coords) > 1 else None


def route(graph: Graph, origin: list, dest: list) -> dict:
    """The free-flow route from `origin` to `dest` (longitude, latitude) over the held
    roads, avoiding every segment that meets the exclusion area; its minutes, road km,
    geometry and whether its connectors cross the exclusion area; or why there is
    none."""
    a, b = graph.snap(origin), graph.snap(dest)
    if a is None or b is None:
        return {"minutes": None, "reason": "no held road"}
    best, prev = graph.dijkstra({b[0]: 0.0}, avoid=True)
    if a[0] not in best:
        return {"minutes": None, "reason": None}
    nodes = graph.path(prev, a[0])
    plane = graph.line(nodes, a[2], b[2])
    minutes = best[a[0]] + (a[1] + b[1]) / 1000 / graph.conn * 60
    geom = D._unplane(plane, graph.c) if plane is not None else None
    crosses = bool(
        plane is not None and graph.excl is not None and plane.intersects(graph.excl)
    )
    road = graph.line(nodes, None, None)
    return {
        "minutes": round(minutes, 1),
        "road_km": round(road.length / 1000, 2) if road is not None else 0.0,
        "connector_m": round(a[1] + b[1]),
        "crosses": crosses,
        "geometry": _gj(geom),
        "reason": None,
    }


# ── the three points (DN-023 section 4.3) ────────────────────────────────────────────


def _sector(bearing: float, wind_from: float, cfg: dict) -> str:
    s = cfg["derive"]["siting"]["sectors"]
    off = abs((bearing - wind_from + 180.0) % 360.0 - 180.0)
    if off <= float(s["upwind_half_deg"]):
        return "upwind"
    if off <= float(s["crosswind_half_deg"]):
        return "crosswind"
    return "downwind"


def _distance_bearing(incident: Point, coords: list) -> tuple[float, float]:
    return D._distance_bearing(incident, Point(coords))


def describe(incident: Point, coords: list, cfg: dict) -> dict:
    """A point's distance and bearing from the spill, in the block's words."""
    from hazbrief.brief.layers import compass

    d, az = _distance_bearing(incident, coords)
    return {
        "distance_m": round(d),
        "bearing_deg": round(az),
        "text": cfg["derive"]["siting"]["words"]["distance"].format(
            km=d / 1000, deg=round(az), compass=compass(az)
        ),
    }


def derive(
    brief,
    fp: dict,
    derived: dict,
    candidates: list[dict],
    lines: list,
    cfg: dict,
    radius_m: float,
) -> dict:
    """The siting derivation: the exclusion area, every candidate's fate, the three
    points with why, and the routes to them. `candidates` are every place offered (the
    services in the area and the places read for siting); `lines` the travel roads
    (`derive._road_lines`). Pure."""
    spec = cfg["derive"]["siting"]
    words = spec["words"]
    tspec = cfg["derive"]["nearby"]["travel"]
    incident = D.incident_point(brief, fp)
    ex = exclusion(brief, fp, derived, cfg)
    excl_plane = D._plane(ex["union"], incident) if ex["union"] is not None else None
    graph = Graph(lines, tspec, incident, excl_plane)
    wind = brief.wind_record or {}
    wind_from = wind.get("direction_deg_from")
    # the area's edge: every graph node beyond the radius is a source of the reverse
    # search, so each candidate's shortest route to the edge is one lookup (rule
    # `road_access`)
    edge = {
        i: 0.0 for i, (x, y) in enumerate(graph.g.nodes) if math.hypot(x, y) > radius_m
    }
    reach, prev = graph.dijkstra(edge, avoid=False) if edge else ({}, {})
    # the rule each exclusion part rests on (DN-023 section 4.1)
    rule_of = {}
    for k, w, _ in ex["parts"]:
        rule_of.setdefault(
            w,
            {
                "paz_sweep": "upwind_uphill_upstream",
                "downstream_corridor": "upwind_uphill_upstream",
                "lower_ground": "lower_ground",
            }.get(k, "outside_hazard"),
        )
    rejected, alive = [], []
    for cand in sorted(candidates, key=lambda c: c["id"]):
        pt = Point(cand["coordinates"])
        d, az = _distance_bearing(incident, cand["coordinates"])
        c = {**cand, "distance_m": round(d), "bearing_deg": round(az)}
        if d > radius_m:
            continue
        hit = inside(pt, ex["parts"])
        if hit:
            c["why"] = words["inside"].format(layer="; ".join(hit))
            c["rule"] = rule_of[hit[0]]
            rejected.append(c)
            continue
        s = graph.snap(cand["coordinates"])
        cost, nb = graph.via(s[0], reach) if s is not None else (math.inf, None)
        if nb is None:
            c["why"], c["rule"] = words["no_road"], "road_access"
            rejected.append(c)
            continue
        nodes = [s[0], *graph.path(prev, nb)]
        plane = graph.line(nodes, s[2], None)
        if (
            plane is not None
            and excl_plane is not None
            and plane.intersects(excl_plane)
        ):
            crossed = [
                w for _, w, g in ex["parts"] if plane.intersects(D._plane(g, incident))
            ]
            c["why"] = words["route_crosses"].format(layer="; ".join(crossed))
            c["rule"] = "road_access"
            rejected.append(c)
            continue
        c["connector_m"] = round(s[1])
        c["sector"] = _sector(az, wind_from, cfg) if wind_from is not None else None
        alive.append(c)
    points: dict[str, dict | None] = {}
    sw = words["sector_words"]

    def pick(pool: list[dict], key, rule: str, why: str) -> dict | None:
        if not pool:
            return None
        best = sorted(pool, key=lambda c: (key(c), c["id"]))[0]
        return {**best, "rule": rule, "why": why.format(sector=sw[best["sector"]])}

    up = [c for c in alive if c["sector"] == "upwind"]
    cross = [c for c in alive if c["sector"] == "crosswind"]
    # 1. the command post: the nearest upwind, crosswind as fallback
    cp = pick(
        up or cross,
        lambda c: c["distance_m"],
        "command_post",
        "the nearest candidate to the incident {sector} of it",
    )
    points["command_post"] = cp
    # 2. triage: nearest the exclusion edge upwind (crosswind), not the command post
    taken = {cp["id"]} if cp else set()

    def edge_m(c):
        if excl_plane is None:
            return c["distance_m"]
        return D._plane(Point(c["coordinates"]), incident).distance(excl_plane.boundary)

    pool = [c for c in up if c["id"] not in taken] or [
        c for c in cross if c["id"] not in taken
    ]
    if not pool:
        pool = [c for c in (up or cross)]
    tr = pick(
        pool,
        edge_m,
        "triage",
        "the candidate nearest the exclusion area's edge {sector} of the incident",
    )
    points["triage"] = tr
    taken |= {tr["id"]} if tr else set()
    # 3. staging: farther out than both, nearest a primary or secondary road
    far = max([p["distance_m"] for p in (cp, tr) if p] or [0])
    pool = [c for c in up + cross if c["id"] not in taken and c["distance_m"] > far]
    direct = float(spec["direct_access_m"])
    ready = [c for c in pool if c["connector_m"] <= direct]
    if ready:
        st = pick(
            ready,
            lambda c: c["distance_m"],
            "staging",
            words["staging_direct"].replace("{m:g}", f"{direct:g}"),
        )
    else:
        st = pick(
            pool,
            lambda c: (c["connector_m"], c["distance_m"]),
            "staging",
            words["staging_nearest_road"],
        )
    points["staging"] = st
    for pid, p in points.items():
        if p is None:
            continue
        p["point"] = pid
        p["title"] = spec["points"][pid]["title"]
        p["suggested"] = list(p["coordinates"])
        p["where"] = describe(incident, p["coordinates"], cfg)["text"]
        p["rule_sources"] = rule_sources(
            p["rule"], (fp.get("material") or {}).get("un_number")
        )
        if pid == "triage" and p["kind"] == "hospital":
            p["both"] = words["hospital_triage"].format(name=p["name"])
    # the candidates not chosen, with why (a survivor not chosen is not rejected)
    out = {
        "points": points,
        "rejected": rejected,
        "alive": [
            {
                k: c[k]
                for k in (
                    "id",
                    "kind",
                    "name",
                    "coordinates",
                    "distance_m",
                    "bearing_deg",
                    "sector",
                )
            }
            for c in alive
        ],
        "exclusion": {
            "parts": [w for _, w, _ in ex["parts"]],
            "sweep": ex["sweep"],
            "dense_class": ex["dense_class"],
            "low_ground_held": ex["low_ground_held"],
            "geometry": _gj(ex["union"]),
        },
        "wind": {
            "direction_deg_from": wind_from,
            "kind": wind.get("kind"),
            "source": wind.get("source"),
        },
        "radius_m": radius_m,
        "reason": None if any(points.values()) else words["none"],
    }
    out["routes"] = routes_for(points, derived.get("nearby") or {}, graph, cfg)
    out["label"] = words["label"].format(
        parts="; ".join(["every drawn hazard layer"] + ex["notes"]),
        wind=(f"from {wind_from:g}°" if wind_from is not None else "no wind record"),
        up=float(spec["sectors"]["upwind_half_deg"]),
        cross=float(spec["sectors"]["crosswind_half_deg"]),
        kinds=", ".join(spec["candidates"]["kinds"].values()),
        weigh=spec["candidates"]["weigh_stations"],
        area=cfg["derive"]["area"]["label"].format(
            miles=round(
                float(cfg["derive"]["area"]["radius_m"])
                / float(cfg["derive"]["area"]["metres_per_mile"]),
                1,
            )
        ),
    )
    # what `move` needs to recompute a route without the derivations (a live serve)
    out["_lines"] = lines
    out["_incident"] = [incident.x, incident.y]
    out["_parts"] = [(k, w, _gj(g)) for k, w, g in ex["parts"]]
    return out


def routes_for(points: dict, nearby: dict, graph: Graph, cfg: dict) -> list[dict]:
    """Item 9: from each nearest fire, EMS and police station to staging, and from
    triage
    to each hospital of the services in the area; each avoiding the exclusion area."""
    spec = cfg["derive"]["siting"]
    titles = cfg["derive"]["nearby"]["classes"]
    out = []
    st, tr = points.get("staging"), points.get("triage")
    for cls in ("fire", "ems", "police"):
        rows = (nearby.get("classes") or {}).get(cls) or []
        if not rows or st is None:
            continue
        r = rows[0]
        out.append(_route_row(graph, r, cls, titles[cls]["title"], st, "staging", spec))
    if tr is not None:
        for r in (nearby.get("classes") or {}).get("hospital") or []:
            out.append(
                _route_row(
                    graph, tr, "triage", None, r, "hospital", spec, to_hospital=True
                )
            )
    return out


def _route_row(graph, a, a_kind, a_title, b, b_kind, spec, to_hospital=False) -> dict:
    r = route(graph, a["coordinates"], b["coordinates"])
    origin = a.get("title") if to_hospital else f"{a_title}: {a.get('name')}"
    dest = b.get("name") if to_hospital else b.get("title")
    url = spec["routes"]["directions_url"].format(
        olat=a["coordinates"][1],
        olon=a["coordinates"][0],
        dlat=b["coordinates"][1],
        dlon=b["coordinates"][0],
    )
    row = {
        "from": a_kind,
        "to": b_kind,
        "origin": origin,
        "dest": dest,
        "origin_xy": list(a["coordinates"]),
        "dest_xy": list(b["coordinates"]),
        "directions": url,
        **r,
    }
    if r["minutes"] is None:
        row["text"] = spec["routes"]["row_none"].format(
            origin=origin, dest=dest, why=r["reason"] or spec["routes"]["none"]
        )
    else:
        row["text"] = spec["routes"]["row"].format(
            origin=origin, dest=dest, minutes=r["minutes"], km=r["road_km"]
        )
    return row


# ── a point the operator moved (DN-023 section 4.5) ──────────────────────────────────


def arrival_at(derived: dict, coords: list) -> dict | None:
    """The first modelled step whose reached area holds `coords` (HB-157's arrival
    bands), or None. HB-163: on a release whose modelled cloud is drawn, the first
    output step whose outermost level covers the point (the cloud's own steps)."""
    pt = Point(coords)
    cl = derived.get("cloud") or {}
    if cl.get("state") == "drawn":
        from hazbrief.brief import derive as D

        outer = cl["tiers"][0]["name"]
        for s in cl.get("steps") or []:
            g = (s.get("tiers") or {}).get(outer)
            if g and shape(g).buffer(0).covers(pt):
                return {"hplus": D.hplus(s["minute"]), "clock": None}
        return None
    tl = (derived.get("puff") or {}).get("timeline") or {}
    for s in tl.get("steps") or []:
        if s.get("reached") and shape(s["reached"]).covers(pt):
            return {"hplus": s["hplus"], "clock": s.get("clock")}
    return None


def move(derived: dict, point: str, coords: list, cfg: dict) -> dict:
    """A moved point (or a point put back on its suggestion): its distance and bearing,
    the exclusion parts it lies in (each a Warning's words), the modelled arrival there,
    and the routes recomputed to it. Pure over `derived["siting"]`."""
    if point not in POINTS:
        raise ValueError(f"{point!r} is not one of {', '.join(POINTS)}")
    if (
        not isinstance(coords, (list, tuple))
        or len(coords) != 2
        or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in coords)
        or not (-180 <= coords[0] <= 180 and -90 <= coords[1] <= 90)
    ):
        raise ValueError("coordinates are [longitude, latitude] in degrees")
    s = derived.get("siting") or {}
    if not s.get("_lines") and not s.get("points"):
        raise ValueError("this brief suggested no point to move")
    spec = cfg["derive"]["siting"]
    incident = Point(s["_incident"])
    parts = [(k, w, shape(g)) for k, w, g in s.get("_parts") or []]
    union = unary_union([g for _, _, g in parts]) if parts else None
    excl_plane = D._plane(union, incident) if union is not None else None
    graph = Graph(s["_lines"], cfg["derive"]["nearby"]["travel"], incident, excl_plane)
    xy = [D._rnd(float(coords[0])), D._rnd(float(coords[1]))]
    points = {k: (dict(v) if v else None) for k, v in (s.get("points") or {}).items()}
    base = points.get(point) or {"title": spec["points"][point]["title"], "name": None}
    base = {**base, "coordinates": xy}
    points[point] = base
    hit = inside(Point(xy), parts)
    where = describe(incident, xy, cfg)
    routes = [
        r
        for r in routes_for(points, derived.get("nearby") or {}, graph, cfg)
        if (point == "staging" and r["to"] == "staging")
        or (point == "triage" and r["from"] == "triage")
    ]
    return {
        "point": point,
        "coordinates": xy,
        "inside": hit,
        "where": where["text"],
        "arrival": arrival_at(derived, xy),
        "routes": [{k: v for k, v in r.items()} for r in routes],
    }
