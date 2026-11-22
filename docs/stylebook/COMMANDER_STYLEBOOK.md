# Commander Stylebook

The writing standard for every sentence hazbrief-mcp drafts: the ICS 201 Incident Briefing, the
Protective Action Decision text, and any public alert text. The server ships this file as the MCP
resource `hazbrief://stylebook/commander` and inside the `ics201_brief` prompt; the controlled
vocabulary it cites ships as `hazbrief://stylebook/vocabulary` (`VOCABULARY.yaml`).

**How to read a rule.** Each rule has an id (`SB-` plus section plus number), the rule, how it is
checked, and its receipts. `Check: stylecheck` means `src/hazbrief/stylecheck.py` finds a breach
deterministically, with the parameters in `STYLECHECK.yaml`; `Check: review` means a reader checks
it. A receipt is a Squiddy row (`doc_id#b<block>:<start>-<end>`, a block of the parsed text of
record) returned by `squiddy.index search --graph the corpus graph (held privately)`, followed by the passage
it locates, quoted from the held document. The parse can render a passage differently from the page
(it drops a list item's number, for one), so a quote is matched to its row as
`src/hazbrief/receipt_quotes.py` states. A receipt still in the page-text form
`doc_id#p<page>:<row>:<start>-<end>` is one HB-19 could not re-anchor to a parsed block.
Every receipt is a held, public-domain or reproduction-permitted document.

**What this is not.** The controlled-English rules in sections 3 and 4 (short sentences, one action
per sentence, one term per object, no synonyms) are this project's own rules, grounded in the
federal sources cited beside each. ASD-STE100 is a licensed specification; nothing here is taken
from its text.

## 1. Purpose and reader

### SB-PUR-01 The reader

The reader is an Incident Commander or a Planning Section Chief under time pressure. Every sentence
serves that reader's next decision; nothing is written for any other reader.

- Check: review
- Receipt: `ics-201#b48:2223-2600` "The Incident Briefing (ICS 201) provides the Incident Commander (and the Command and General Staffs) with basic information regarding the incident situation and the resources allocated to the incident."
- Receipt: `ics-forms-instructions#p4:13:576-869` "ICS 201 Incident Briefing Initial Incident Commander *ICS 202 Incident Objectives Planning Section Chief"

### SB-PUR-02 One rapid reading

Write so that the reader understands the brief in one rapid reading.

- Check: review
- Receipt: `ar-25-50#b246:39604-39755` "Effective Army writing is understood by the reader in a single rapid reading"

### SB-PUR-03 A draft for the Incident Commander

The brief is a draft. The Incident Commander reviews it, corrects it, signs it and briefs from it.
The brief never states that a decision has been made.

- Check: review
- Receipt: `ics-201#b49:2602-2764` "The briefing form is prepared by the Incident Commander for presentation to the incoming Incident Commander along with a more detailed oral briefing."

## 2. Structure

### SB-STR-01 Bottom line up front

Put the main point first: in the brief, in each ICS 201 block, and in each paragraph.

- Check: review
- Receipt: `ar-25-50#b247:39757-39991` "putting the main point at the beginning of the correspondence (bottom line up front)"
- Receipt: `cdc-cci-user-guide#b72:7670-7959` "When you put the main message first, people can find it more easily and quickly."

### SB-STR-02 One main message

The brief carries one main message: the Protective Action Decision basis. Every other sentence
supports it.

- Check: review
- Receipt: `cdc-cci-user-guide#b67:7203-7371` "The main message statement is the one thing the audience must remember."

### SB-STR-03 ICS 201 block order

Write the ICS 201 in the form's block order, with the form's block titles: 1 Incident Name;
2 Incident Number; 3 Date/Time Initiated; 4 Map/Sketch; 5 Situation Summary and Health and Safety
Briefing; 6 Prepared by; 7 Current and Planned Objectives; 8 Current and Planned Actions,
Strategies, and Tactics; 9 Current Organization; 10 Resource Summary.

- Check: review
- Receipt: `ics-201#p2:4:0-105` "1. Incident Name: 2. Incident Number: 3. Date/Time Initiated:"
- Receipt: `ics-201#b6:99-348` "4. Map/Sketch"
- Receipt: `ics-201#b7:350-649` "5. Situation Summary and Health and Safety Briefing (for briefings or transfer of command)"
- Receipt: `ics-201#p2:5:107-216` "7. Current and Planned Objectives: 8. Current and Planned Actions, Strategies, and Tactics:"
- Receipt: `ics-201#p6:36:119-437` "9 Current Organization"
- Receipt: `ics-201#b47:1477-2221` "10. Resource Summary:"

### SB-STR-04 The Map/Sketch is the footprint

Block 4 is the protective action footprint: the initial isolation zone and the protective action
zone, the incident site, and the facilities inside them. Block 5 names what the map shows; it does
not describe the map.

- Check: review
- Receipt: `ics-201#b54:3371-5294` "Show perimeter and other graphics depicting situational status, resource assignments, incident facilities, and other special information on a map/sketch or with attached maps."

### SB-STR-05 Isolate first, then protect downwind

State the initial isolation zone before the protective action zone, as the ERG orders the two.

- Check: review
- Receipt: `erg2024-en-pdf#p343:7467:19-100` "First ISOLATE in all Directions Then PROTECT persons Downwind"
- Receipt: `erg2024-en-pdf#b4264:753216-753362` "This is the first step for any protective actions that may follow."

### SB-STR-06 Protective Action Decision order: action, area, basis

State a Protective Action Decision as action, then area, then basis, in that order and in one
sentence: the ERG verb, the zone with its distance, then the source tag that names the ERG table
row. The Incident Commander chooses between evacuation and shelter-in-place; the brief names the
ERG decision factors and does not choose.

- Check: review
- Receipt: `erg2024-en-pdf#p343:7467:19-100` "First ISOLATE in all Directions Then PROTECT persons Downwind"
- Receipt: `erg2024-en-pdf#b4281:755309-755738` "The choice of protective actions for a given situation depends on a number of factors."

### SB-STR-07 Public alert text

When the brief carries a draft public alert for the Public Information Officer, order it hazard,
location, time, action, source. Keep it within the Wireless Emergency Alert limits in
`STYLECHECK.yaml`: 360 characters, with a 90-character version.

- Check: stylecheck
- Receipt: `nws-10-518#b151:47180-47194` "1) type of hazard"
- Receipt: `nws-10-518#b152:47196-47214` "2) location of hazard"
- Receipt: `nws-10-518#b153:47216-47254` "3) actions to be taken by affected people"
- Receipt: `fema-ipaws-wea#b0:0-9953` "The message will show the type and time of the alert, any action you should take, and the agency issuing the alert. The message will be no more than 360 characters."
- Receipt: `fema-ipaws-wea#b1:9955-10697` "Alerting authorities must include 90-character versions of their alerts"

### SB-STR-08 Block 5 follows the orange guide

Write Block 5 in the order of an ERG orange guide: potential hazards, then public safety, then
emergency response. Within potential hazards, the primary hazard comes first.

- Check: review
- Receipt: `erg2024-en-pdf#p348:7514:10-74` "Each guide is divided into 3 main sections: POTENTIAL HAZARDS:"
- Receipt: `erg2024-en-pdf#b4569:879150-879191` "Primary potential hazard is listed first."

### SB-STR-09 The ERG app link goes with the map

When the footprint carries a `verify_in_erg_app` link, Block 4 prints it under the map/sketch,
once, as a check against PHMSA's own drawing of the same scenario: "Check against the PHMSA ERG
app: <link>." Follow it with the footprint's edition sentence: "The app may use ERG 2020
distances. This footprint uses ERG 2024." Never present the app's drawing as the footprint.
Reserved by HB-08b for HB-11's ICS 201 draft.

- Check: review
- Receipt: `phmsa-erg-api-definition#b81:8043-8243` "These parameters are only required and valid if you choose to display the protective distance map (set showMap equal to true)."

## 3. Sentence rules

### SB-SEN-01 Sentence length

Write no sentence longer than **20 words**. The source tag does not count. Write one sentence per
line or bullet: the checker treats each line end as a sentence end.

- Check: stylecheck
- Receipt: `ar-25-50#b259:41157-41238` "Keep sentences short. The average length of a sentence should be about 15 words."

### SB-SEN-02 One action per sentence

Give one action in each sentence. Two actions are two sentences. The ERG guide pages, which
responders already read under pressure, write their actions this way.

- Check: review
- Receipt: `erg-guide-124#b18:1092-1125` "Keep unauthorized personnel away."
- Receipt: `erg-guide-124#b19:1127-1163` "Stay upwind, uphill and/or upstream."

### SB-SEN-03 Active voice

Use the active voice. Name who acts, before the verb.

- Check: review
- Receipt: `ar-25-50#b256:40890-41041` "Use of active voice is the basic style of Army writing."
- Receipt: `cdc-cci-user-guide#b135:12737-12863` "Use active voice and allow the subject of the sentence to perform the action."

### SB-SEN-04 Present tense for conditions, imperative for actions

State a condition in the present tense ("Chlorine is toxic"). State an action in the imperative
("Stay upwind"). Do not predict. The ERG guide pages are the model: hazards in the present
tense, actions in the imperative.

- Check: review
- Receipt: `erg-guide-124#b3:20-93` "TOXIC and/or CORROSIVE; may be fatal if inhaled or absorbed through skin."
- Receipt: `erg-guide-124#b19:1127-1163` "Stay upwind, uphill and/or upstream."

### SB-SEN-05 Plain words, no codes

Use short, common words. Use no codes and no jargon.

- Check: review
- Receipt: `ar-25-50#b258:41138-41155` "(1) Use short words."
- Receipt: `nims-doctrine-2017#b652:149291-149471` "Using plain language and clear text, not codes, in incident management is a matter of public safety"

### SB-SEN-06 Abbreviations

Spell out an abbreviation the first time it appears, then use it. Never write an abbreviation
with two meanings. A source tag names a source as the source names itself.

- Check: review
- Receipt: `cdc-cci-user-guide#b147:14356-14778` "use acronyms and abbreviations sparingly, and when you do use them, spell them out and explain what they refer to"
- Receipt: `nims-doctrine-2017#b653:149473-149911` "Personnel should avoid using acronyms or jargon unique to an agency, organization, or jurisdiction"

## 4. Terminology

### SB-TRM-01 One term per object

Name each object with its one term from `VOCABULARY.yaml`, every time.

- Check: review
- Receipt: `nims-doctrine-2017#b258:67834-68055` "NIMS establishes common terminology that allows diverse incident management and support organizations to work together"
- Receipt: `nims-doctrine-2017#b260:68253-68440` "are given common names and are typed to help avoid confusion"

### SB-TRM-02 No synonyms

Never write a term's forbidden synonym. Each term in `VOCABULARY.yaml` lists them; the ERG's own
glossary names many ("exclusion zone" for the hot zone).

- Check: stylecheck
- Receipt: `erg2024-en-pdf#b4897:933635-935973` "Many terms are used to describe control zones; however, in this guidebook, these zones are defined as"
- Receipt: `erg2024-en-pdf#b4898:935975-938192` "This zone is also referred to as exclusion zone, red zone or restricted zone in other documents."

### SB-TRM-03 The ERG's and the ICS's terms win

When two sources name one object, the ERG's term wins for hazards, zones, distances and protective
actions; the ICS form's term wins for the ICS 201 blocks; NIMS wins for organization, facilities
and resources. The server's own term, protective action footprint, names only the drawing of the
ERG zones.

- Check: review
- Receipt: `nims-doctrine-2017#b259:68057-68251` "Terminology for incident organizational elements is standard and consistent."
- Receipt: `erg2024-en-pdf#b4222:747850-748136` "The Protective Action Zone defines an area downwind from the incident"

## 5. Numbers

### SB-NUM-01 Units always

Every number carries its unit, or the noun that names what it counts, directly after it. Write a
distance as the ERG prints it: metric first, US customary in parentheses ("600 m (2,000 ft)").

- Check: stylecheck
- Receipt: `erg2024-en-pdf#b4597:882463-882804` "the "initial isolation distance" is 150 meters (500 feet)"
- Receipt: `ics-209#p3:60:1251-1882` "(use unit label – e.g., "sq mi")"

### SB-NUM-02 Margin of error

State the margin of error beside every estimate whose source carries one (the American Community
Survey, the Community Resilience Estimates), in the same sentence: "(margin of error 610
residents)".

