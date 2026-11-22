"""Land cover from a Cloud Optimized GeoTIFF read by HTTP range (HB-59 ADDENDUM-03):
the TIFF reader (`hazbrief.brief.cog`), the windowed read (`derive.fetch_cover`) and
the class at the spill, the class mix and the path's classes (`derive.land_cover`).

Every test runs on a small GeoTIFF built here in the layout the mirror's file has
(classic TIFF, 8-bit, tiled, Deflate, Predictor 2, EPSG:4326, nodata 250), so no test
touches the network and each one can say exactly which cell holds what."""

from __future__ import annotations

import asyncio
import math
import struct
import zlib

import numpy as np
import pytest
from shapely.geometry import Point, shape

from hazbrief.brief import cog, derive
from hazbrief.brief.orchestrator import load_config
from hazbrief.utils import Exchange

LAT0, LON0 = 39.5, -77.0
X0, Y0, D = -77.012, 39.509, 0.0005  # west edge, north edge, cell size (degrees)
TILE, TILES = 16, 3  # 3 x 3 tiles of 16 x 16 cells
SIZE = TILE * TILES
NODATA = 250
SPLIT_LON = -77.002  # class 41 west of it, 82 east of it
NODATA_ROW = 20  # one row of no data, crossing the footprint


def _cells() -> np.ndarray:
    cols = X0 + (np.arange(SIZE) + 0.5) * D
    grid = np.where(cols < SPLIT_LON, 41, 82).astype(np.uint8)
    grid = np.tile(grid, (SIZE, 1))
    grid[NODATA_ROW, :] = NODATA
    return grid


def _ifd(entries: list[tuple], data_at: int) -> tuple[bytes, bytes]:
    """A classic IFD (sorted tags) and the out-of-line values it points to."""
    entries = sorted(entries)
    body, extra = b"", b""
    after = data_at + 2 + 12 * len(entries) + 4
    for tag, typ, values in entries:
        fmt = {2: "s", 3: "H", 4: "I", 12: "d"}[typ]
        if typ == 2:
            raw, count = values, len(values)
        else:
            raw, count = struct.pack("<" + fmt * len(values), *values), len(values)
        if len(raw) <= 4:
            field = raw.ljust(4, b"\x00")
        else:
            field = struct.pack("<I", after + len(extra))
            extra += raw + (b"\x00" if len(raw) % 2 else b"")
        body += struct.pack("<HHI", tag, typ, count) + field
    return struct.pack("<H", len(entries)) + body + struct.pack("<I", 0), extra


def _tiff(
    *,
    version=42,
    compression=8,
    tiled=True,
    geographic=4326,
    raster_type=1,
    sparse=(),
    pad_to=20000,
) -> bytes:
    """The test GeoTIFF: header, one IFD and its values, the two tile arrays (placed
    after the head in the real file; here wherever they fall), the tiles, then padding
    so a head read of `cover_head_bytes` is satisfiable."""
    cells = _cells()
    tiles = []
    for tr in range(TILES):
        for tc in range(TILES):
            t = cells[tr * TILE : (tr + 1) * TILE, tc * TILE : (tc + 1) * TILE]
            diff = np.diff(t.astype(np.int16), axis=1, prepend=0).astype(np.uint8)
            tiles.append(b"" if (tc, tr) in sparse else zlib.compress(diff.tobytes()))
    n = TILES * TILES
    geokeys = [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, raster_type]
    geokeys += [2048, 0, 1, geographic]
    common = [
        (256, 4, [SIZE]),
        (257, 4, [SIZE]),
        (258, 3, [8]),
        (259, 3, [compression]),
        (262, 3, [1]),
        (277, 3, [1]),
        (284, 3, [1]),
        (317, 3, [2]),
        (339, 3, [1]),
        (33550, 12, [D, D, 0.0]),
        (33922, 12, [0.0, 0.0, 0.0, X0, Y0, 0.0]),
        (34735, 3, geokeys),
        (42113, 2, b"250\x00"),
    ]
    # Lay out: header (8) | IFD | its values (the two tile arrays among them) | tiles |
    # padding. A first pass with zeroed arrays of the same length places the tiles.
    probe, extra = _ifd(
        common
        + [(322, 3, [TILE]), (323, 3, [TILE]), (324, 4, [0] * n), (325, 4, [0] * n)]
        if tiled
        else common + [(273, 4, [0] * n), (279, 4, [0] * n)],
        8,
    )
    tiles_at = 8 + len(probe) + len(extra)
    offsets, at = [], tiles_at
    for t in tiles:
        offsets.append(at if t else 0)
        at += len(t)
    counts = [len(t) for t in tiles]
    final = common + (
        [(322, 3, [TILE]), (323, 3, [TILE]), (324, 4, offsets), (325, 4, counts)]
        if tiled
        else [(273, 4, offsets), (279, 4, counts)]
    )
    ifd, extra = _ifd(final, 8)
    head = b"II" + struct.pack("<HI", version, 8) + ifd + extra
    assert len(head) == tiles_at, "the tiles must start where the offsets say"
    body = head + b"".join(tiles)
    return body + b"\x00" * max(0, pad_to - len(body))


