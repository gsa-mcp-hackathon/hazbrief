# HB-178 Part B item 7: why the held roads do not connect Marion Volunteer Fire Department to the I-81 incident

Issue `76400690`. Brief `i81-md-pa-line-day`; station Marion Volunteer Fire Department - Company 8, 15,653 m from the
incident, inside the 16.1 km area radius.

## What the replay shows (no call)

`the HB-178 evidence (held privately) i81-md-pa-line-day`, on the travel graph the derivation builds
(`derive._RoadGraph`, TIGER primary and secondary roads, S1100 and S1200, `derive.nearby.travel.classes`):

- The held travel roads form **two** connected pieces: the incident's (24,761 nodes) and one of 183 nodes.
- The station snaps 114 m to Molly Pitcher Hwy (US 11; TIGER line 1102390146808, S1200), which lies in the small piece.
- The small piece's nearest node to the incident's piece is at (-77.708765, 39.856188), in Greencastle, Pennsylvania.

## What the source holds there (three diagnostic GETs, tigerweb.geo.census.gov, on the Network line)

`the HB-178 evidence (held privately){2,6,8}.json`, one envelope (-77.7110, 39.8545, -77.7070, 39.8570) on TIGERweb
Transportation layers 2 (primary), 6 (secondary) and 8 (local), 2026-11-13 22:54 UTC:

- The southern S1200 sections (US Hwy 11 1102390144390, S Main St 1102390147666, Molly Pitcher Hwy 1106092754451) end
  at (-77.708938, 39.856221).
- The northern S1200 sections (Molly Pitcher Hwy 1102390146808, US Hwy 11 1108311990709, S Main St 1108297134167)
  begin at (-77.708765, 39.856188).
- The two points, about 15 m apart, are joined only by an unnamed **S1400** line (TIGER 1102639325296, three vertices)
  and, beside it, Main St (S1400, 110513239899) and Feaster Rd (S1400).

**Cause: a real disconnect in the source data's two travel classes.** US 11's two S1200 sections through Greencastle
meet only through a 15 m local-road (S1400) link that the travel classes do not read. It is not a gap in what was
recorded (the travel query's box holds both sections whole) and not a one-way or ramp rule (the graph is undirected).

## What the row says now

More road data on the Network line would close it only by reading local roads into the travel graph, which changes
the travel classes for every brief (DN-019 ADDENDUM-02 and HB-151's configuration) and is not this task's decision. So
the row says what is known, with no time estimated (task item 7):

> Travel time: no route in the held roads (TIGER S1100, S1200): 15.7 km from the incident in a straight line, bearing
> 6 degrees

The words are `derive.nearby.travel.no_route`; the distance and bearing are the station's geodesic inverse from the
incident. Whether a short local link may join two travel-class lines is filed as an Issue (see the RESULT).