- Check: stylecheck
- Receipt: `cre-2024-techdoc#b19:6407-6837` "ACS estimates contain statistical error, in the form of sampling variability"
- Receipt: `cre-2024-file-layout#b14:2904-2971` "Margins of error are calculated at the 90 percent confidence level."
- Receipt: `ics-209#b131:19846-22984` "Indicate that the size is an estimate, if a more specific figure is not available."

### SB-NUM-03 As-of date on every live value

Every value read from a live call (wind, population, workers, facilities, beds) carries its as-of
date in its source tag: "as of 10/20/2026 13:40 EDT".

- Check: stylecheck
- Receipt: `ics-209#b131:19846-22984` "Enter the time interval for which the form applies."
- Receipt: `nws-disclaimer#b2:5444-12517` "NWS products are constantly updated/changed/decommissioned"

### SB-NUM-04 No unsourced number

Every sentence with a number ends with a source tag, in square brackets before the full stop: "...
east of the spill [ERG 2024 Table 3]." The tag names the source, the table or guide, and for a
live value the as-of date. A number with no source is not written.

- Check: stylecheck
- Receipt: `nws-10-518#b148:46499-46629` "The lead-in to the NWEM will contain the source of the information"
- Receipt: `nws-10-518#b110:39774-39995` "The source of the information should be a federal, state, tribal or local government agency"

