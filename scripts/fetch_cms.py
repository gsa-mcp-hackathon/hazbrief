#!/usr/bin/env python3
"""Cache the CMS hospital and nursing home files `facilities_in_footprint` and
`receiving_hospitals` read (HB-10), into `settings.hazbrief_cms_dir` (fixtures/cms/).

**Zero model spend.** What is fetched, and why at build rather than per incident
(`facilities_sources.yaml` `cms`):

* **Hospital General Information** (`xubh-q36u`): every Medicare-registered hospital,
  with its type and whether it provides emergency services. It has no coordinates, so
  the hospitals with emergency services are geocoded once, by address, through the
  Census Geocoder's batch service, and the match rate is written into the file.
* **Provider of Services** (`cms_data`): bed counts, joined to the hospitals on the CMS
  Certification Number (CCN), active hospitals only; and a second address. A hospital
  whose address the geocoder does not match is tried once more (`second_pass`): its
  address with any post office box removed when there was one, else its Provider of
  Services street address when that differs. A hospital still unplaced takes the USGS
  National Structures Dataset hospital point with the same 5-digit ZIP, house number and
  first street-name word, when exactly one point has them (`nsd_join`): deterministic
  record linkage on an exact agreement key (Christen, *Data Matching*, Springer 2012),
  never a fuzzy name match. Which input placed each hospital is recorded.
* **Nursing Home Provider Information** (`4pq5-n9py`): every Medicare- and
  Medicaid-certified nursing home, with CMS's own latitude and longitude.

GETs go through `scripts/fetch_allowlisted.py`'s `PoliteClient` (allowlist before any
socket, robots first, one identified user agent, per-host pacing, bounded backoff). The
geocoder's batch service takes a POST, which that client does not make; the POST is
sent here, to an allowlisted host only, with the server's user agent.

Checkpoint plan (constitution section 15). A unit is one request: a metastore record, a
CSV download, a page of POS rows, or one geocoder batch. Its key is the sha256 of its
name, url and request body, so a changed batch is a new unit. Each unit's response is
written atomically to the work directory (`--work`, gitignored under packs/build/) and
a row appended, fsynced, to `units.jsonl` before the next request; re-running is the
resume, and a unit whose file and row exist is not requested again. `--max-calls` bounds
the requests this run makes (the client's robots.txt reads are its own and are not
counted); a run that reaches it stops before the request, exits 3, and keeps what it
saved. A failed unit is a row with its error; the run goes on and exits 1. Pilot: the
first geocoder batch is timed and projected onto the rest before they run. Progress:
one line per unit, to stdout and to `logs/<date>_HB-10_fetch_cms.log`.

    uv run python scripts/fetch_cms.py [--max-calls N]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief import facilities  # noqa: E402
from hazbrief.config import settings  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "fetch_allowlisted", REPO / "scripts" / "fetch_allowlisted.py"
)
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

WORK = REPO / "packs" / "build" / "cms"
#: A post office box written into a street address ("P O BOX 1270", ", PO BOX 618",
#: "(P O BOX 966)"): the geocoder matches street ranges, never boxes.
PO_BOX = re.compile(r"[,(\s]*\bP\.?\s*O\.?\s*BOX\s+\w+\)?", re.I)
POS_API = "https://data.cms.gov/data-api/v1/dataset/{dataset}/data"


class CallCeiling(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def unit_key(name: str, url: str, body: bytes = b"") -> str:
    h = hashlib.sha256(f"{name}\n{url}\n".encode())
    h.update(body)
    return h.hexdigest()[:20]


class Units:
    """The checkpoint: one file per completed unit, and `units.jsonl` naming each."""

    def __init__(self, work: Path, max_calls: int, say: Callable[[str], None]):
        self.work, self.max_calls, self.say = work, max_calls, say
        work.mkdir(parents=True, exist_ok=True)
        self.index = work / "units.jsonl"
        self.done = {}
        if self.index.is_file():
            for line in self.index.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("ok"):
                    self.done[row["key"]] = row
        self.calls = 0

    def _record(self, row: dict) -> None:
        with self.index.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def run(self, name: str, url: str, fetch: Callable[[], bytes], body=b"") -> bytes:
        """The unit's saved bytes, fetching them first if no checkpoint holds them."""
        key = unit_key(name, url, body)
        path = self.work / f"{key}.bin"
        if key in self.done and path.is_file():
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == self.done[key]["sha256"]:
                return data
        if self.calls >= self.max_calls:
            raise CallCeiling(f"--max-calls {self.max_calls} reached before {name}")
        self.calls += 1
        t0 = time.monotonic()
        try:
            data = fetch()
        except (RuntimeError, httpx.HTTPError) as exc:
            self._record(
                {"key": key, "unit": name, "url": url, "ok": False, "at": _now()}
                | {"error": f"{type(exc).__name__}: {exc}"}
            )
            raise
        write_atomic(path, data)
        row = {
            "key": key,
            "unit": name,
            "url": url,
            "ok": True,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "seconds": round(time.monotonic() - t0, 2),
            "at": _now(),
        }
        self._record(row)
        self.done[key] = row
        self.say(f"{name}: {len(data):,} bytes in {row['seconds']} s")
        return data