FILE = _tiff()


def _xy(x_m: float, y_m: float) -> list[float]:
    dlon = 1 / (111_320 * math.cos(math.radians(LAT0)))
    return [LON0 + x_m * dlon, LAT0 + y_m / 111_320]


def _footprint(half_m: float = 300) -> dict:
    ring = [_xy(-half_m, -half_m), _xy(half_m, -half_m), _xy(half_m, half_m)]
    ring += [_xy(-half_m, half_m), _xy(-half_m, -half_m)]
    return {
        "footprint": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"zone": "spill"},
                    "geometry": {"type": "Point", "coordinates": _xy(0, 0)},
                },
                {
                    "type": "Feature",
                    "properties": {"zone": "protective_action_zone"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                },
            ],
        }
    }


class _Reads:
    """`fetch_range` over FILE, counting reads."""

    def __init__(self, data: bytes = FILE):
        self.data, self.calls = data, []

    async def __call__(self, api, path, start, end) -> Exchange:
        self.calls.append((start, end))
        return Exchange(
            api=api,
            method="GET",
            url=f"https://example.test/{path}",
            status=206,
            as_of_headers={},
            body=self.data[start : end + 1],
            origin="recorded",
        )


@pytest.fixture
def reads(monkeypatch):
    r = _Reads()
    monkeypatch.setattr(derive, "fetch_range", r)
    return r


def test_the_header_gives_the_grid_of_the_full_resolution_image():
    g = cog.parse_header(FILE[:16384])
    assert (g.width, g.height, g.tile_w, g.tile_h) == (SIZE, SIZE, TILE, TILE)
    assert (g.x0, g.y0, g.dx, g.dy) == (X0, Y0, D, D)
    assert (g.nodata, g.predictor, g.tiles_across) == (NODATA, 2, TILES)
    # A point's cell, and a point west of the image.
    assert g.cell(X0 + 2.5 * D, Y0 - 0.5 * D) == (2, 0)
    assert g.cell(X0 - D, Y0 - D) is None


def test_a_tile_decodes_to_the_cells_it_was_built_from():
    g = cog.parse_header(FILE[:16384])
    i = g.tile_index(1, 1)
    off = cog.entries_of(g, FILE[g.offsets_at + 4 * i : g.offsets_at + 4 * i + 4])[0]
    n = cog.entries_of(g, FILE[g.counts_at + 4 * i : g.counts_at + 4 * i + 4])[0]
    got = cog.decode_tile(g, FILE[off : off + n])
    assert np.array_equal(got, _cells()[TILE : 2 * TILE, TILE : 2 * TILE])


@pytest.mark.parametrize(
    "kwargs, says",
    [
        ({"version": 43}, "BigTIFF"),
        ({"compression": 5}, "Deflate only"),
        ({"tiled": False}, "strips"),
        ({"geographic": 4269}, "not EPSG:4326"),
        ({"raster_type": 2}, "PixelIsPoint"),
    ],
    ids=["bigtiff", "lzw", "strips", "nad83", "pixel-is-point"],
)
def test_a_file_this_reader_does_not_read_is_refused_by_name(kwargs, says):
    with pytest.raises(cog.CogError, match=says):
        cog.parse_header(_tiff(**kwargs)[:16384])


