import base64
def img(n):
    return "data:image/jpeg;base64,"+base64.b64encode(open(f"img_{n}.jpg","rb").read()).decode()
CSS="""
@page{size:13.333in 7.5in;margin:0}
*{box-sizing:border-box}
html{background:#e9e9e9}
body{margin:0;font-family:Calibri,Carlito,'Segoe UI',Arial,sans-serif;color:#1a1a1a}
.s{width:1280px;height:720px;background:#fff;margin:24px auto;padding:54px 70px 50px;position:relative;overflow:hidden;page-break-after:always;break-after:page;box-shadow:0 2px 14px rgba(0,0,0,.18);display:flex;flex-direction:column}
@media print{html{background:#fff}.s{margin:0;box-shadow:none}}
h1{font-size:46px;line-height:1.08;margin:0 0 6px;font-weight:700;letter-spacing:-.3px}
h1 em,.o{color:#D4581C;font-style:normal}
.k{font-size:15px;letter-spacing:2.5px;text-transform:uppercase;color:#D4581C;font-weight:700;margin-bottom:10px}
.sub{font-size:24px;color:#595959;margin:8px 0 0;line-height:1.3}
.body{flex:1;display:flex;gap:44px;margin-top:26px;min-height:0;align-items:stretch}
.col{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center}
ul{margin:0;padding:0;list-style:none}
li{font-size:25px;line-height:1.3;margin:0 0 17px;padding-left:24px;position:relative}
li:before{content:"";position:absolute;left:0;top:13px;width:10px;height:10px;background:#D4581C;border-radius:50%}
li small,.g{color:#6b6b6b}
li small{display:block;font-size:19px;margin-top:2px}
.pic{border:1px solid #cfcfcf;box-shadow:0 3px 12px rgba(0,0,0,.14);max-width:100%;max-height:100%;display:block}
.picwrap{display:flex;align-items:center;justify-content:center;min-height:0;min-width:0}
.cap{font-size:15px;color:#6b6b6b;margin-top:8px}
.ft{position:absolute;left:70px;right:70px;bottom:18px;font-size:13px;color:#8a8a8a;display:flex;justify-content:space-between}
.big{font-size:84px;font-weight:700;color:#D4581C;line-height:1}
.bigl{font-size:21px;color:#404040;margin:4px 0 22px;line-height:1.25}
.say{font-size:33px;line-height:1.25;font-weight:700}
.q{display:grid;grid-template-columns:44px 1fr 1fr;column-gap:14px;row-gap:0;align-items:baseline;font-size:23px}
.q>div{padding:7px 0;border-bottom:1px solid #e3e3e3}
.q .n{color:#D4581C;font-weight:700;font-size:25px}
.q .qq{font-weight:700}
.q .a{color:#555;font-size:20px}
.flow{display:flex;align-items:stretch;gap:0;margin:6px 0 26px}
.box{flex:1;border:2px solid #bdbdbd;border-radius:10px;padding:18px 20px;font-size:21px;line-height:1.3;color:#404040}
.box b{display:block;font-size:26px;color:#1a1a1a;margin-bottom:6px}
.box.m{border-color:#D4581C;background:#FDF3EC}
.arr{width:60px;display:flex;align-items:center;justify-content:center;font-size:40px;color:#D4581C}
.chips{display:flex;flex-wrap:wrap;gap:10px}
.chip{border:1px solid #c9c9c9;border-radius:20px;padding:6px 16px;font-size:18px;color:#404040}
.chip b{color:#1a1a1a}
table{border-collapse:collapse;width:100%;font-size:21px;margin-top:6px}
td,th{text-align:left;padding:9px 10px;border-bottom:1px solid #dcdcdc}
th{font-size:15px;text-transform:uppercase;letter-spacing:1px;color:#6b6b6b}
.t{font-size:112px;font-weight:700;letter-spacing:-2px;line-height:.95}
.three{display:grid;grid-template-columns:1fr 1fr;gap:18px 40px}
.card{border-left:5px solid #D4581C;padding:4px 0 4px 18px}
.card b{font-size:27px;display:block}
.card span{font-size:20px;color:#555;line-height:1.3;display:block;margin-top:3px}
"""
N=[0]
def slide(inner,foot=True):
    N[0]+=1
    f='<div class="ft"><span>hazbrief</span><span>@@N@@</span></div>' if foot else '<!--@@N@@-->'
    return f'<section class="s">{inner}{f}</section>'
