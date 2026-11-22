// The start page (HB-208): "Open the recorded run" asks the server to make this
// server's one brief the scenario's served replay, then opens it; "Run it with today's
// conditions" and "Enter a new incident" are links to the entry form.
(function () {
  "use strict";
  var err = document.getElementById("start-error");
  Array.prototype.forEach.call(document.querySelectorAll("button.open-recorded"), function (b) {
    b.addEventListener("click", function () {
      err.textContent = "";
      fetch("/start/recorded", {method: "POST", headers: {"Content-Type": "application/json"},
                                body: JSON.stringify({scenario: b.dataset.scenario})})
        .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
        .then(function (res) {
          if (res[0] !== 201) {
            err.textContent = res[1] && res[1].error ?
              res[1].error.code + ": " + res[1].error.detail : "the server refused the request";
            return;
          }
          window.location.assign(res[1].url);
        });
    });
  });
})();
