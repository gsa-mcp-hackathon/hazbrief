"""Index candidates: the ERG 2024 yellow-index entries a typed name could mean.

A typed name the index does not print ("ammonia", "liquid nitrogen", "clorine") is
not refused bare. The entries its words point to are returned, each an index row as
printed (ID number, name, guide), for a reader or a client model to choose from; the
choice is then checked against the index byte for byte (`in_index`) and every guide,
distance and property comes from the packs by the verified ID number.

This is the candidate-generation half of entity linking against a knowledge base (Shen,
Wang and Han 2015, "Entity Linking with a Knowledge Base: Issues, Techniques, and
Solutions", IEEE TKDE 27(2): a name dictionary, surface-form expansion and approximate
matching produce the candidate set; a separate step ranks it). Here the dictionary is
the yellow index; a typed word is expanded to the index words it is spelled like
(`difflib`'s ratio at or above `CLOSE_CUTOFF`, so "clorine" reaches "chlorine"); a row
scores the inverse document frequency of each typed word it carries, so the rare word
("nitrogen") outranks the common one ("liquid"). Ranking among the candidates is not
done here: the entry form gives the list to its model and then to the reader, and the
server gives it to the client.

No model, no network: a pure function of the ERG pack.
"""

from __future__ import annotations

import difflib
import math
import re
from typing import Any

#: The most candidates returned. NO MEASURED BASIS beyond HB-207's test lines: the
#: shortlist the form's model chooses from must hold every ammonia solution (four ID
#: numbers, six rows) and every nitrogen row with room to spare, and stay a few hundred
#: tokens (the whole index is about 2,767 rows, 237,835 characters of JSON).
CANDIDATES_MAX = 25
#: A typed word reaches an index word spelled like it at this `difflib` ratio or above:
#: "clorine" to "chlorine" is 0.93, "ammonia" to "ammonium" 0.80 (a different
#: compound, so below the cutoff). NO MEASURED BASIS beyond those pairs.
CLOSE_CUTOFF = 0.85
#: A word this short carries no meaning of its own here ("of", "in", "a").
MIN_WORD = 3

_WORD = re.compile(r"[a-z0-9]+")


def words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) >= MIN_WORD]


def id_number(un: str) -> str:
    """The ID number as the server's resolver writes it for an index key."""
    return f"UN{un}"


#: the rows and word weights of each ERG pack object seen, by `id` (the pack is loaded
#: once per process; a pydantic model is not hashable, so no `lru_cache`)
_CACHE: dict[int, tuple[Any, list[dict], dict[str, float]]] = {}


def _rows(erg: Any) -> tuple[list[dict], dict[str, float]]:
    held = _CACHE.get(id(erg))
    if held is not None and held[0] is erg:
        return held[1], held[2]
    rows = [
        {"id_number": id_number(un), "name": n.name, "guide": n.guide}
        for un, entry in erg.index.items()
        for n in entry.names
    ]
    df: dict[str, int] = {}
    for r in rows:
        r["_words"] = set(words(r["name"]))
        for w in r["_words"]:
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log(len(rows) / c) for w, c in df.items()}
    _CACHE[id(erg)] = (erg, rows, idf)
    return rows, idf


def candidates(text: str, erg: Any, n: int = CANDIDATES_MAX) -> list[dict]:
    """Up to `n` index rows the words of `text` point to, best first: each
    `{id_number, name, guide}` as the index prints it. Empty when no word of `text` is
    an index word or spelled like one."""
    rows, idf = _rows(erg)
    vocab = list(idf)
    typed = words(text)
    if not typed:
        return []
    reach: dict[str, dict[str, float]] = {}
    for w in typed:
        if w in idf:
            reach[w] = {w: 1.0}
        else:
            near = difflib.get_close_matches(w, vocab, n=3, cutoff=CLOSE_CUTOFF)
            reach[w] = {v: difflib.SequenceMatcher(None, w, v).ratio() for v in near}
    key = " ".join(typed)
    scored = []
    for i, r in enumerate(rows):
        s = 0.0
        for w in typed:
            got = [wt * idf[v] for v, wt in reach[w].items() if v in r["_words"]]
            s += max(got, default=0.0)
        if s > 0:
            close = difflib.SequenceMatcher(None, key, r["name"].lower()).ratio()
            scored.append((-s, -close, i, r))
    scored.sort(key=lambda t: t[:3])
    return [
        {"id_number": r["id_number"], "name": r["name"], "guide": r["guide"]}
        for *_, r in scored[:n]
    ]


def in_index(id_num: str | None, name: str, erg: Any) -> dict | None:
    """The index row `id_num` and `name` name, byte for byte (`{id_number, name,
    guide}`), or None. The ID number is `UN` or `NA` and four digits; the name must be
    one the index prints under it, exactly. With no ID number, the name must be one of
    the rows the index prints without one (the explosives, ERG 2024 PDF p. 31)."""
    if not id_num:
        for r in erg.unnumbered:
            if r.name == name:
                return {"id_number": None, "name": r.name, "guide": r.guide}
        return None
    m = re.fullmatch(r"(UN|NA)(\d{4})", id_num)
    if not m:
        return None
    entry = erg.index.get(m.group(2))
    if entry is None:
        return None
    for nm in entry.names:
        if nm.name == name:
            return {"id_number": id_num, "name": nm.name, "guide": nm.guide}
    return None
