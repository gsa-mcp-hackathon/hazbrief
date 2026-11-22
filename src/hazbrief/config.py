"""Server configuration loaded from environment variables and two dotenv files.

Precedence, highest first (DN-004): an exported environment variable, then the
project `.env`, then the operator's master secrets file (`~/.secrets/master.env`, or
the path in `HAZBRIEF_MASTER_ENV`). Either file may be absent: pydantic-settings
skips a path that is not a file (2.16.0, `sources/providers/dotenv.py`
`_read_env_files`). An empty value is ignored, so a `.env` copied from `.env.example`
does not blank a master key. Every field can be overridden by an environment
variable of the same name (upper- or lower-case).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from hazbrief import __version__

#: The repository root, located from the package (`src/hazbrief/` -> root) the way
#: `stylebook_files.py` locates `docs/stylebook/`. It holds in a checkout and in the
#: container, whose WORKDIR /app is the root.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: DN-004: the one master secrets file outside every repository, and the variable that
#: moves it (a machine without one, CI, a test).
MASTER_ENV_VAR = "HAZBRIEF_MASTER_ENV"
DEFAULT_MASTER_ENV = "~/.secrets/master.env"
#: HB-08 ADDENDUM-00: the project file is the root's `.env`, as an absolute path, so a
#: client that launches the server from another directory (Claude Desktop, MCP
#: Inspector) still reads it.
PROJECT_ENV = REPO_ROOT / ".env"


def env_files() -> tuple[str, str]:
    """`(master, project)`, read in that order so the project file wins.

    The default master may be absent (a container never receives it). A path named by
    `HAZBRIEF_MASTER_ENV` must exist: setting the override and pointing it nowhere is a
    misconfiguration, so it fails here rather than running without the keys."""
    override = os.environ.get(MASTER_ENV_VAR)
    master = Path(override or DEFAULT_MASTER_ENV).expanduser()
    if override and not master.is_file():
        raise RuntimeError(f"{MASTER_ENV_VAR}={override!r} names no file ({master})")
    return (str(master), str(PROJECT_ENV))


class Settings(BaseSettings):
    """MCP server settings. Override any field via environment variables."""

    model_config = SettingsConfigDict(
        env_file=env_files(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # ── Transport ─────────────────────────────────────────────────────────────
    # "stdio"           — local subprocess (Claude Desktop / Claude Code / Zed)
    # "streamable-http" — remote HTTP server (containers, cloud deploys)
    #
    # NOTE: app.py also auto-selects HTTP when a platform injects DATABRICKS_APP_PORT
    # or PORT, so you usually do NOT need to set this on a cloud host.
    mcp_transport: str = "stdio"
    # HB-89 (review L3-1, L3-7): the HTTP transport binds the loopback interface unless
    # this is widened. The route carries no authentication and no rate limit, so
    # widening it publishes an open endpoint that spends CENSUS_API_KEY. The container
    # widens it to 0.0.0.0 inside its own network namespace (Dockerfile), and the
    # README publishes the container's port on 127.0.0.1 only. A platform-injected port
    # (app.py) binds this host too: there is no other bind.
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    # Host names the HTTP transport accepts in a request's Host header beyond the
    # loopback names fastmcp always accepts (127.0.0.1, localhost, ::1;
    # fastmcp/server/http.py DEFAULT_HOSTS). Empty: loopback only. A JSON list in the
    # environment, e.g. MCP_ALLOWED_HOSTS='["hazbrief.example.gov"]'. Guards a local
    # server against DNS rebinding (review L3-7).
    mcp_allowed_hosts: list[str] = []

    # ── Outbound identity (DN-002 section 1) ─────────────────────────────────
    # Every upstream call sends `user_agent`: the NWS API requires a User-Agent that
    # names the application and a contact (corpus/api_catalog.yaml, `nws`), and the
    # other federal APIs ask for the same courtesy. Override the contact with
    # HAZBRIEF_CONTACT_URL when running a fork.
    hazbrief_contact_url: str = "https://github.com/brockwebb/hazbrief-mcp"

    # ── Dataset API keys (HB-06; corpus/api_catalog.yaml) ─────────────────────
    # Census Data API: REQUIRED for every data query since May 2026 ("An API key must
    # be used with all data queries", census-api-query-limits). Empty means the
    # Census-backed tools report that the key is missing; they never fall back to a
    # keyless call that the API refuses.
    # Signup: https://api.census.gov/data/key_signup.html
    census_api_key: str = ""
    # No other key is read. HB-95 (review L1-9) removed the healthdata.gov (Socrata) app
    # token: no call uses it (DN-002 section 4; corpus/api_catalog.yaml lists the API as
    # `reference`). A future healthdata.gov call adds its setting with that call.

    # ── Upstream endpoints (HB-K1, resolved by HB-08; DN-005 section 2) ──────────
    # Every upstream origin the server calls, by API name. A tool names the API, never a
    # URL: an origin is operator configuration, not a tool argument. Each value ends in
    # "/" so a relative path joins beneath it.
    nws_api_base_url: str = "https://api.weather.gov/"
    # Census Data API (2020 DHC, ACS 5-year, CRE) and TIGERweb (2020 tabulation
    # geography): corpus/api_catalog.yaml `census_data` and `tigerweb` (HB-09).
    census_api_base_url: str = "https://api.census.gov/data/"
    tigerweb_base_url: str = (
        "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
    )
    # facilities_in_footprint (HB-10): USGS National Structures Dataset, USGS 3DHP, and
    # the BTS NTAD rail layers (corpus/api_catalog.yaml usgs_structures, usgs_3dhp,
    # bts_ntad).
    usgs_structures_base_url: str = (
        "https://carto.nationalmap.gov/arcgis/rest/services/"
    )
    usgs_3dhp_base_url: str = "https://hydro.nationalmap.gov/arcgis/rest/services/"
    bts_ntad_base_url: str = (
        "https://services.arcgis.com/xOi1kZaI0eWDREZv/ArcGIS/rest/services/"
    )
    # The state linear-referencing services the workbench resolves a milepost through
    # (HB-49; DN-013 section 5.3; corpus/workbench_api_catalog.yaml mdot_sha_milepoints,
    # pasda_penndot, vdot_lrs). No tool calls them: the workbench's location resolver
    # (hazbrief.brief.location) does, through this one client and its recorder.
    mdot_sha_milepoints_base_url: str = (
        "https://maps.roads.maryland.gov/arcgis/rest/services/"
    )
    pasda_penndot_base_url: str = (
        "https://mapservices.pasda.psu.edu/server/rest/services/"
    )
    vdot_lrs_base_url: str = (
        "https://services.arcgis.com/p5v98VHDX9Atv3l7/ArcGIS/rest/services/"
    )
    # The Census Geocoder's one-line address and geographies endpoints, which the
    # workbench's address derivation reads (HB-50; DN-013 section 5.4;
    # corpus/workbench_api_catalog.yaml census_geocoder_locations). No key (DN-003
    # section 1). No tool calls it per incident: the hospital file was geocoded once.
    census_geocoder_base_url: str = "https://geocoding.geo.census.gov/geocoder/"
    # The USGS Hydro Network-Linked Data Index, which the workbench's downstream path
    # navigates (HB-54; DN-015 section 3; corpus/workbench_api_catalog.yaml nldi). No
    # key. No tool calls it.
    nldi_base_url: str = "https://api.water.usgs.gov/nldi/"
    # The USGS Elevation Point Query Service, which the workbench's terrain panel reads,
    # and MRLC's NLCD WMS, which it read until MRLC stopped serving CONUS (HB-55, HB-59;
    # DN-015 section 5; corpus/workbench_api_catalog.yaml epqs, mrlc_nlcd). No key. No
    # tool calls them.
    epqs_base_url: str = "https://epqs.nationalmap.gov/v1/"
    mrlc_base_url: str = "https://www.mrlc.gov/geoserver/"
    # The public-domain Annual NLCD Cloud Optimized GeoTIFF mirror, which the terrain
    # panel's land cover reads by HTTP range since MRLC's GeoServer stopped serving
    # CONUS (HB-59 ADDENDUM-03; corpus/workbench_api_catalog.yaml nlcd_cog_mirror). No
    # key. No tool calls it.
    nlcd_cog_base_url: str = "https://s3-west.nrp-nautilus.io/public-land-cover/"
    # The USGS 3DEP elevation ImageServer, whose getSamples reads many points in one
    # GET (HB-59; DN-015 section 5; corpus/workbench_api_catalog.yaml usgs_3dep). No
    # key. No tool calls it; EPQS (above) is its fallback.
    usgs_3dep_base_url: str = "https://elevation.nationalmap.gov/arcgis/rest/services/"
    # NOAA nowCOAST's GeoServer, whose WMS capabilities name the radar layer and its
    # newest scan time (HB-56; DN-016 section 4; corpus/workbench_api_catalog.yaml
    # nowcoast_radar). No key. No tool calls it.
    nowcoast_base_url: str = "https://nowcoast.noaa.gov/geoserver/"
    # The two public, keyless sources the brief's materials resolver reads when a
    # material is not in the seeded properties pack (HB-119; DN-020 ADDENDUM-02 section
    # 2 item 2; corpus/workbench_api_catalog.yaml cameo_chemicals, pubchem_pug_rest,
    # pubchem_pug_view). No tool calls them: the application does
    # (hazbrief.brief.materials), through this one client and its recorder.
    # CAMEO Chemicals' datasheets (NOAA). Only `chemical/<id>` is read: its robots.txt
    # disallows `/search` for every agent (the HB-119 evidence), and the project
    # counts a GET there a manners violation (HB-01 RESULT section 8).
    cameo_base_url: str = "https://cameochemicals.noaa.gov/"
    # PubChem's PUG REST (`rest/pug/...`) and PUG View (`rest/pug_view/...`), one
    # origin; a path names which.
    pubchem_base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/"
    # PubChem's request limits, which the resolver's client-side gate honours: "No more
    # than 5 requests per second. No more than 400 requests per minute. No longer than
    # 300 s running time per minute." (pubchem-pug-view-limits, Kim et al. 2019,
    # "Usage policy"; pubchem-programmatic-access repeats the 5 per second: "We ask
    # that any user, application, or organization not make more than 5 requests per
    # second"). The running time is measured as wall time per request.
    pubchem_max_requests_per_second: int = 5
    pubchem_max_requests_per_minute: int = 400
    pubchem_max_running_seconds_per_minute: float = 300.0
    # The resolver's runtime cache path is the application's, not a server setting:
    # src/hazbrief/brief/materials.yaml `cache_path` (a Path here would be counted a
    # server runtime path by scripts/runtime_paths.py and shipped in the image).
    # Federal APIs can be slow or intermittently unresponsive; every call has an
    # explicit timeout and a response size cap.
    upstream_timeout_seconds: float = 30.0
    upstream_max_response_bytes: int = 5_000_000

    # ── Recorded exchanges (DN-005 section 2) ────────────────────────────────────
    # live:   call the upstream; write nothing.
    # record: serve an exchange that has a file; call and write one that has none
    #         (vcrpy's new_episodes, so a re-run resumes). Used once, by the task that
    #         adds a tool, to record its fixtures.
    # replay: serve only recorded exchanges; refuse any other call. tests/conftest.py
    #         makes this the default under pytest.
    hazbrief_http_mode: Literal["live", "record", "replay"] = "live"
    hazbrief_exchanges_dir: Path = REPO_ROOT / "fixtures" / "exchanges"

    # ── LODES workplace files (HB-09) ─────────────────────────────────────────────
    # LODES is static files, not an API (corpus/api_catalog.yaml `lodes`). The state WAC
    # files are fetched once by scripts/fetch_lodes.py into this directory, named as
    # LEHD names them, and read from here; nothing is downloaded per incident.
    hazbrief_lodes_dir: Path = REPO_ROOT / "fixtures" / "lodes"

    # ── CMS hospital and nursing home files (HB-10) ──────────────────────────────
    # Hospital General Information joined to Provider of Services beds and geocoded
    # once, and Nursing Home Provider Information, cached by scripts/fetch_cms.py and
    # read from here (facilities_sources.yaml `cms`); nothing is downloaded per
    # incident.
    hazbrief_cms_dir: Path = REPO_ROOT / "fixtures" / "cms"

    # ── PHMSA ERG app link (HB-08b) ──────────────────────────────────────────────
    # The `material` path of PHMSA's ERG deep-link API (phmsa-erg-api-definition, "ERG
    # 2020 Version 3.1"; corpus/erg2020_datafiles.md section 4): with `showMap=true` it
    # opens the ERG app, or the DOT page that offers it, at PHMSA's own protective
    # distance drawing for a scenario. The footprint returns this link; it never calls
    # it.
    erg_app_material_url: str = "https://www.phmsa.dot.gov/erg/material"

    # ── Footprint geometry (DN-005 section 4) ────────────────────────────────────
    # Vertices of a zone circle's polygon. 72 (every 5 degrees) puts each chord's
    # midpoint within 0.1 percent of the radius inside the circle: 0.6 m at 600 m.
    footprint_circle_vertices: int = 72

    # ── Bounds on a caller's footprint (HB-89; review L3-2) ──────────────────────
    # population_at_risk and facilities_in_footprint accept a caller's polygon and page
    # federal services across its bounding box. geo.footprint_shape refuses one larger
    # than these before any upstream call.
    #
    # Area: the disk whose radius is the ERG 2024's largest Table 3 protective action
    # distance, 11.0 km (UN 1079, rail tank car, low and moderate wind, day and night;
    # packs/erg.json), pi * 11.0**2 = 380.1 km2, rounded up. The largest footprint
    # protective_action_footprint itself draws is a square of the largest Table 1
    # distance (11.1 km, 123.2 km2) plus a guide circle of at most 1,600 m (8.0 km2):
    # at most 131.3 km2, inside the ceiling. test_footprint_bounds.py holds both.
    max_footprint_area_km2: float = 381.0
    # Vertices: protective_action_footprint draws at most five circles of
    # footprint_circle_vertices + 1 points and one five-point square, 370 at 72; the cap
    # leaves room for a hand-drawn or GIS-exported zone and refuses a multi-megabyte
    # polygon before GEOS reads it.
    max_footprint_vertices: int = 4096

    def upstream_base_url(self, api: str) -> str:
        """The configured origin of `api`; an unknown name is a programming error."""
        bases = {
            "nws": self.nws_api_base_url,
            "census": self.census_api_base_url,
            "tigerweb": self.tigerweb_base_url,
            "usgs_structures": self.usgs_structures_base_url,
            "usgs_3dhp": self.usgs_3dhp_base_url,
            "bts_ntad": self.bts_ntad_base_url,
            "mdot_sha_milepoints": self.mdot_sha_milepoints_base_url,
            "pasda_penndot": self.pasda_penndot_base_url,
            "vdot_lrs": self.vdot_lrs_base_url,
            "census_geocoder": self.census_geocoder_base_url,
            "nldi": self.nldi_base_url,
            "epqs": self.epqs_base_url,
            "mrlc": self.mrlc_base_url,
            "nlcd_cog": self.nlcd_cog_base_url,
            "usgs_3dep": self.usgs_3dep_base_url,
            "nowcoast": self.nowcoast_base_url,
            "cameo": self.cameo_base_url,
            "pubchem": self.pubchem_base_url,
        }
        if api not in bases:
            raise KeyError(f"no upstream named {api!r}; configured: {sorted(bases)}")
        return bases[api]

    @property
    def user_agent(self) -> str:
        """`hazbrief-mcp/<version> (+<contact url>)`, as DN-002 section 1 fixes it."""
        return f"hazbrief-mcp/{__version__} (+{self.hazbrief_contact_url})"


settings = Settings()
