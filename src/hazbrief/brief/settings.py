"""The application's settings (DN-004's layers; HB-45 step 2).

The workbench is a client of the server (DN-012), and its keys are its own. They
are read from the same two files as the server's (`hazbrief.config.env_files`: the
master file, then the project `.env`, then the exported environment wins), but by this
class, which the server never imports (test_brief_map.py pins that no server
module reads `GOOGLE_MAPS_API_KEY`). An empty value is no key: the map falls back to
Leaflet over the USGS National Map tiles.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from hazbrief.config import env_files


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=env_files(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # The Google Maps JavaScript API key the map loads the basemap with. A browser key:
    # it is written into the page the CLI builds, so restrict it by HTTP referrer in the
    # Google Cloud console. The committed briefs are built without it (`--no-google`).
    # Signup: https://developers.google.com/maps/documentation/javascript/get-api-key
    google_maps_api_key: str = ""

    # HB-111: a SLAB binary for development. When set, the dense-gas client runs SLAB
    # as a subprocess of this path, not in the `hazbrief-models` image (deploy/models/).
    # Empty is unset: the image is the route. Build one as the image does:
    # `gfortran -std=legacy -O0 -o slab SLAB.FOR`, from corpus/raw/epa-slab-code.zip.
    hazbrief_slab_bin: str = ""

    # HB-112: record SLAB's runs while replaying a brief. A replayed brief reads each
    # dense-gas run from `weather.dense_gas.recordings_dir` and never runs SLAB, so it
    # regenerates byte for byte without the image; with this set, a deck not yet
    # recorded is run (image, or HAZBRIEF_SLAB_BIN) and its run written there. Unset:
    # a deck not recorded is the layer's "not available" line, never a fresh run.
    hazbrief_slab_record: bool = False


def google_maps_api_key() -> str:
    """The key as configured now (read fresh, so a test's environment applies)."""
    return AppSettings().google_maps_api_key


def slab_bin() -> str:
    """HAZBRIEF_SLAB_BIN as configured now, or "" for the models image."""
    return AppSettings().hazbrief_slab_bin


def slab_record() -> bool:
    """HAZBRIEF_SLAB_RECORD as configured now: whether a replayed brief records a SLAB
    run it does not hold (HB-112)."""
    return AppSettings().hazbrief_slab_record
