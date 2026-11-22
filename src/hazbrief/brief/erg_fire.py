"""The ERG fire isolation distance of a guide, with its own words and page (DN-021
sections 1 and 7; HB-129 Part A step 2).

Every orange guide but seven prints, under EVACUATION, a "Fire" paragraph: "If tank,
rail tank car or highway tank is involved in a fire, ISOLATE for 800 meters (1/2 mile)
in all directions" (Guide 128, erg2024-en-pdf p. 188), or the guide's own condition
(Guide 112: "If rail car or trailer is involved in a fire"). ERG Table 1's introduction
says the same distance is the isolation distance for a Table 1 material in a fire: "the
fire hazard distance should be used as an isolation distance" (p. 282). Guides 161 to
166 and 172 print only "consider an initial evacuation distance" for a major fire, no
isolation distance, and have none here.

The distance is the server's own reading of the guide (`hazbrief.incident.
guide_distances`, the ERG pack's `evacuation.fire_isolate`); the paragraph is the
guide's `public_safety` item that states it, verbatim from the pack; the page is the
section's locator. The brief prints this for every guide that carries it, fire or not;
the ring is drawn only when the incident says fire (the server's `fire_isolation` zone).
"""

from __future__ import annotations

import functools

from hazbrief.incident import guide_distances, guide_key
from hazbrief.packs import default_packs


class ErgFireError(ValueError):
    """The pack's guide prints a fire isolation distance but no paragraph states it."""


@functools.lru_cache(maxsize=None)
def fire_isolation(guide: str) -> dict | None:
    """The guide's fire isolation distance, its paragraph and its page, or None where
    the guide prints no isolation distance for a fire."""
    g = default_packs().erg.data.guides[guide_key(guide)]
    gd = guide_distances(g, True)
    fi = gd.get("fire_isolate")
    if fi is None:
        return None
    basis = gd["basis"]["fire_isolate"]
    doc, _, page = (basis["locator"] or "").partition("#p")
    items = g.sections["public_safety"].items
    heading = next(
        (i for i, it in enumerate(items) if it.kind == "heading" and it.text == "Fire"),
        None,
    )
    want = f"{fi['metres']} meters"
    quote = next(
        (
            it.text
            for it in items[(heading or 0) :]
            if it.kind == "bullet" and "ISOLATE" in it.text and want in it.text
        ),
        None,
    )
    if heading is None or quote is None:
        raise ErgFireError(
            f"Guide {guide}: the pack gives a fire isolation distance of "
            f"{fi['text']} but no Fire paragraph under {basis['locator']} states it"
        )
    return {
        "guide": g.guide,
        "metres": fi["metres"],
        "distance": fi["text"],
        "tag": basis["tag"],
        "locator": basis["locator"],
        "doc": doc,
        "page": int(page),
        "quote": quote,
    }