S=[]
# 1 headline
S.append(slide(f"""
<div class="body" style="margin-top:0;gap:40px">
 <div class="col" style="flex:0 0 410px">
  <div class="k">Decision support for hazmat response</div>
  <div class="t">haz<span class="o">brief</span></div>
  <p class="sub" style="font-size:30px;color:#1a1a1a;margin-top:22px;line-height:1.2">A truck or a rail car is leaking something dangerous.<br><span class="o"><b>We give the commander the whole picture in minutes.</b></span></p>
  <p class="sub" style="font-size:19px;margin-top:26px">Real-time decision support for emergency response to hazardous material releases on highways and rail lines.</p>
  <p class="sub" style="font-size:16px;margin-top:22px">GSA MCP Server and SI Agent Government Hackathon, 2026 &middot; Data track<br>github.com/gsa-mcp-hackathon/hazbrief</p>
 </div>
 <div class="col picwrap"><img class="pic" src="{img('hero')}"></div>
</div>""",False))
# 2 problem
S.append(slide("""
<div class="k">Problem statement</div>
<h1>The first hour decides the outcome.<br><em>Today's tools are too slow for it.</em></h1>
<div class="body">
 <div class="col" style="flex:1.25"><ul>
  <li>When a hazardous material gets loose, every minute counts: protect people, send help, limit the loss of life and property.</li>
  <li>The tools that model the danger are locked away and take special training to run.</li>
  <li>Someone gathers the data, runs the old tools, and pastes the results into a briefing by hand.</li>
  <li>What comes out is static: not interactive, and not flexible enough to deal with change quickly.</li>
 </ul></div>
 <div class="col" style="flex:.75;border-left:5px solid #D4581C;padding-left:30px"><div class="say">The commander needs an answer good enough to act on, <span class="o">while there is still time to act.</span></div></div>
</div>"""))
# 3 scale
S.append(slide(f"""
<div class="k">Problem statement &middot; the scale</div>
<h1>This is not rare. <em>It is about 66 times a day.</em></h1>
<div class="body">
 <div class="col" style="flex:0 0 400px">
  <div class="big">24,265</div><div class="bigl">hazardous material incidents in transportation reported in one year (2023)</div>
  <div class="big">146</div><div class="bigl">rail accidents that released hazardous material, 2016 to 2025</div>
  <div class="big">$209.5M</div><div class="bigl" style="margin-bottom:0">in damage to rail equipment and track alone from those 146</div>
 </div>
 <div class="col picwrap" style="flex-direction:column"><img src="{img('map')}" style="max-width:100%;max-height:440px">
 <div class="cap">Each circle is one of the 146 rail accidents; a bigger circle means more reported damage. Sources: Bureau of Transportation Statistics; Federal Railroad Administration accident reports.</div></div>
</div>"""))
# 4 what it does
S.append(slide(f"""
<div class="k">Solution overview</div>
<h1>Tell it what happened. <em>Get the whole picture back.</em></h1>
<div class="body" style="gap:14px;align-items:center">
 <div style="flex:0 0 300px;display:flex;flex-direction:column;height:100%;justify-content:center">
  <div class="picwrap"><img class="pic" src="{img('form')}" style="max-height:330px"></div>
  <div class="cap" style="font-size:20px;color:#1a1a1a;margin-top:14px"><b>In:</b> where, what, when.<br>Typed or spoken. No software training.</div>
 </div>
 <div class="arr" style="width:50px">&#10140;</div>
 <div style="flex:1;display:flex;flex-direction:column;height:100%;justify-content:center;min-width:0">
  <div class="picwrap"><img class="pic" src="{img('out')}" style="max-height:400px"></div>
  <div class="cap" style="font-size:20px;color:#1a1a1a;margin-top:14px"><b>Out:</b> the danger area on a live map, who and what is inside it, the responders nearby, the first actions, and a draft briefing. <span class="o"><b>A workup in 3 or 4 minutes.</b></span></div>
 </div>
</div>"""))
# 5 cloud over time
S.append(slide(f"""
<div class="k">Solution overview &middot; the gas over time</div>
<h1>It shows where the gas will be, <em>and when.</em></h1>
<div class="body" style="gap:26px;align-items:center">
 <div class="col"><div class="picwrap"><img class="pic" src="{img('cloud15')}"></div><div class="cap" style="font-size:22px;color:#1a1a1a"><b>15 minutes</b> after the release</div></div>
 <div class="col"><div class="picwrap"><img class="pic" src="{img('cloud75')}"></div><div class="cap" style="font-size:22px;color:#1a1a1a"><b>1 hour 15 minutes</b> after the release</div></div>
</div>
<p class="sub" style="font-size:21px;margin-bottom:6px">Red is life-threatening, orange is serious harm, yellow is discomfort. The cloud follows the forecast wind, hour by hour, so a commander can see which road, school or neighborhood it reaches next.</p>"""))
# 6 no one has this
S.append(slide("""
<div class="body" style="margin-top:0"><div class="col">
 <div class="k">Solution overview &middot; why this is new</div>
 <div class="t" style="font-size:92px">No one has a tool <span class="o">like this.</span></div>
 <p class="sub" style="font-size:30px;margin-top:30px;max-width:1000px">The pieces exist: the guidebook distances, the gas models, the population counts, the briefing form. We are the first to put them together, live, in one place, for deciding quickly with data when every minute counts.</p>
</div></div>"""))
# 7 questions
rows=[("What is this material, and how dangerous is it?","The material, its hazards, day or night","assess_incident"),
("How far back do we keep people?","The isolation and protection distances, pointed with the wind","protective_action_footprint"),
("Who is inside that area?","Residents by night, workers by day, people who need help to leave","population_at_risk"),
("What is inside that area?","Schools, nursing homes, hospitals, stations, rail lines, water","facilities_in_footprint"),
("Where do the injured go?","The nearest hospitals outside the danger area","receiving_hospitals"),
("What do we do first?","The guidebook's response actions, word for word","material_response_guidance"),
("What else do I need to know?","The rest of the picture, drafted into the standard incident briefing form","build_ics_201")]
q="".join(f'<div class="n">{i+1}</div><div class="qq">{a}</div><div class="a">{b}<br><span style="font-family:Consolas,Menlo,monospace;font-size:14px;color:#9a9a9a">{c}</span></div>' for i,(a,b,c) in enumerate(rows))
S.append(slide(f"""
<div class="k">Solution overview &middot; what it answers</div>
<h1>Questions a commander might ask. <em>One tool for each.</em></h1>
<div class="body" style="margin-top:14px"><div class="col"><div class="q">{q}</div></div></div>"""))
# 8 how it works
S.append(slide("""
<div class="k">Technical approach</div>
<h1>One server. Seven tools. <em>Many public sources at once.</em></h1>
<div class="body" style="flex-direction:column;gap:0;justify-content:center">
 <div class="flow">
  <div class="box"><b>The incident</b>Where, what and when, from a person or from any SI assistant that speaks MCP.</div>
  <div class="arr">&#10140;</div>
  <div class="box m"><b>hazbrief</b>Asks every source at the same time. Combines the answers as they arrive. If a source fails, it says so and falls back.</div>
  <div class="arr">&#10140;</div>
  <div class="box"><b>The picture</b>The map, the cloud over time, the people, the responders, the briefing.</div>
 </div>
 <div class="cap" style="font-size:17px;margin:0 0 10px;text-transform:uppercase;letter-spacing:1.5px">What it draws on</div>
 <div class="chips">
  <span class="chip"><b>Census Bureau</b> people, workplaces, places, roads</span>
  <span class="chip"><b>National Weather Service</b> the wind forecast</span>
  <span class="chip"><b>NOAA</b> radar and cloud</span>
  <span class="chip"><b>Emergency Response Guidebook</b> distances and first actions</span>
  <span class="chip"><b>Federal hazmat regulations</b> the materials table</span>
  <span class="chip"><b>NOAA and EPA chemical database</b> what each material does</span>
  <span class="chip"><b>Medicare and Medicaid</b> hospitals and nursing homes</span>
  <span class="chip"><b>Federal maps</b> schools, stations, rail, water</span>
  <span class="chip"><b>Published gas models</b> the cloud, grounded in the science</span>
 </div>
</div>"""))
# 9 person in charge
S.append(slide(f"""
<div class="k">Solution overview &middot; the person stays in charge</div>
<h1>It keeps the expert's brain <em>switched on.</em></h1>
<div class="body">
 <div class="col" style="flex:1.3"><ul>
  <li>Every picture opens with a checklist of what to verify before acting.</li>
  <li>It says what is assumed, what is modelled, and what data is missing.</li>
  <li>The expert checks it against what they see at the scene and what they know.</li>
  <li><b>We do the assembly. The person makes the call.</b></li>
 </ul></div>
 <div class="col picwrap" style="flex:.7"><img class="pic" src="{img('check')}" style="height:100%"></div>
</div>"""))
# 10 briefing
S.append(slide(f"""
<div class="k">Solution overview &middot; the briefing, at once</div>
<h1>The briefing is drafted <em>the moment the picture is.</em></h1>
<div class="body">
 <div class="col" style="flex:.95"><ul>
  <li>The standard incident briefing form (ICS 201), filled in block by block.</li>
  <li>Every line names where it came from.</li>
  <li>Built from the data gathered for this incident, at this place and hour.</li>
  <li>A draft for the commander to review, correct and sign.</li>
 </ul></div>
 <div style="flex:1.05;min-width:0;overflow:hidden;border:1px solid #cfcfcf;box-shadow:0 3px 12px rgba(0,0,0,.14);padding:10px 14px"><img src="{img('ics')}" style="width:100%;display:block"></div>
</div>"""))
# 11 trust
S.append(slide("""
<div class="k">Technical approach &middot; why trust it</div>
<h1>Every number shows its source. <em>The testing is on the page.</em></h1>
<div class="body">
 <div class="col"><ul>
  <li>A source on every number, one click away.</li>
  <li>Every picture comes with its own test page, open to anyone.</li>
  <li>Nobody can test on a live incident. So we use published benchmarks from field experiments to validate and verify the models.</li>
  <li>Our yardsticks are HPAC and ALOHA, the accepted standards. The goal is statistical equivalence with them.</li>
 </ul></div>
 <div class="col" style="flex:.8;border-left:5px solid #D4581C;padding-left:30px">
  <div class="say" style="font-size:29px">Benchmarked on a real chlorine release experiment, <span class="o">against the published results of HPAC and ALOHA.</span></div>
  <p class="sub" style="font-size:19px;margin-top:16px">Jack Rabbit II field trial. The full table of tests and results is in our evaluation write-up.</p>
 </div>
</div>"""))
# 12 before the incident
S.append(slide("""
<div class="k">Beyond the incident</div>
<h1>The same tool works <em>before anything goes wrong.</em></h1>
<div class="body"><div class="col"><div class="three">
 <div class="card"><b>Plan</b><span>About 11,740 facilities file a worst-case release plan with the EPA, and every local emergency planning committee must plan for releases. Each one is a picture we can draw.</span></div>
 <div class="card"><b>Ask "what if"</b><span>Set the wind, the hour or the place and run it again. Day against night. Today's forecast against the worst case. This works today.</span></div>
 <div class="card"><b>Train</b><span>Put a new responder in the chair with a realistic incident on their own roads, with no software to learn first.</span></div>
 <div class="card"><b>Rehearse</b><span>Tabletop exercises with a ready list of events: what the cloud reaches, and when, in time order.</span></div>
</div></div></div>"""))
# 13 next
S.append(slide("""
<div class="k">What is next</div>
<h1>This is a working prototype. <em>Here is where we take it.</em></h1>
<div class="body">
 <div class="col"><ul>
  <li>Live traffic and traffic cameras around the scene</li>
  <li>A real-time conversational assistant: ask the knowledge base, adjust the scenario, explore what-ifs</li>
  <li>Smoke, fire and other hazards</li>
 </ul></div>
 <div class="col"><ul>
  <li>More interactive, exploratory views of the picture</li>
  <li>More field trials against the accepted standards</li>
  <li>Design sessions with responders</li>
 </ul></div>
</div>
<div style="border-top:3px solid #D4581C;padding-top:18px;margin-bottom:14px"><div class="say" style="font-size:38px">Every minute counts. <span class="o">We give them back.</span></div>
<p class="sub" style="font-size:18px;margin-top:6px">github.com/gsa-mcp-hackathon/hazbrief</p></div>"""))
S.append(slide("""
<div class="k">Technical approach &middot; key decisions</div>
<h1>Five decisions <em>that shaped it.</em></h1>
<div class="body"><div class="col"><div class="q" style="grid-template-columns:44px 1fr 1.25fr">
 <div class="n">1</div><div class="qq">Use the accepted science. Never invent our own.</div><div class="a">The gas models are published, open ones the field already knows. The chemistry of the release picks the model.</div>
 <div class="n">2</div><div class="qq">Show the gas over time.</div><div class="a">A single fixed shape cannot tell a commander what to do next. Time is what planning needs.</div>
 <div class="n">3</div><div class="qq">Keep the person in the checking seat.</div><div class="a">We assemble; the expert verifies. Guided alerts keep critical thinking engaged.</div>
 <div class="n">4</div><div class="qq">A source on every number.</div><div class="a">Free public data, each value traceable to where it came from and when.</div>
 <div class="n">5</div><div class="qq">One server any SI assistant can use.</div><div class="a">Built on the open MCP standard, so it is not tied to one vendor or one screen.</div>
</div></div></div>"""))
S.append(slide(f"""
<div class="k">Demonstration of functionality</div>
<h1>The demonstration is live, <em>from one start page.</em></h1>
<div class="body">
 <div class="col" style="flex:.8"><ul>
  <li><b>Open a recorded run.</b><small>A prepared scenario from our test set, exactly as it was recorded.</small></li>
  <li><b>Run it with today's conditions.</b><small>The same place and material, right now, on today's forecast.</small></li>
  <li><b>Enter a new incident.</b><small>A point on the map and one line about what happened.</small></li>
  <li>The gas cloud plays as it is computed, and the briefing is ready to print.</li>
 </ul></div>
 <div class="col picwrap" style="flex:1.2"><img class="pic" src="{img('start')}"></div>
</div>"""))
# order: title, problem, scale, in/out, cloud, no one, questions, checklist, briefing, how, decisions, trust, demo, before, next
order=[0,1,2,3,4,5,6,8,9,7,13,10,14,11,12]
S=[S[i] for i in order]
for i in range(len(S)): S[i]=S[i].replace("@@N@@",str(i+1))
N[0]=len(S)
open("hazbrief_pitch.html","w").write(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>hazbrief: the pitch</title><style>{CSS}</style></head><body>{"".join(S)}</body></html>')
print(N[0],"slides")