def test_a_head_too_short_for_its_directory_is_refused():
    with pytest.raises(cog.CogError, match="outside the head read"):
        cog.parse_header(FILE[:64])


def _brute_force(fp: dict) -> tuple[dict, int, int]:
    """The class mix by visiting every cell: weights by class, cells, no-data cells."""
    poly = shape(fp["footprint"]["features"][1]["geometry"])
    cells, weights, n, gone = _cells(), {}, 0, 0
    for r in range(SIZE):
        for c in range(SIZE):
            lon, lat = X0 + (c + 0.5) * D, Y0 - (r + 0.5) * D
            if not poly.contains(Point(lon, lat)):
                continue
            n += 1
            v = int(cells[r, c])
            if v == NODATA:
                gone += 1
            else:
                weights[v] = weights.get(v, 0) + math.cos(math.radians(lat))
    return weights, n, gone


def test_the_cover_is_the_spills_cell_the_footprints_mix_and_the_paths_vertices(
    reads,
):
    cfg = load_config()
    fp = _footprint()
    path = {"type": "LineString", "coordinates": [_xy(0, 0), _xy(-400, 0)]}
    read = asyncio.run(derive.fetch_cover(fp, cfg, path))
    out = derive.land_cover(read, fp, cfg, path)
    assert out["point"] == {"code": 82, "name": "Cultivated Crops"}
    weights, n, gone = _brute_force(fp)
    total = sum(weights.values())
    assert out["mix"]["cells"] == n and out["mix"]["no_data"] == gone > 0
    assert [r["code"] for r in out["mix"]["rows"]] == sorted(
        weights, key=lambda k: -weights[k]
    )
    for r in out["mix"]["rows"]:
        assert r["share"] == pytest.approx(weights[r["code"]] / total)
        assert r["name"] == cfg["derive"]["terrain"]["nlcd_classes"][r["code"]]
    # The path runs from the spill (east of the split) to 400 m west of it.
    assert out["path"]["vertices"] == out["path"]["answered"] == 2
    assert {r["code"] for r in out["path"]["rows"]} == {41, 82}
    assert out["vintage"] == cfg["derive"]["terrain"]["cover_vintage"]
    assert str(out["vintage"]) in out["label"] and "public domain" in out["label"]


def test_one_range_per_row_of_adjacent_tiles_and_one_per_tile_under_a_small_cap(
    reads, monkeypatch
):
    cfg = load_config()
    fp = _footprint()
    g = cog.parse_header(FILE[:16384])
    rows = {tr for _, tr in derive._cover_tiles(g, fp, cfg, None)}
    tiles = derive._cover_tiles(g, fp, cfg, None)
    asyncio.run(derive.fetch_cover(fp, cfg))
    # the head, then per row its offsets and counts entries and one run of tiles
    assert len(reads.calls) == 1 + 3 * len(rows)
    reads.calls.clear()
    spec = cfg["derive"]["terrain"]
    monkeypatch.setitem(spec, "cover_max_read_bytes", 1)
    asyncio.run(derive.fetch_cover(fp, cfg))
    assert len(reads.calls) == 1 + 2 * len(rows) + len(tiles)


def test_a_sparse_tile_is_no_data_and_is_never_read(monkeypatch):
    cfg = load_config()
    fp = _footprint()
    g = cog.parse_header(FILE[:16384])
    gone = sorted(derive._cover_tiles(g, fp, cfg, None))[0]
    r = _Reads(_tiff(sparse={gone}))
    monkeypatch.setattr(derive, "fetch_range", r)
    read = asyncio.run(derive.fetch_cover(fp, cfg))
    assert np.all(read.tiles[gone] == NODATA)
    out = derive.land_cover(read, fp, cfg)
    assert out["mix"]["no_data"] > _brute_force(fp)[2]