### SB-NUM-05 Numbers with context

Say what each number counts and where: "4,180 residents live in the protective action zone", not
"4,180 affected".

- Check: review
- Receipt: `cdc-cci-full-score-sheet#b83:9807-9862` "16. Does the material always explain what the numbers mean?"
- Receipt: `cdc-cci-user-guide#b284:29417-29852` "Provide reasons why the numbers in the material are important to the main message"

### SB-NUM-06 Dates and times

Write dates month/day/year and times on the 24-hour clock with the time zone: "10/20/2026 13:40
EDT".

- Check: stylecheck
- Receipt: `ics-201#b54:3371-5294` "Enter date initiated (month/day/year)"
- Receipt: `ics-209#p8:127:193-386` "Time Zone Enter the time zone of the incident (e.g., EDT, PST)."

## 6. What is never written

### SB-NEV-01 No dispersion language

Never write "plume", "dispersion" or "dispersion model". The server runs no dispersion model
(DN-001 section 4, invariant 1). The ERG uses "plume" only for the atmospheric analysis behind its
tables; the area people act in is the protective action zone. The ERG verb "disperse", a response
action ("disperse vapors" with water spray), stays.

- Check: stylecheck
- Receipt: `erg2024-en-pdf#b4222:747850-748136` "The Protective Action Zone defines an area downwind from the incident"
- Receipt: `erg2024-en-pdf#b4327:760600-760733` "Since atmospheric mixing is less effective at dispersing vapor plumes during nighttime, day and night were separated in the analysis."

