/* FF Research — draft room companion.
   Runs inside an ESPN draft room, reads the Picks feed, and pushes new picks to
   the local helper on 127.0.0.1:8787. This is the only way to see practice and
   mock drafts, which ESPN never writes to the league API. Works in a real draft
   room too, and gets picks a beat sooner than the API does. */
(function () {
  var HELPER = 'http://127.0.0.1:8787/api/ingest';
  var EVERY = 1500;
  if (window.__ffScraper) { window.__ffScraper.stop(); }

  var seen = Object.create(null), sent = 0, fails = 0;

  var box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:12px;bottom:12px;' +
    'background:#17181a;color:#fff;font:600 12px/1.35 -apple-system,Segoe UI,sans-serif;' +
    'padding:8px 11px;border-radius:7px;box-shadow:0 4px 14px rgba(0,0,0,.35);cursor:pointer;';
  box.title = 'Click to stop the FF Research companion';
  document.body.appendChild(box);

  function paint(msg, color) {
    box.innerHTML = '<span style="color:' + (color || '#4ade80') + '">●</span> FF Research · ' + msg;
  }

  function parse(li) {
    var t = (li.innerText || '').replace(/ /g, ' ').trim();
    // "Mike Evans / SF WR"  +  "R9, P3 - Je Ne Saquon"
    // position may be a list: "Travis Hunter / JAX WR, CB"
    var m = t.match(/^([^\/\n]+?)\s*\/\s*([A-Z]{2,4})\s+([A-Z\/]+(?:\s*,\s*[A-Z\/]+)*)\s*\n\s*R(\d+)\s*,\s*P(\d+)\s*[-–]\s*(.+)$/);
    if (!m) return null;
    return {
      name: m[1].trim(),
      nfl: m[2],
      pos: m[3].split(',')[0].trim(),
      round: +m[4],
      pick: +m[5],
      team: m[6].trim()
    };
  }

  function scan() {
    var rows = document.querySelectorAll('li.pick-message__container');
    if (!rows.length) rows = document.querySelectorAll('[class*="pick-message__container"]');
    var fresh = [];
    for (var i = 0; i < rows.length; i++) {
      var p = parse(rows[i]);
      if (!p) continue;
      var k = p.round + '.' + p.pick;
      if (seen[k]) continue;
      seen[k] = 1;
      fresh.push(p);
    }
    fetch(HELPER, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },   // avoids a CORS preflight
      body: JSON.stringify(fresh)
    }).then(function (r) { return r.json(); }).then(function (j) {
      sent += fresh.length; fails = 0;
      paint(sent + ' picks sent', '#4ade80');
    }).catch(function () {
      fails++;
      for (var i = 0; i < fresh.length; i++) delete seen[fresh[i].round + '.' + fresh[i].pick];
      paint('helper offline — is draft_sync.py running?', '#f87171');
    });
  }

  var timer = setInterval(scan, EVERY);
  window.__ffScraper = { stop: function () { clearInterval(timer); box.remove(); window.__ffScraper = null; } };
  box.onclick = function () { window.__ffScraper.stop(); };
  paint('starting…', '#facc15');
  scan();
})();
