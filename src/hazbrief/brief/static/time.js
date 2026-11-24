// HB-157 item 12 (DN-024 section 3.7): the time-step control along the map's lower
// edge. One clock: a step moves the puff's step outline and its uncertainty lines and
// range (every map feature with a `step`), the wind field's hour stepper `#wind-hour`
// (its arrows and its hour label), the step's wind chip `#time-wind`, and the figure of
// residents under the area reached by the step, together. It makes no request: every
// step is in the built page (`map-config`'s `time`). Keyboard: the range input takes
// the arrow keys, Home and End; every button is a button. The map script calls
// `window.hbTime(T, restyle, setOn)` once its layers are drawn.
//
// HB-163 ADDENDUM-01 item 2: on a page whose modelled cloud is drawn (`T.cloud`) the
// one button is "Animate". The page opens on the harm path (`window.hbView` "path":
// each level reached at any time). Animate sets the map to `T.keep` alone (base map,
// incident, ERG zones, the cloud by level, its side lines, the suggested points and the
// wind), shows the cloud at a time (`window.hbView` "time") and plays from the release;
// the same button stops it and restores the layers the reader had, exactly. While
// stopped, the step buttons and slider show the cloud at that step with the same set.
// HB-222 item 1: a layer in `T.leave` (the roads image) is never switched by Animate,
// the slider or the step buttons: off stays off, on stays on.
(function () {
  'use strict';
  window.hbTime = function (T, restyle, setOn) {
    var box = document.getElementById('time-control');
    if (!box || !T || !T.steps || !T.steps.length) { return; }
    var range = document.getElementById('time-step');
    var now = document.getElementById('time-now');
    var wchip = document.getElementById('time-wind');
    var pop = document.getElementById('time-pop');
    var play = document.getElementById('time-play');
    var wind = document.getElementById('wind-hour');
    var map = document.getElementById('map');
    var btns = Array.prototype.slice.call(box.querySelectorAll('button[data-step]'));
    var timer = null, own = false, at = 0, saved = null;
    function go(i, keepWind) {
      i = Math.max(0, Math.min(T.steps.length - 1, i));
      var s = T.steps[i];
      at = i;
      window.hbStep = s.minute;
      range.value = String(i);
      now.textContent = s.hplus + ' · ' + s.clock;
      wchip.textContent = s.wind_text;
      pop.textContent = s.pop_text;
      btns.forEach(function (b) {
        b.setAttribute('aria-current', b.dataset.step === String(i) ? 'step' : 'false');
      });
      var hour = wind ? parseInt(wind.value, 10) : null;
      if (keepWind && hour !== s.hour) {
        // the stepper's hour is past the modelled time: the readout says so
        now.textContent += ' ' + T.words.past.replace('{hour}', String(hour));
      }
      if (!keepWind && wind && s.hour !== null) {
        hour = Math.min(s.hour, parseInt(wind.max, 10));
        own = true;
        wind.value = String(hour);
        wind.dispatchEvent(new Event('input'));
        own = false;
      }
      restyle();
      map.dataset.timeStep = JSON.stringify({
        index: i, minute: s.minute, wind_hour: hour, step_hour: s.hour,
        wind: s.wind_text, residents: s.pop_n, view: window.hbView || null
      });
    }
    function boxes() {
      return Array.prototype.slice.call(
        document.querySelectorAll('#layer-list input[data-layer]'));
    }
    // HB-163: the cloud at a time, with the layer set Animate keeps; the reader's
    // layers are saved once, and restored exactly by `toPath`
    function toTime() {
      if (!T.cloud || window.hbView === 'time') { return; }
      saved = {};
      boxes().forEach(function (b) { saved[b.dataset.layer] = b.checked; });
      Object.keys(saved).forEach(function (id) {
        if (setOn && (T.leave || []).indexOf(id) < 0) {
          setOn(id, T.keep.indexOf(id) >= 0);
        }
      });
      window.hbView = 'time';
      map.dataset.view = 'time';
    }
    function toPath() {
      if (!T.cloud || window.hbView !== 'time') { return; }
      window.hbView = 'path';
      map.dataset.view = 'path';
      if (saved && setOn) {
        Object.keys(saved).forEach(function (id) { setOn(id, saved[id]); });
      }
      saved = null;
      restyle();
    }
    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      play.setAttribute('aria-pressed', 'false');
      play.textContent = T.cloud ? T.words.animate : T.words.play;
    }
    range.addEventListener('input', function () {
      stop(); toTime(); go(parseInt(range.value, 10));
    });
    btns.forEach(function (b) {
      b.addEventListener('click', function () {
        stop(); toTime(); go(parseInt(b.dataset.step, 10));
      });
    });
    // HB-192 (DN-024 ADDENDUM-01 decisions 3 and 6): the frames' mesh, beside the page
    // (`frames.json`), read once when Play or a lookup is first used; a click on the
    // map with the cloud at a time reads the frame's mesh there (bilinear), with the
    // lookup's stated accuracy. The point is put in the mesh's frame by a spherical
    // azimuthal equidistant projection on the site's Gaussian mean radius (WGS84),
    // metres from the engine's ellipsoidal one within 60 km of the site.
    var mesh = null;
    function loadMesh() {
      if (mesh || !T.frames) { return mesh || Promise.reject(new Error('none')); }
      if (location.protocol === 'file:') {
        mesh = Promise.reject(new Error(T.frames.lookup.file));
      } else {
        mesh = fetch('frames.json').then(function (r) {
          if (!r.ok) { throw new Error('frames.json: ' + r.status); }
          return r.json();
        });
      }
      return mesh;
    }
    function codes(m) {
      var bin = atob(m.codes_gz_b64), u = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) { u[i] = bin.charCodeAt(i); }
      var s = new Blob([u]).stream().pipeThrough(new DecompressionStream('gzip'));
      return new Response(s).arrayBuffer().then(function (b) { return new Uint8Array(b); });
    }
    function localKm(site, lat, lon) {
      var a = 6378.137, e2 = 0.00669437999014, p = site.lat * Math.PI / 180;
      var w = 1 - e2 * Math.sin(p) * Math.sin(p);
      var R = Math.sqrt(a * (1 - e2) / Math.pow(w, 1.5) * a / Math.sqrt(w));
      var p2 = lat * Math.PI / 180, dl = (lon - site.lon) * Math.PI / 180;
      var c = Math.acos(Math.min(1, Math.sin(p) * Math.sin(p2) +
        Math.cos(p) * Math.cos(p2) * Math.cos(dl)));
      var az = Math.atan2(Math.sin(dl) * Math.cos(p2),
        Math.cos(p) * Math.sin(p2) - Math.sin(p) * Math.cos(p2) * Math.cos(dl));
      return [R * c * Math.sin(az), R * c * Math.cos(az)];
    }
    function lookAt(ll) {
      var L1 = T.frames.lookup, minute = T.steps[at].minute;
      loadMesh().then(function (P) {
        var fr = P.frames.filter(function (f) { return f.minute === minute; })[0];
        if (!fr || !fr.mesh) { return L1.outside; }
        var m = fr.mesh, xy = localKm(P.site, ll.lat, ll.lng);
        var fx = (xy[0] - m.x0_km) / m.dx_km, fy = (xy[1] - m.y0_km) / m.dy_km;
        if (fx < 0 || fy < 0 || fx > m.nx - 1 || fy > m.ny - 1) { return L1.outside; }
        return codes(m).then(function (c) {
          function v(i, j) {
            var k = c[i * m.nx + j];
            return k ? m.floor_kg_m3 * Math.pow(10, (k - 1) / m.per_decade) : 0;
          }
          var j = Math.min(Math.floor(fx), m.nx - 2), i = Math.min(Math.floor(fy), m.ny - 2);
          var tx = fx - j, ty = fy - i;
          var kg = v(i, j) * (1 - tx) * (1 - ty) + v(i, j + 1) * tx * (1 - ty) +
            v(i + 1, j + 1) * tx * ty + v(i + 1, j) * (1 - tx) * ty;
          var lv = P.levels, perKg = lv[0].ppm / T.frames.kg[lv[0].name], band = null;
          lv.forEach(function (l) { if (kg >= T.frames.kg[l.name]) { band = l.name; } });
          var acc = (P.accuracy && P.accuracy.all) || {};
          if (kg < m.floor_kg_m3) {
            return L1.below.replace('{floor}', (m.floor_kg_m3 * perKg).toPrecision(2));
          }
          return L1.at.replace('{ppm}', (kg * perKg).toPrecision(2))
            .replace('{band}', band || T.frames.below_levels)
            .replace('{spacing}', String(P.spacing_m))
            .replace('{ratio}', String(acc.median)).replace('{worst}', String(acc.worst));
        });
      }).catch(function (e) {
        return L1.unread.replace('{why}', e.message);
      }).then(function (text) {
        if (window.hbMapApi && window.L) {
          L.popup().setLatLng(ll).setContent(text).openOn(window.hbMapApi.map);
        }
        map.dataset.lookup = text;
      });
    }
    if (T.frames && window.hbMapApi) {
      window.hbMapApi.map.on('click', function (e) {
        if (window.hbView === 'time') { lookAt(e.latlng); }
      });
    }
    play.addEventListener('click', function () {
      if (T.frames && !timer) { loadMesh().catch(function () {}); }
      if (timer) { stop(); toPath(); return; }
      if (T.cloud) {
        toTime();
        go(0);
      } else if (at >= T.steps.length - 1) { go(0); }
      play.setAttribute('aria-pressed', 'true');
      play.textContent = T.cloud ? T.words.stop : T.words.pause;
      timer = setInterval(function () {
        if (at >= T.steps.length - 1) {
          stop();
          if (T.cloud) { toPath(); }
          return;
        }
        go(at + 1);
      }, T.play_ms);
    });
    // the stepper moved by hand: the one clock follows it to the last step whose hour
    // is at or before the stepped hour, and the stepper keeps its hour; past the
    // modelled time the readout says the outline is this step's
    if (wind) {
      wind.addEventListener('input', function () {
        if (own) { return; }
        stop();
        var h = parseInt(wind.value, 10), best = 0;
        T.steps.forEach(function (s, k) { if (s.hour !== null && s.hour <= h) { best = k; } });
        go(best, true);
      });
    }
    // HB-171 item 10: a threat timeline row on the first view moves the control to
    // that row's step (the first step at or after its arrival), the cloud at a time
    document.querySelectorAll('#threat-next button.tn-go').forEach(function (b) {
      b.addEventListener('click', function () {
        stop(); toTime(); go(parseInt(b.dataset.step, 10));
      });
    });
    if (T.cloud) { map.dataset.view = 'path'; }
    go(T.open_index);
  };
})();