### SB-NEV-02 No adjusted distance

Write an ERG distance exactly as the table prints it, "+" included ("11.0+ km (7.0+ mi)"). Never
adjust, interpolate or extrapolate one.

- Check: review
- Receipt: `erg2024-en-pdf#b4223:748138-748441` "These adjustments should only be made by technically qualified personnel."
- Receipt: `erg2024-en-pdf#b4234:749758-749900` "If a material has a protective action distance of 11.0+ km (7.0+ miles), the actual distance can be larger in certain atmospheric conditions."

### SB-NEV-03 No confidence words without a source

Never write a confidence word ("likely", "probably", "certainly"; the list is in `STYLECHECK.yaml`)
in a sentence with no source tag. State what is known and what is not known instead.

- Check: stylecheck
- Receipt: `cdc-cci-user-guide#b223:22313-22637` "Acknowledge uncertainty about data, findings, recommendations, guidance and action steps."

### SB-NEV-04 No named individuals, no contact details

Name people by ICS position, never by name. Write no phone number and no email address. The
Incident Commander enters names in Block 6 and Block 9. The server promises facilities in the
footprint, not contacts (DN-001 section 5).

- Check: stylecheck
- Receipt: `ics-209#p9:147:378-714` "ICS Position The ICS title of the person preparing the form (e.g., "Situation Unit Leader")."
- Receipt: `ics-201#b55:5296-7512` "Enter on the organization chart the names of the individuals assigned to each position."

