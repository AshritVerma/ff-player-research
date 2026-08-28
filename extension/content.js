/* Runs in every ESPN fantasy page (and every frame of one). Reads the pick feed
   and hands new picks to the service worker, which forwards them to the local
   helper.

   Three things this has to survive, learned the hard way in a live draft:

   - ESPN moves you between routes. The old build only injected on three guessed
     paths at document_idle, so a real league's draft room could load with no
     script running at all -- or start it late and miss the opening picks. It now
     injects everywhere on the site, from document_start. A page with no pick
     feed simply finds nothing and stays quiet.
   - The draft room can live in an iframe, so all_frames is on. Only the frame
     that actually finds picks puts a badge up, so you don't get four of them.
   - The league id in the URL can change under you mid-draft. It is reported so
     the helper can tell one mock from the next, but the helper no longer treats
     a change on its own as "new draft, bin everything".                       */
(function () {
  var EVERY = 1500;                  // how often to read the room
  var BEAT = 5000;                   // ping the helper at least this often
  var seen = Object.create(null), sent = 0, lastPing = 0, everFound = false;
  var unparsed = 0, lastUnparsed = '', lastRows = 0, matchedBy = '';
  var START = Date.now();

  // Re-read on every sweep rather than once at load: ESPN is a single-page app
  // and the query string changes without the script being torn down.
  function draftId() {
    try {
      var q = new URLSearchParams(location.search);
      return q.get('leagueId') || q.get('leagueID') || q.get('mockDraftId') || '';
    } catch (e) { return ''; }
  }

  var box = null;
  function paint(msg, c) {
    if (!box) {
      box = document.createElement('div');
      box.style.cssText = 'position:fixed;z-index:2147483647;right:12px;bottom:12px;' +
        'background:#17181a;color:#fff;font:600 12px/1.35 -apple-system,Segoe UI,sans-serif;' +
        'padding:8px 11px;border-radius:7px;box-shadow:0 4px 14px rgba(0,0,0,.35);' +
        'pointer-events:none;opacity:.92';
    }
    box.innerHTML = '<span style="color:' + (c || '#4ade80') + '">&#9679;</span> FF Research &middot; ' + msg;
    if (!box.isConnected && document.body) document.body.appendChild(box);
  }

  function parse(li) {
    var t = (li.innerText || '').replace(/ /g, ' ').trim();
    if (!t) return null;
    var m = t.match(/^([^\/\n]+?)\s*\/\s*([A-Z]{2,4})\s+([A-Z\/]+(?:\s*,\s*[A-Z\/]+)*)\s*\n\s*R(\d+)\s*,\s*P(\d+)\s*[-–]\s*(.+)$/);
    if (!m) {
      // Anything shaped like a pick that we could not read is worth knowing
      // about -- silently skipping it is how picks go missing without a trace.
      if (/R\d+\s*,\s*P\d+/.test(t)) { unparsed++; lastUnparsed = t.slice(0, 80); }
      return null;
    }
    return { name: m[1].trim(), nfl: m[2], pos: m[3].split(',')[0].trim(),
             round: +m[4], pick: +m[5], team: m[6].trim() };
  }

  function post(rows) {
    lastPing = Date.now();
    try {
      // Everything the helper would have wanted to know the night this broke:
      // whether a companion is running at all, on what URL, in which frame, how
      // many feed rows it can see, and whether any of them are unreadable.
      var diag = {
        url: location.pathname + location.search.slice(0, 120),
        frame: (window.top === window ? 'top' : 'iframe'),
        rows: lastRows, matchedBy: matchedBy,
        unparsed: unparsed, lastUnparsed: lastUnparsed || undefined,
        ext: (chrome.runtime.getManifest && chrome.runtime.getManifest().version) || '?',
        uptime: Math.round((Date.now() - START) / 1000)
      };
      chrome.runtime.sendMessage({ type: 'ff-picks', picks: rows, draftId: draftId(), diag: diag }, function (res) {
        if (chrome.runtime.lastError || !res || !res.ok) {
          // let anything we failed to deliver be picked up on the next sweep
          for (var i = 0; i < rows.length; i++) delete seen[rows[i].round + '.' + rows[i].pick];
          if (everFound) paint('helper offline &mdash; is draft_sync.py running?', '#f87171');
          return;
        }
        sent += rows.length;
        var msg = res.total + ' picks tracked';
        if (res.missing) msg += ' &middot; <span style="color:#facc15">' + res.missing + ' missing</span>';
        if (unparsed) msg += ' &middot; <span style="color:#facc15">' + unparsed + ' unreadable</span>';
        paint(msg, '#4ade80');
      });
    } catch (e) {
      if (everFound) paint('extension reloaded &mdash; refresh this page', '#facc15');
    }
  }

  function scan() {
    var rows = document.querySelectorAll('li.pick-message__container');
    matchedBy = 'li.pick-message__container';
    if (!rows.length) { rows = document.querySelectorAll('[class*="pick-message__container"]'); matchedBy = 'class*=pick-message__container'; }
    if (!rows.length) { rows = document.querySelectorAll('[class*="pick-message"]'); matchedBy = 'class*=pick-message'; }
    lastRows = rows.length;
    if (!rows.length) {
      // Not the draft room (or not rendered yet). Say nothing, keep looking --
      // but once we have found picks here, keep the heartbeat going so the
      // helper knows the room is still open.
      if (everFound && Date.now() - lastPing > BEAT) post([]);
      return;
    }
    everFound = true;
    var fresh = [];
    for (var i = 0; i < rows.length; i++) {
      var p = parse(rows[i]);
      if (!p) continue;
      var k = p.round + '.' + p.pick;
      if (seen[k]) continue;
      seen[k] = 1;
      fresh.push(p);
    }
    if (fresh.length) post(fresh);
    else if (Date.now() - lastPing > BEAT) post([]);   // heartbeat proves the room is open
  }

  /* Every 30s, forget what we have sent and re-read the whole feed. The helper
     ignores picks it already holds, so this costs nothing -- and it means a
     pick that was missed while the feed was still rendering heals itself
     instead of being gone for the rest of the draft. */
  setInterval(function () { seen = Object.create(null); }, 30000);

  setInterval(scan, EVERY);
  scan();
  // document_start means the body may not exist yet
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scan);
  }
})();
