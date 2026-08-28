/* Yahoo draft rooms. Same job as content.js does for ESPN: read the pick feed,
   hand new picks to the service worker, which forwards them to the helper.

   Yahoo's room differs from ESPN's in three ways that matter:

   - The pick list lives under the "Picks" tab. Nothing else in the room shows
     more than the single most recent pick, so if that tab is not open there is
     nothing to read -- the badge says so rather than sitting there silently.
   - Names are abbreviated to an initial and a surname ("J. Gibbs"), so the
     helper resolves them against position and NFL team as well. A surname plus
     RB plus Det is unambiguous in a way "J. Gibbs" alone is not.
   - Picks are numbered overall (1..N) rather than by round, and the room says
     outright how many teams there are, so we report that instead of leaving the
     dashboard to infer it after round one.

   Class names here are Yahoo's Atomic CSS and churn between deploys, so the
   only hook used is `.ys-player` plus the shape of the row's own text. */
(function () {
  var EVERY = 1500;
  var BEAT = 5000;
  var POS = /^(QB|RB|WR|TE|K|DEF|D\/ST)$/;
  var seen = Object.create(null), lastPing = 0, everFound = false;
  var unparsed = 0, lastUnparsed = '', lastRows = 0;
  var START = Date.now();

  function draftId() {
    // /draftclient/f1/<draftId>/<teamId>
    var m = location.pathname.match(/\/draftclient\/[^/]+\/(\d+)/);
    return m ? m[1] : '';
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

  /* How many teams are in this room. Yahoo prints every team's name down the
     draft board, so the distinct count is the answer -- no inference needed. */
  function teamCount() {
    var names = {}, n = 0;
    (document.body.innerText || '').split('\n').forEach(function (l) {
      l = l.trim();
      if (/^(You|Team \d+)$/.test(l) && !names[l]) { names[l] = 1; n++; }
    });
    return n >= 4 ? n : 0;
  }

  /* A pick row reads: overall, fantasy team, "J. Gibbs", [injury tag], pos,
     NFL team, "Bye 6". The optional tag is why the position is searched for
     rather than read at a fixed offset. */
  function parseRow(el) {
    var lines = (el.innerText || '').split('\n')
      .map(function (s) { return s.trim(); }).filter(Boolean);
    if (lines.length < 5 || lines.length > 8) return null;
    if (!/^\d+$/.test(lines[0])) return null;
    var overall = +lines[0];
    if (!overall || overall > 400) return null;
    var team = lines[1], name = lines[2];
    var pi = -1;
    for (var i = 3; i < lines.length; i++) if (POS.test(lines[i])) { pi = i; break; }
    if (pi < 0 || !name) return null;
    var pos = lines[pi] === 'DEF' ? 'D/ST' : lines[pi];
    var nfl = (lines[pi + 1] || '').toUpperCase();
    if (!/^[A-Z]{2,4}$/.test(nfl)) return null;
    return { overall: overall, name: name, pos: pos, nfl: nfl, team: team };
  }

  function scan() {
    var anchors = document.querySelectorAll('.ys-player');
    var rows = [], picks = [];
    for (var i = 0; i < anchors.length; i++) {
      // walk up at most two levels to the row that carries the pick number
      var e = anchors[i];
      for (var up = 0; e && up < 3; up++, e = e.parentElement) {
        var p = parseRow(e);
        if (p) { picks.push(p); break; }
      }
      rows.push(1);
    }
    lastRows = picks.length;

    if (!anchors.length) {
      if (everFound && Date.now() - lastPing > BEAT) post([]);
      return;
    }
    if (!picks.length) {
      // The room is open but the pick list is not on screen.
      paint('open the <b>Picks</b> tab so I can read the draft', '#facc15');
      if (everFound && Date.now() - lastPing > BEAT) post([]);
      return;
    }
    everFound = true;

    var n = teamCount(), fresh = [];
    picks.forEach(function (p) {
      if (seen[p.overall]) return;
      seen[p.overall] = 1;
      /* overall -> round + position within that round. The snake is in *who*
         picks, not in how the picks are numbered: in a 10-team league overall
         20 is the tenth pick of round two, made by the team that opened round
         one. Reversing the number here instead put every even round backwards
         on the board. */
      var round = n ? Math.floor((p.overall - 1) / n) + 1 : 1;
      var pick = n ? ((p.overall - 1) % n) + 1 : p.overall;
      fresh.push({ name: p.name, nfl: p.nfl, pos: p.pos, team: p.team,
                   round: round, pick: pick, overall: p.overall });
    });
    if (fresh.length) post(fresh, n);
    else if (Date.now() - lastPing > BEAT) post([], n);
  }

  function post(rows, n) {
    lastPing = Date.now();
    var diag = {
      url: location.pathname,
      frame: (window.top === window ? 'top' : 'iframe'),
      rows: lastRows, matchedBy: '.ys-player',
      unparsed: unparsed, lastUnparsed: lastUnparsed || undefined,
      ext: (chrome.runtime.getManifest && chrome.runtime.getManifest().version) || '?',
      uptime: Math.round((Date.now() - START) / 1000)
    };
    try {
      chrome.runtime.sendMessage(
        { type: 'ff-picks', picks: rows, draftId: draftId(), source: 'yahoo',
          teamCount: n || undefined, diag: diag },
        function (res) {
          if (chrome.runtime.lastError || !res || !res.ok) {
            for (var i = 0; i < rows.length; i++) delete seen[rows[i].overall];
            if (everFound) paint('helper offline &mdash; is draft_sync.py running?', '#f87171');
            return;
          }
          var msg = res.total + ' picks tracked <span style="opacity:.6">Yahoo</span>';
          if (res.missing) msg += ' &middot; <span style="color:#facc15">' + res.missing + ' missing</span>';
          paint(msg, '#4ade80');
        });
    } catch (e) {
      if (everFound) paint('extension reloaded &mdash; refresh this page', '#facc15');
    }
  }

  // Same self-healing sweep as the ESPN side: forget what we sent every 30s and
  // re-read, so anything missed while the room was rendering comes back.
  setInterval(function () { seen = Object.create(null); }, 30000);
  setInterval(scan, EVERY);
  scan();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan);
})();
