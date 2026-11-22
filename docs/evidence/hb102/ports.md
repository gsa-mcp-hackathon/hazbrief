# HB-102 step 6: prior art for a port — PyPI, searched within its robots.txt

**Hosts.** pypi.org and files.pythonhosted.org, the task's allowlist. Nothing was installed.
Nothing was registered in the corpus.

## What was searched, and how

1. pypi.org's `robots.txt`, read 2026-11-04, disallows `/search*`, `/simple/`, `/packages/`,
   `/pypi/*/json` and `/pypi*?`. So the search page, the simple index and the JSON API are all
   closed to an automated client. It publishes `Sitemap: https://pypi.org/sitemap.xml` and does
   not disallow `/project/<name>/`.
2. `pypi_name_scan.py` read the sitemap index (257 sub-sitemaps) and every sub-sitemap. That gave
   **920,772 project names**, PyPI's full project list as of the sitemap's `lastmod` dates
   (2026-10-21). The checkpoint plan is in the script's docstring. The unit is one file, and a
   unit whose file exists is skipped. There was a pilot of one sub-sitemap (0.08 s, 0.56 MB,
   8,117 names), 1 s pacing, and a 15-minute ceiling. The first run was killed by this session's
   10-minute tool timeout while it was fetching project pages (243 of 345). Re-running the same
   command resumed it and fetched only the missing pages (`pypi/pypi_scan.log`,
   `pypi/pypi_scan2.log`).
3. Names were matched against the terms `slab, degadis, densegas, dense-gas, dense_gas, heavygas,
   heavy-gas, heavy_gas, hegadas, hegadis, gasdispersion, gas-dispersion, gas_dispersion,
   britter, aloha-, pyaloha, denz, dispersion-model, airdispersion`. There were **345 hits**
   (`pypi/pypi_report.json`).
4. Each hit's `/project/<name>/` page was fetched for its summary, version, licence and date.
   **Every page came back as PyPI's JavaScript "Client Challenge"**, a 3,038-byte bot check, not
   the project page (`pypi/degadisx_client_challenge.html`). The fetcher therefore reached no
   project metadata. This is a refusal at rung 1 of the acquisition ladder (DN-002 ADDENDUM-00).
   This session has no browser tools connected, so it could not climb rung 2 itself.

## What was found

*Rewritten by HB-107 (2026-11-06). HB-102 found the names. HB-105 Part D and HB-107 Part B read
the pages at rung 2, and HB-107 Part A read degadisx's repository at rung 1. All ten are held as
`reference-only` corpus rows in release `hb107_ports`. HB-102's original text of this section is
in git history.*

**Two real port leads, by the same author (Ugwiyeon Lee, PyPI `lyullee`), both released
2026-09-12, both MIT:**

- **`degadisx` 0.1.4, "A Python reimplementation of EPA DEGADIS 2.1"** (`pypi-degadisx`;
  repository files `degadisx-readme`, `degadisx-reproduction`, `degadisx-license` and
  `degadisx-pyproject` at commit `35ffd39b`, which is tag `v0.1.4`). Development Status 4 - Beta.
  Its reproduction claims (`docs/evidence/hb107/degadisx.md`):
  - It covers the ground-level steady and transient routes, the pressurised jet, the deck readers
    and the bridge.
  - It replayed the five EPA examples HB-102 ran (B9, B9 transient, EX1, EX2, EX3). The steady and
    jet cases reproduced "all non-timestamp listing lines". B9 transient had "eight differences
    confined to seventh-significant-digit numerical formatting". That is the same order as
    HB-102's 8.1e-7.
  - Python against its source-built Fortran: about 1e-6 on profiles. "Some full-driver
    concentration outputs differed by up to about 3%."
  - "These are reproduction checks, not experimental validation."
  - **It does not mention the `/ERROR/` COMMON padding or `EPSILON`** that HB-102 found. It names
    no compiler or source edit for its reference build.
- **`slabx` 1.0.7, "A Python reimplementation of the SLAB dense-gas dispersion model, verified
  against the original and evaluated against field and wind-tunnel trials"** (`pypi-slabx`;
  repository https://github.com/lyullee/slabx, concept DOI 10.5281/zenodo.22023625).
  Development Status 5 - Production/Stable. Its page states:
  - **Against the original Fortran:** the five decks of the manual agree "to 0.05–1.48 % on every
    cloud variable". A random differential test over 108 decks gives a median difference of
    0.09 % on temperature and 0.67 % on concentration.
  - **Against measurements:** 38 field and wind-tunnel trials. On the ten LNG trials it "passes
    all five Chang–Hanna criteria (FAC2 0.90, MG 1.25, NMSE 0.12)".
  - **Its limits:** a `LIMITATIONS.md` names a runaway for dense, low-momentum releases, an
    over-strong stability response and a hard-coded reference height.
  - Its repository's `VALIDATION.md` and `LIMITATIONS.md` are **not held**.

**Ruled out by their own pages (not the dense-gas model):**

| package | version, released | summary on the page |
|---|---|---|
| `slab` (`pypi-slab`) | 1.8.2, 2025-08-11 | "Tools for generating and manipulating digital signals, particularly sounds" |
| `pyslab` (`pypi-pyslab`) | 0.1.0, 2021-02-14 | "Play Your Sudoku Like A Boss" |
| `pyslabs` (`pypi-pyslabs`) | 0.1.7, 2022-01-17 | "Pure Python Paralle I/O" (sic) |
| `slabs` (`pypi-slabs`) | 1.0.3, 2026-04-30 | "Automated network lab provisioning on GCP with containerlab and netlab" |

So of HB-102's six priority pages, **two are ports and four are not.** HB-102's recipe expected
one lead, and it was wrong on `slabx`.

**By name only, unchanged from HB-102:**
- No name contains `densegas`, `heavygas`, `hegadas`, `hegadis`, `britter`, `gasdispersion` or
  `airdispersion`.
- `slabkit`, `slab-cli`, `slab-utils` and `slabdip` are still unread, not ruled out.
- The `aloha-*` and `denz` hits are judged unrelated by name alone (`aloha-api`,
  `django-aloha-editor`, `gym-aloha-dummy`, `slotted-aloha-simulator`, `cadenza`, `denzel` ...).
  The `denz` term was too broad: it matches "cadenza".

Not searched: GitHub, conda-forge, Julia's General registry and the literature. Those hosts are
outside this task's allowlist. "No port found" is therefore claimed only for PyPI project
*names*. PyPI package *contents* and other registries were not searched.

## Rung 2, for the Desktop thread or a session with browser tools

*Done (HB-107): HB-105 Part D and HB-107 Part B read all six pages below through nested
`claude -p --chrome` sessions (`the HB-105 evidence (held privately)`, `docs/evidence/hb107/ports/`). The
recipe is kept as written.*

Open these pages in the operator's browser and read the summary, latest version and date,
licence, homepage or repository, and whether the description claims validation against field
trials or the original code's test cases. In priority order:

1. `https://pypi.org/project/degadisx/`
2. `https://pypi.org/project/slab/`, `https://pypi.org/project/pyslab/`,
   `https://pypi.org/project/pyslabs/`, `https://pypi.org/project/slabs/`,
   `https://pypi.org/project/slabx/`

Register a page in `corpus/sources.yaml` only if DN-020 will cite it.
