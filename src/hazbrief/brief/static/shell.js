// HB-158 (DN-019 ADDENDUM-04; the operator's reviews of 2026-11-10 19:16 and 19:25 EST,
// Issues 02bfc66e and ad8be8a7): the live shell's parts that show less at once. A script
// of its own, inlined before static/live.js (HB-158 ADDENDUM-02 item 5: live.js keeps
// its 700-line bound). It reads the stream through the `hb:<type>` events live.js
// dispatches on the document, and the DOM the stream builds.
// - the status strip in the header (ADDENDUM-01 item 5): one mark for the hazbrief MCP
//   server and one per channel (a public source group behind one of its tools), each in
//   one of the three states' shapes, with a count; a click opens the Sources and MCP
//   servers tab;
// - the assembling view (ADDENDUM-01 item 4): until `stage_reached`, the map carries the
//   sources with their marks and "n of m sources retrieved"; the CSS keeps the columns
//   and the tabs back until `body[data-stage]`;
// - the wind chip's hour (item 6; HBD-340's one clock): the hour `#wind-hour` is on,
//   with the previous and next hour, which move `#wind-hour` itself;
// - the tab summaries (ADDENDUM-01 item 6): a tab's first line is its sections' marks and
//   the one-line figures of its layer rows (`web.shell.tab_rows`);
// - one row open at a time per region unless the reader keeps it open (item 3);
// - groups remember open or closed for the session (item 9).
(function () {
  'use strict';
  var body = document.body;
  var cfg = JSON.parse(body.dataset.shell);
  var replay = !!body.dataset.replay;
  var chans = {};
  cfg.channels.forEach(function (t) { chans[t] = 'pending'; });

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }
  // a channel state (ok, error, missing, timeout, skipped, not_run, pending) as one of
  // the three states (`page.states`); a replay's retrieved is recorded
  function stateOf(st) {
    if (st === 'pending') { return 'retrieving'; }
    if (st === 'ok') { return replay ? 'recorded' : 'retrieved'; }
    return 'failed';
  }
  function words(key) {
    return cfg.states[key].words.replace(/ ?\{(time|date)\}/, '');
  }
  function mark(key, label) {
    var cls = key === 'recorded' ? 'retrieved' : key;
    var m = el('span', 'st st-' + cls);
    m.dataset.state = key;
    m.appendChild(el('span', 'mk', cfg.states[key].glyph)).setAttribute('aria-hidden', 'true');
    m.appendChild(el('span', 'vh', (label ? label + ': ' : '') + words(key)));
    m.title = (label ? label + ': ' : '') + words(key);
    return m;
  }

  // ── a served replay's marks (ADDENDUM-01 item 2) ──
  // A fragment is the static page's bytes, the same for a live build and its replay
  // (DN-011 D7), so it reads "Retrieved <date time>"; on a served replay the page
  // relabels each such mark "Recorded <date>", in place. live.js calls this after each
  // swap and after the sources view loads.
  window.hbRecorded = function (root) {
    // HB-215: the Sources view's basemap rows, marked by the map script as tiles load
    if (root && window.hbBaseApply) { window.hbBaseApply(root); }
    if (!replay || !root) { return; }
    // HB-215: a replay's sources answered from the recording, not the basemap's
    root.querySelectorAll('tr:not([data-browser]) .bst[data-status="answered"]')
      .forEach(function (m) {
        var b = cfg.board_statuses.recorded;
        m.dataset.status = 'recorded';
        m.className = 'bst bst-recorded';
        m.lastChild.textContent = ' ' + b.words;
      });
    root.querySelectorAll('.st[data-state="retrieved"]').forEach(function (m) {
      var said = m.lastChild;
      var date = (said.textContent.match(/\d\d\/\d\d\/\d{4}/) || [''])[0];
      m.dataset.state = 'recorded';
      said.textContent = (said.nodeType === 3 ? ' ' : '') +
        cfg.states.recorded.words.replace('{date}', date).trim();
    });
  };

  // ── the status strip and the assembling view ──
  var stripMarks = document.getElementById('strip-marks');
  var stripCount = document.getElementById('strip-count');
  var strip = document.getElementById('status-strip');
  var asmCount = document.getElementById('assembling-count');
  var asmList = document.getElementById('assembling-list');
  function serverState(keys) {
    if (keys.indexOf('retrieving') >= 0) { return 'retrieving'; }
    if (keys.every(function (k) { return k === 'failed'; })) { return 'failed'; }
    return replay ? 'recorded' : 'retrieved';
  }
  function drawStatus() {
    var keys = cfg.channels.map(function (t) { return stateOf(chans[t]); });
    var by = {};
    keys.forEach(function (k) { by[k] = (by[k] || 0) + 1; });
    var counts = ['retrieving', 'retrieved', 'recorded', 'failed'].filter(function (k) {
      return by[k];
    }).map(function (k) {
      return cfg.strip_counts[k].replace('{n}', String(by[k]));
    }).join(', ');
    stripMarks.textContent = '';
    var srv = mark(serverState(keys), cfg.server);
    srv.dataset.server = 'hazbrief';
    stripMarks.appendChild(srv);
    asmList.textContent = '';
    cfg.channels.forEach(function (t, i) {
      var m = mark(keys[i], t.replace(/_/g, ' '));
      m.dataset.channel = t;
      stripMarks.appendChild(m);
      var li = el('li');
      li.appendChild(mark(keys[i]));
      li.appendChild(document.createTextNode(' ' + t.replace(/_/g, ' ')));
      asmList.appendChild(li);
    });
    stripCount.textContent = counts;
    strip.title = cfg.strip_title.replace('{counts}', counts);
    var done = keys.filter(function (k) { return k !== 'retrieving'; }).length;
    asmCount.textContent = cfg.assembling_count.replace('{n}', String(done))
      .replace('{m}', String(keys.length));
    body.dataset.strip = JSON.stringify(cfg.channels.map(function (t, i) {
      return [t, keys[i]];
    }));
  }
  document.addEventListener('hb:channel_settled', function (e) {
    chans[e.detail.tool] = e.detail.state;
    drawStatus();
  });
  // HB-189 (DN-028 ADDENDUM-14 decision 4): each hour of the moving cloud as the
  // engine hands it over, while the run carries on
  document.addEventListener('hb:cloud_hour', function (e) {
    var out = document.getElementById('assembling-cloud');
    out.textContent = cfg.cloud_hour.replace('{h}', String(e.detail.hour))
      .replace('{n}', String(e.detail.extracted));
    body.dataset.cloudHour = String(e.detail.hour);
  });
  // HB-192 (DN-024 ADDENDUM-01 decisions 3 and 4): each 15-minute frame as the engine
  // hands it over: the status line says how far the run has computed and at what
  // setting, and the frame's outlines are drawn on the map in place of the last
  // frame's, so the frames already in stay usable while later ones compute
  var liveFrame = null;
  // the page's own form (`derive.hplus`): H+15 min, H+1 h, H+1 h 15 min
  function hplus(m) {
    var h = Math.floor(m / 60), r = m % 60;
    if (!h) { return 'H+' + r + ' min'; }
    return 'H+' + h + ' h' + (r ? ' ' + r + ' min' : '');
  }
  document.addEventListener('hb:cloud_frame', function (e) {
    var d = e.detail, f = cfg.frames;
    var setting = d.vertical_setting_m === null ? f.no_setting
      : f.setting.replace('{m}', String(d.vertical_setting_m));
    var line = f.live.replace('{to}', hplus(d.minute)).replace('{of}', hplus(d.until_min))
      .replace('{setting}', setting).replace('{k}', String(d.k)).replace('{n}', String(d.n));
    var out = document.getElementById('frames-status') ||
      document.getElementById('assembling-cloud');
    if (out) { out.textContent = line; }
    body.dataset.cloudFrame = String(d.minute);
    var api = window.hbMapApi;
    if (!api || !window.L) { return; }
    if (liveFrame) { api.map.removeLayer(liveFrame); }
    liveFrame = L.layerGroup();
    Object.keys(d.outlines).forEach(function (t) {
      L.geoJSON(d.outlines[t], {style: {color: f.colors[t] || '#444', weight: 2,
        fillOpacity: 0.15}}).addTo(liveFrame);
    });
    liveFrame.addTo(api.map);
  });
  strip.addEventListener('click', function () {
    var b = document.getElementById('tab-btn-sources');
    if (b) { b.click(); }
  });
  drawStatus();

  // ── the wind chip's hour (item 6) ──
  var prev = document.getElementById('wind-prev');
  var next = document.getElementById('wind-next');
  var hourOut = document.getElementById('wind-chip-hour');
  function slider() { return document.getElementById('wind-hour'); }
  function drawHour() {
    var s = slider();
    var lab = document.getElementById('wind-hour-label');
    prev.hidden = next.hidden = !s;
    if (!s) { hourOut.textContent = ''; return; }
    hourOut.textContent = cfg.wind_hour.replace('{hour}', lab ? lab.textContent : s.value);
    prev.disabled = parseInt(s.value, 10) <= parseInt(s.min, 10);
    next.disabled = parseInt(s.value, 10) >= parseInt(s.max, 10);
  }
  function step(by) {
    var s = slider();
    if (!s) { return; }
    var v = Math.max(parseInt(s.min, 10), Math.min(parseInt(s.max, 10),
      parseInt(s.value, 10) + by));
    s.value = String(v);
    // the one clock: the map script redraws the arrows, time.js follows the hour
    s.dispatchEvent(new Event('input', {bubbles: true}));
  }
  prev.addEventListener('click', function () { step(-1); });
  next.addEventListener('click', function () { step(1); });
  // time.js and the map script move `#wind-hour` with non-bubbling events: listen in
  // the capture phase, and read the label once their own handlers have run
  document.addEventListener('input', function (e) {
    if (e.target && e.target.id === 'wind-hour') { setTimeout(drawHour, 0); }
  }, true);

  // ── groups that remember (item 9) and rows one open at a time (item 3) ──
  var store = window.sessionStorage;
  function remembered(key, dflt) {
    var v = store ? store.getItem('hb158:' + key) : null;
    return v === null ? dflt : v === 'open';
  }
  function remember(key, open) {
    if (store) { store.setItem('hb158:' + key, open ? 'open' : 'closed'); }
  }
  document.querySelectorAll('#checklist details.group').forEach(function (g) {
    g.open = remembered('group:' + g.id, g.open);
    g.addEventListener('toggle', function () { remember('group:' + g.id, g.open); });
  });
  function setLayerGroup(h, open) {
    var li = h.closest('li.lgroup');
    li.classList.toggle('lclosed', !open);
    var n = li.nextElementSibling;
    while (n && !n.classList.contains('lgroup') && n.id !== 'symbols-note') {
      n.hidden = !open;
      n = n.nextElementSibling;
    }
  }
  function anyOn(li) {
    var n = li.nextElementSibling;
    while (n && !n.classList.contains('lgroup') && n.id !== 'symbols-note') {
      if (n.querySelector('input[data-layer]:checked')) { return true; }
      n = n.nextElementSibling;
    }
    return false;
  }
  function layerGroups() {
    document.querySelectorAll('#layers-slot li.lgroup').forEach(function (li) {
      var h = li.querySelector('h3');
      var gid = li.dataset.group;
      if (!h.dataset.wired) {
        h.dataset.wired = '1';
        h.tabIndex = 0;
        h.setAttribute('role', 'button');
        var flip = function () {
          var open = li.classList.contains('lclosed');
          setLayerGroup(h, open);
          remember('lgroup:' + gid, open);
        };
        h.addEventListener('click', flip);
        h.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); }
        });
      }
      // the rows of layers with nothing there open closed; HB-155 (ADDENDUM-05 item 7:
      // the left column must not scroll at 1440 x 900): so does a group none of whose
      // layers is on, its heading and count still in view
      setLayerGroup(h, remembered('lgroup:' + gid, gid !== 'none' && anyOn(li)));
    });
  }
  var ROWS = 'li.lrow > details, #checklist li.item > details, #tab-body details.trow';
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (!(d instanceof HTMLDetailsElement) || !d.matches(ROWS) || !d.open) { return; }
    var region = d.closest('#layers-body, #checklist, #tab-body') || document;
    region.querySelectorAll(ROWS).forEach(function (o) {
      if (o !== d && o.open && !o.dataset.pinned) { o.open = false; }
    });
    if (!d.querySelector(':scope > .pin')) {
      var b = el('button', 'pin', cfg.pin);
      b.type = 'button';
      b.setAttribute('aria-pressed', 'false');
      b.addEventListener('click', function () {
        var on = !d.dataset.pinned;
        if (on) { d.dataset.pinned = '1'; } else { delete d.dataset.pinned; }
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.textContent = on ? cfg.pinned : cfg.pin;
      });
      d.appendChild(b);
    }
  }, true);

  // ── the tab summaries (ADDENDUM-01 item 6) ──
  function summarise(tid) {
    var out = document.getElementById('sum-' + tid);
    var btn = document.getElementById('tab-btn-' + tid);
    if (!out || !btn) { return; }
    out.textContent = '';
    var names = btn.dataset.sections ? btn.dataset.sections.split(' ') : [];
    names.forEach(function (n) {
      var sec = document.getElementById('section-' + n);
      var m = sec && sec.querySelector(':scope > details > summary .st');
      var h = sec && sec.querySelector(':scope > details > summary h2');
      if (!m || !h) { return; }
      var span = el('span', 'sum-item');
      span.appendChild(m.cloneNode(true));
      span.appendChild(document.createTextNode(' ' + h.textContent));
      out.appendChild(span);
    });
    (cfg.tab_rows[tid] || []).forEach(function (lid) {
      var row = document.querySelector('#layers-slot li.lrow[data-row="' + lid + '"]');
      if (!row) { return; }
      var fig = row.querySelector('summary .n').textContent;
      var item = el('span', 'sum-item sum-row',
        row.querySelector('summary .ln').textContent + (fig ? ' ' + fig : ''));
      // HB-161 ADDENDUM-01 item 2: the row's TEVV number ends its summary item too
      var ref = row.querySelector('a.tref');
      if (ref) { item.appendChild(document.createTextNode(' ')); item.appendChild(ref.cloneNode(true)); }
      out.appendChild(item);
    });
    if (tid === 'sources') {
      out.appendChild(el('span', 'sum-item', stripCount.textContent));
    }
  }
  document.querySelectorAll('#tabs .tab').forEach(function (b) {
    b.addEventListener('click', function () { summarise(b.dataset.tab); });
  });

  document.addEventListener('hb:section_settled', function (e) {
    if (e.detail.section === 'map') { layerGroups(); drawHour(); }
    if (body.dataset.tab) { summarise(body.dataset.tab); }
  });
  document.addEventListener('hb:run_finished', function () {
    drawHour();
    if (body.dataset.tab) { summarise(body.dataset.tab); }
  });

  // HB-173 (DN-028 ADDENDUM-04 decision 7): the two engines' checklist item opens its
  // pop-out, the measure's TEVV section, in a new tab, as the timeline's item does;
  // DN-028 ADDENDUM-10: under a stable class its one line opens the Conditions of use
  document.addEventListener('hb:alert', function (e) {
    var eng = cfg.engines, d = e.detail;
    var ln = eng && eng.links[d.kind];
    if (!ln) { return; }
    var sel = '#checklist li.item-' + d.kind + ' > details';
    document.querySelectorAll(sel).forEach(function (det) {
      if (det.querySelector('a.engines-pop')) { return; }
      var a = el('a', 'engines-pop', ln.text);
      a.href = ln.href; a.target = '_blank'; a.rel = 'noopener';
      det.appendChild(a);
    });
  });

  // ── HB-207 item 13: what is still working, by name; ADDENDUM-03 item 1: the start
  // time used; item 13 and item 10: when no cloud is drawn, one sentence where the Play
  // control stands. live.js redraws the strip on each event, then dispatches hb:<type>,
  // so this line is put back after it; run_finished collapses the strip, and it goes.
  var W = cfg.working, notes = cfg.form_notes || {}, titles = [], settled = {};
  var computing = false, done = false;
  function workingLine() {
    var strip = document.getElementById('progress');
    if (!strip || done) { return; }
    var old = document.getElementById('working-now');
    if (old) { old.remove(); }
    var names = titles.filter(function (t) { return !settled[t.name]; })
      .map(function (t) { return t.title; });
    if (computing) { names.push(W.cloud_working); }
    if (!names.length) { return; }
    strip.appendChild(el('span', 'working', '; ' +
      W.working.replace('{names}', names.join(', '))));
    strip.lastChild.id = 'working-now';
  }
  document.addEventListener('hb:run_started', function (e) {
    titles = e.detail.sections || [];
    if (notes.start_time) {
      // (dateStyle and timeStyle cannot be combined with timeZoneName: Chrome throws)
      var when = new Date(notes.start_time).toLocaleString([], {year: 'numeric',
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
        timeZoneName: 'short'});
      // a row of its own under the header's bar (the bar has no room left at 1440 px)
      var row = el('div', 'form-note', W.start_used.replace('{when}', when));
      row.id = 'start-used';
      var bar = document.querySelector('#top .bar');
      if (bar) { bar.parentNode.insertBefore(row, bar.nextSibling); }
    }
    workingLine();
  });
  document.addEventListener('hb:section_settled', function (e) {
    settled[e.detail.section] = true;
    workingLine();
  });
  document.addEventListener('hb:cloud_frame', function () {
    computing = true;
    workingLine();
  });
  function noCloud() {
    done = true;
    var old = document.getElementById('working-now');
    if (old) { old.remove(); }
    // a cloud is drawn where the Play control is and the cloud's row is not failed
    var row = document.querySelector('li[data-row="cloud"] .st');
    var failed = row && row.dataset.state === 'failed';
    if (document.getElementById('time-play') && !failed) { return; }
    // the page's own reason, as its layer row prints it; a material with no levels
    // held says so in plain words (item 10)
    var why = notes.levels || '';
    ['cloud', 'dense_gas', 'puff_worst_case'].some(function (r) {
      var w = document.querySelector('li[data-row="' + r + '"] .why');
      if (!why && w && w.textContent.trim()) {
        why = w.textContent.trim().replace(/^[^:]{0,40}: /, '');
      }
      return !!why;
    });
    if (!why) { return; }
    var p = el('p', 'no-cloud', W.no_cloud.replace('{why}', why));
    p.id = 'no-cloud-why';
    var tc = document.getElementById('time-control');
    var region = document.getElementById('map-region');
    if (tc) { tc.appendChild(p); } else if (region) { region.appendChild(p); }
  }
  document.addEventListener('hb:run_finished', noCloud);
  document.addEventListener('hb:run_failed', function () { done = true; });
})();