### SB-NEV-05 No unflagged alarm

Write only the flags the server's rule packs raised, each with its rule and source (DN-001
section 4, invariant 2). Never add a warning, a priority or a judgment of severity of the
writer's own. Officials decide; the brief informs them.

- Check: review
- Receipt: `erg2024-en-pdf#b4300:756688-757038` "Officials must continue to gather information and monitor the situation until the threat is removed."

## 7. Worked example

A synthetic scenario, written to this standard. Daytime, 10/20/2026. A highway tank truck carrying
chlorine (UN1017, ERG Guide 124) is leaking on I-81 southbound; the spill is large. The NWS wind is
from the west at 13 km/h (8 mph), a moderate wind, so ERG Table 3 gives a 600 m (2,000 ft)
initial isolation distance and a 3.3 km (2.1 mi) daytime protective action distance. The live
counts are invented for the example. The text between the markers passes `stylecheck` with no
findings (test_stylebook.py (a test held privately)).

<!-- worked-example:start -->
#### Block 5. Situation Summary and Health and Safety Briefing

##### Bottom line

- Isolate the initial isolation zone: 600 m (2,000 ft) in all directions from the spill [ERG 2024 Table 3, UN1017, highway tank truck].
- Protect people in the protective action zone: 3.3 km (2.1 mi) downwind, east of the spill [ERG 2024 Table 3, UN1017, highway tank truck, daytime, moderate wind].
- Choose evacuation or shelter-in-place for that zone from the ERG decision factors [ERG 2024 Protective Actions].

##### Potential hazards

- Chlorine (UN1017) is leaking from a highway tank truck on I-81 southbound at mile marker 59 [incident report, as of 10/20/2026 13:25 EDT].
- Chlorine is toxic and may be fatal if inhaled [ERG 2024 Guide 124].
- Chlorine does not burn but supports combustion [ERG 2024 Guide 124].
- Vapor from the liquefied gas is heavier than air and spreads along the ground [ERG 2024 Guide 124].

##### Public safety

- Wind is from the west at 13 km/h (8 mph) [NWS api.weather.gov gridpoint forecast, as of 10/20/2026 13:40 EDT].
- 4,180 residents live in the protective action zone (margin of error 610 residents) [ACS 2020-2024 5-year, table B01003, as of 01/29/2026].
- 1,950 workers have jobs in the protective action zone [LEHD LODES8 workplace area characteristics 2022, as of 12/03/2025].
- 2 schools and 1 nursing home are inside the protective action zone [USGS National Map Structures, as of 10/2026].
- 1 hospital is inside the protective action zone and is a casualty site [USGS National Map Structures, as of 10/2026].

##### Emergency response

- Stay upwind, uphill and upstream of the spill [ERG 2024 Guide 124].
- Keep unauthorized personnel out of the initial isolation zone [ERG 2024 Guide 124].
- Wear positive pressure self-contained breathing apparatus (SCBA) inside the initial isolation zone [ERG 2024 Guide 124].
- Do not direct water at the spill or the source of the leak [ERG 2024 Guide 124].
- Send casualties only to hospitals outside the protective action zone.
<!-- worked-example:end -->