def polite_get(client) -> Callable[[str], bytes]:
    def get(url: str) -> bytes:
        r = client.get(url)
        if r["outcome"] != "response" or r.get("status") != 200 or not r.get("body"):
            raise RuntimeError(
                f"GET {url}: {r['outcome']} {r.get('status')} {r.get('reason')}"
            )
        return r["body"]

    return get


def geocoder_post(url: str, benchmark: str, allowlist: tuple, timeout: float):
    """A function that posts one batch file to the Census Geocoder and returns the CSV
    it answers with."""
    F.check_url(url, allowlist)

    def post(batch: bytes) -> bytes:
        r = httpx.post(
            url,
            data={"benchmark": benchmark},
            files={"addressFile": ("batch.csv", batch, "text/csv")},
            headers={"User-Agent": settings.user_agent},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )
        r.raise_for_status()
        return r.content

    return post


# ── Parsing ───────────────────────────────────────────────────────────────────


def read_csv(data: bytes, columns: dict) -> list[dict]:
    """Rows of a CMS CSV, renamed by `columns` (ours -> the CSV header). A header that
    lacks a configured column is a changed file and stops the build, naming it."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    missing = [c for c in columns.values() if c not in (reader.fieldnames or [])]
    if missing:
        raise RuntimeError(f"CSV header lacks {missing}; has {reader.fieldnames}")
    return [{k: (row[c] or "").strip() for k, c in columns.items()} for row in reader]


def batch_csv(rows: list[dict]) -> bytes:
    """The geocoder's batch input: id, street, city, state, ZIP; no header."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    for r in rows:
        w.writerow([r["ccn"], r["address"], r["city"], r["state"], r["zip"]])
    return out.getvalue().encode("utf-8")


def parse_geocodes(data: bytes) -> dict[str, dict]:
    """CCN -> {match, exactness, matched_address, longitude, latitude} from a batch
    response. Columns: id, input address, Match/No_Match/Tie, Exact/Non_Exact, matched
    address, "longitude,latitude", TIGER line id, side (the geocoder's batch output)."""
    out = {}
    for row in csv.reader(io.StringIO(data.decode("utf-8"))):
        if not row:
            continue
        rec = {"match": row[2] if len(row) > 2 else "No_Match"}
        if rec["match"] == "Match" and len(row) > 5 and row[5]:
            lon, lat = (float(v) for v in row[5].split(","))
            rec |= {
                "exactness": row[3],
                "matched_address": row[4],
                "longitude": round(lon, 6),
                "latitude": round(lat, 6),
            }
        out[row[0]] = rec
    return out


def geocode_all(
    rows: list[dict],
    units: Units,
    post: Callable[[bytes], bytes],
    url: str,
    batch_size: int,
    label: str = "geocode",
) -> dict[str, dict]:
    """Geocode `rows` in batches, each batch a unit; the pilot is the first batch."""
    batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
    out: dict[str, dict] = {}
    t0 = time.monotonic()
    for n, batch in enumerate(batches, 1):
        body = batch_csv(batch)
        before = units.calls
        data = units.run(f"{label} {n}/{len(batches)}", url, lambda: post(body), body)
        out |= parse_geocodes(data)
        if n == 1 and units.calls > before and len(batches) > 1:
            spent = time.monotonic() - t0
            units.say(
                f"pilot: batch 1 of {len(batches)} took {spent:.0f} s; the rest "
                f"projected at {spent * (len(batches) - 1):.0f} s"
            )
    return out


