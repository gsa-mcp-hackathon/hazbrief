"""Run SCICHEM once: a project in, the engine's sensor output and contours out (HB-167
Part B item 7 and Part C item 11).

The models image (`deploy/models/Dockerfile`) holds this file at
`/opt/scichem/scichem_driver.py` and runs it per request with no network. A request is
one JSON object on stdin:

    {"project": "csx",                      # the project name the files share
     "files": {"csx.inp": "...", ...},      # every input file, as text
     "extract": [                           # contours from the engine's post-processor
        {"name": "m_000", "kind": "mean", "time_h": 0.0833, "levels": [...]},
        {"name": "x05_000", "kind": "exceedance", "percent": 5.0,
         "time_h": 0.0833, "levels": [...]}]}

The response is one JSON object on stdout: `runsci` (exit code, the last lines of the
engine's log, whether it reported normal termination, wall seconds), `smp` (the sensor
output file as text, or null), `overlays` (name -> the `.ovl` text `scipp` wrote, or the
one-line reason it did not) and `wall_s`.

`runsci` is SCICHEM's batch program and `scipp` its post-processor (both built from
EPRI's source in the image, HB-165 and HB-167). `scipp` is interactive: it reads its
answers from stdin, in the order its own prompts ask them (HB-165 RESULT, "What it
outputs over time"; HB-167 measured each prompt):

    NU                 mode: extract fields with index prompts
    3                  field class: Concentration
    3                  category: Horizontal Slice
    1 | 3, P           plot type: Mean Value, or Exceedance v[Pc>P] with P in percent
    T                  the output time, in hours after the start
    (3 blank lines)    slice lower-left, upper-right, height: the defaults (the whole
                       domain, at ground level: the overlay says "Height : 0.0 (AGL)")
    6                  extraction: Custom Contours
    N                  the number of contour levels
    (blank)            contour scale factor: the default, 1
    L1 L2 ...          the contour levels (kg/m3)
    1                  export: SCIPUFF overlay (.ovl)
    NAME               output file prefix

A field with one material offers no field choice, so none is answered. Exceedance at P
is the concentration exceeded with probability P (technical documentation section
12.2.1, the clipped normal), so the contour of exceedance-at-P at a level L is the edge
of the area where P(C > L) >= P: one call gives that area for every level.

Standard library only; it opens no socket. Usage (the image's scichem entry):
    python -I scichem_driver.py < request.json > response.json
`SCICHEM_HOME` names the installed engine (`bin/runsci`, `bin/scipp`, `lib/`,
`sciData/landuse_scichem.dat`) and `SCICHEM_TIMEOUT_S` the time limit of each program
call, both from the environment. Exit 0 with the response; exit 2 with one line on
stderr when the request cannot be read or the engine is not where SCICHEM_HOME says.
A run that fails is not exit 2: its response says so (`runsci.normal` false), so the
caller records the engine's own words.

HB-189 (DN-028 ADDENDUM-14 decision 4): a request with `"hourly": true` is read hour by
hour while the engine runs. The engine writes its whole puff state at every save time
and carries on (`output.f90` `WritePuffData`: one version record, then seven records per
dump, the first holding the dump's time; HB-187 `staged.tsv`: 91 of 91 copies taken the
moment a dump was whole equal the final file to that hour). The driver polls the puff
file; the moment the dump at a whole simulated hour is whole, it copies the project as
it stands into a snapshot directory (the puff file cut after that dump's last whole
record) and extracts that hour's contours there, while the engine carries on. Each hour
is one JSON line on stdout, before the response line:

    {"hour": 1, "engine_wall_s": 136.2, "shown_wall_s": 139.9, "extracted": 36}

(`engine_wall_s` when the dump was whole, `shown_wall_s` when its contours were
extracted, both from the engine's start). The response, the last line, adds `staged`
(those rows) and `staged_check`: after the run, each hour's first mean extraction is
made again from the final files and compared with the staged one, byte for byte.

HB-192 (DN-024 ADDENDUM-01): an hourly request with `"frames"` ({"every_s", "until_s",
"spacing_km", "margin_cells", "max_points"}) is also staged at every dump whose time is
a multiple of `every_s` up to `until_s`. There, after the contours due by then are
extracted, the frame's mesh is written: scipp's uniform grid of mean concentration
("Uniform Grid (UG)", extraction method 1) over the box the outermost level of that
time's mean contour reaches, out by `margin_cells`, its corners on the spacing; the
spacing is doubled while the box would hold more than `max_points` points. Each frame
is one JSON line on stdout, before the response line:

    {"frame_s": 900.0, "engine_wall_s": 31.0, "shown_wall_s": 33.4, "x0_km": ...,
     "y0_km": ..., "dx_km": 0.025, "dy_km": 0.025, "nx": 120, "ny": 80,
     "mean_f32_gz_b64": "..."}

(the means row by row, south first, as little-endian float32, gzip and base64; a frame
whose outermost level covers nothing carries `"empty": true`, one that failed
`"error"`). The response adds `frames`: the same rows without their means.
"""

