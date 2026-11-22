// HB-210: the Google branch's own script, inlined on every page (since HB-215, Issue
// 9e5dd74c); it does anything only where the page carries a Google Maps key. The map
// script (render.MAP_JS) calls `window.hbGoogleLoad` in place of loading Google itself,
// and `window.hbTraffic` once its Google map has drawn.
//
// One load per page. The live page runs the map script again each time the map section
// is replaced (static/live.js `swap`); each run used to append its own copy of Google's
// script, and a second copy breaks the first (Google's console: "Element with name
// gmp-map already defined", "Loader.provide not called by module 'marker'", "setMap: not
// an instance of Map"; docs/evidence/hb210/key_check.tsv, run "first"). Google documents
// that its API is loaded once per page.
(function () {
  var state = 'none';  // none, loading, ready, failed
  var why = '';
  var waiting = [];    // the map script runs waiting for the script: {el, start, fallback}
  var current = null;  // the latest run, whose map shows the refusal note
  // the time the page was opened, which the traffic row's label reads (DN-010)
  var opened = new Date();

  function live(w) { return w.el.isConnected; }
  function settle(ok, text) {
    state = ok ? 'ready' : 'failed';
    why = text || '';
    var w = waiting.filter(live);
    waiting = [];
    w.forEach(function (x) { if (ok) { x.start(); } else { x.fallback(why); } });
  }

  // `C` is the map's `map-config`; `start` draws the Google map, `fallback` draws
  // Leaflet with a note, `note` writes the map's note; `el` is the map element
  window.hbGoogleLoad = function (C, el, start, fallback, note) {
    current = {el: el, note: note};
    // the API already on the page (loaded by an earlier run, or by the page's host)
    if (state === 'none' && window.google && window.google.maps &&
        window.google.maps.Map) { state = 'ready'; }
    if (state === 'ready') { start(); return; }
    if (state === 'failed') { fallback(why); return; }
    waiting.push({el: el, start: start, fallback: fallback});
    // each run waits at most the configured time for its map, then draws Leaflet;
    // Google arriving later starts only the runs still waiting
    setTimeout(function () {
      var i = waiting.findIndex(function (x) { return x.el === el; });
      if (state === 'loading' && i >= 0) {
        waiting.splice(i, 1);
        fallback(C.google_note_timeout);
      }
    }, C.google_timeout_ms);
    if (state === 'loading') { return; }
    state = 'loading';
    window.hbGoogleReady = function () { settle(true, ''); };
    window.gm_authFailure = function () {
      if (current && current.el.isConnected) { current.note(C.google_note_refused); }
    };
    var sc = document.createElement('script');
    sc.async = true;
    sc.src = C.google_js + '?key=' + encodeURIComponent(C.google_key) +
             '&callback=hbGoogleReady&loading=async';
    sc.onerror = function () { settle(false, C.google_note_blocked); };
    document.head.appendChild(sc);
  };

  // The traffic row (HB-210): on the Leaflet fallback it stays the "not available"
  // line the page was built with, and has no switch; on the Google map it becomes the
  // layer's switch, off, `objs.traffic` the TrafficLayer the map script made. Google
  // draws the traffic in the browser; hazbrief requests, receives and stores none.
  window.hbTraffic = function (C, boxes) {
    var T = C.traffic;
    var row = document.querySelector('#layer-list li[data-row="traffic"]');
    if (!T || !row) { return; }
    var sum = row.querySelector('summary');
    var box = document.createElement('input');
    box.type = 'checkbox';
    box.dataset.layer = 'traffic';
    var lab = document.createElement('label');
    lab.className = 'lbox';
    var vh = document.createElement('span');
    vh.className = 'vh';
    vh.textContent = 'Show ' + T.name;
    lab.appendChild(box); lab.appendChild(vh);
    sum.insertBefore(document.createTextNode(' '), sum.firstChild);
    sum.insertBefore(lab, sum.firstChild);
    var at = opened.toLocaleTimeString('en-US', {timeZone: T.time_zone,
      hour: '2-digit', minute: '2-digit', hour12: false, timeZoneName: 'short'});
    row.querySelector('.n').textContent = T.figure;
    row.querySelector('.traffic-label').textContent = T.label.replace('{time}', at);
    row.querySelector('.traffic-na').hidden = true;
    row.querySelector('.traffic-legend').hidden = false;
    row.classList.remove('lnone');
    boxes.push(box);
    // the live shell builds its overlay buttons from the list's boxes; this box
    // arrives once Google has loaded, after the shell last built them
    if (typeof window.hbSwitches === 'function') { window.hbSwitches(); }
  };
})();
