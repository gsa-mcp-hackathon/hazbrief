# HB-155: the operator's statements this task registers, one per line, in the Issues' words

Each line below is copied from the Issue it names (the Desktop chat as the Issue records it), so each register record
cites its own line. S1 to S4 are from Issues 2924654f and b8a3b913 (2026-11-09) and 0ccfb43c (2026-11-09 09:48);
S5 to S7 from Issue 96263e67 (2026-11-10 10:44); S8 to S11 from Issue c0ea2d82 (2026-11-10 10:51).

S1. Three points are required on the map: command post, triage, staging. Each is suggested automatically and the operator can set a new point for each. This overtakes the siting clause of hazbrief-mcp:HBD-265 and makes HB-145's optional triage_point the override, not the only path. (Issue 2924654f item 1)
S2. Candidate sites for those points are parking lots and public places (shopping centre, school, other public building); the operator stated this as a guess, so the candidate rule needs a held source before it is fixed. (Issue 2924654f item 2) Siting candidates widened by the operator: a nearby hospital, a fire or police station with parking, a highway weigh station or rest area, as well as parking lots, schools and public buildings. (Issue b8a3b913 item 3)
S3. The suggested points are an initial solution so responder transit time can be computed; they are recomputed when a point moves. (Issue b8a3b913 item 4)
S4. The suggested points are the endpoints of the drive-time routes (09:48 decision, Issue 0ccfb43c). (Issue 2924654f item 3) The triage or command-post point is therefore an important point on the map, since it is the endpoint of those routes. (Issue 0ccfb43c item 2)
S5. The nearby-services search should give situational awareness of everything in the area, not only the nearest three: a default radius of about 20 miles, adjustable by the reader (he called it a slider), narrower or wider. (Issue 96263e67 item 2)
S6. The search extends past the default until at least one of each class is found; in a sparse area that may mean 50 miles or more. (Issue 96263e67 item 3)
S7. The reader may be new to the area (he gave a guardsman put on duty in an unfamiliar town) and cannot be assumed to know where anything is. (Issue 96263e67 item 4)
S8. Flow concern: at the first map view, zooming out a little must not show the symbols vanish and leave the reader asking what else is out there. (Issue c0ea2d82 item 1)
S9. The default area radius is local: 10 miles, widening (his example: to 20) as needed to find first responders and hospitals; he also said 10 or 15 and that he has no justification for the number; the radius should be whatever is needed to find fire, rescue, police and hospitals in the area. (Issue c0ea2d82 item 2)
S10. Traffic exists to get responders onto the scene and people out, so it is local too: the traffic radius and the responder radius are paired by default; they may be tuned independently; he asked that the pairing and its reason be written in specifically as a design consideration. (Issue c0ea2d82 item 3)
S11. Acquisition in two stages because the build is asynchronous: fetch what is immediately necessary for the display first, then the wider data, and anything beyond (his example: 100 miles) on demand. (Issue c0ea2d82 item 4)