from __future__ import annotations

import array
import base64
import gzip
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: SCICHEM's `scipuff.ini` as the Linux distribution ships it
#: (`linux/bin/scipuff_linux.ini`), with its two paths pointed at the image's data
#: directory; the README: "the appropriate scipuff.ini file ... should be edited so that
#: the paths for the sciData directory and landuse.dat file point to the correct
#: directory". One thread (HB-165's build has OpenMP off).
INI = """[Paths]
SciDataDir={data}
DefaultOutDir={work}

[Land_Use]
LandUseDataFile={data}/landuse_scichem.dat

[Currency]
SCIPtoolVersion=4.1Development
SCIPUFF_Version=2.001
LandUse_Version=0.1
SYStool_Version=0.103

[SCIPMode]
GUImode=Custom
MaxPuff=20000
MaxGrid=25000
MaxRelease=3000
MaxIncident=200
MaxMaterial=40
NumThreads=1
"""

#: The words of `runsci`'s log that end a run that finished.
NORMAL = "Normal termination detected"
#: How many of the log's last lines the response carries.
LOG_TAIL = 12


class RequestError(ValueError):
    """The request is not one this driver can run; the message is one line."""


def scipp_answers(ex: dict, field_class: str = "3") -> str:
    """The answers `scipp` reads for one extraction (the module docstring).
    `field_class` is Concentration's number in scipp's class list: 3 in a finished
    project, whose surface dosage and deposition files hold records; in a project read
    while the engine runs, the deposition class is not offered until its file holds a
    record, and the list shifts (HB-189: `_concentration_class` reads it)."""
    kind = ex.get("kind")
    levels = ex.get("levels") or []
    if not levels:
        raise RequestError(f"extraction {ex.get('name')!r} has no levels")
    if kind == "mean":
        plot = ["1"]
    elif kind == "exceedance":
        pct = float(ex["percent"])
        if not 0.0 < pct < 100.0:
            raise RequestError(f"exceedance percent {pct} is not inside (0, 100)")
        plot = ["3", f"{pct:g}"]
    else:
        raise RequestError(f"extraction kind {kind!r} is not mean or exceedance")
    lines = ["NU", field_class, "3", *plot, f"{float(ex['time_h']):.6f}", "", "", ""]
    lines += ["6", str(len(levels)), "", " ".join(f"{float(v):.6e}" for v in levels)]
    lines += ["1", str(ex["name"]), "Y", ""]
    return "\n".join(lines) + "\n"


def _tail(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="latin-1").splitlines()[-LOG_TAIL:]


