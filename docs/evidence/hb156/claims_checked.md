# HB-156: the two claims, checked against the held text

**Task:** `HB-156`
**Claims from:** Issue `69466498` (Desktop's notes, from recollection).
**Held in release:** `hb01b_59` (Work 504 → 507).

Every quotation below was matched in the held bytes by `tools/locate_quotes.py` against `quotes.yaml`. Its output,
`locate_quotes.txt`, gives the PDF page and the sha256 of each file read. Page references give both the printed page
and the PDF page.

## Sources read

| doc_id | What it is | Held |
|---|---|---|
| `cfr40-part68-govinfo-2025` | 40 CFR part 68, CFR 2025 edition (revised as of 2025-07-01), govinfo | before this task (HB-23) |
| `usc-42-7412-caa-112-2024` | 42 U.S.C. 7412 (CAA section 112), U.S. Code 2024 edition, govinfo | this task |
| `plaw-106-40-csissfrra-1999` | Public Law 106-40, 113 Stat. 207, 1999-08-05, govinfo | this task |
| `fr-2000-19785-oca-distribution-final-rule` | EPA and DOJ final rule, 65 FR 48108, 2000-08-04, with part 1400's text as promulgated (65 FR 48131-48133), govinfo | this task |
| `epa-rmp-sccap-final-rule-2024-prepub` | EPA's 2024 Safer Communities final rule, pre-publication copy | before this task (HB-127) |
| `epa-rmp-federal-reading-rooms` | EPA's Federal Reading Rooms page (last updated 2026-07-14 as held) | before this task (HB-135) |

**Not held: 40 CFR part 1400 as codified.**
- govinfo's 2025 title 40 edition has no volume 37 yet. Its sitemap lists volumes 1 to 36, and volume 36's
  metadata names no part 1400.
- The 2024 edition's metadata lists the part-level granule `CFR-2024-title40-vol37-part1400`. Its PDF rendition
  answered 200 with five pages of 40 CFR part 1090 (§§ 1090.10 to 1090.1845) and no part 1400 text
  (`part1400_wrong_granule_sections.txt`, `fetch_log_part1400_wrong_granule.jsonl`). Those bytes were not admitted.
- eCFR refuses this client. HB-135's probes found the versioner API robots-disallowed and the pages bot-walled.
- So part 1400 is quoted from its text as promulgated in the 2000 final rule. The CFR source note is "65 FR 48131,
  Aug. 4, 2000, unless otherwise noted". The held 2026 reading-rooms page states the same 10-facility limit as §
  1400.3(c), which is current corroboration but not the codified text. Issue: see the RESULT.

## C1, the named practice

> EPA's Risk Management Program requires covered facilities to analyse and report a worst-case release scenario as
> part of an offsite consequence analysis.

**Verdict: confirmed as worded.**

- **40 CFR 68.20** (subpart B, Hazard Assessment; 40 CFR, 7-1-25 edition, p. 169; PDF p. 8): "The owner or operator
  of a stationary source subject to this part shall prepare a worst-case release scenario analysis as provided in §
  68.25 of this part and complete the five-year accident history as provided in § 68.42."
- **40 CFR 68.25(a)** (p. 169; PDF p. 8): "(a) The owner or operator shall analyze and report in the RMP: (1) For
  Program 1 processes, one worst-case release scenario for each Program 1 process;". Paragraph (a)(2) then requires,
  for Program 2 and 3 processes, one worst-case scenario for toxics and one for flammables.
- **40 CFR 68.165(a)**, the section headed "Offsite consequence analysis" (p. 203; PDF p. 42): "(a) The owner or
  operator shall submit in the RMP information: (1) One worst-case release scenario for each Program 1 process;".
  Paragraph (b) lists the 14 data reported, among them the distance to endpoint and the receptors within it.
- **The statute** behind the rule, 42 U.S.C. 7412(r)(7)(B)(ii)(I) (U.S. Code 2024, Page 7221; PDF p. 22), says the
  plan's hazard assessment "shall include an estimate of potential release quantities and a determination of
  downwind effects, including potential exposures to affected populations" and "shall include an evaluation of worst
  case accidental releases".
- **EPA and DOJ's own summary** (65 FR 48108; PDF p. 1): "Congress further mandated that facilities perform an
  off-site consequences analysis (OCA) for one or more hypothetical accidental worst case and/ or alternative release
  scenarios and report the results of the analysis in a risk management plan (RMP)".

**Precision notes.** These do not change the verdict:
- "Covered facilities" is the rule's "stationary source subject to this part".
- The requirement covers every covered process, Program 1 included.
- Program 2 and 3 processes also report alternative release scenarios (§ 68.165(a)(2)).
- The parameters fixed for the worst case are in § 68.22, among them "a wind speed of 1.5 meters per second and F
  atmospheric stability class".

## C2, the misuse precedent

> Congress restricted public dissemination of the offsite consequence analysis information facilities filed, on a
> misuse concern, while keeping the planning requirement.

**Verdict: confirmed with a correction.**

**The correction.** Congress restricted disclosure by the government and by those it shares the information with,
not by the facilities. It also did not set the public limits itself. It directed that rules be made after an
assessment, and EPA and DOJ made them in 2000.

**Corrected wording:** In 1999, Public Law 106-40 added Clean Air Act section 112(r)(7)(H). The new subparagraph took
the offsite consequence analysis portions of filed risk management plans out of FOIA. It barred the government
officials and researchers who receive that information from disclosing it to the public. It also had the President
assess "the increased risk of terrorist and other criminal activity associated with the posting of off-site
consequence analysis information on the Internet" and then set access rules. EPA and DOJ's 2000 rule (40 CFR part
1400) limits public access to read-only paper copies in Federal Reading Rooms, up to 10 facilities a month anywhere
plus every facility in the reader's own LEPC jurisdiction. The requirement that facilities perform and report the
analysis was left in place. A facility may still publish its own analysis.

