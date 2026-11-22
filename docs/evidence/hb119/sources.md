# HB-119 Part A: the two sources, read and recorded

Date: 2026-11-07. Read by the headless session executing
`HB-119`
with ADDENDUM-00 and ADDENDUM-01. Every page quoted below is held (`corpus/sources.yaml`) unless it says otherwise.

## 1. robots.txt (step 1; DN-002 ADDENDUM-00)

Both hosts were already on `corpus/allowlist.txt` (HB-01, HB-01b). Each robots.txt was read again under the project's
one identity, `hazbrief-mcp/0.1.0 (+https://github.com/brockwebb/hazbrief-mcp)`, at 2026-11-07T08:08:22Z, by
`tools/read_robots.py`. Bodies, hashes and the per-path decisions (Protego, the fetcher's parser) are in `robots/`.

| Host | Status | sha256 | What it says for `*` | Paths the resolver uses |
|---|---|---|---|---|
| cameochemicals.noaa.gov | 200 | `fd265de2…aaa48` | Disallow /help, /my, /reactivity, /search, /stats; no crawl delay | `/chemical/<id>` allowed; `/unna/<UN>` allowed; `/search/…` disallowed |
| pubchem.ncbi.nlm.nih.gov | 200 | `3a832150…5830c` | Version 2026-10-29.1. `Crawl-delay: 5`; disallows `/rest/pug/` and keeps `/rest/pug_view` crawlable ("Keep /rest/pug/ scoped so /rest/pug_view remains crawlable") | PUG View allowed; PUG REST disallowed |

**CAMEO: the resolver reads `/chemical/<id>` and nothing under `/search`.** CAMEO's only route from a UN number to a
datasheet is `/search/chemicals_for_unna/<UN>`. The held UN/NA page `cameo-unna-1017` links to it ("CAMEO Chemicals
has 1 chemical datasheet with response recommendations for this UN/NA number"), and robots.txt disallows it. The
project already counted eight GETs there a manners violation (HB-01 RESULT section 8). So the resolver finds CAMEO's
datasheet through PubChem: PUG View's record for a compound lists its references, and CAMEO Chemicals is one, with the
datasheet id as `SourceID` (chlorine, CID 24526: `CAMEO Chemicals`, `2862`,
`https://cameochemicals.noaa.gov/chemical/2862`).

**PubChem PUG REST: a per-request API call, under DN-002 section 1.** Its robots.txt disallows `/rest/pug/` for every
agent. DN-002 section 1 already rules on this case: "Runtime API calls … are not crawling. Each is a documented
public API whose own terms govern programmatic use … `robots.txt` on `api.weather.gov` does not bind a per-request API
client. The server identifies itself …, honors documented rate limits, and never enumerates." The resolver makes at
most two name or CAS lookups and one property call per material, identifies itself, and honours the held limits
(section 2). The corpus fetcher stays robots-bound. The robots.txt change is dated 2026-10-29, after HB-98 read the
access pages. Issue `bdfbe892` records it for the Desktop, in case the operator reads the
change as PubChem's intent for API clients too.

## 2. PubChem's limits and URL forms (step 1)

**Limits.** From `pubchem-pug-view-limits` (Kim et al., J Cheminform 2019, "Usage policy"): "The current limits are:
No more than 5 requests per second. No more than 400 requests per minute. No longer than 300 s running time per
minute." It also says: "when PubChem gets an excessive number of service requests, these limits are tightened through a
dynamic web-request throttling". From `pubchem-programmatic-access`: "We ask that any user, application, or
organization not make more than 5 requests per second, in order to avoid overloading these servers. … We cannot offer
API keys or whitelists to exceed these limits." It adds: "PubChem has a standard time limit of 30 seconds per web
service request." The three numbers are `config.py` `pubchem_max_requests_per_second`,
`pubchem_max_requests_per_minute` and `pubchem_max_running_seconds_per_minute`. `materials.RateGate` enforces them on
every PubChem call that is not a replay.

**PUG View URL form**, from `pubchem-pug-view-limits`:
- by CID with a section: `https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/1983/JSON?heading=Experimental+Properties`
  ("Experimental properties of CID 1983");
- by CID only: "PUG-View primarily takes only the corresponding CID (rather than chemical names, … ) in the request
  URL … to get annotations corresponding to non-CID identifiers, they need to be converted to CIDs first (e.g., using
  PUG REST)";
- a missing section: "If the compound does not have any data to present in that section, the requests would return an
  error message."

The resolver reads two sections, `heading=Experimental Properties` and `heading=CAS`.

**PUG REST URL forms: not on a held page.** Neither held page prints PUG REST's grammar. The official documentation,
`https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest`, answered this client with a reCAPTCHA challenge page
(`pug_rest_docs/record.json`; the challenge body is not kept). HB-98 met the same wall on the programmatic-access page.
That is rung 3 of the ladder (DN-002 ADDENDUM-00, a CAPTCHA). Issue `03cb703e` holds it.
The forms the resolver uses were verified instead by their recorded answers (`pubchem/ (held privately)`):
- `rest/pug/compound/name/<name or CAS>/cids/JSON` gives `{"IdentifierList": {"CID": [...]}}`. A CAS number is accepted
  as a name (`7782-50-5` gives 24526). An unknown name answers **404** with a JSON `Fault` (`PUGREST.NotFound`).
- `rest/pug/compound/cid/<cid>/property/MolecularWeight,MolecularFormula,Title/JSON` gives a `PropertyTable`.

**What PubChem serves, per the recorded records.** Molecular weight is PUG REST's computed property. The experimental
values are PUG View's "Experimental Properties" headings, each row naming its depositor (`Reference.SourceName`) and
that depositor's licence URL. `pubchem_headings.txt` lists the headings of the three recorded records. Chlorine's:
Physical Description, Color/Form, Odor, Boiling Point, Melting Point, Solubility, Density, Vapor Density, Vapor
Pressure, Henry's Law Constant, Stability/Shelf Life, Autoignition Temperature, Decomposition, Viscosity, Corrosivity,
Heat of Vaporization, Surface Tension, Ionization Potential, Odor Threshold, Refractive Index, Other Experimental
Properties.

Of the task's list, PubChem's headings that the resolver reads are:
- **molecular weight**: PUG REST `MolecularWeight`;
- **boiling point**: "Boiling Point", rows at one atmosphere only;
- **vapour pressure**: "Vapor Pressure", rows in mm Hg;
- **heat of vaporisation**: "Heat of Vaporization", per mole;
- **flash point**: "Flash Point". It is recorded here but not mapped, because HB-109's schema has no flash point field;
- **LFL**: "Lower Explosive Limit (LEL)" or "Flammable Limits", where printed;
- **density**: "Density". It is not mapped: its rows mix gas density, liquid density and relative density with no
  declared basis (chlorine's: "2.898 g/L", "1.424 at 59 °F (pressurized liquid)", "2.47(relative gas density)").

**Selection rules** (code: `materials._pubchem_*`). The rules follow HB-109's:
- a boiling point is the first row that agrees with another within the larger of their printed precisions; a single
  row is taken as printed; none is taken when no two rows agree;
- a heat of vaporisation is the row nearest the boiling point;
- every other field takes the first row that parses with its unit.

## 3. CAMEO Chemicals' datasheet (step 1)

**URL forms**, from the held pages' own URLs:
- a datasheet: `https://cameochemicals.noaa.gov/chemical/<id>` (`cameo-chem-2862` and the seven other `cameo-chem-*`);
- a UN/NA page: `https://cameochemicals.noaa.gov/unna/<UN>` (`cameo-unna-*`). It carries the ERG material names, the
  guide and the isolation distances. It prints no physical property, and links to its datasheets only through
  `/search` (section 1).

**What CAMEO's properties section carries.** The task calls it "Chemical Properties". On the datasheet the heading is
**"Physical Properties"** (`<h2 id="section4">`; its help link reads "Physical Property fields"). On `cameo-chem-2862`
(chlorine) it carries:
- the chemical formula;
- Flash Point, Lower Explosive Limit (LEL) and Upper Explosive Limit (UEL), each "data unavailable";
- Autoignition Temperature ("Not flammable");
- Melting Point (-150°F);
- Vapor Pressure (7600 mmHg at 86°F);
- Vapor Density (Relative to Air) (2.49);
- Specific Gravity (1.424 at 59°F, pressurized liquid);
- Boiling Point (-30.3°F at 760 mmHg);
- Molecular Weight (70.91);
- Water Solubility (0.7 %);
- Ionization Energy/Potential (11.48 eV);
- IDLH (10 ppm, NIOSH 2024);
- the AEGL table.

Each value carries its own citation ("(EPA, 1998)"). The resolver reads the Molecular Weight, Boiling Point,
Vapor Pressure, Specific Gravity and LEL fields, each at the temperature it prints. It reads the datasheet's CAS Number
and UN/NA Number cells too. A datasheet whose UN/NA cell does not list the material's UN number is not used.

## 4. Heat capacities (ADDENDUM-01 section 2)

**CAMEO Chemicals: none.** The Physical Properties fields above are the whole section. No field names a heat capacity,
on `cameo-chem-2862` or on the recorded `chemical/2907` (whose fields all print "data unavailable"). HB-109 found the
same ("CAMEO has no such field").

**PubChem: no heading, sometimes a sentence.** None of the three recorded Experimental Properties records has a heat
capacity heading. Chlorine's carries one in an HSDB sentence filed under **Density**: "Heat capacity at constant
pressure (gas, 25 °C): 8.11 cal/mol °C". The resolver reads a heat capacity from any row that names one with its phase
and a per-mole or per-mass unit, keeping the phase and temperature printed beside it in the receipt. Chlorine's
becomes `vapour_heat_capacity_j_mol_k` 33.93 J/mol/K at 298.15 K. Its conversion names the thermochemical calorie
(4.184 J). The page does not say which calorie, and the International Table calorie differs by 0.07 %. No held page
defines the calorie; this follows HB-109's precedent of converting by a stated definition. "Ratio of Specific Heats of
Vapor (Gas): 1.325" is not a heat capacity and is not read. Ibuprofen's and 4-chlorophenyltrichlorosilane's records
print none, so both fields are absent with the reason named.

The resolver stores the value at the temperature it is stated at. It applies no temperature correction and does not
decide whether a value at 298.15 K may supply SLAB's CPS at another release temperature (Issue `6f5a8ac5`, unchanged).

## 5. The thresholds (step 4, ADDENDUM-00)

**The order**, read from `cameo-chemicals-help-locs` and quoted in `src/hazbrief/brief/materials.yaml`:
- "you may want to select your values based on a hierarchy of available public exposure guidelines (for instance,
  using AEGLs preferentially over TEELs if both systems define values for a chemical)";
- "This hierarchy of values (60-minute AEGLs > ERPGs > TEELs) is implemented in the PACs dataset";
- on IDLHs: "IDLH limits were created mainly to assist in making decisions regarding respirator use", and "the current
  definition has no exposure duration associated with it".

ERPGs and PACs are not held. The order is therefore AEGL-2, then IDLH, then nothing.

**The tables**, parsed once with the page of every row by `scripts/build_packs.py thresholds` (HB-109's builder):
- **`packs/src/thresholds_aegl_compiled_2018.json`**: 270 entries from `epa-aegl-compiled-2018` (228 in ppm, 42 in
  mg/m3; 185 Final, 72 Interim, 12 Proposed, 1 Holding).
  - "see below" cells are resolved from the entry's own "AEGL n - … = … ppm" line (propane's AEGL-2 is 17,000 ppm).
  - NR and ND cells are absent with their meaning.
  - 15 rows print fewer cells than the five columns: the nerve and mustard agents, acetone's AEGL-2 and AEGL-3, and
    MTBE's AEGL-3. Each is kept as printed, marked `unparsed` with the reason, and never guessed.
  - Chlorine's AEGL-2 reads 2.8, 2.8 and 2.0 ppm at 10, 30 and 60 min (p. 43), the seed's own cells.
- **`packs/src/thresholds_niosh_npg_idlh.json`**: 675 entries from `niosh-npg-2005-149`; 397 print an IDLH value. Each
  row carries its receipt, "CAS#: … RTECS#: … IDLH: …" verified on its page, and the DOT field's UN and guide pairs.
  Chlorine: 10 ppm, p. 89.

Both are application data: `.dockerignore` keeps them out of the server's image.