def run_request(req: dict, home: Path, timeout_s: float) -> dict:
    """Run one request in a fresh directory and return the response object."""
    prj = str(req.get("project") or "")
    files = req.get("files") or {}
    if not prj or not prj.isidentifier():
        raise RequestError(f"project name {prj!r} is not a plain identifier")
    if f"{prj}.inp" not in files:
        raise RequestError(f"the request holds no {prj}.inp")
    for name in files:
        if "/" in name or name.startswith("."):
            raise RequestError(f"file name {name!r} is not a plain name")
    runsci, scipp = home / "bin" / "runsci", home / "bin" / "scipp"
    data = home / "sciData"
    for exe in (runsci, scipp):
        if not os.access(exe, os.X_OK):
            raise RequestError(f"{exe} is not an executable file")
    if not (data / "landuse_scichem.dat").is_file():
        raise RequestError(f"{data}/landuse_scichem.dat is missing")
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="scichem-") as tmp:
        work = Path(tmp)
        for name, text in files.items():
            (work / name).write_text(text, encoding="ascii")
        ini = work / "scipuff.ini"
        ini.write_text(INI.format(data=data, work=work), encoding="ascii")
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = str(home / "lib")
        exs = list(req.get("extract") or [])
        for ex in exs:
            if not str(ex.get("name") or "").isidentifier():
                raise RequestError(f"extraction name {ex.get('name')!r} is not plain")
        hourly = bool(req.get("hourly"))
        frames = req.get("frames")
        if frames is not None and not hourly:
            raise RequestError("frames are read from an hourly run only")
        staged: list[dict] = []
        early: dict = {}
        framed: list[dict] = []
        r0 = time.monotonic()
        if hourly:
            rc = _run_hourly(
                [str(runsci), f"-I:{ini}", f"-P:{prj}"],
                work,
                prj,
                env,
                timeout_s,
                lambda d, todo: _extract_in(
                    scipp, d, prj, data, env, timeout_s, todo, by_name=True
                ),
                exs,
                staged,
                early,
                r0,
                frames=frames,
                grid=lambda d, spec: _grid_in(
                    scipp, d, prj, data, env, timeout_s, spec
                ),
                framed=framed,
            )
        else:
            try:
                proc = subprocess.run(
                    [str(runsci), f"-I:{ini}", f"-P:{prj}"],
                    cwd=work,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=timeout_s,
                    check=False,
                    env=env,
                )
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                rc = None
        log = _tail(work / f"{prj}.log")
        normal = rc == 0 and any(NORMAL in ln for ln in log)
        out: dict = {
            "runsci": {
                "exit": rc,
                "normal": normal,
                "log_tail": log,
                "err_tail": _tail(work / f"{prj}.err"),
                "wall_s": round(time.monotonic() - r0, 3),
            },
            "smp": None,
            "overlays": {},
        }
        smp = work / f"{prj}.smp"
        if normal and smp.is_file():
            out["smp"] = smp.read_text(encoding="latin-1")
        if normal:
            # an hour staged while the engine ran keeps its contours; the rest (and
            # every extraction of a request that is not hourly) are made now
            todo = [ex for ex in exs if ex["name"] not in early]
            out["overlays"] = {
                **early,
                **_extract_in(
                    scipp, work, prj, data, env, timeout_s, todo, by_name=hourly
                ),
            }
            out["overlays"] = {ex["name"]: out["overlays"][ex["name"]] for ex in exs}
        if frames is not None:
            out["frames"] = framed
        if hourly:
            out["staged"] = staged
            out["staged_check"] = (
                _staged_check(
                    scipp, work, prj, data, env, timeout_s, exs, staged, early
                )
                if normal
                else []
            )
    out["wall_s"] = round(time.monotonic() - t0, 3)
    return out


def _ini(where: Path, data: Path) -> Path:
    ini = where / "scipuff.ini"
    ini.write_text(INI.format(data=data, work=where), encoding="ascii")
    return ini


def _extract_in(
    scipp: Path,
    where: Path,
    prj: str,
    data: Path,
    env: dict,
    timeout_s: float,
    exs: list[dict],
    by_name: bool = False,
) -> dict:
    """`scipp`'s overlay for each extraction in `exs`, made in `where` (the run's
    directory, or an hour's snapshot of it), name -> the `.ovl` text or the one-line
    reason it was not written. With `by_name`, Concentration's number in the class
    list is read from scipp's own menu first (`_concentration_class`)."""
    ini = _ini(where, data)
    got: dict = {}
    cls = "3"
    if by_name and exs:
        cls = _concentration_class(scipp, where, ini, prj, env, timeout_s)
        if cls is None:
            why = "scipp's class list offers no Concentration class"
            return {str(ex["name"]): {"error": why} for ex in exs}
    for ex in exs:
        name = str(ex["name"])
        try:
            p = subprocess.run(
                [str(scipp), f"-I:{ini}", f"-P:{prj}"],
                cwd=where,
                input=scipp_answers(ex, cls).encode("ascii"),
                capture_output=True,
                timeout=timeout_s,
                check=False,
                env=env,
            )
            ovl = where / f"{name}.ovl"
            if p.returncode == 0 and ovl.is_file():
                got[name] = ovl.read_text(encoding="latin-1")
            else:
                last = p.stdout.decode("latin-1").strip().splitlines()[-1:]
                got[name] = {"error": f"scipp exited {p.returncode}: {' '.join(last)}"}
        except subprocess.TimeoutExpired:
            got[name] = {"error": f"scipp did not finish within {timeout_s:g} s"}
    return got


