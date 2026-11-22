// HB-155 (DN-023): the suggested command post, triage and staging on the live page, and
// the Area radius steps. Its own file so live.js keeps its 700-line bound (ADDENDUM-05
// item 8); web.shell_html inlines it after the map script, which calls window.hbSiting
// once its layers are drawn (and again each time the map section is swapped in).
//
// - The block under the checklist (`#siting`, ADDENDUM-05 item 1) is printed only when
//   the points layer is drawn: one closed line, then a one-line row per point (its name
//   and its distance and bearing) that opens onto the place, why, the rule sources and the
//   candidates rejected, with "Move" and "Use suggestion".
// - "Move" arms a map click, or a listed candidate's button (no menu, no form: HBD-328);
//   either POSTs /site, and the server appends `site_moved` with the routes and the
//   Warning recomputed; this page draws the stream's event, never its own guess.
// - The Area radius steps (ADDENDUM-02 item 5) are buttons under Responders. A step whose
//   data is in hand filters at once and POSTs /area (an `area_radius_set` event); a step
//   not in hand shows ◌ Retrieving until the server's event arrives on a live serve, and
//   on a replay reads "not recorded for this replay" and is not offered.
(function () {
  'use strict';
  var body = document.body;
  var base = '/brief/' + encodeURIComponent(body.dataset.brief);
  var api = null, S = null, A = null, armed = null, replay = null;
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }
  function button(text, fn, cls) {
    var b = el('button', cls || 'sbtn', text);
    b.type = 'button';
    // a button on a group heading must not also fold the group
    b.addEventListener('click', function (e) { e.stopPropagation(); fn(e); });
    b.addEventListener('keydown', function (e) { e.stopPropagation(); });
    return b;
  }
  function post(path, payload) {
    body.dataset.siting = 'posting';
    return fetch(base + path, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) { throw new Error((j.error && j.error.detail) || ('answered ' + r.status)); }
        return window.hbReadAfter ? window.hbReadAfter() : null;
      });
    }).then(function () { body.dataset.siting = 'done'; })
      .catch(function (e) { body.dataset.siting = 'error: ' + e.message; });
  }

  // ── the block (ADDENDUM-05 items 1, 2 and 7) ──
  function row(pid) {
    var p = S.points[pid];
    var det = el('details', 'lrow srow');
    det.dataset.point = pid;
    var sum = el('summary');
    sum.appendChild(el('span', 'sname', p.title));
    sum.appendChild(el('span', 'sfig', p.none ? '' : ' ' + p.where.split(',')[0] +
                       ', ' + p.where.split('(')[1].split(')')[0]));
    sum.appendChild(el('span', 'smark', ''));
    det.appendChild(sum);
    if (p.none) { det.appendChild(el('p', 'note', p.none)); return det; }
    var d = el('div', 'sdetail');
    d.appendChild(el('p', 'splace', p.name + ' (' + p.kind + ')'));
    if (p.both) { d.appendChild(el('p', 'note', p.both)); }
    d.appendChild(el('p', 'swhere', p.where));
    d.appendChild(el('p', 'swhy', p.why));
    d.appendChild(el('p', 'note', 'Rule sources: ' + p.sources));
    d.appendChild(el('p', 'note', S.suggested));
    var acts = el('p', 'sacts');
    acts.appendChild(button(S.words.siting_move, function () { arm(pid); }, 'sbtn smove'));
    acts.appendChild(button(S.words.siting_use, function () {
      post('/site', {point: pid, suggestion: true});
    }, 'sbtn suse'));
    d.appendChild(acts);
    var pick = el('div', 'spick');
    pick.hidden = true;
    pick.appendChild(el('p', 'note', S.words.siting_pick));
    S.candidates.forEach(function (c) {
      pick.appendChild(button(c.name + ' (' + c.kind + '), ' + c.where.split(',')[0],
        function () { post('/site', {point: pid, coordinates: c.xy}); disarm(); },
        'sbtn scand'));
    });
    pick.appendChild(button(S.words.siting_cancel, disarm, 'sbtn'));
    d.appendChild(pick);
    if (S.rejected.length) {
      var rj = el('details', 'srej');
      rj.appendChild(el('summary', null, S.rejected.length + ' candidates rejected'));
      var ul = el('ul');
      S.rejected.forEach(function (r) {
        ul.appendChild(el('li', null, r.name + ' (' + r.kind + '): ' + r.why));
      });
      rj.appendChild(ul);
      d.appendChild(rj);
    }
    det.appendChild(d);
    return det;
  }
  function block() {
    var old = document.getElementById('siting');
    if (old) { old.remove(); }
    var host = document.getElementById('checklist-body');
    if (!S || !host) { return; }
    var sec = el('section', 'panel');
    sec.id = 'siting';
    var det = el('details', 'sgroup');
    det.appendChild(el('summary', null, S.words.siting_title));
    ['command_post', 'triage', 'staging'].forEach(function (pid) {
      det.appendChild(row(pid));
    });
    sec.appendChild(det);
    host.appendChild(sec);
  }

  // ── moving a point ──
  function arm(pid) {
    disarm();
    armed = pid;
    body.dataset.siting = 'armed:' + pid;
    var r = document.querySelector('#siting details[data-point="' + pid + '"] .spick');
    if (r) { r.hidden = false; }
    api.map.getContainer().style.cursor = 'crosshair';
  }
  function disarm() {
    armed = null;
    Array.prototype.forEach.call(document.querySelectorAll('#siting .spick'),
      function (p) { p.hidden = true; });
    if (api) { api.map.getContainer().style.cursor = ''; }
  }
  function moved(d) {
    var lay = api.layers.sited_points;
    if (lay) {
      lay.features.forEach(function (f) {
        if (f.properties.point === d.point) { f.geometry.coordinates = d.coordinates; }
      });
      api.redraw('sited_points');
    }
    var routes = api.layers.siting_routes;
    if (routes) {
      var keep = routes.features.filter(function (f) {
        return !((d.point === 'staging' && f.properties.to === 'staging') ||
                 (d.point === 'triage' && f.properties.src === 'triage'));
      });
      d.routes.forEach(function (r) {
        if (!r.geometry) { return; }
        keep.push({type: 'Feature', geometry: r.geometry, properties: {
          to: r.to, src: r.from, labs: [],
          popup: '<strong></strong><table><tr><th>Route</th><td></td></tr></table>'}});
        var f = keep[keep.length - 1];
        f.properties.popup = f.properties.popup.replace('<strong></strong>',
          '<strong>' + esc(r.text) + '</strong>').replace('<td></td>', '<td>' + esc(r.text) + '</td>');
      });
      routes.features = keep;
      api.redraw('siting_routes');
    }
    var r = document.querySelector('#siting details[data-point="' + d.point + '"]');
    if (r) {
      r.querySelector('.sfig').textContent = ' ' + d.where.split(',')[0] + ', ' +
        d.where.split('(')[1].split(')')[0];
      r.querySelector('.smark').textContent = d.suggestion ? '' :
        ' · ' + S.words.siting_moved;
      r.dataset.moved = d.suggestion ? '' : d.time;
    }
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }

  // ── the Area radius steps (ADDENDUM-02 item 5; ADDENDUM-05 item 4) ──
  function filterRows(m) {
    var byCls = {};
    Array.prototype.forEach.call(document.querySelectorAll('tr[data-area-m]'), function (tr) {
      var c = tr.dataset.cls, a = parseInt(tr.dataset.areaM, 10);
      byCls[c] = byCls[c] || {near: Infinity, any: false};
      byCls[c].near = Math.min(byCls[c].near, a);
      if (a <= m) { byCls[c].any = true; }
    });
    Array.prototype.forEach.call(document.querySelectorAll('tr[data-area-m]'), function (tr) {
      var c = byCls[tr.dataset.cls], a = parseInt(tr.dataset.areaM, 10);
      tr.hidden = !(a <= m || (!c.any && a === c.near));
    });
  }
  function setArea(m, held) {
    window.hbArea = m;
    if (api) { api.redraw('nearby_services'); }
    filterRows(m);
    Array.prototype.forEach.call(document.querySelectorAll('#area-steps button'),
      function (b) { b.setAttribute('aria-pressed', String(parseInt(b.dataset.m, 10) === m)); });
    var st = document.getElementById('area-state');
    if (st) { st.textContent = ''; st.dataset.state = held ? 'retrieved' : 'retrieving'; }
  }
  function step(s) {
    if (s.held || s.m === 0) { setArea(s.m, true); post('/area', {radius_m: s.m}); return; }
    var st = document.getElementById('area-state');
    st.dataset.state = 'retrieving';
    st.textContent = '◌ Retrieving';
    post('/area', {radius_m: s.m});
  }
  function control() {
    var old = document.getElementById('area-control');
    if (old) { old.remove(); }
    var li = document.querySelector('#layer-list li.lgroup[data-group="responders"]');
    if (!A || !li) { return; }
    var box = el('span', 'area-control');
    box.id = 'area-control';
    box.appendChild(el('span', 'area-title vh', S ? S.words.area_title : 'Area radius'));
    box.setAttribute('aria-label', S ? S.words.area_title : 'Area radius');
    var steps = el('span');
    steps.id = 'area-steps';
    steps.setAttribute('role', 'group');
    A.steps.concat([{mi: 0, m: 0, held: true}]).forEach(function (s) {
      var b = button(s.m === 0 ? (S ? S.words.area_nearest_short : 'nearest') :
                     String(s.mi), function () { step(s); }, 'sbtn astep');
      b.title = s.m === 0 ? (S ? S.words.area_nearest : 'Widen to nearest') :
        s.mi + ' miles';
      b.dataset.m = s.m;
      b.setAttribute('aria-pressed', 'false');
      if (!s.held && replay) {
        // a reason beside its mark (ADDENDUM-05 item 4), read in the tooltip and by a
        // screen reader; the step is not offered
        b.disabled = true;
        b.title = s.mi + ' miles: ' + (S ? S.words.area_not_recorded : 'not recorded for this replay');
        b.appendChild(el('span', 'vh', ' ' + b.title));
      }
      steps.appendChild(b);
    });
    box.appendChild(steps);
    var state = el('span', 'area-state');
    state.id = 'area-state';
    box.appendChild(state);
    li.querySelector('h3').appendChild(box);
    setArea(Math.round(A.radius_m), true);
  }

  window.hbSiting = function (mapApi) {
    api = mapApi;
    // the map section is swapped in whole, so its config is read afresh each time
    var C = JSON.parse(document.getElementById('map-config').textContent);
    S = C.siting; A = C.area;
    block();
    api.map.on('click', function (e) {
      if (!armed) { return; }
      var pid = armed;
      disarm();
      post('/site', {point: pid, coordinates: [Math.round(e.latlng.lng * 1e6) / 1e6,
                                                Math.round(e.latlng.lat * 1e6) / 1e6]});
    });
    var go = function () { control(); };
    if (replay === null) {
      fetch(base + '/recorded', {cache: 'no-store'}).then(function (r) { return r.json(); })
        .then(function (j) { replay = !!j.replay; go(); }).catch(function () { replay = true; go(); });
    } else { go(); }
  };
  document.addEventListener('hb:site_moved', function (e) { if (api) { moved(e.detail); } });
  document.addEventListener('hb:area_radius_set', function (e) {
    var d = e.detail;
    if (d.features && d.features.length && api && api.layers.nearby_services) {
      api.layers.nearby_services.features = d.features;
      A.held_m = Math.max(A.held_m, d.radius_m);
      A.steps.forEach(function (s) { if (s.m <= A.held_m + 1) { s.held = true; } });
    }
    setArea(d.radius_m, true);
  });
  document.addEventListener('hb:alert', function (e) {
    if (e.detail.kind !== 'siting_review') { return; }
    Array.prototype.forEach.call(document.querySelectorAll('#siting .srow .smark'),
      function (m) { m.textContent = ' · ' + (S ? S.words.siting_review : 'review'); });
  });
})();
