/* FF Research — draft room companion.
   Reads the ESPN draft room's pick feed and hands new picks to the local
   helper. This is the only way to see practice and mock drafts, which ESPN
   never writes to the league API; it works in a real draft room too.

   Transport: Chrome refuses every subresource request from an HTTPS page to a
   local HTTP server — fetch, XHR and images alike. But a page may navigate a
   window it opened. So we keep one small window pointed at the helper and
   re-navigate it with each batch. Ugly, and the only thing that works without
   installing an extension. */
(function () {
  var HELPER = 'http://127.0.0.1:8787/api/ingest';
  var EVERY = 1500;          // how often to read the room
  var BEAT = 5000;           // ping the helper at least this often
  var MAXURL = 6000;

  if (window.__ffScraper) window.__ffScraper.stop();

  var seen = Object.create(null), sent = 0, queue = [], lastPing = 0, sink = null;
  var DRAFT_ID = new URLSearchParams(location.search).get('leagueId') || '';

  var box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:12px;bottom:12px;' +
    'background:#17181a;color:#fff;font:600 12px/1.35 -apple-system,Segoe UI,sans-serif;' +
    'padding:8px 11px;border-radius:7px;box-shadow:0 4px 14px rgba(0,0,0,.35);cursor:pointer';
  box.title = 'Click to stop the FF Research companion';
  document.body.appendChild(box);
  function paint(msg, c) {
    box.innerHTML = '<span style="color:' + (c || '#4ade80') + '">●</span> FF Research · ' + msg;
  }

  function parse(li) {
    var t = (li.innerText || '').replace(/ /g, ' ').trim();
    var m = t.match(/^([^\/\n]+?)\s*\/\s*([A-Z]{2,4})\s+([A-Z\/]+(?:\s*,\s*[A-Z\/]+)*)\s*\n\s*R(\d+)\s*,\s*P(\d+)\s*[-–]\s*(.+)$/);
    if (!m) return null;
    return { name: m[1].trim(), nfl: m[2], pos: m[3].split(',')[0].trim(),
             round: +m[4], pick: +m[5], team: m[6].trim() };
  }

  function b64(o) {
    return btoa(unescape(encodeURIComponent(JSON.stringify(o))))
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function push(rows) {
    if (!sink || sink.closed) {
      paint('sink window closed — click the bookmark again', '#f87171');
      return false;
    }
    var url = HELPER + (rows.length ? '?p=' + b64(rows) : '?beat=1')
              + '&d=' + encodeURIComponent(DRAFT_ID) + '&t=' + Date.now();
    if (url.length > MAXURL) return false;
    try { sink.location.replace(url); } catch (e) { return false; }
    lastPing = Date.now();
    return true;
  }

  function flush() {
    if (queue.length) {
      // send in small batches so the URL stays well under any length limit
      var batch = queue.slice(0, 8);
      if (push(batch)) { sent += batch.length; queue = queue.slice(batch.length); }
      paint(sent + ' picks sent' + (queue.length ? ' (' + queue.length + ' queued)' : ''));
    } else if (Date.now() - lastPing > BEAT) {
      push([]);                       // heartbeat: proves the room is still open
      paint(sent + ' picks sent');
    }
  }

  function scan() {
    var rows = document.querySelectorAll('li.pick-message__container');
    if (!rows.length) rows = document.querySelectorAll('[class*="pick-message__container"]');
    for (var i = 0; i < rows.length; i++) {
      var p = parse(rows[i]);
      if (!p) continue;
      var k = p.round + '.' + p.pick;
      if (seen[k]) continue;
      seen[k] = 1;
      queue.push(p);
    }
    if (!rows.length) paint('no picks visible — is this the draft room?', '#facc15');
    flush();
  }

  // must happen inside the click that ran the bookmarklet, or the popup blocker eats it
  sink = window.open(HELPER + '?beat=1', 'ffsink', 'width=280,height=150');
  if (!sink) {
    paint('popup blocked — allow popups for espn.com, then click again', '#f87171');
    return;
  }

  var timer = setInterval(scan, EVERY);
  window.__ffScraper = { stop: function () {
    clearInterval(timer); box.remove();
    try { if (sink && !sink.closed) sink.close(); } catch (e) {}
    window.__ffScraper = null;
  } };
  box.onclick = function () { window.__ffScraper.stop(); };
  paint('starting…', '#facc15');
  scan();
})();