#: scipp's class list as it prints it ("  3 Concentration"), after "Available Field
#: Classes" and before "Class number ?"
CLASS_LINE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")


def _concentration_class(
    scipp: Path, where: Path, ini: Path, prj: str, env: dict, timeout_s: float
) -> str | None:
    """Concentration's number in scipp's class list for the project in `where`: scipp
    is started with the mode answer alone, prints its classes, and stops at the end of
    its input; the list is read from what it printed. None where no class is named
    exactly Concentration."""
    try:
        p = subprocess.run(
            [str(scipp), f"-I:{ini}", f"-P:{prj}"],
            cwd=where,
            input=b"NU\n",
            capture_output=True,
            timeout=min(timeout_s, 120.0),
            check=False,
            env=env,
        )
        text = p.stdout.decode("latin-1")
    except subprocess.TimeoutExpired as exc:
        text = (exc.stdout or b"").decode("latin-1")
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if "Available Field Classes" in ln)
    except StopIteration:
        return None
    for ln in lines[start + 1 :]:
        if "Class number" in ln:
            break
        m = CLASS_LINE.match(ln)
        if m and m.group(2) == "Concentration":
            return m.group(1)
    return None


def _whole_hour(t_s: float) -> int | None:
    """The simulated hour a dump time (s) is, where it is a whole one (>= 1)."""
    h = round(t_s / 3600.0)
    return h if h >= 1 and abs(t_s - 3600.0 * h) < 1.0 else None


def _frame_time(t_s: float, frames: dict | None) -> float | None:
    """HB-192: the frame time (s) a dump time is, where it is a multiple of
    `frames.every_s` (>= one interval) at or before `frames.until_s`."""
    if not frames:
        return None
    every = float(frames["every_s"])
    k = round(t_s / every)
    if k < 1 or abs(t_s - every * k) >= 1.0 or every * k > float(frames["until_s"]) + 1:
        return None
    return every * k


def overlay_box(ovl: str) -> tuple[float, float, float, float] | None:
    """The box (x0, x1, y0, y1; km) the lowest level of an overlay reaches: the
    smallest and largest coordinate of every point of every line of its first-read
    `#CONTOUR` block whose level is the least. None where that level has no line."""
    level = None
    best: float | None = None
    pts: dict[float, list[tuple[float, float]]] = {}
    in_line = False
    for raw in ovl.splitlines():
        s = raw.strip()
        if s.startswith("#CONTOUR"):
            level = float(s.split()[1])
            pts.setdefault(level, [])
            in_line = False
        elif s.startswith("!LINE"):
            in_line = level is not None
        elif s and not s.startswith(("#", "!")) and in_line and level is not None:
            x, y = s.split()[:2]
            pts[level].append((float(x), float(y)))
    if pts:
        best = min(pts)
    if best is None or not pts[best]:
        return None
    xs = [p[0] for p in pts[best]]
    ys = [p[1] for p in pts[best]]
    return min(xs), max(xs), min(ys), max(ys)


def grid_spec(
    box: tuple[float, float, float, float], frames: dict
) -> tuple[float, float, float, float, float, int, int]:
    """(x0, x1, y0, y1, spacing, nx, ny): `box` out by `margin_cells`, its corners on
    the spacing, the spacing doubled while the grid would hold more than
    `max_points` points."""
    sp = float(frames["spacing_km"])
    while True:
        m = int(frames["margin_cells"]) * sp
        x0 = math.floor((box[0] - m) / sp) * sp
        x1 = math.ceil((box[1] + m) / sp) * sp
        y0 = math.floor((box[2] - m) / sp) * sp
        y1 = math.ceil((box[3] + m) / sp) * sp
        nx = int(round((x1 - x0) / sp)) + 1
        ny = int(round((y1 - y0) / sp)) + 1
        if nx * ny <= int(frames["max_points"]):
            return x0, x1, y0, y1, sp, nx, ny
        sp *= 2.0