def second_pass(unmatched: list[dict], pos: dict) -> list[dict]:
    """One more address per unmatched hospital, or none: its own address without a post
    office box when it had one and a street remains, else its Provider of Services
    street address when that differs from its own. Each row says which (`input`)."""
    out = []
    for h in unmatched:
        street = PO_BOX.sub("", h["address"]).strip(" ,()")
        if street and street != h["address"]:
            out.append(h | {"address": street, "input": "hgi_without_po_box"})
            continue
        p = pos.get(h["ccn"]) or {}
        other = (p.get("address") or "").strip()
        if other and other.upper() != h["address"].upper():
            out.append(
                h
                | {
                    "address": other,
                    "city": p.get("city") or h["city"],
                    "state": p.get("state") or h["state"],
                    "zip": (p.get("zip") or h["zip"])[:5],
                    "input": "pos",
                }
            )
    return out


#: Number words a street address spells ("ONE HOSPITAL DRIVE") and the directionals a
#: street name may lead with, which the agreement key drops ("500 W BERKELEY ST").
_NUMBER_WORDS = {"ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5"}
_DIRECTIONALS = set(
    "N S E W NE NW SE SW NORTH SOUTH EAST WEST NORTHEAST NORTHWEST SOUTHEAST "
    "SOUTHWEST".split()
)


def address_key(address: str, zip_code: str) -> tuple | None:
    """(ZIP5, house number, first street-name word), or None when the address has no
    house number or no street name."""
    words = re.sub(r"[^A-Z0-9 ]", " ", PO_BOX.sub("", address).upper()).split()
    if not words:
        return None
    number = _NUMBER_WORDS.get(words[0], words[0])
    if not number.isdigit():
        return None
    rest = [w for w in words[1:] if w not in _DIRECTIONALS]
    zip5 = (zip_code or "").strip()[:5]
    if not rest or len(zip5) != 5:
        return None
    return (zip5, number, rest[0])


def nsd_points(features: list[dict]) -> dict[tuple, list]:
    """Agreement key -> the National Structures Dataset hospital points with it."""
    out: dict[tuple, list] = {}
    for f in features:
        # The service names attributes in lower case whatever `outFields` spells.
        a = {k.lower(): v for k, v in (f.get("attributes") or {}).items()}
        g = f.get("geometry") or {}
        if g.get("x") is None or not a.get("address"):
            continue
        key = address_key(str(a["address"]), str(a.get("zipcode") or ""))
        if key is not None:
            out.setdefault(key, []).append(
                {
                    "longitude": round(g["x"], 6),
                    "latitude": round(g["y"], 6),
                    "name": a.get("name"),
                    "source_id": a.get("permanent_identifier"),
                }
            )
    return out


def nsd_join(unplaced: list[dict], points: dict[tuple, list]) -> dict[str, dict]:
    """CCN -> a geocode-shaped record for each hospital that exactly one point agrees
    with."""
    out = {}
    for h in unplaced:
        key = address_key(h["address"], h["zip"])
        found = points.get(key) if key else None
        if found and len(found) == 1:
            p = found[0]
            out[h["ccn"]] = {
                "match": "Match",
                "exactness": "nsd_address",
                "matched_address": f"{p['name']} ({p['source_id']})",
                "longitude": p["longitude"],
                "latitude": p["latitude"],
            }
    return out


# ── Assembly ──────────────────────────────────────────────────────────────────


