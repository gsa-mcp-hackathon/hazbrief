// The entry form (HB-132R Part B; DN-022 section 7): a point and a situation line.
// The map click sets the point; a typed location is resolved by the server (DN-013's
// rules) and its derivation and accuracy are printed. The line is read by the server
// into three fields, shown back editable with the span each came from marked in the
// line. One click builds: the server writes the fixture first, then the page reloads
// onto the live brief.
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var point = null, marker = null, parsed = null, resolvedGiven = null;
  var tiles = JSON.parse($("entry-tiles").textContent);
  var map = L.map("entry-map").setView([39.2, -77.3], 8);
  // HB-207 Part F: a driver places the point as a click would (map.fire("click"))
  window.hbEntryMap = map;
  var base = tiles[0];
  L.tileLayer(base.url, {attribution: base.attribution, maxZoom: base.max_zoom}).addTo(map);

  var KINDS = {
    point: [],
    address: [["address", "100 Jones Point Dr, Alexandria, VA 22314"]],
    intersection: [["street_a", "Jefferson St"], ["street_b", "S Lee St"],
                   ["place", "Alexandria"], ["state", "VA"]],
    milepost: [["state", "PA"], ["route", "I-81"], ["from_mile", "0"], ["to_mile", "1"]],
    crossing: [["state", "MD"], ["city", "Point of Rocks"], ["street", "Canal Road"]]
  };
  function showKind() {
    var k = $("loc-kind").value, box = $("loc-fields");
    box.textContent = "";
    KINDS[k].forEach(function (f) {
      var lab = document.createElement("label");
      lab.textContent = f[0] + " ";
      var inp = document.createElement("input");
      inp.name = f[0]; inp.placeholder = f[1]; inp.dataset.loc = "1";
      lab.appendChild(inp); box.appendChild(lab);
    });
    $("loc-resolve").hidden = (k === "point");
    resolvedGiven = null;
  }
  $("loc-kind").addEventListener("change", showKind);
  showKind();

  map.on("click", function (e) {
    $("loc-kind").value = "point"; showKind();
    point = {latitude: +e.latlng.lat.toFixed(4), longitude: +e.latlng.lng.toFixed(4)};
    if (marker) { map.removeLayer(marker); }
    marker = L.marker(e.latlng).addTo(map);
    $("loc-label").textContent = "Point " + point.latitude + ", " + point.longitude +
      ": no accuracy stated; the footprint is drawn as if this point were exact.";
  });

  function given() {
    var g = {kind: $("loc-kind").value};
    Array.prototype.forEach.call(document.querySelectorAll("[data-loc]"), function (i) {
      var v = i.value.trim();
      if (v) { g[i.name] = /_mile$/.test(i.name) ? +v : v; }
    });
    return g;
  }
  function post(url, body) {
    return fetch(url, {method: "POST", headers: {"Content-Type": "application/json"},
                       body: JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); });
  }
  function fail(j) {
    $("entry-error").textContent = j && j.error ?
      j.error.code + ": " + j.error.detail : "the server refused the request";
  }

  $("loc-resolve").addEventListener("click", function () {
    $("entry-error").textContent = "";
    var g = given();
    post("/entry/locate", {given: g}).then(function (res) {
      var j = res[1];
      if (res[0] !== 200) { fail(j); return; }
      $("loc-label").textContent = (j.resolved ? "" : "Not resolved: ") +
        (j.derivation || "") + (j.accuracy_m != null ? ", accuracy " + j.accuracy_m +
        " m (" + j.basis + ")" : "") + ". " + j.label;
      resolvedGiven = j.resolved ? g : null;
      point = null;
      if (j.resolved && j.shape) {
        var lay = L.geoJSON(j.shape).addTo(map);
        map.fitBounds(lay.getBounds(), {maxZoom: 15});
      }
    });
  });

  function marked(line, fields) {
    // the line with each field's span marked, so the reader sees where it came from
    var spans = [];
    ["material", "container", "state"].forEach(function (n) {
      var s = fields[n].span;
      if (s) { var at = line.indexOf(s); if (at >= 0) { spans.push([at, at + s.length, n]); } }
    });
    spans.sort(function (a, b) { return a[0] - b[0]; });
    var p = $("line-shown"), pos = 0;
    p.textContent = "";
    spans.forEach(function (sp) {
      if (sp[0] < pos) { return; }
      p.appendChild(document.createTextNode(line.slice(pos, sp[0])));
      var m = document.createElement("mark");
      m.title = sp[2]; m.textContent = line.slice(sp[0], sp[1]);
      p.appendChild(m); pos = sp[1];
    });
    p.appendChild(document.createTextNode(line.slice(pos)));
  }

  // HB-207 items 5 and 9, ADDENDUM-03 item 1: the ERG entry shown back for one
  // confirmation beside the words typed, and what is assumed, each with its source
  var choice = null;
  function entryText(c) {
    return (c.id_number ? c.id_number + ", " : "") + c.name +
      (c.guide ? " (ERG Guide " + c.guide + ")" : "");
  }
  function chosen() {
    var r = document.querySelector("input[name=erg-entry]:checked");
    return r && choice ? choice.candidates[+r.value] : null;
  }
  function localInput(iso) {
    // an ISO instant as the datetime-local input's value, in the reader's own zone
    var d = new Date(iso), p = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      "T" + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  function zoneWords(d) {
    return d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit",
                                     timeZoneName: "short"});
  }
  function showAssumed(a) {
    if (!a) { return; }
    if (a.start_time && a.start_time.value) {
      $("a-time").value = localInput(a.start_time.value);
      $("a-time-note").textContent = "Start time: now, " +
        zoneWords(new Date(a.start_time.value)) + ". " + a.start_time.note;
    }
    var q = a.quantity || {};
    $("a-qty").value = q.kg != null ? q.kg : "";
    $("a-qty-source").textContent = q.kg != null ? q.short + "." :
      (q.ask || "") + (q.why ? " (" + q.why + ")" : "");
    var st = a.storage_state;
    $("a-state").textContent = st ? "Storage state: " + (st.state || "not stated") +
      " (" + st.basis + "). Release route: " + st.route.status +
      (st.route.route ? ", " + st.route.route : "") +
      (st.route.reason ? ": " + st.route.reason : "") + "." :
      (a.waits_on_material || "");
    if (a.levels) { $("a-state").textContent += " " + a.levels; }
    $("a-worst").textContent = a.worst_case || "";
  }
  function assume() {
    var c = chosen();
    if (!c) { return; }
    post("/entry/assume", {confirmed: c, container: $("f-container").value})
      .then(function (res) { if (res[0] === 200) { showAssumed(res[1]); } });
  }
  function showChoice(typed, ch) {
    choice = ch;
    var box = $("candidates");
    box.textContent = "";
    $("material-reason").textContent = ch.reason || ch.question || "";
    $("confirm-entry").checked = false;
    $("confirm-label").hidden = !ch.candidates.length;
    $("typed-shown").textContent = ch.candidates.length ?
      "You typed: " + typed + ". ERG entry: " + entryText(ch.candidates[0]) +
      (ch.candidates.length > 1 ? ". Other entries that fit are listed; pick one." : ".") :
      "";
    ch.candidates.forEach(function (c, i) {
      var lab = document.createElement("label");
      var r = document.createElement("input");
      r.type = "radio"; r.name = "erg-entry"; r.value = i; r.checked = i === 0;
      r.addEventListener("change", function () {
        $("confirm-entry").checked = false; assume();
      });
      lab.appendChild(r);
      lab.appendChild(document.createTextNode(" " + entryText(c)));
      box.appendChild(lab);
    });
  }
  $("f-container").addEventListener("change", assume);
  $("use-now").addEventListener("click", function () {
    $("a-time").value = localInput(new Date().toISOString());
    $("entry-top").textContent = "";
  });

  $("parse").addEventListener("click", function () {
    $("entry-error").textContent = "";
    $("entry-top").textContent = "";
    var line = $("line").value;
    post("/entry/parse", {line: line}).then(function (res) {
      var j = res[1];
      if (res[0] !== 200) { fail(j); return; }
      parsed = j;
      $("f-material").value = j.fields.material.value;
      $("f-container").value = j.fields.container.value;
      $("f-state").value = j.fields.state.value;
      var erg = j.fields.material.erg;
      $("f-material-erg").textContent = !erg ? "" : erg.resolved ?
        (erg.id_number || erg.name) + ", ERG Guide " + erg.guide : "";
      $("route").textContent = j.route.why;
      marked(line, j.fields);
      showChoice(j.fields.material.span || j.fields.material.value, j.material_choice);
      showAssumed(j.assumptions);
    });
  });

  function field(name, el) {
    var v = $(el).value.trim() || "unknown";
    var p = parsed && parsed.fields[name];
    // a field the reader left as read keeps its span; a corrected one has none
    return {value: v, span: p && p.value === v ? p.span : null};
  }

  $("entry-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    $("entry-error").textContent = "";
    var weather = {};
    Array.prototype.forEach.call(document.querySelectorAll("[data-weather]"), function (i) {
      if (i.value.trim()) { weather[i.name] = i.value.trim(); }
    });
    var material = field("material", "f-material");
    var c = chosen();
    if (material.value !== "unknown") {
      // nothing is built until the reader confirms one ERG entry (HB-207 item 5)
      if (!c || !$("confirm-entry").checked) {
        $("entry-error").textContent = "Confirm the material: pick its ERG entry " +
          "and tick \"This is the material\", or set the material to unknown.";
        return;
      }
      material.confirmed = {id_number: c.id_number, name: c.name};
    }
    var t = $("a-time").value;
    var body = {
      line: $("line").value,
      parse: parsed,
      fields: {material: material,
               container: field("container", "f-container"),
               state: field("state", "f-state")},
      weather: weather,
      assumptions: {incident_time: t ? new Date(t).toISOString() : null,
                    quantity_kg: $("a-qty").value === "" ? null : +$("a-qty").value}
    };
    if (template) { body.template = template.scenario; }
    if ($("loc-kind").value === "point") { body.point = point; } else { body.given = resolvedGiven || given(); }
    post("/entry/build", body).then(function (res) {
      if (res[0] !== 201) {
        if (res[1] && res[1].error && res[1].error.code === "past_time") {
          // one plain message at the top, with the two ways on (HB-207 item 11)
          $("entry-top").textContent = res[1].error.detail;
          return;
        }
        fail(res[1]); return;
      }
      window.location.assign(res[1].url);
    });
  });

  // HB-208 item 3: a prepared scenario run with today's conditions. Its point, its
  // fields and its confirmed ERG entry are filled in; the start time is now and the
  // weather the forecast (the form's default). Every field stays editable: a map click
  // moves the point. Nothing is read by the model and nothing is built here.
  var tEl = $("entry-template");
  var template = tEl ? JSON.parse(tEl.textContent) : null;
  if (template) {
    if (template.point) {
      var ll = L.latLng(template.point.latitude, template.point.longitude);
      map.fire("click", {latlng: ll});
      map.setView(ll, 12);
    }
    $("f-material").value = template.fields.material.value;
    $("f-container").value = template.fields.container.value;
    $("f-state").value = template.fields.state.value;
    var row = template.confirmed;
    showChoice(template.fields.material.value, {candidates: row ? [row] : [],
                                                reason: row ? "" : template.material_note});
    if (row) {
      $("confirm-entry").checked = true;
      $("typed-shown").textContent = template.material_note;
    }
    showAssumed(template.assumptions);
  }
})();
