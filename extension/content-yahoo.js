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

  /* ------------------------------------------------------------------ *
     Two places in a Yahoo room list picks, and which one you are looking at
     is up to you, so read whichever is on screen.

     BOARD tab  - a grid of cells reading "JAHMYR GIBBS / RB - Det / 1.1".
                  Best source there is: full names and the round.pick label
                  already worked out, no snake maths and no abbreviations.
                  The cell does not name the fantasy team, so each cell is
                  matched to its column heading by horizontal position --
                  which survives Yahoo renaming its CSS, as it does often.

     PICKS tab  - a list reading "1 / My Sucky Team / J. Gibbs / RB / Det".
                  Names are abbreviated but the fantasy team is right there.

     The first build of this read only the Picks tab and worked out the team
     count by counting the strings "You" and "Team 2".."Team 10" -- fine in
     the instant mock it was written against, useless in a real league where
     the teams are called HOOSIERS 0828 and STEEL DOGS.                      */

  /* A board cell's text is one item per line, not the single styled line the
     screen shows. "JAHMYR GIBBS  RB - Det  1.1" is really:

         Jahmyr / Gibbs / RB / Det / 1.1

     -- forename and surname on separate lines, and the bullet between position
     and team drawn by CSS rather than present in the text. The first version of
     this looked for "RB - Det" on one line and so matched nothing at all, on
     every cell, silently. Anchor on the parts that are really there: a bare
     position line, a team abbreviation after it, a round.pick label, and
     everything before the position as the name. */
  function cellPicks() {
    var out = [];
    var all = document.querySelectorAll('div,li,td,section,article');
    for (var i = 0; i < all.length; i++) {
      var e = all[i];
      if (e.children.length > 6) continue;
      var lines = (e.innerText || '').split('\n')
        .map(function (s) { return s.trim(); }).filter(Boolean);
      if (lines.length < 4 || lines.length > 8) continue;
      var rp = null, ri = -1;
      for (var k = 0; k < lines.length; k++) {
        var m = lines[k].match(/^(\d{1,2})\.(\d{1,2})$/);
        if (m) { rp = m; ri = k; }
      }
      if (!rp) continue;
      var pi = -1;
      for (var j = 0; j < ri; j++) if (POS.test(lines[j])) { pi = j; break; }
      if (pi < 1) continue;                      // need at least one name line
      var nfl = (lines[pi + 1] || '').toUpperCase();
      if (!/^[A-Z]{2,4}$/.test(nfl)) continue;
      var name = lines.slice(0, pi).join(' ');
      if (!name) continue;
      var r = +rp[1], pk = +rp[2];
      if (!r || !pk || r > 30 || pk > 32) continue;
      var box = e.getBoundingClientRect();
      if (!box.width) continue;
      out.push({ name: name, pos: lines[pi] === 'DEF' ? 'D/ST' : lines[pi], nfl: nfl,
                 round: r, pick: pk, x: box.left + box.width / 2, y: box.top,
                 len: (e.innerText || '').length });
    }
    // keep the innermost element for each pick
    var best = {};
    out.forEach(function (p) {
      var k = p.round + '.' + p.pick;
      if (!best[k] || p.len < best[k].len) best[k] = p;
    });
    return Object.keys(best).map(function (k) { return best[k]; });
  }

  /* Column headings carry the fantasy team names. Match a cell to its heading
     by horizontal overlap rather than by walking the DOM, because the grid's
     structure and class names change and a centre point does not. */
  function columnNames(cells) {
    if (!cells.length) return {};
    var topCell = Math.min.apply(null, cells.map(function (c) { return c.y; }));
    var heads = [];
    document.querySelectorAll('div,span,a,th').forEach(function (e) {
      if (e.children.length > 2) return;
      var t = (e.innerText || '').trim();
      if (!t || t.length > 28 || t.indexOf('\n') >= 0) return;
      if (/^\d+\.\d+$/.test(t) || POS.test(t)) return;
      var b = e.getBoundingClientRect();
      if (!b.width || b.top >= topCell) return;
      heads.push({ t: t, x: b.left + b.width / 2, y: b.top, w: b.width });
    });
    if (!heads.length) return {};
    var map = {};
    cells.forEach(function (c) {
      var best = null, bd = 1e9;
      heads.forEach(function (h) {
        var d = Math.abs(h.x - c.x);
        if (d < bd && d < Math.max(60, h.w)) { bd = d; best = h; }
      });
      if (best) map[c.round + '.' + c.pick] = best.t;
    });
    return map;
  }

  /* Picks tab: "1 / My Sucky Team / J. Gibbs / RB / Det / Bye 6" */
  function listPicks() {
    var anchors = document.querySelectorAll('.ys-player'), out = [];
    for (var i = 0; i < anchors.length; i++) {
      var e = anchors[i];
      for (var up = 0; e && up < 3; up++, e = e.parentElement) {
        var lines = (e.innerText || '').split('\n')
          .map(function (s) { return s.trim(); }).filter(Boolean);
        if (lines.length < 5 || lines.length > 8) break;
        if (!/^\d+$/.test(lines[0])) continue;
        var overall = +lines[0];
        if (!overall || overall > 400) continue;
        var pi = -1;
        for (var k = 3; k < lines.length; k++) if (POS.test(lines[k])) { pi = k; break; }
        if (pi < 0) continue;
        var nfl = (lines[pi + 1] || '').toUpperCase();
        if (!/^[A-Z]{2,4}$/.test(nfl)) continue;
        out.push({ overall: overall, team: lines[1], name: lines[2],
                   pos: lines[pi] === 'DEF' ? 'D/ST' : lines[pi], nfl: nfl });
        break;
      }
    }
    return out;
  }

  function scan() {
    var cells = cellPicks();
    var fresh = [], n = 0;

    if (cells.length) {
      // Board tab. Round one's widest pick number is the league size.
      cells.forEach(function (c) { if (c.round === 1 && c.pick > n) n = c.pick; });
      var names = columnNames(cells);
      lastRows = cells.length;
      everFound = true;
      cells.forEach(function (c) {
        var key = c.round + '.' + c.pick;
        if (seen[key]) return;
        seen[key] = 1;
        fresh.push({ name: c.name, nfl: c.nfl, pos: c.pos,
                     team: names[key] || ('Team ' + c.pick),
                     round: c.round, pick: c.pick });
      });
    } else {
      var list = listPicks();
      lastRows = list.length;
      if (!list.length) {
        var inRoom = document.querySelector('.ys-player') ||
                     /draftclient/.test(location.pathname);
        if (inRoom) {
          paint('open the <b>Board</b> or <b>Picks</b> tab so I can read the draft', '#facc15');
          /* Report anyway. A companion that says "I am here and I can see
             nothing" is worth a great deal more than silence: without this the
             helper cannot tell a room it is failing to read from an extension
             that was never loaded, and those two look identical in the log. */
          if (Date.now() - lastPing > BEAT) post([], 0);
        } else if (everFound && Date.now() - lastPing > BEAT) {
          post([], 0);
        }
        return;
      }
      everFound = true;
      // distinct fantasy teams is the league size once round one is done
      var t = {}; list.forEach(function (p) { if (!t[p.team]) { t[p.team] = 1; n++; } });
      list.forEach(function (p) {
        if (seen[p.overall]) return;
        seen[p.overall] = 1;
        var round = n ? Math.floor((p.overall - 1) / n) + 1 : 1;
        var pick = n ? ((p.overall - 1) % n) + 1 : p.overall;
        fresh.push({ name: p.name, nfl: p.nfl, pos: p.pos, team: p.team,
                     round: round, pick: pick, overall: p.overall });
      });
    }

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
