# HB-190: open copies the fetcher could not take, for the Desktop thread (rung 2)

Written by `tools/report.py` from `unreached.tsv`. Each URL below is an open copy (a repository's submitted or
accepted manuscript, a publisher's open-access PDF, or a repository HB-188 or the task named) that the allowlisted
fetcher refused: its host is not on this task's network line (`blocked_host`, no request made), the host answered
403 or 202, or its robots.txt Crawl-delay exceeds the fetcher's limit. No refusal was gone around. Nothing here is for
the operator to download by hand: the operator is the last rung, only for a credential, payment, CAPTCHA or legal gate
(DN-002 ADDENDUM-00).

Until a copy is saved, every work below is held in the corpus graph as its OpenAlex record (`held_doc_id`), so a
reboot loses nothing.

## The recipe (Desktop thread, with the operator's browser connected)

Window: the Desktop thread for hazbrief-mcp, with Claude in Chrome. Order: top first.

1. Open the URL. If the page is the document (a PDF, or the accepted manuscript's full text), save it into
   `/Users/brock/GitHub/hazbrief-mcp/corpus/inbox/` with its downloaded name; for an HTML full text, clip it into the
   inbox as HB-98 did.
2. If the page asks for a sign-in, payment or CAPTCHA, stop on that URL: it is the operator's (rung 3), and the row
   stays abstract or metadata only.
3. After the last item, in Claude Code in `/Users/brock/GitHub/hazbrief-mcp`, register by content:

   ```
   uv run python scripts/register_inbox.py --inbox corpus/inbox
   ```

   A later task admits what was registered (a corpus row per work, `plan: operator_download`, so the manifest's
   `acquired_by` reads `operator`).

## The list

### 1. Item 1: HPAC model studies of selected Jack Rabbit II (JRII) releases and comparisons to test data

- DOI: https://doi.org/10.1016/j.atmosenv.2020.117675
- Held now: `simpson-2020-hpac-model-studies-selected-jack-rabbit-openalex-record` (metadata only)
- Open copy: https://www.sciencedirect.com/science/article/am/pii/S1352231020304076

### 2. Item 4: twodee-2: A shallow layer model for dense gas dispersion on complex topography

- DOI: https://doi.org/10.1016/j.cageo.2007.12.017
- Held now: `folch-2008-twodee-2-shallow-layer-model-dense-openalex-record` (metadata only)
- Open copy: https://www.earth-prints.org/handle/2122/4539

### 3. Item 5: twodee: the Health and Safety Laboratory's shallow layer model for heavy gas dispersion Part 1. Mathematical basis and physical assumptions

- DOI: https://doi.org/10.1016/s0304-3894(98)00269-6
- Held now: `hankin-1999-twodee-health-safety-laboratory-s-shallow-part-1-openalex-record` (metadata only)
- Open copy: http://publications.eng.cam.ac.uk/336607/
- Open copy: http://publications.eng.cam.ac.uk/336608/

### 4. Item 5: twodee: The Health and Safety Laboratory's shallow layer model for heavy gas dispersion Part 2: Outline and validation of the computational scheme

- DOI: https://doi.org/10.1016/s0304-3894(98)00275-1
- Held now: `hankin-1999-twodee-health-safety-laboratory-s-shallow-part-2-openalex-record` (metadata only)
- Open copy: http://publications.eng.cam.ac.uk/336605/
- Open copy: http://publications.eng.cam.ac.uk/336701/

### 5. Item 5: twodee: the Health and Safety Laboratory's shallow layer model for heavy gas dispersion Part 3: Experimental validation (Thorney Island)

- DOI: https://doi.org/10.1016/s0304-3894(98)00270-2
- Held now: `hankin-1999-twodee-health-safety-laboratory-s-shallow-part-3-openalex-record` (metadata only)
- Open copy: http://publications.eng.cam.ac.uk/336606/
- Open copy: http://publications.eng.cam.ac.uk/336700/

### 6. Item 6: The Integral Dense-gas Dispersion Model (IDDM) and comparison with Jack Rabbit II data

- DOI: https://doi.org/10.1016/j.atmosenv.2022.119563
- Held now: `weil-2022-integral-dense-gas-dispersion-model-iddm-openalex-record` (metadata only)
- Open copy: https://www.sciencedirect.com/science/article/am/pii/S1352231022006288
- Open copy: https://opensky.ucar.edu/search?query=%22Integral+Dense-gas+Dispersion+Model%22

### 7. Item 8: Gaps in toxic industrial chemical model systems: Improvements and changes over past 10 years

- DOI: https://doi.org/10.1002/prs.12289
- Held now: `hanna-2021-gaps-toxic-industrial-chemical-model-systems-openalex-record` (abstract only)
- Open copy: https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/prs.12289

### 8. Item 10: Hazmat risk area assessment by atmospheric dispersion modelling using Latin hypercube sampling with weather ensemble

- DOI: https://doi.org/10.1002/met.1722
- Held now: `sigg-2018-hazmat-risk-area-assessment-atmospheric-dispersion-openalex-record` (abstract only)
- Open copy: https://rmets.onlinelibrary.wiley.com/doi/pdfdirect/10.1002/met.1722
- Open copy: https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/met.1722

### 9. Item 11: Meta-modelling for fast analysis of CFD-simulated vapour cloud dispersion processes

- DOI: https://doi.org/10.1016/j.compchemeng.2014.07.003
- Held now: `wang-2014-meta-modelling-fast-analysis-cfd-simulated-openalex-record` (metadata only)
- Open copy: http://epubs.surrey.ac.uk/806978/1/kwang2014_cce_meta_vapour.pdf
- Open copy: https://openresearch.surrey.ac.uk/esploro/outputs/journalArticle/Meta-modelling-for-fast-analysis-of-CFD-simulated/99514399602346

### 10. Item 13: Overview of the Jack Rabbit II (JR II) field experiments and summary of the methods used in the dispersion model comparisons

- DOI: https://doi.org/10.1016/j.atmosenv.2021.118783
- Held now: `fox-2021-overview-jack-rabbit-jr-field-experiments-openalex-record` (metadata only)
- Open copy: https://www.sciencedirect.com/science/article/am/pii/S1352231021006051

### 11. Item 13: Cloud dimensions from Jack Rabbit II field trial data

- DOI: https://doi.org/10.1016/j.atmosenv.2020.117614
- Held now: `mazzola-2020-cloud-dimensions-jack-rabbit-field-trial-openalex-record` (metadata only)
- Open copy: https://www.sciencedirect.com/science/article/am/pii/S1352231020303484

### 12. Item 14: Development of heavy vapour clouds in very low wind speeds

- DOI: https://doi.org/10.1016/j.jlp.2017.04.011
- Held now: `atkinson-2017-development-heavy-vapour-clouds-very-low-openalex-record` (metadata only)
- Open copy: https://www.sciencedirect.com/science/article/pii/S0950423017301365/pdf

### 13. Item 14: Minimum turbulence assumptions and u* and L estimation for dispersion models during low-wind stable conditions

- DOI: https://doi.org/10.1080/10962247.2013.872709
- Held now: `hanna-2013-minimum-turbulence-assumptions-u-l-estimation-openalex-record` (abstract only)
- Open copy: https://www.tandfonline.com/doi/pdf/10.1080/10962247.2013.872709?needAccess=true&role=button

### 14. Item 15: DISPLAY-2: a two-dimensional shallow layer model for dense gas dispersion including complex features

- DOI: https://doi.org/10.1016/s0304-3894(03)00011-6
- Held now: `venetsanos-2003-display-2-two-dimensional-shallow-layer-openalex-record` (metadata only)
- Open copy: http://publications.jrc.ec.europa.eu/repository/handle/JRC25091

### 15. Item 16: PHMSA's Argonne_Report.pdf

- Held now: `(none)` (not held)
- Open copy: https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/docs/Argonne_Report.pdf

## Refused, but no open copy is known

- Item 2, Sykes and Henn (1995), doi:10.1175/1520-0450(1995)034<2715:ROVGEI>2.0.CO;2: the publisher's page (https://journals.ametsoc.org/view/journals/apme/34/12/1520-0450_1995_034_2715_rovgei_2_0_co_2.xml) answered 403 to the fetcher; OpenAlex records it closed. Held as its abstract (`sykes-1995-representation-velocity-gradient-effects-gaussian-puff-openalex-record`). Not on the list above.
