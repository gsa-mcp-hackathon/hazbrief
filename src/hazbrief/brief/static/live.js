// The live page's script (DN-022 sections 3, 4 and 8; HB-130R Part B step 4; HB-131R;
// HB-141; HB-154). It opens the brief's event stream, swaps in the fragment of each section
// that settles wherever the shell holds its place, and keeps the progress count at the
// tab bar's end (sections settled over sections declared; counts, not a clock), each tab
// marked with its sections' state. On run_finished it checks the static page's sha256
// against the stream's.
// - the shell (HB-154): the two columns collapse to a strip by their buttons (the
//   checklist's strip counts the unticked Verify items); the under-map panel opens on a
//   tab and closes by Hide; the map section's layer control moves into the left column,
//   its basemap radios become the view switch at the map's top right beside the overlay
//   buttons, and its side panel moves into its tab; below the stacking width the map
//   moves only under two fingers or a modifier key;
// - the operator checklist (HB-141; DN-019 ADDENDUM-02 section 3): each `alert` and each
//   tool's first `channel_started` is an item in its group's list for its kind, in
//   arrival order, with a checkbox; a tick posts the item's stream id to /check or
//   /uncheck, and the box is drawn from the `check` and `uncheck` events of the stream
//   alone; an `alert_withdrawn` strikes its item through and keeps it, ticked or not;
// - the guide panels (item 6): a chip per panel the guidance section holds, opening a
//   closable view whose HTML is the section's own slice, from the panels route;
// - the replay banner's date (F4), from the recorded route when the run finishes;
// - the evidence log: one row per `channel_started`, filled from its `channel_settled`
//   and from the record route; every cell is a field of the event or of the record;
// - the commander's report, fetched from the report route when the run finishes.
// The page makes no POST but a tick's (HBD-271: no question box on the page).
// No framework, no bundler; Leaflet's pinned assets and the static page's map script
// (window.hbMap) are the only other scripts on the page.
(function () {
  'use strict';
  var body = document.body;
  var id = body.dataset.brief;
  var base = '/brief/' + encodeURIComponent(id);
  var strip = document.getElementById('progress');
  var declared = [];
  var shown = {};
  var finished = false;
  var lastId = -1;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }

  function counts() {
    var n = 0, by = {};
    declared.forEach(function (s) {
      var st = shown[s.name] || 'pending';
      if (st !== 'pending') { n += 1; }
      by[st] = (by[st] || 0) + 1;
    });
    return {settled: n, by: by};
  }

  // the progress count in the header: "n of m sections in"; each tab marks its
  // sections' worst state in the three states' shapes (HB-158 ADDENDUM-01 item 2), the
  // mark copied from the section's own summary, its words for a screen reader
  var RANK = {failed: 3, retrieving: 2, recorded: 1, retrieved: 1};
  function progress(n) {
    return shellCfg.progress.replace('{n}', String(n))
      .replace('{m}', String(declared.length));
  }
  function drawStrip() {
    var c = counts();
    strip.textContent = '';
    strip.appendChild(el('span', 'count', progress(c.settled)));
    tabButtons.forEach(function (b) {
      var names = b.dataset.sections ? b.dataset.sections.split(' ') : [];
      if (!names.length) { return; }
      var worst = null;
      names.forEach(function (n) {
        var m = document.querySelector('#section-' + n + ' > details > summary .st');
        if (m && (!worst || RANK[m.dataset.state] > RANK[worst.dataset.state])) {
          worst = m;
        }
      });
      if (!worst) { return; }
      var mark = worst.cloneNode(true);
      mark.lastChild.replaceWith(el('span', 'vh', worst.textContent.slice(2)));
      b.title = worst.textContent.slice(2);
      b.querySelector('.st').replaceWith(mark);
    });
  }

  // one line once the run is finished: the count and the page check's result
  function collapse(check) {
    var c = counts();
    strip.textContent = '';
    // the count shows; the page check's result is its tooltip and its hidden words
    var s = el('span', 'count done', progress(c.settled));
    s.appendChild(el('span', 'vh', '; ' + check));
    strip.title = check;
    strip.appendChild(s);
  }

  function swap(name, fragment) {
    var old = document.getElementById('section-' + name);
    var t = document.createElement('template');
    t.innerHTML = fragment;
    var fresh = t.content.firstElementChild;
    if (!old || !fresh || fresh.id !== 'section-' + name) {
      throw new Error('no section ' + name + ' to swap');
    }
    var tab = old.closest('.tab-panel');
    old.replaceWith(fresh);
    window.hbRecorded(fresh);
    // a section in an open tab opens; in a closed tab it opens with the tab
    if (tab && !tab.hidden) { openDetails(fresh); }
    if (name === 'map') {
      placeMap(fresh);
      // the map section carries its own data; the static page's map script draws it
      if (typeof window.hbMap === 'function') { window.hbMap(); }
      buildSwitches();
      loadHead();
    }
  }

  // ── the shell (HB-154) ──
  var shellCfg = JSON.parse(body.dataset.shell);
  var tabButtons = Array.prototype.slice.call(document.querySelectorAll('#tabs .tab'));
  var tabBody = document.getElementById('tab-body');
  var hideTab = document.getElementById('tab-hide');
  function relayout() {
    // Leaflet resizes its map on the window's resize event (trackResize)
    window.dispatchEvent(new Event('resize'));
  }
  function openDetails(root) {
    // HB-158 (ADDENDUM-01 item 6): a tab of one section opens it; a tab of several
    // shows each as its one-line heading with its mark, opened by the reader
    var p = root.closest('.tab-panel') || root;
    var all = p.querySelectorAll('section > details');
    if (all.length === 1) { all[0].open = true; }
  }
  function openTab(tid) {
    tabButtons.forEach(function (b) {
      var on = b.dataset.tab === tid;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      var p = document.getElementById('tab-' + b.dataset.tab);
      p.hidden = !on;
      if (on) { openDetails(p); }
    });
    tabBody.hidden = false;
    hideTab.hidden = false;
    body.dataset.tab = tid;
    if (tid === 'sources') { loadSources(); }
    relayout();
  }
  function closeTabs() {
    tabBody.hidden = true;
    hideTab.hidden = true;
    tabButtons.forEach(function (b) { b.setAttribute('aria-selected', 'false'); });
    body.dataset.tab = '';
    relayout();
  }
  tabButtons.forEach(function (b) {
    b.addEventListener('click', function () { openTab(b.dataset.tab); });
  });
  hideTab.addEventListener('click', closeTabs);
  // a link to anything inside a tab (a section, the evidence log) opens that tab
  function followHash() {
    var t = location.hash && document.getElementById(location.hash.slice(1));
    var p = t && t.closest('.tab-panel');
    if (p) { openTab(p.id.slice(4)); t.scrollIntoView(); }
  }
  window.addEventListener('hashchange', followHash);
  function setColumn(col, open) {
    col.dataset.open = open ? '1' : '0';
    var b = col.querySelector('.col-toggle');
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    b.textContent = open ? b.dataset.hide : b.dataset.show;
    relayout();
  }
  ['col-layers', 'col-checklist'].forEach(function (cid) {
    var col = document.getElementById(cid);
    col.querySelector('.col-toggle').addEventListener('click', function () {
      setColumn(col, col.dataset.open !== '1');
    });
  });
  // item 10: a narrow window opens with the layers collapsed
  if (window.innerWidth < shellCfg.collapse_left_below_px) {
    setColumn(document.getElementById('col-layers'), false);
  }
  // item 10: stacked, the page scrolls; the map moves only under two fingers or a
  // modifier key, so one finger and a plain wheel scroll the page (Google's
  // "cooperative" gesture handling, which a Google map applies by itself)
  var region = document.getElementById('map-region');
  function stacked() { return window.innerWidth < shellCfg.stack_below_px; }
  region.addEventListener('wheel', function (e) {
    if (stacked() && !(e.ctrlKey || e.metaKey || e.altKey || e.shiftKey)) {
      e.stopPropagation();
    }
  }, true);
  region.addEventListener('touchstart', function (e) {
    if (stacked() && e.touches.length < 2) { e.stopPropagation(); }
  }, true);
  // the map section's parts go to the shell's places: the layer control to the left
  // column, the side panel to its tab (the static page keeps them where they were)
  function placeMap(sec) {
    var ctl = sec.querySelector('#layer-control');
    var slot = document.getElementById('layers-slot');
    if (ctl) {
      slot.textContent = '';
      ctl.open = true;
      slot.appendChild(ctl);
    }
    var side = sec.querySelector('#panel');
    var detail = document.getElementById('detail-slot');
    if (side) {
      detail.textContent = '';
      detail.appendChild(side);
    }
  }
  // the view switch (the basemap radios) and the overlay buttons, at the map's top right
  function buildSwitches() {
    var view = document.getElementById('view-switch');
    var over = document.getElementById('overlay-switch');
    var bm = document.getElementById('basemaps');
    view.textContent = '';
    if (bm && !bm.hidden) { view.appendChild(bm); }
    over.textContent = '';
    shellCfg.overlays.forEach(function (o) {
      var box = null;
      o.layers.some(function (lid) {
        box = document.querySelector('#layer-list input[data-layer="' + lid + '"]');
        return box !== null;
      });
      if (!box) { return; }
      var b = el('button', null, o.label);
      b.type = 'button';
      b.dataset.overlay = o.id;
      b.dataset.layer = box.dataset.layer;
      function sync() { b.setAttribute('aria-pressed', box.checked ? 'true' : 'false'); }
      sync();
      box.addEventListener('change', sync);
      b.addEventListener('click', function () { box.click(); });
      over.appendChild(b);
    });
  }
  window.hbSwitches = buildSwitches;  // HB-210: google.js's traffic box comes late
  // the header line's facts, from the blackboard as it stands
  function loadHead() {
    return fetch(base + '/head', {cache: 'no-store'}).then(function (r) {
      return r.json();
    }).then(function (h) {
      if (h.material) {
        document.getElementById('head-title').textContent =
          h.material + (h.un ? ' (' + h.un + ')' : '');
      }
      var facts = document.getElementById('head-facts');
      var code = facts.querySelector('code');
      facts.textContent = '';
      facts.appendChild(code);
      [h.container, h.place, h.as_given ? 'as given ' + h.as_given : null]
        .forEach(function (t) { if (t) { facts.appendChild(el('span', null, t)); } });
      var chip = document.getElementById('wind-chip');
      if (h.wind) {
        // HB-158 item 6: the record, short, the full label as its tooltip
        document.getElementById('wind-chip-text').textContent =
          shellCfg.wind_chip.replace('{wind}', h.wind_short || h.wind);
        chip.title = 'Wind: ' + h.wind;
        chip.hidden = false;
      }
      facts.title = facts.textContent;
    });
  }
  // the Data sources view (item 9): the channels' rows, as the blackboard stands
  var sourcesDue = false;
  function loadSources() {
    if (sourcesDue) { return null; }
    sourcesDue = true;
    return fetch(base + '/sources', {cache: 'no-store'}).then(function (r) {
      return r.text();
    }).then(function (text) {
      sourcesDue = false;
      document.getElementById('sources-table').innerHTML = text;
      window.hbRecorded(document.getElementById('sources-table'));
      body.dataset.sources = finished ? 'final' : 'partial';
    });
  }
  document.getElementById('print-ics').addEventListener('click', function () {
    window.print();
  });

  function hex(buf) {
    return Array.prototype.map.call(new Uint8Array(buf), function (b) {
      return ('0' + b.toString(16)).slice(-2);
    }).join('');
  }

  // the static render of the same records and now must hash to the stream's final page
  function checkPage(want) {
    body.dataset.pageCheck = 'running';
    return fetch(base + '/page', {cache: 'no-store'}).then(function (r) {
      if (!r.ok) { throw new Error('the page answered ' + r.status); }
      return r.arrayBuffer();
    }).then(function (buf) {
      return crypto.subtle.digest('SHA-256', buf);
    }).then(function (d) {
      var got = hex(d);
      var ok = got === want;
      body.dataset.pageCheck = ok ? 'match' : 'mismatch';
      collapse(ok
        ? 'the static page hashes to the stream: sha256 ' + want.slice(0, 12)
        : 'the static page does NOT hash to the stream: ' + got.slice(0, 12) +
          ' against ' + want.slice(0, 12));
    }).catch(function (e) {
      body.dataset.pageCheck = 'error';
      collapse('the page check failed: ' + e.message);
    });
  }

  // ── the operator checklist (HB-141 item 2) ──
  var emptyNote = document.getElementById('checklist-empty');
  var tools = {};
  function recount() {
    var n = 0;
    document.querySelectorAll('#checklist details.group').forEach(function (g) {
      var k = g.querySelectorAll('li[data-item]').length;
      document.getElementById('count-' + g.id.slice(6)).textContent = String(k);
      n += k;
    });
    emptyNote.hidden = n > 0;
    countVerify();
  }
  // the collapsed checklist's strip: the unticked Verify items that stand (HBD-218 as
  // amended; the report's first line counts the same, `checklist.unticked_verify`)
  function countVerify() {
    var k = 0;
    document.querySelectorAll('#group-verify li[data-item]').forEach(function (li) {
      if (!li.classList.contains('withdrawn') && !li.querySelector('input').checked) {
        k += 1;
      }
    });
    var upd = document.querySelectorAll('#checklist li .upd').length;
    document.getElementById('checklist-count').textContent =
      shellCfg.collapsed_count.replace('{n}', String(k)) + (upd
        ? ' · ' + shellCfg.collapsed_updated.replace('{n}', String(upd)) : '');
    body.dataset.unticked = String(k);
    body.dataset.updated = String(upd);
  }
  // HB-158 ADDENDUM-01 item 4: after the critical set, an item a later arrival adds,
  // changes or withdraws carries "updated HH:MM", and the collapsed strip counts it
  function markUpdated(li) {
    if (!body.dataset.stage || !li) { return; }
    var old = li.querySelector('.upd');
    if (old) { old.remove(); }
    var t = new Date();
    var hhmm = ('0' + t.getHours()).slice(-2) + ':' + ('0' + t.getMinutes()).slice(-2);
    li.querySelector('summary').appendChild(
      el('span', 'upd', shellCfg.updated.replace('{time}', hhmm)));
  }
  // a Sources line's state, in the three states' words (ADDENDUM-01 item 2)
  function sourceWords(state) {
    var key = state === 'pending' ? 'retrieving' : state === 'ok'
      ? (body.dataset.replay ? 'recorded' : 'retrieved') : 'failed';
    var s = shellCfg.states[key];
    return s.glyph + ' ' + s.words.replace(/ ?\{(time|date)\}/, '');
  }
  // a checklist item carries at most one action button (HB-154 ADDENDUM-01 section 2;
  // "Open the ERG guide" is the pattern): a second call replaces the first
  function setAction(li, label, fn) {
    var old = li.querySelector('.item-action');
    if (old) { old.remove(); }
    var b = el('button', 'item-action', label);
    b.type = 'button';
    b.addEventListener('click', fn);
    li.querySelector('details').appendChild(b);
    return b;
  }
  function addItem(itemId, kind, text, receipt) {
    var list = document.getElementById('items-' + kind);
    if (!list) { throw new Error('no checklist list for ' + kind); }
    // HB-158 item 3: one line (the box and the text, cut at the column's edge) that
    // opens onto the whole text, its receipt and its action
    var li = el('li', 'item item-' + kind);
    li.dataset.item = itemId;
    var det = el('details');
    var sum = el('summary');
    var label = el('label', 'lbox');
    var box = el('input');
    box.type = 'checkbox';
    box.dataset.item = itemId;
    box.addEventListener('change', function () {
      var want = box.checked;
      // the box is the stream's: put it back until the event arrives
      box.checked = !want;
      tick(itemId, want);
    });
    label.appendChild(box);
    sum.appendChild(label);
    sum.appendChild(el('span', 'item-text', ' ' + text));
    det.appendChild(sum);
    li.appendChild(det);
    if (kind === 'source') {
      var a = el('a', 'receipt', receipt);
      a.href = '#evidence';
      det.appendChild(a);
    } else {
      det.appendChild(el('span', 'receipt', receipt));
    }
    // HB-171 item 11: the item the timeline rows' times rest on points back to them
    var tl = shellCfg.timeline, back = tl && text === tl.item && el('a', 'tl-back', tl.text);
    if (back) {
      back.href = tl.href; back.target = '_blank'; back.rel = 'noopener';
      det.appendChild(back);
    }
    list.appendChild(li);
    markUpdated(li);
    recount();
    return li;
  }
  function item(itemId) {
    return document.querySelector('#checklist li[data-item="' + itemId + '"]');
  }
  function withdraw(d) {
    var li = item(d.alert);
    if (!li) { return; }
    li.classList.add('withdrawn');
    li.querySelector('details').appendChild(
      el('span', 'receipt withdrawn-by', 'withdrawn: ' + d.receipt));
    markUpdated(li);
    countVerify();
  }
  function marked(d, on) {
    var li = item(d.item);
    if (!li) { return; }
    li.querySelector('input').checked = on;
    li.dataset.checked = on ? d.time : '';
    countVerify();
    // the report's first line and annex read the ticks: fetch it again once loaded
    if (body.dataset.report) { loadReport(); }
  }
  function tick(itemId, on) {
    body.dataset.tick = 'posting';
    fetch(base + (on ? '/check' : '/uncheck'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({item: parseInt(itemId, 10)})
    }).then(function (r) {
      if (!r.ok) { throw new Error('the tick answered ' + r.status); }
      // during the run the open stream carries the event; after it, read what follows
      return finished ? readAfter() : null;
    }).then(function () { body.dataset.tick = 'done'; })
      .catch(function (e) { body.dataset.tick = 'error: ' + e.message; });
  }
  // the stream after the last event this page holds, once the run has finished
  function readAfter() {
    return fetch(base + '/events?after=' + lastId, {cache: 'no-store'})
      .then(function (r) { return r.text(); })
      .then(function (text) {
        text.split('\n\n').forEach(function (block) {
          var type = null, eid = null, data = null;
          block.split('\n').forEach(function (line) {
            if (line.indexOf('event: ') === 0) { type = line.slice(7); }
            if (line.indexOf('id: ') === 0) { eid = line.slice(4); }
            if (line.indexOf('data: ') === 0) { data = JSON.parse(line.slice(6)); }
          });
          if (eid) { lastId = Math.max(lastId, parseInt(eid, 10)); }
          if (type && handlers[type]) {
            handlers[type](data, eid);
            document.dispatchEvent(new CustomEvent('hb:' + type, {detail: data}));
          }
        });
      });
  }

  // HB-155: static/siting.js reads what follows its own POST the same way
  window.hbReadAfter = function () { return finished ? readAfter() : Promise.resolve(); };

  // ── the guide panels (HB-141 item 6) ──
  var view = document.getElementById('panel-view');
  var held = {};
  function openPanel(pid) {
    var p = held[pid];
    if (!p) { return; }
    document.getElementById('panel-title').textContent = p.title;
    document.getElementById('panel-body').innerHTML = p.html;
    view.dataset.panel = pid;
    view.hidden = false;
  }
  document.getElementById('panel-close').addEventListener('click', function () {
    view.hidden = true;
    view.dataset.panel = '';
  });
  document.querySelectorAll('#guide-chips .guide-chip').forEach(function (b) {
    b.addEventListener('click', function () { openPanel(b.dataset.panel); });
  });
  function loadPanels() {
    return fetch(base + '/panels', {cache: 'no-store'}).then(function (r) {
      return r.json();
    }).then(function (got) {
      held = got;
      document.querySelectorAll('#guide-chips .guide-chip').forEach(function (b) {
        b.hidden = !held[b.dataset.panel];
      });
      linkPanels();
    });
  }
  // a Verify item whose receipt cites the ERG guide opens the guide tab on the guide
  function linkPanels() {
    if (!held.erg_guide) { return; }
    document.querySelectorAll('#items-cue li[data-item]').forEach(function (li) {
      if (li.querySelector('.item-action')) { return; }
      // the cue receipts cite the guide's held page as `erg2024-en-pdf p. N`
      if (!/erg/i.test(li.querySelector('.receipt').textContent)) { return; }
      setAction(li, 'Open the ERG guide', function () {
        openTab('guide');
        openPanel('erg_guide');
      }).classList.add('open-guide');
    });
  }

  // ── the replay banner's date (HB-141 item 3) ──
  function loadRecorded() {
    var span = document.getElementById('replay-recorded');
    if (!span) { return null; }
    return fetch(base + '/recorded', {cache: 'no-store'}).then(function (r) {
      return r.json();
    }).then(function (got) {
      if (got.recorded) { span.textContent = got.recorded; }
    });
  }

  // ── the evidence log (HB-131R item 2) ──
  var logBody = document.querySelector('#log tbody');
  var filter = document.getElementById('log-filter');
  var calls = [];
  function cell(tr, i, text) { tr.cells[i].textContent = text; }
  function addCall(d) {
    var tr = document.createElement('tr');
    for (var i = 0; i < 6; i += 1) { tr.appendChild(el('td')); }
    tr.dataset.tool = d.tool;
    cell(tr, 0, d.tool.replace(/_/g, ' '));
    var det = el('details');
    det.appendChild(el('summary', null, 'parameters as sent'));
    det.appendChild(el('pre', null, JSON.stringify(d.parameters, null, 1)));
    tr.cells[1].appendChild(det);
    cell(tr, 2, sourceWords('pending'));
    logBody.appendChild(tr);
    calls.push({tool: d.tool, sample: d.sample, tr: tr, settled: false});
    if (!filter.querySelector('option[value="' + d.tool + '"]')) {
      var o = el('option', null, d.tool.replace(/_/g, ' '));
      o.value = d.tool;
      filter.appendChild(o);
    }
    applyFilter();
  }
  function fillRecord(tr, sha) {
    return fetch(base + '/record/' + sha, {cache: 'no-store'}).then(function (r) {
      if (!r.ok) { throw new Error('the record route answered ' + r.status); }
      return r.json();
    }).then(function (rec) {
      cell(tr, 0, rec.source);
      tr.cells[1].insertBefore(el('span', 'asked', rec.asked), tr.cells[1].firstChild);
      var a = el('a', null, rec.hash_prefix);
      a.href = base + '/record/' + sha;
      a.target = '_blank';
      a.rel = 'noopener';
      tr.cells[3].textContent = '';
      tr.cells[3].appendChild(a);
      cell(tr, 4, rec.as_of);
      cell(tr, 5, rec.validation);
    }).catch(function (e) { cell(tr, 5, 'record not read: ' + e.message); });
  }
  function settleCalls(d) {
    calls.forEach(function (c) {
      if (c.tool !== d.tool || c.settled) { return; }
      c.settled = true;
      var sha = d.samples ? d.samples[c.sample || 0] : d.record_sha256;
      var why = d.reason || '';
      // the three states' words, then the reason without its state's prefix
      cell(c.tr, 2, sourceWords(d.state) +
        (why ? ': ' + why.replace(new RegExp('^' + d.state + ': '), '') : ''));
      if (sha) {
        c.tr.dataset.sha = sha;
        fillRecord(c.tr, sha);
      }
    });
  }
  function applyFilter() {
    var v = filter.value;
    calls.forEach(function (c) { c.tr.hidden = v !== '' && c.tool !== v; });
  }
  filter.addEventListener('change', applyFilter);

  // ── the commander's report (HB-131R item 3) ──
  function loadReport() {
    var panel = document.getElementById('report');
    return fetch(base + '/report', {cache: 'no-store'}).then(function (r) {
      if (!r.ok) { throw new Error('the report answered ' + r.status); }
      return r.text();
    }).then(function (text) {
      // printed by the header's "Print the ICS 201" (HB-154 item 4)
      panel.innerHTML = text;
      window.hbRecorded(panel);
      body.dataset.report = 'loaded';
    }).catch(function (e) {
      body.dataset.report = 'error';
      panel.appendChild(el('p', 'degraded', 'The report did not load: ' + e.message));
    });
  }

  var handlers = {
    alert: function (d, eid) {
      addItem(eid, d.kind, d.text, d.receipt);
      if (d.kind === 'cue') { linkPanels(); }
    },
    alert_withdrawn: function (d) { withdraw(d); },
    channel_started: function (d, eid) {
      addCall(d);
      if (tools[d.tool] === undefined) {
        tools[d.tool] = eid;
        addItem(eid, 'source', d.tool.replace(/_/g, ' ') + ': ' +
                sourceWords('pending'), 'the evidence log\'s row for this call');
      }
    },
    channel_settled: function (d) {
      settleCalls(d);
      var li = tools[d.tool] !== undefined ? item(tools[d.tool]) : null;
      if (li && !li.dataset.state) {
        li.dataset.state = d.state;
        li.querySelector('.item-text').textContent =
          ' ' + d.tool.replace(/_/g, ' ') + ': ' + sourceWords(d.state);
      }
      if (body.dataset.tab === 'sources') { loadSources(); }
    },
    stage_reached: function (d) { body.dataset.stage = d.stage; },
    // HB-155: drawn by static/siting.js, from the hb: event below
    site_moved: function () {}, area_radius_set: function () {}, cloud_hour: function () {},
    cloud_frame: function () {}, // HB-192: drawn by static/shell.js
    check: function (d) { marked(d, true); },
    uncheck: function (d) { marked(d, false); },
    run_started: function (d) {
      declared = d.sections;
      body.dataset.run = 'started';
      drawStrip();
    },
    section_settled: function (d) {
      swap(d.section, d.fragment);
      shown[d.section] = d.shown;
      drawStrip();
      if (d.section === 'guidance') { loadPanels(); }
    },
    run_finished: function (d) {
      finished = true;
      src.close();
      body.dataset.run = 'finished';
      body.dataset.stage = body.dataset.stage || shellCfg.critical_stage;
      checkPage(d.sha256);
      Promise.all([loadReport(), loadRecorded(), loadHead(), loadSources()])
        .then(measure);
    }
  };

  // what the shell measures of itself once the run has finished and after each
  // layout change (item 3: the document never scrolls), for the browser tests
  function rect(id) {
    var r = document.getElementById(id).getBoundingClientRect();
    return [Math.round(r.left), Math.round(r.top), Math.round(r.width),
            Math.round(r.height)];
  }
  function measure() {
    body.dataset.fit = JSON.stringify({
      scroll_height: document.scrollingElement.scrollHeight,
      inner_height: window.innerHeight,
      inner_width: window.innerWidth,
      layers: rect('col-layers'), map: rect('map-region'), under: rect('under'),
      tab_body: rect('tab-body'),
      checklist: rect('col-checklist'), top: rect('top'),
      layers_open: document.getElementById('col-layers').dataset.open,
      checklist_open: document.getElementById('col-checklist').dataset.open,
      tab_body_hidden: tabBody.hidden
    });
  }
  window.addEventListener('resize', function () { if (finished) { measure(); } });

  var src = new EventSource(base + '/events');
  Object.keys(handlers).forEach(function (type) {
    src.addEventListener(type, function (e) {
      if (e.lastEventId) { lastId = parseInt(e.lastEventId, 10); }
      var d = JSON.parse(e.data);
      handlers[type](d, e.lastEventId);
      // HB-158: static/shell.js draws the status strip and the assembling view
      document.dispatchEvent(new CustomEvent('hb:' + type, {detail: d}));
    });
  });
  src.addEventListener('run_failed', function (e) {
    var d = JSON.parse(e.data);
    finished = true;
    src.close();
    body.dataset.run = 'failed';
    strip.textContent = '';
    strip.appendChild(el('span', 'count failed', 'The brief failed: ' + d.error));
  });
  src.onerror = function () {
    // the browser reconnects by itself, from the last event it holds (Last-Event-ID)
    if (!finished) { body.dataset.run = 'reconnecting'; }
  };
})();