def _int(text: str) -> int | None:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def hospitals_file(
    hgi: list[dict], pos: dict, geo: dict, second: dict, meta: dict
) -> dict:
    """`geo` is the first pass by CCN; `second` the second pass, CCN -> (input,
    geocode)."""
    emergency = [h for h in hgi if h["emergency_services"].lower() == "yes"]
    rows, matched, exact = [], 0, 0
    by_input: dict[str, int] = {}
    for h in emergency:
        g, used = geo.get(h["ccn"], {"match": "No_Match"}), "hgi"
        if g["match"] != "Match" and h["ccn"] in second:
            used, g = second[h["ccn"]]
        beds = pos.get(h["ccn"], {})
        row = {k: h[k] for k in ("ccn", "name", "address", "city", "state", "zip")}
        row |= {
            "type": h["type"],
            "beds": beds.get("beds"),
            "certified_beds": beds.get("certified_beds"),
            "geocode": g["match"],
            "latitude": g.get("latitude"),
            "longitude": g.get("longitude"),
        }
        if g["match"] == "Match":
            matched += 1
            exact += g.get("exactness") == "Exact"
            row["geocode_exactness"] = g.get("exactness")
            row["geocode_input"] = used
            by_input[used] = by_input.get(used, 0) + 1
        rows.append(row)
    meta |= {
        "hospitals_in_source": len(hgi),
        "with_emergency_services": len(emergency),
        "joined_to_pos_beds": sum(1 for r in rows if r["beds"] is not None),
        "geocode": {
            "submitted": len(emergency),
            "matched": matched,
            "exact": exact,
            "non_exact": matched - exact,
            "unmatched": len(emergency) - matched,
            "match_rate": round(matched / len(emergency), 4) if emergency else None,
            "matched_by_input": dict(sorted(by_input.items())),
        },
    }
    return {"meta": meta, "hospitals": rows}


def nursing_homes_file(nh: list[dict], meta: dict) -> dict:
    rows, located = [], 0
    for r in nh:
        lat, lon = _float(r["latitude"]), _float(r["longitude"])
        located += lat is not None and lon is not None
        rows.append(
            {
                k: r[k]
                for k in ("ccn", "name", "address", "city", "state", "zip", "type")
            }
            | {"beds": _int(r["beds"]), "latitude": lat, "longitude": lon}
        )
    meta |= {"nursing_homes_in_source": len(nh), "with_coordinates": located}
    return {"meta": meta, "nursing_homes": rows}


def _metastore(data: bytes) -> dict:
    m = json.loads(data)
    [dist] = [d for d in m["distribution"] if d.get("mediaType") == "text/csv"]
    return {
        "title": m["title"],
        "modified": m["modified"],
        "released": m.get("released"),
        "download_url": dist["downloadURL"],
        "data_dictionary": dist.get("describedBy"),
    }


