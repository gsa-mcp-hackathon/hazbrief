"""A windowed reader of one tiled, Deflate-compressed GeoTIFF read by HTTP range
(HB-59 ADDENDUM-03): the land-cover class at the spill and the class mix over the
footprint, from the public-domain Annual NLCD Cloud Optimized GeoTIFF mirror.

What it implements, and where each rule is from:

* **The TIFF structure** (TIFF Revision 6.0, Adobe, 1992): the 8-byte header and the
  first image file directory (IFD) only, which is the full-resolution image; section 15
  (tiled images: TileWidth, TileLength, TileOffsets, TileByteCounts, tiles stored row
  by row); section 14 (Predictor 2, horizontal differencing, undone by a running sum
  along each row modulo 2**8 for 8-bit samples). Compression 8 is Adobe Deflate (zlib,
  RFC 1950/1951; TIFF Technical Note "Adobe Deflate"), which the standard library
  decodes.
* **The georeferencing** (OGC GeoTIFF 1.1, 19-008r4): ModelTiepointTag and
  ModelPixelScaleTag, with GTRasterTypeGeoKey PixelIsArea (the tiepoint is a cell's
  corner) and GeographicTypeGeoKey 4326.
* **The cloud-optimized layout** (OGC Cloud Optimized GeoTIFF 1.0, 21-026): every IFD
  ahead of the image data, so one read of the file's head holds the directory; each
  tile is fetched by its own byte range.

What it refuses, loudly (`CogError`): BigTIFF, more than one sample per pixel, other
than 8-bit unsigned samples, other compressions or predictors, strips instead of
tiles, a CRS other than EPSG:4326, a PixelIsPoint raster, and any IFD value that lies
outside the head that was read. Each refusal names what the file had. Why a
hand-written reader and not rasterio or tifffile: HB-59 RESULT ADDENDUM-03 section 2.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

#: TIFF field types (TIFF 6.0 section 2) and their sizes in bytes.
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 11: 4, 12: 8, 16: 8}
_TYPE_FMT = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}

_TAGS = {
    "width": 256,
    "height": 257,
    "bits": 258,
    "compression": 259,
    "samples": 277,
    "planar": 284,
    "predictor": 317,
    "tile_w": 322,
    "tile_h": 323,
    "tile_offsets": 324,
    "tile_counts": 325,
    "sample_format": 339,
    "scale": 33550,
    "tiepoint": 33922,
    "geokeys": 34735,
    "nodata": 42113,
}
#: GeoTIFF keys read from the GeoKeyDirectory (OGC 19-008r4 annex).
_GT_RASTER_TYPE, _GEOGRAPHIC_TYPE = 1025, 2048
_PIXEL_IS_AREA, _WGS84 = 1, 4326
_DEFLATE = (8, 32946)


class CogError(RuntimeError):
    """A file this reader does not read, or a head that does not hold its directory."""


@dataclass(frozen=True)
class Grid:
    """The full-resolution image's layout and georeferencing."""

    width: int
    height: int
    tile_w: int
    tile_h: int
    offsets_at: int  # file offset of TileOffsets (LONG, 4 bytes each)
    counts_at: int  # file offset of TileByteCounts (LONG, 4 bytes each)
    entry_size: int
    byte_order: str
    predictor: int
    x0: float  # west edge of column 0, degrees
    y0: float  # north edge of row 0, degrees
    dx: float
    dy: float
    nodata: int | None

    @property
    def tiles_across(self) -> int:
        return -(-self.width // self.tile_w)

    def cell(self, lon: float, lat: float) -> tuple[int, int] | None:
        """(column, row) of the cell holding the point, or None outside the image."""
        col = int((lon - self.x0) // self.dx)
        row = int((self.y0 - lat) // self.dy)
        if 0 <= col < self.width and 0 <= row < self.height:
            return col, row
        return None

    def tile_of(self, col: int, row: int) -> tuple[int, int]:
        return col // self.tile_w, row // self.tile_h

    def tile_index(self, tcol: int, trow: int) -> int:
        return trow * self.tiles_across + tcol

    def tiles_over(
        self, west: float, south: float, east: float, north: float
    ) -> set[tuple[int, int]]:
        """Every tile (tile column, tile row) the box touches, clipped to the image."""
        c0, r0 = self._clip(west, north)
        c1, r1 = self._clip(east, south)
        return {
            (tc, tr)
            for tc in range(c0 // self.tile_w, c1 // self.tile_w + 1)
            for tr in range(r0 // self.tile_h, r1 // self.tile_h + 1)
        }

    def _clip(self, lon: float, lat: float) -> tuple[int, int]:
        col = int((lon - self.x0) // self.dx)
        row = int((self.y0 - lat) // self.dy)
        return min(max(col, 0), self.width - 1), min(max(row, 0), self.height - 1)

    def centres(self, tcol: int, trow: int) -> tuple[np.ndarray, np.ndarray]:
        """Cell-centre longitudes (per column) and latitudes (per row) of a tile."""
        cols = tcol * self.tile_w + np.arange(self.tile_w)
        rows = trow * self.tile_h + np.arange(self.tile_h)
        return self.x0 + (cols + 0.5) * self.dx, self.y0 - (rows + 0.5) * self.dy


def _ifd_entries(head: bytes, bo: str, at: int) -> dict[int, tuple[int, int, bytes]]:
    """tag -> (type, count, value field) of the IFD at `at`."""
    if at + 2 > len(head):
        raise CogError(f"the first IFD (offset {at}) lies outside the head read")
    (n,) = struct.unpack_from(bo + "H", head, at)
    end = at + 2 + 12 * n
    if end > len(head):
        raise CogError(f"the first IFD ends at {end}, outside the head read")
    out = {}
    for i in range(n):
        tag, typ, count = struct.unpack_from(bo + "HHI", head, at + 2 + 12 * i)
        out[tag] = (typ, count, head[at + 10 + 12 * i : at + 14 + 12 * i])
    return out


def _values(head: bytes, bo: str, entry: tuple[int, int, bytes], name: str) -> list:
    typ, count, field = entry
    if typ == 2:
        raw = _bytes_of(head, bo, typ, count, field, name)
        return [raw.rstrip(b"\x00").decode("ascii")]
    if typ not in _TYPE_FMT:
        raise CogError(f"{name} has TIFF type {typ}, which this reader does not read")
    raw = _bytes_of(head, bo, typ, count, field, name)
    return list(struct.unpack(bo + _TYPE_FMT[typ] * count, raw))


def _bytes_of(head, bo, typ, count, field, name) -> bytes:
    size = _TYPE_SIZE[typ] * count
    if size <= 4:
        return field[:size]
    (at,) = struct.unpack(bo + "I", field)
    if at + size > len(head):
        raise CogError(f"{name} lies at {at}..{at + size}, outside the head read")
    return head[at : at + size]


def parse_header(head: bytes) -> Grid:
    """The full-resolution image's Grid from the file's first bytes."""
    if head[:2] == b"II":
        bo = "<"
    elif head[:2] == b"MM":
        bo = ">"
    else:
        raise CogError("not a TIFF: no byte-order mark")
    (version,) = struct.unpack_from(bo + "H", head, 2)
    if version != 42:
        raise CogError(f"TIFF version {version} (43 is BigTIFF); only classic is read")
    (ifd_at,) = struct.unpack_from(bo + "I", head, 4)
    entries = _ifd_entries(head, bo, ifd_at)

    def one(name: str, default=None):
        entry = entries.get(_TAGS[name])
        if entry is None:
            if default is None:
                raise CogError(f"the image has no {name} tag")
            return default
        return _values(head, bo, entry, name)

    fixed = {
        "bits": [8],
        "samples": [1],
        "planar": [1],
        "sample_format": [1],
    }
    for name, want in fixed.items():
        got = one(name, want)
        if got != want:
            raise CogError(f"{name} is {got}; this reader reads {want} only")
    compression = one("compression")[0]
    if compression not in _DEFLATE:
        raise CogError(f"compression {compression}; this reader reads Deflate only")
    predictor = one("predictor", [1])[0]
    if predictor not in (1, 2):
        raise CogError(f"predictor {predictor}; this reader reads 1 and 2 only")
    if _TAGS["tile_w"] not in entries:
        raise CogError("the image is stored in strips, not tiles")
    offsets, counts = entries[_TAGS["tile_offsets"]], entries[_TAGS["tile_counts"]]
    if offsets[0] != 4 or counts[0] != 4:
        raise CogError("tile offsets and byte counts must be LONG (type 4)")
    keys = one("geokeys")
    geo = {keys[i]: keys[i + 3] for i in range(4, 4 + 4 * keys[3], 4)}
    if geo.get(_GT_RASTER_TYPE, _PIXEL_IS_AREA) != _PIXEL_IS_AREA:
        raise CogError("the raster is PixelIsPoint; this reader reads PixelIsArea")
    if geo.get(_GEOGRAPHIC_TYPE) != _WGS84:
        raise CogError(f"geographic type {geo.get(_GEOGRAPHIC_TYPE)}, not EPSG:4326")
    scale, tie = one("scale"), one("tiepoint")
    if tie[0] or tie[1]:
        raise CogError("the tiepoint is not at cell (0, 0)")
    nodata = entries.get(_TAGS["nodata"])
    return Grid(
        width=one("width")[0],
        height=one("height")[0],
        tile_w=one("tile_w")[0],
        tile_h=one("tile_h")[0],
        offsets_at=struct.unpack(bo + "I", offsets[2])[0],
        counts_at=struct.unpack(bo + "I", counts[2])[0],
        entry_size=4,
        byte_order=bo,
        predictor=predictor,
        x0=tie[3],
        y0=tie[4],
        dx=scale[0],
        dy=scale[1],
        nodata=int(_values(head, bo, nodata, "nodata")[0]) if nodata else None,
    )


def entries_of(grid: Grid, raw: bytes) -> list[int]:
    """The LONG values of a run of TileOffsets or TileByteCounts entries."""
    n = len(raw) // grid.entry_size
    return list(struct.unpack(grid.byte_order + "I" * n, raw))


def decode_tile(grid: Grid, raw: bytes) -> np.ndarray:
    """A tile's cells, (tile_h, tile_w) uint8, from its compressed bytes."""
    try:
        data = zlib.decompress(raw)
    except zlib.error as exc:
        raise CogError(f"a tile did not inflate: {exc}") from None
    if len(data) != grid.tile_w * grid.tile_h:
        raise CogError(
            f"a tile inflated to {len(data)} bytes, not {grid.tile_w * grid.tile_h}"
        )
    cells = np.frombuffer(data, dtype=np.uint8).reshape(grid.tile_h, grid.tile_w)
    if grid.predictor == 2:
        # TIFF 6.0 section 14: each sample after the first in a row is stored as its
        # difference from the one before; undone modulo 2**8.
        cells = np.cumsum(cells, axis=1, dtype=np.uint8)
    return cells