def grid_answers(t_h: float, cls: str, spec: tuple, name: str) -> str:
    """scipp's answers for a uniform grid of the mean (HB-192; the prompts read from
    `RegularGrid.f90` `CreateGridUniform` and a run of scipp): the mode, class,
    Horizontal Slice, Mean Value, the time, the slice defaults, method 1 (Uniform
    Grid), the X range, its points, the Y range, its points, and the output file."""
    x0, x1, y0, y1, _sp, nx, ny = spec
    return "\n".join(
        [
            "NU",
            cls,
            "3",
            "1",
            f"{t_h:.6f}",
            "",
            "",
            "",
            "1",
            f"{x0:.6f} {x1:.6f}",
            str(nx),
            f"{y0:.6f} {y1:.6f}",
            str(ny),
            name,
            "",
        ]
    )


def read_grid_means(text: str, nx: int, ny: int) -> list[float]:
    """The means of scipp's uniform-grid file, row by row south first (the file lists
    X outer and Y inner)."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("====")) + 2
    vals = [float(ln.split()[2]) for ln in lines[start:] if ln.strip()]
    if len(vals) != nx * ny:
        raise ValueError(f"the grid holds {len(vals)} points, not {nx} by {ny}")
    # file index k = ix * ny + iy; stored index iy * nx + ix
    return [vals[ix * ny + iy] for iy in range(ny) for ix in range(nx)]


def _grid_in(
    scipp: Path,
    where: Path,
    prj: str,
    data: Path,
    env: dict,
    timeout_s: float,
    job: dict,
) -> dict:
    """HB-192: one frame's mesh written in `where` (a snapshot): `job` holds the frame
    time (`t_s`), its box (`box`) and the frames spec. The row's grid fields, or
    `{"error": ...}`."""
    ini = _ini(where, data)
    cls = _concentration_class(scipp, where, ini, prj, env, timeout_s)
    if cls is None:
        return {"error": "scipp's class list offers no Concentration class"}
    spec = grid_spec(job["box"], job["frames"])
    name = f"frame_{int(job['t_s'])}"
    try:
        p = subprocess.run(
            [str(scipp), f"-I:{ini}", f"-P:{prj}"],
            cwd=where,
            input=grid_answers(job["t_s"] / 3600.0, cls, spec, name).encode("ascii"),
            capture_output=True,
            timeout=timeout_s,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"scipp did not finish within {timeout_s:g} s"}
    out = where / name
    if p.returncode != 0 or not out.is_file():
        last = p.stdout.decode("latin-1").strip().splitlines()[-1:]
        return {"error": f"scipp exited {p.returncode}: {' '.join(last)}"}
    x0, _x1, y0, _y1, sp, nx, ny = spec
    means = read_grid_means(out.read_text(encoding="latin-1"), nx, ny)
    raw = array.array("f", means)
    if sys.byteorder != "little":
        raw.byteswap()
    return {
        "x0_km": round(x0, 6),
        "y0_km": round(y0, 6),
        "dx_km": round(sp, 6),
        "dy_km": round(sp, 6),
        "nx": nx,
        "ny": ny,
        "mean_f32_gz_b64": base64.b64encode(
            gzip.compress(raw.tobytes(), mtime=0)
        ).decode("ascii"),
    }


class PuffWatch:
    """Reads the puff file's new bytes at each poll and returns, for each dump whose
    seven records have become whole since the last poll, its time (s) and the byte
    offset the file is whole to (HB-187's `driver187.PufWatch`, which `staged.tsv`
    measured; the version record first)."""

    def __init__(self) -> None:
        self.off = 0
        self.buf = b""
        self.whole = 0
        self.nrec = 0
        self.dump_t: float | None = None

    def poll(self, path: Path) -> list[tuple[float, int]]:
        out: list[tuple[float, int]] = []
        if not path.is_file():
            return out
        with open(path, "rb") as fh:
            fh.seek(self.off)
            new = fh.read()
        self.off += len(new)
        self.buf += new
        i = 0
        while i + 4 <= len(self.buf):
            (size,) = struct.unpack_from("<i", self.buf, i)
            j = i + 4 + size
            if size < 0 or j + 4 > len(self.buf):
                break
            body = self.buf[i + 4 : j]
            k = (self.nrec - 1) % 7 if self.nrec >= 1 else None
            if k == 0 and len(body) >= 4:
                (self.dump_t,) = struct.unpack_from("<f", body, 0)
            self.nrec += 1
            self.whole += j + 4 - i
            if k == 6 and self.dump_t is not None:
                out.append((float(self.dump_t), self.whole))
            i = j + 4
        self.buf = self.buf[i:]
        return out


#: The surface files (deposition and dosage). The engine writes them through a buffer,
#: so mid-run they can end inside a record, and scipp then refuses the project ("Error
#: reading SAG times", HB-189's probe); only concentration is extracted, so a snapshot
#: carries each as it stood at the run's first dump, its header alone, and scipp then
#: offers the classes that header holds (the class list is read by name).
SURFACE = (".dep", ".dos")
#: The overlay's header line that holds the time scipp wrote it: the one line a staged
#: overlay and one made again from the final files may differ by
STAMP = "# File    Creation :"


def _snapshot(
    work: Path, prj: str, cut: int, where: Path, heads: dict[str, bytes]
) -> None:
    """The project as it stands, into `where`: every file of the run's directory but
    the overlays, with the puff file cut after its last whole dump (`cut` bytes) and
    each surface file as `heads` holds it (`SURFACE`)."""
    for f in work.iterdir():
        if f.is_file() and f.suffix != ".ovl" and f.name != "scipuff.ini":
            if f.name == f"{prj}.puf":
                with open(f, "rb") as src, open(where / f.name, "wb") as dst:
                    dst.write(src.read(cut))
            elif f.suffix in SURFACE and f.suffix in heads:
                (where / f.name).write_bytes(heads[f.suffix])
            else:
                shutil.copy2(f, where / f.name)


def _run_hourly(
    argv: list[str],
    work: Path,
    prj: str,
    env: dict,
    timeout_s: float,
    extract,
    exs: list[dict],
    staged: list[dict],
    early: dict,
    r0: float,
    *,
    frames: dict | None = None,
    grid=None,
    framed: list[dict] | None = None,
) -> int | None:
    """Run the engine and stage each whole hour as it lands (module docstring): the
    hour's extractions are made in a snapshot while the engine carries on, their
    overlays put into `early`, a row appended to `staged` and printed. The engine's
    exit code, or None past `timeout_s`.

    HB-192: with `frames`, every frame time is staged too: the extractions due by then
    are made, then the frame's mesh (`grid`), and its row printed (with the means) and
    appended to `framed` (without them). An hour's row counts the extractions of that
    hour, made at this stage or an earlier frame's, as it did before frames."""
    poll_s = float(os.environ.get("SCICHEM_HOURLY_POLL_S") or 0.5)
    proc = subprocess.Popen(
        argv,
        cwd=work,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    watch = PuffWatch()
    done_h = 0
    rc: int | None = None
    heads: dict[str, bytes] | None = None
    while True:
        rc = proc.poll()
        for t_s, cut in watch.poll(work / f"{prj}.puf"):
            if heads is None:
                # the surface files at the first dump: their headers (`SURFACE`)
                heads = {
                    s: (work / f"{prj}{s}").read_bytes()
                    for s in SURFACE
                    if (work / f"{prj}{s}").is_file()
                }
            h = _whole_hour(t_s)
            if h is not None and h <= done_h:
                h = None
            ft = _frame_time(t_s, frames)
            if h is None and ft is None:
                continue
            seen = round(time.monotonic() - r0, 3)
            due = (h if h is not None else 0.0) * 3600.0
            due = max(due, ft or 0.0) / 3600.0
            todo = [
                ex
                for ex in exs
                if ex["name"] not in early and float(ex["time_h"]) <= due + 1e-6
            ]
            with tempfile.TemporaryDirectory(prefix="hour-") as snap:
                _snapshot(work, prj, cut, Path(snap), heads)
                got = extract(Path(snap), todo)
                ok = [n for n, v in got.items() if isinstance(v, str)]
                early.update({n: got[n] for n in ok})
                if ft is not None:
                    _stage_frame(
                        Path(snap), ft, seen, r0, exs, early, frames, grid, framed
                    )
            if h is None:
                continue
            mine = [ex["name"] for ex in exs if h - 1 < float(ex["time_h"]) <= h + 1e-6]
            row = {
                "hour": h,
                "engine_wall_s": seen,
                "shown_wall_s": round(time.monotonic() - r0, 3),
                "extracted": sum(1 for n in mine if n in early),
                "not_extracted": sum(1 for n in mine if n not in early),
            }
            bad = [v["error"] for v in got.values() if not isinstance(v, str)]
            if bad:
                row["first_error"] = bad[0]
            staged.append(row)
            sys.stdout.write(json.dumps(row, sort_keys=True) + "\n")
            sys.stdout.flush()
            done_h = h
        if rc is not None:
            return rc
        if time.monotonic() - r0 > timeout_s:
            proc.kill()
            proc.wait()
            return None
        time.sleep(poll_s)


def _stage_frame(
    snap: Path,
    ft: float,
    seen: float,
    r0: float,
    exs: list[dict],
    early: dict,
    frames: dict,
    grid,
    framed: list[dict] | None,
) -> None:
    """HB-192: the frame at `ft` (s): the box from that time's mean contour (already
    extracted into `early`), the mesh written in the snapshot, the row printed with its
    means and kept in `framed` without them."""
    mean = next(
        (
            ex
            for ex in exs
            if ex.get("kind") == "mean" and abs(float(ex["time_h"]) * 3600.0 - ft) < 1.0
        ),
        None,
    )
    row: dict = {"frame_s": ft, "engine_wall_s": seen}
    ovl = early.get(mean["name"]) if mean is not None else None
    if not isinstance(ovl, str):
        row["error"] = "no mean contour was extracted at the frame's time"
    else:
        box = overlay_box(ovl)
        if box is None:
            row["empty"] = True
        else:
            row.update(grid(snap, {"t_s": ft, "box": box, "frames": frames}))
    row["shown_wall_s"] = round(time.monotonic() - r0, 3)
    sys.stdout.write(json.dumps(row, sort_keys=True) + "\n")
    sys.stdout.flush()
    if framed is not None:
        framed.append({k: v for k, v in row.items() if k != "mean_f32_gz_b64"})


def _staged_check(
    scipp: Path,
    work: Path,
    prj: str,
    data: Path,
    env: dict,
    timeout_s: float,
    exs: list[dict],
    staged: list[dict],
    early: dict,
) -> list[dict]:
    """Each staged hour's first mean extraction made again from the final files and
    compared with the staged overlay, byte for byte but for the overlay's own time
    stamp line (`STAMP`) (HB-187's `staged.tsv` check, kept with every record that was
    read hour by hour)."""

    def body(ovl) -> object:
        if not isinstance(ovl, str):
            return ovl
        return "\n".join(ln for ln in ovl.split("\n") if not ln.startswith(STAMP))

    out = []
    for row in staged:
        h = row["hour"]
        first = next(
            (
                ex
                for ex in exs
                if ex.get("kind") == "mean"
                and ex["name"] in early
                and h - 1 < float(ex["time_h"]) <= h + 1e-6
            ),
            None,
        )
        if first is None:
            continue
        again = _extract_in(
            scipp, work, prj, data, env, timeout_s, [first], by_name=True
        )
        out.append(
            {
                "hour": h,
                "extraction": first["name"],
                "equal": body(again.get(first["name"])) == body(early[first["name"]]),
            }
        )
    return out


def main(argv: list[str]) -> int:
    home = os.environ.get("SCICHEM_HOME")
    if not home:
        print(
            "SCICHEM_HOME is not set: the installed engine's directory", file=sys.stderr
        )
        return 2
    try:
        timeout_s = float(os.environ["SCICHEM_TIMEOUT_S"])
    except (KeyError, ValueError):
        print("SCICHEM_TIMEOUT_S is not set to a number of seconds", file=sys.stderr)
        return 2
    raw = Path(argv[1]).read_bytes() if len(argv) > 1 else sys.stdin.buffer.read()
    try:
        req = json.loads(raw)
        resp = run_request(req, Path(home), timeout_s)
    except (json.JSONDecodeError, RequestError, KeyError, TypeError) as exc:
        print(f"request refused: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(resp, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