**The restriction and its reach** (Public Law 106-40, section 3(a), enacting CAA 112(r)(7)(H)):
- **What is restricted**, (H)(i)(III) (113 Stat. 208; PDF p. 2): "The term 'off-site consequence analysis
  information' means those portions of a risk management plan, excluding the executive summary of the plan,
  consisting of an evaluation of 1 or more worst-case release scenarios or alternative release scenarios, and any
  electronic data base created by the Administrator from those portions."
- **FOIA**, (H)(iii)(II) (113 Stat. 209; PDF p. 3): "off-site consequence analysis information covered by the
  regulations, and any ranking of stationary sources derived from the information, shall not be made available under
  section 552 of title 5, United States Code, after the end of that period."
- **Who may not disclose**, (H)(v)(I) (113 Stat. 210; PDF p. 4): "a covered person shall not disclose to the public
  off-site consequence analysis information in any form, or any statewide or national ranking of identified
  stationary sources derived from such information, except as authorized by this subparagraph". A "covered person"
  is a federal, state or local official, a contractor, a planning or response entity, or a qualified researcher
  ((H)(i)(I)). The same words stand in the codified text, 42 U.S.C. 7412(r)(7)(H)(v)(I) (U.S. Code 2024, Page 7223;
  PDF p. 24).
- **Facilities are not bound**, (H)(v)(III) (113 Stat. 210; PDF p. 4): "If the owner or operator of a stationary
  source makes off-site consequence analysis information relating to that stationary source available to the public
  without restriction", the prohibition and penalties do not apply to that information.
- **The rule** (40 CFR 1400.10 as promulgated, 65 FR 48133; PDF p. 26): "federal, state, and local government
  officials, and qualified researchers are prohibited from disseminating OCA information and OCA rankings to the
  public." And § 1400.3(c) (65 FR 48132; PDF p. 25): "(c) Limited number. Any person shall be provided with access to
  a paper copy of the OCA information for up to 10 stationary sources located anywhere in the country, without
  geographical restriction, in a calendar month."
- **Today** (2024 final rule, pre-publication copy, PDF p. 194): "This OCA information remains accessible to the
  public only in Federal Reading Rooms". And PDF p. 186: "By policy, EPA has restricted access to the RMP database,
  even though only a portion of the database is restricted by CAA section 112(r)(7)(H) and its implementing
  regulations in 40 CFR part 1400."

**The misuse concern:**
- **The statute**, (H)(ii)(I)(aa) (113 Stat. 208; PDF p. 2): the President shall assess "the increased risk of
  terrorist and other criminal activity associated with the posting of off-site consequence analysis information on
  the Internet;".
- **The rule's background** (65 FR 48109; PDF p. 2): "the Federal Bureau of Investigation and other representatives
  of the law enforcement and intelligence communities raised concerns that releasing the OCA portions of RMPs via the
  Internet would enable individuals anywhere in the world anonymously to search electronically for industrial
  facilities in the U.S. to target for purposes of causing an intentional industrial chemical release."
- The same statute also required an assessment of "the incentives created by public disclosure of off-site
  consequence analysis information for reduction in the risk of accidental releases" ((H)(ii)(I)(bb); 113 Stat.
  208-209, PDF pp. 2-3). The rule
  records that the benefits assessment "concluded that public disclosure of OCA information would likely lead to a
  significant reduction in the number and severity of accidental chemical releases" (65 FR 48109). The precedent
  weighs both value and caution, as Desktop's note said.

**The planning requirement kept:**
- Public Law 106-40 amends CAA 112(r)(2) and (r)(4) and adds (r)(7)(H). It does not amend (r)(7)(B), which still
  requires the evaluation of worst-case releases in the 2024 U.S. Code (C1 above).
- Part 1400 as promulgated, § 1400.1 (65 FR 48131; PDF p. 24): "Stationary sources subject to the Chemical Accident
  Prevention Provisions of 40 CFR part 68 are required to analyze the potential harm to public health and welfare of
  hypothetical chemical accidents and submit the results of their analyses to the U.S. Environmental Protection
  Agency as part of risk management plans."
- The Act also required, section 4(a) (113 Stat. 214; PDF p. 8), that "each owner or operator of a stationary source
  covered by section 112(r)(7)(B)(ii) of the Clean Air Act shall convene a public meeting, after reasonable public
  notice, in order to describe and discuss the local implications of the risk management plan", including a summary
  of the offsite consequence analysis.

## What this means for the backlog design note (Issue 69466498)

- The worst-case release scenario is a named federal practice under 40 CFR part 68 subpart B. Its fixed conditions
  are in § 68.22: 1.5 m/s wind, F stability, the highest daily maximum temperature. This is what a worst-case builder
  would cite.
- The disclosure precedent is narrower than recollected:
  - The law limits the government's distribution of facilities' filed analyses: no FOIA, reading rooms, no
    Internet posting of a national database.
  - It does not forbid the analysis itself, and it does not forbid a facility, or anyone, from publishing their own.
  - Congress weighed the planning and risk-reduction value against the misuse risk and kept both. That is the same
    balance the operator stated.