def run(max_calls: int, work: Path, out_dir: Path, log_path: Path) -> int:
    src = facilities.sources()["cms"]
    cfg = F.load_config(REPO / "corpus" / "fetch_config.yaml")
    allowlist = F.load_allowlist(REPO / "corpus" / "allowlist.txt")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:

        def say(line: str) -> None:
            text = f"{_now()} {line}"
            print(text, flush=True)
            log.write(text + "\n")
            log.flush()

        units = Units(work, max_calls, say)
        client = F.PoliteClient(cfg, allowlist, F.FetchLog(work / "fetch_log.jsonl"))
        get = polite_get(client)
        say(f"start: --max-calls {max_calls}; {len(units.done)} units already saved")
        try:
            frames = {}
            for which in ("hospitals", "nursing_homes"):
                s = src[which]
                client.doc_id = f"cms-{s['dataset']}"
                meta_url = s["metastore"]
                m = _metastore(
                    units.run(f"{which} metastore", meta_url, lambda: get(meta_url))
                )
                csv_url = m["download_url"]
                data = units.run(f"{which} csv", csv_url, lambda: get(csv_url))
                frames[which] = (read_csv(data, s["columns"]), m)
            p = src["pos"]
            client.doc_id = "cms-pos"
            pos, offset = {}, 0
            while True:
                url = (
                    POS_API.format(dataset=p["dataset"])
                    + f"?filter[{p['category_field']}]={p['category']}"
                    + f"&column={','.join(p['columns'].values())}"
                    + f"&size={p['page_size']}&offset={offset}"
                )
                page = json.loads(
                    units.run(f"pos offset {offset}", url, lambda: get(url))
                )
                for r in page:
                    c = {k: r.get(v) for k, v in p["columns"].items()}
                    if c["termination"] == "00":
                        pos[c["ccn"]] = {
                            "beds": _int(c["beds"]),
                            "certified_beds": _int(c["certified_beds"]),
                        } | {k: c[k] for k in ("address", "city", "state", "zip")}
                if len(page) < p["page_size"]:
                    break
                offset += p["page_size"]
            hgi, hm = frames["hospitals"]
            g = src["geocoder"]
            emergency = [h for h in hgi if h["emergency_services"].lower() == "yes"]
            post = geocoder_post(
                g["url"], g["benchmark"], allowlist, float(g["timeout_seconds"])
            )
            size = int(g["batch_size"])
            geo = geocode_all(emergency, units, post, g["url"], size)
            missed = [
                h for h in emergency if geo.get(h["ccn"], {}).get("match") != "Match"
            ]
            retry = second_pass(missed, pos)
            again = geocode_all(retry, units, post, g["url"], size, "geocode retry")
            second = {r["ccn"]: (r["input"], again[r["ccn"]]) for r in retry}
            placed = sum(1 for _, x in second.values() if x["match"] == "Match")
            say(
                f"second pass: {len(missed)} unmatched, {len(retry)} with another "
                f"address, {placed} matched"
            )
            j = src["nsd_join"]
            client.doc_id = "usgs-structures-hospitals"
            features, offset = [], 0
            while True:
                url = (
                    f"{j['url']}?where=1%3D1&outFields={j['out_fields']}"
                    "&returnGeometry=true&outSR=4326&orderByFields=OBJECTID"
                    f"&resultOffset={offset}&resultRecordCount={j['page_size']}&f=json"
                )
                body = json.loads(
                    units.run(f"nsd offset {offset}", url, lambda: get(url))
                )
                if "error" in body:
                    raise RuntimeError(f"NSD hospital query: {body['error']}")
                page = body.get("features") or []
                features += page
                if not body.get("exceededTransferLimit") and len(page) < int(
                    j["page_size"]
                ):
                    break
                if not page:
                    break
                offset += len(page)
            unplaced = [
                h
                for h in missed
                if not (h["ccn"] in second and second[h["ccn"]][1]["match"] == "Match")
            ]
            for ccn, rec in nsd_join(unplaced, nsd_points(features)).items():
                second[ccn] = ("nsd_address", rec)
            say(
                f"third pass: {len(unplaced)} unplaced, "
                f"{sum(1 for i, _ in second.values() if i == 'nsd_address')} joined to "
                f"one of {len(features)} National Structures Dataset hospital points"
            )
        except CallCeiling as exc:
            say(f"STOPPED: {exc}; saved units stay; re-run to resume")
            return 3
        except RuntimeError as exc:
            say(f"FAILED: {exc}; saved units stay; re-run to resume")
            return 1
        built = _now()
        hospitals = hospitals_file(
            hgi,
            pos,
            geo,
            second,
            {
                "source": src["hospitals"]["label"],
                "dataset": src["hospitals"]["dataset"],
                "as_of": hm["modified"],
                "released": hm["released"],
                "csv": hm["download_url"],
                "beds_source": src["pos"]["label"],
                "beds_as_of": src["pos"]["as_of"],
                "geocoder": f"Census Geocoder, benchmark {g['benchmark']}",
                "built_at": built,
            },
        )
        nh, nm = frames["nursing_homes"]
        homes = nursing_homes_file(
            nh,
            {
                "source": src["nursing_homes"]["label"],
                "dataset": src["nursing_homes"]["dataset"],
                "as_of": nm["modified"],
                "released": nm["released"],
                "csv": nm["download_url"],
                "built_at": built,
            },
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, doc in (
            (src["hospitals"]["file"], hospitals),
            (src["nursing_homes"]["file"], homes),
        ):
            text = json.dumps(doc, sort_keys=True, separators=(",", ":"))
            write_atomic(out_dir / name, (text + "\n").encode("utf-8"))
        gc = hospitals["meta"]["geocode"]
        say(
            f"done: {units.calls} requests; {len(hospitals['hospitals'])} hospitals "
            f"with emergency services, {gc['matched']} placed "
            f"({gc['match_rate']:.1%}); "
            f"{len(homes['nursing_homes'])} nursing homes"
        )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--out", type=Path, default=settings.hazbrief_cms_dir)
    a = ap.parse_args(argv)
    day = datetime.now().strftime("%Y-%m-%d")
    return run(a.max_calls, a.work, a.out, REPO / "logs" / f"{day}_HB-10_fetch_cms.log")


if __name__ == "__main__":
    sys.exit(main())
