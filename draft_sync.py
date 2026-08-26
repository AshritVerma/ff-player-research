#!/usr/bin/env python3
"""
Live draft helper for the FF Player Research board.

The dashboard itself cannot read your draft: ESPN's draft endpoint needs the
espn_s2 / SWID session cookies, and a browser page can't set cookie headers on
a cross-site fetch. So this small local process holds the cookies, polls ESPN,
and exposes the result to the page on http://127.0.0.1:8787/api/draft.

The cookies never leave this process -- the page only ever sees picks, teams
and player names.

Usage
-----
    python3 draft_sync.py                  # read ./draft_config.json
    python3 draft_sync.py --league 12345   # override the league (mock drafts)
    python3 draft_sync.py --demo           # fake a draft; no ESPN, no cookies

Config (draft_config.json, gitignored -- it holds your session cookies):

    {
      "leagueId": 714515427,
      "season": 2026,
      "espn_s2": "AEB...",
      "SWID": "{XXXXXXXX-....}",
      "pollInterval": 5
    }

Getting the cookies: log in to fantasy.espn.com, open DevTools -> Application ->
Cookies -> https://fantasy.espn.com, and copy the values of `espn_s2` and `SWID`.
They last months, not days, but they do expire -- when they do this prints an
auth error and the page shows it.
"""

import argparse
import base64
import concurrent.futures
import json
import re
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))


def _self_version():
    """Hash of this file. The launcher compares it against the running helper's
    and restarts on a mismatch -- otherwise editing draft_sync.py does nothing
    until someone remembers to kill the old process, which is exactly how a
    reset button ends up 404ing against a helper from three versions ago."""
    try:
        import hashlib
        with open(os.path.abspath(__file__), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except Exception:
        return "unknown"


VERSION = _self_version()
CONFIG = os.path.join(HERE, "draft_config.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "Chrome/126.0 Safari/537.36")
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"

TEAMS_NFL = {0:'FA',1:'ATL',2:'BUF',3:'CHI',4:'CIN',5:'CLE',6:'DAL',7:'DEN',8:'DET',9:'GB',
             10:'TEN',11:'IND',12:'KC',13:'LV',14:'LAR',15:'MIA',16:'MIN',17:'NE',18:'NO',
             19:'NYG',20:'NYJ',21:'PHI',22:'ARI',23:'PIT',24:'LAC',25:'SF',26:'SEA',27:'TB',
             28:'WSH',29:'CAR',30:'JAX',33:'BAL',34:'HOU'}
POS = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'D/ST'}


# ----------------------------------------------------------------- shared state
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.payload = {
            "ok": False, "status": "starting", "message": "Connecting to ESPN...",
            "updated": None, "picks": [], "teams": [], "players": {},
            "onClock": None, "complete": False,
        }

    def set(self, **kw):
        with self.lock:
            self.payload.update(kw)

    def get(self):
        with self.lock:
            p = dict(self.payload)
        p["version"] = VERSION
        p["age"] = None if not p.get("updated") else round(time.time() - p["updated"], 1)
        return p


STATE = State()


class Ingest:
    """Picks pushed in from the draft-room bookmarklet.

    ESPN never writes practice/mock draft picks to the league API, and even in a
    real draft the room is the earliest source. The bookmarklet scrapes the room
    and POSTs here; names are matched back to our player ids so the page sees
    exactly the same shape either way.
    """

    def __init__(self, data_path):
        self.lock = threading.Lock()
        self.picks = {}          # (round, pick) -> pick dict
        self.updated = None
        self.draft_id = None     # which draft these picks belong to
        self.started = None
        self.by_name = {}
        try:
            for p in json.load(open(data_path))["players"]:
                self.by_name.setdefault(norm_name(p["name"]), p)
        except Exception:
            pass

    def resolve(self, name, pos, nfl):
        p = self.by_name.get(norm_name(name))
        if p:
            return p["id"], {"name": p["name"], "pos": p["pos"], "team": p["team"]}
        # not in the top-300 snapshot: keep a stable synthetic id so the page
        # can still show them on a roster
        sid = -(abs(hash(norm_name(name))) % 10_000_000 + 1)
        return sid, {"name": name, "pos": pos or "?", "team": nfl or ""}

    def reset(self, draft_id=None):
        with self.lock:
            self.picks = {}
            self.draft_id = draft_id
            self.started = time.time()
            self.updated = time.time()

    def add(self, rows, draft_id=None):
        """Any POST -- even an empty one -- is a heartbeat proving the draft room
        is still open. Freshness must track that, not the last pick: a 30s gap
        between picks is normal and must not read as 'stale'.

        draft_id is the league id of the room the picks came from. Back-to-back
        mock drafts each get their own, so a change means a new draft and the
        old picks must go -- otherwise draft two opens showing draft one."""
        if draft_id and self.draft_id and draft_id != self.draft_id:
            print("new draft (%s -> %s); clearing %d picks"
                  % (self.draft_id, draft_id, len(self.picks)))
            self.reset(draft_id)
        added = 0
        with self.lock:
            if draft_id and not self.draft_id:
                self.draft_id = draft_id
                self.started = self.started or time.time()
            for r in rows:
                try:
                    rnd, pk = int(r["round"]), int(r["pick"])
                except Exception:
                    continue
                key = (rnd, pk)
                if key in self.picks:
                    prev = self.picks[key]
                    same = norm_name(r.get("name", "")) == norm_name(prev["_info"]["name"])
                    if same or (rnd, pk) != (1, 1):
                        continue
                    # 1.01 replayed with a different player: the room restarted
                    print("pick 1.01 changed; treating as a new draft")
                    self.picks = {}
                pid, info = self.resolve(r.get("name", ""), r.get("pos"), r.get("nfl"))
                self.picks[key] = {
                    "playerId": pid, "teamName": (r.get("team") or "").strip(),
                    "round": rnd, "roundPick": pk, "keeper": False, "_info": info,
                }
                added += 1
            self.updated = time.time()
        return added

    def snapshot(self, teams_per_round):
        with self.lock:
            keys = sorted(self.picks)
            teams, tid = {}, {}
            picks, players = [], {}
            for rnd, pk in keys:
                p = dict(self.picks[(rnd, pk)])
                nm = p.pop("teamName") or ("Team %d" % pk)
                if nm not in tid:
                    tid[nm] = len(tid) + 1
                    teams[nm] = {"id": tid[nm], "name": nm, "abbrev": abbrev_of(nm)}
                p["teamId"] = tid[nm]
                n = teams_per_round or max((k[1] for k in keys), default=1)
                p["overall"] = (rnd - 1) * n + pk
                players[str(p["playerId"])] = p.pop("_info")
                picks.append(p)
            return picks, list(teams.values()), players, self.updated


def norm_name(n):
    n = (n or "").lower()
    for junk in (" jr.", " jr", " sr.", " sr", " iii", " ii", " iv", "'", ".", "-"):
        n = n.replace(junk, " " if junk.startswith(" ") else "")
    return " ".join(n.split())


def abbrev_of(name):
    words = [w for w in (name or "").split() if w]
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:4].upper()
    return "".join(w[0] for w in words[:4]).upper()


INGEST = None



class News:
    """Aggregated player news, kept warm in the background.

    Two sources, because neither is enough alone. ESPN has per-player history
    and is what the baked-in snapshot already uses, so its links are preserved.
    Rotowire's RSS carries only the last handful of items league-wide, but those
    are the breaking ones -- a practice-field injury shows up there first.

    FantasyPros is deliberately absent: it has no working public feed (their RSS
    paths 404 or return empty, the API is 403) and the player pages render news
    client-side, so the only way in would be driving a browser.
    """

    ESPN = ("https://site.web.api.espn.com/apis/fantasy/v2/games/ffl/news/"
            "players?playerId=%d&limit=8")
    ROTOWIRE = "https://www.rotowire.com/rss/news.php?sport=NFL"
    PER_CYCLE = 25          # players refreshed each pass, so a full sweep is gentle

    def __init__(self, data_path):
        self.lock = threading.Lock()
        self.items = {}
        self.updated = None
        self.cursor = 0
        self.roster = []
        try:
            for p in json.load(open(data_path))["players"]:
                self.roster.append((p["id"], norm_name(p["name"])))
        except Exception:
            pass

    # ---- fetching -------------------------------------------------------
    def _get(self, url, raw=False):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "ignore")
        return body if raw else json.loads(body)

    def espn(self, pid):
        out = []
        try:
            d = self._get(self.ESPN % pid)
        except Exception:
            return out
        for f in (d.get("feed") or []):
            head = (f.get("headline") or "").strip()
            if not head:
                continue
            body = ""
            for st in (f.get("story") or "", f.get("description") or ""):
                if st:
                    body = re.sub(r"<[^>]+>", "", st).strip()
                    break
            link = ""
            try:
                link = (((f.get("links") or {}).get("web") or {}).get("href") or "")
            except Exception:
                pass
            out.append({"h": head, "d": body, "t": f.get("published") or "",
                        "u": link, "s": "ESPN"})
        return out

    def rotowire(self):
        """-> {normalised player name: [items]}"""
        by_name = {}
        try:
            x = self._get(self.ROTOWIRE, raw=True)
        except Exception:
            return by_name

        def tag(block, t):
            m = re.search(r"<%s>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</%s>" % (t, t), block, re.S)
            return html_unescape(m.group(1)).strip() if m else ""

        for block in re.findall(r"<item>(.*?)</item>", x, re.S):
            title = tag(block, "title")
            if ":" not in title:
                continue
            who, head = title.split(":", 1)
            item = {
                "h": head.strip(), "d": re.sub(r"<[^>]+>", "", tag(block, "description")).strip(),
                "t": rfc822(tag(block, "pubDate")), "u": tag(block, "link").replace("//football", "/football"),
                "s": "RotoWire",
            }
            by_name.setdefault(norm_name(who), []).append(item)
        return by_name

    # ---- merge ----------------------------------------------------------
    @staticmethod
    def merge(*lists):
        seen, out = set(), []
        for group in lists:
            for it in group:
                key = norm_name(it["h"])[:70]
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
        out.sort(key=lambda i: i.get("t") or "", reverse=True)
        return out[:10]

    def cycle(self):
        wire = self.rotowire()
        batch = []
        with self.lock:
            n = len(self.roster)
            if not n:
                return
            for i in range(self.PER_CYCLE):
                batch.append(self.roster[(self.cursor + i) % n])
            self.cursor = (self.cursor + self.PER_CYCLE) % n
        fresh = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            for (pid, nm), got in zip(batch, ex.map(lambda b: self.espn(b[0]), batch)):
                fresh[pid] = self.merge(wire.get(nm, []), got)
        # anyone named in the wire feed gets it immediately, not on their turn
        for pid, nm in self.roster:
            if nm in wire and pid not in fresh:
                with self.lock:
                    fresh[pid] = self.merge(wire[nm], self.items.get(pid, []))
        with self.lock:
            self.items.update({k: v for k, v in fresh.items() if v})
            self.updated = time.time()

    def payload(self):
        with self.lock:
            return {"updated": self.updated, "count": len(self.items),
                    "news": {str(k): v for k, v in self.items.items()}}


def html_unescape(s):
    import html as _h
    return _h.unescape(s or "")


def rfc822(s):
    """RSS date -> the ISO-ish string the page already formats."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return ""


NEWS = None


def news_loop(interval=90):
    while True:
        try:
            if NEWS:
                NEWS.cycle()
        except Exception as e:
            print("news cycle failed:", e, file=sys.stderr)
        time.sleep(interval)


# ----------------------------------------------------------------- espn client
class Espn:
    def __init__(self, league, season, s2, swid):
        self.league, self.season = league, season
        self.cookie = ""
        if s2 and swid:
            self.cookie = "espn_s2=%s; SWID=%s" % (s2, swid)
        self.names = {}          # playerId -> {name, pos, team}

    def _get(self, url, extra=None):
        h = {"User-Agent": UA, "Accept": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        h.update(extra or {})
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())

    def league_url(self, views):
        q = "&".join("view=" + v for v in views)
        return "%s/%d/segments/0/leagues/%d?%s" % (BASE, self.season, self.league, q)

    def resolve_names(self, ids):
        """Fill in names for player ids we haven't seen. Public endpoint, no auth."""
        missing = [i for i in ids if i not in self.names]
        if not missing:
            return
        for chunk in (missing[i:i + 200] for i in range(0, len(missing), 200)):
            try:
                url = "%s/%d/players?scoringPeriodId=0&view=players_wl" % (BASE, self.season)
                rows = self._get(url, {"X-Fantasy-Filter": json.dumps(
                    {"filterIds": {"value": chunk}})})
            except Exception:
                continue
            for p in rows or []:
                self.names[p["id"]] = {
                    "name": p.get("fullName") or ("Player %d" % p["id"]),
                    "pos": POS.get(p.get("defaultPositionId"), "?"),
                    "team": TEAMS_NFL.get(p.get("proTeamId"), "FA"),
                }

    def poll(self):
        data = self._get(self.league_url(["mDraftDetail", "mTeam"]))

        teams = []
        for t in data.get("teams") or []:
            nm = t.get("name") or " ".join(
                x for x in (t.get("location"), t.get("nickname")) if x).strip()
            teams.append({
                "id": t.get("id"),
                "name": nm or ("Team %s" % t.get("id")),
                "abbrev": t.get("abbrev") or "",
            })

        dd = data.get("draftDetail") or {}
        picks = []
        for p in dd.get("picks") or []:
            picks.append({
                "playerId": p.get("playerId"),
                "teamId": p.get("teamId"),
                "overall": p.get("overallPickNumber"),
                "round": p.get("roundId"),
                "roundPick": p.get("roundPickNumber"),
                "keeper": bool(p.get("keeper")),
            })
        picks = [p for p in picks if p["playerId"] and p["playerId"] > 0]
        picks.sort(key=lambda p: p["overall"] or 0)

        self.resolve_names([p["playerId"] for p in picks])
        complete = bool(dd.get("drafted"))
        if complete:
            status, msg = "complete", "Draft complete"
        elif picks:
            status, msg = "live", ""
        else:
            status, msg = "waiting", "Connected - waiting for the first pick"

        return {
            "ok": True, "status": status, "message": msg,
            "updated": time.time(), "picks": picks, "teams": teams,
            "players": {str(k): v for k, v in self.names.items()},
            "complete": complete,
        }


# ----------------------------------------------------------------- demo driver
class Demo:
    """Fakes a draft so the UI can be exercised without ESPN or cookies."""

    def __init__(self, path):
        self.teams = [{"id": i + 1, "name": n, "abbrev": a} for i, (n, a) in enumerate([
            ("Gridiron Dynasty", "GRID"), ("Sunday Scaries", "SCAR"),
            ("Pylon Pushers", "PYLN"), ("Hurts So Good", "HRTS"),
            ("Nacua Matata", "NACU"), ("Bijan Mustard", "BIJN"),
            ("Chase Money", "CHSE"), ("Puka Chu", "PUKA"),
            ("Audible Panic", "PANC"), ("Fourth and Long", "4TH"),
        ])]
        d = json.load(open(path))
        self.pool = [p for p in d["players"] if p.get("rank")]
        self.pool.sort(key=lambda p: p["rank"])
        self.picks = []
        self.t0 = time.time()

    def poll(self):
        # one pick roughly every 4 seconds, slightly out of ADP order
        want = min(len(self.pool), int((time.time() - self.t0) // 4))
        while len(self.picks) < want:
            n = len(self.picks)
            window = self.pool[n:n + 4]
            pick = random.choice(window) if window else None
            if not pick:
                break
            self.pool.remove(pick)
            rnd, rp = n // len(self.teams) + 1, n % len(self.teams) + 1
            tid = self.teams[rp - 1]["id"] if rnd % 2 else self.teams[len(self.teams) - rp]["id"]
            self.picks.append({"playerId": pick["id"], "teamId": tid, "overall": n + 1,
                               "round": rnd, "roundPick": rp, "keeper": False})
        names = {str(p["playerId"]): None for p in self.picks}
        by_id = {p["id"]: p for p in json.load(open(os.path.join(HERE, "data.json")))["players"]}
        for k in list(names):
            src = by_id.get(int(k))
            names[k] = {"name": src["name"], "pos": src["pos"], "team": src["team"]} if src \
                else {"name": "Player " + k, "pos": "?", "team": "FA"}
        return {
            "ok": True, "status": "live" if self.picks else "waiting",
            "message": "DEMO MODE - simulated picks, not your real draft",
            "updated": time.time(), "picks": self.picks, "teams": self.teams,
            "players": names, "complete": False,
        }


# ----------------------------------------------------------------- http server
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, *a):
        pass                                   # keep the console quiet

    def _cors(self):
        # The page may be opened straight from disk, whose origin is "null".
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        # Chrome's Private Network Access: a page on a public origin (espn.com)
        # reaching a local address is refused unless we opt in explicitly. This
        # is the header that makes the draft-room bookmarklet possible at all.
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/ingest":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode() or "[]")
            draft_id = None
            if isinstance(payload, dict):
                draft_id = payload.get("draftId")
                rows = payload.get("picks") or []
            else:
                rows = payload
            added = INGEST.add(rows, draft_id) if INGEST else 0
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
        else:
            body = json.dumps({"ok": True, "added": added,
                               "total": len(INGEST.picks) if INGEST else 0}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Sink window: the draft room page can't reach us as a subresource
        # (Chrome blocks HTTPS -> local HTTP for fetch, XHR and images alike),
        # but it CAN navigate a window it opened. The bookmarklet keeps one
        # small window and re-navigates it here with each batch of picks.
        if self.path.split("?")[0] == "/api/news":
            body = json.dumps(NEWS.payload() if NEWS else {"news": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.split("?")[0] == "/api/reset":
            if INGEST:
                INGEST.reset()
            STATE.set(picks=[], teams=[], players={}, status="waiting",
                      message="Reset - waiting for the next draft", updated=time.time())
            body = b'{"ok": true, "reset": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.split("?")[0] in ("/api/ingest", "/api/sink"):
            added, err = 0, ""
            try:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                blob = (q.get("p") or [""])[0]
                did = (q.get("d") or [None])[0]
                if blob:
                    pad = "=" * (-len(blob) % 4)
                    rows = json.loads(base64.urlsafe_b64decode(blob + pad).decode())
                    added = INGEST.add(rows if isinstance(rows, list) else [], did) if INGEST else 0
                elif INGEST:
                    INGEST.add([], did)                 # heartbeat
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, e)
                print("sink ingest failed:", err, file=sys.stderr)

            total = len(INGEST.picks) if INGEST else 0
            last = ""
            if INGEST and INGEST.picks:
                k = sorted(INGEST.picks)[-1]
                p = INGEST.picks[k]
                last = "%s.%02d &middot; %s" % (k[0], k[1], p["_info"]["name"])
            body = ("""<!doctype html><meta charset=utf-8><title>FF Research sink</title>
<style>html,body{margin:0;height:100%%;background:#17181a;color:#e8eaec;
font:600 12px/1.45 -apple-system,'Segoe UI',sans-serif;display:flex;align-items:center;
justify-content:center;text-align:center}b{font-size:22px;display:block;color:#4ade80}
small{color:#9aa3ab;font-weight:500}em{color:#f87171;font-style:normal}</style>
<div><b>%d</b>picks received<br><small>%s</small>%s
<br><small>keep this window open</small></div>""" % (
                total, last or "waiting for the first pick",
                ("<br><em>%s</em>" % err) if err else "")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Added", str(added))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.split("?")[0] == "/api/draft":
            body = json.dumps(merged()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        # Only the static file responses need CORS added here. The /api/*
        # handlers already send it via _cors(), and a second copy makes the
        # response invalid -- browsers reject duplicate Access-Control-Allow-
        # Origin headers, which silently broke every /api/ call made with
        # fetch() rather than a navigation.
        if not self.path.split("?")[0].startswith("/api/"):
            self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()



def merged():
    """What the dashboard sees: the API result, overridden by the draft room
    whenever the room knows about more picks (always, for practice drafts)."""
    base = STATE.get()
    base["version"] = VERSION
    if not INGEST:
        base["source"] = "api"
        return base
    n_per_round = len(base.get("teams") or []) or None
    picks, teams, players, updated = INGEST.snapshot(n_per_round)
    if len(picks) <= len(base.get("picks") or []):
        base["source"] = "api"
        base["roomPicks"] = len(picks)
        return base
    # prefer the league's real team names when the counts line up
    api_teams = base.get("teams") or []
    if len(api_teams) == len(teams):
        for t, a in zip(teams, api_teams):
            t.setdefault("_apiName", a.get("name"))
    out = dict(base)
    out.update({
        "ok": True, "status": "live", "source": "room",
        "draftId": INGEST.draft_id,
        "message": base.get("message") or "",
        "picks": picks, "teams": teams,
        "players": {**(base.get("players") or {}), **players},
        "updated": updated,
        "age": None if not updated else round(time.time() - updated, 1),
    })
    return out


def poll_loop(client, interval):
    fails = 0
    while True:
        try:
            STATE.set(**client.poll())
            fails = 0
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                STATE.set(ok=False, status="auth",
                          message="ESPN rejected the session cookies (HTTP %d). "
                                  "Re-copy espn_s2 and SWID into draft_config.json." % e.code)
            else:
                fails += 1
                STATE.set(ok=False, status="error",
                          message="ESPN returned HTTP %d" % e.code)
        except Exception as e:
            fails += 1
            STATE.set(ok=False, status="error", message="%s: %s" % (type(e).__name__, e))
        # back off a little when things are failing, but never stop trying
        time.sleep(interval * (1 if not fails else min(6, 1 + fails)))



def dump(client):
    """One-shot diagnostic: what did ESPN actually send back?

    Prints structure only -- no cookies, no member ids, no owner names -- so the
    output is safe to paste to someone helping you debug.
    """
    if not isinstance(client, Espn):
        print("--dump needs a real league (not --demo)")
        return
    print("=" * 60)
    print("league %s  season %s  cookies %s"
          % (client.league, client.season, "yes" if client.cookie else "NO"))
    try:
        raw = client._get(client.league_url(["mDraftDetail", "mTeam"]))
    except urllib.error.HTTPError as e:
        print("HTTP %d -- %s" % (e.code, e.reason))
        if e.code in (401, 403):
            print("-> ESPN rejected the cookies. Re-copy espn_s2 and SWID.")
        return
    except Exception as e:
        print("FAILED: %s: %s" % (type(e).__name__, e))
        return

    print("top-level keys:", sorted(raw.keys()))
    teams = raw.get("teams") or []
    print("teams: %d" % len(teams))
    if teams:
        t = teams[0]
        print("  team keys:", sorted(k for k in t.keys() if k not in ("owners", "members")))
        print("  first team parses as: name=%r abbrev=%r" % (
            t.get("name") or " ".join(x for x in (t.get("location"), t.get("nickname")) if x),
            t.get("abbrev")))
    dd = raw.get("draftDetail") or {}
    print("draftDetail keys:", sorted(dd.keys()))
    print("  drafted=%s inProgress=%s" % (dd.get("drafted"), dd.get("inProgress")))
    picks = dd.get("picks") or []
    print("  picks: %d" % len(picks))
    if picks:
        p = {k: v for k, v in picks[0].items() if k not in ("memberId",)}
        print("  first pick raw:", json.dumps(p, sort_keys=True))
    print("-" * 60)
    try:
        parsed = client.poll()
        print("PARSED OK -> status=%s teams=%d picks=%d"
              % (parsed["status"], len(parsed["teams"]), len(parsed["picks"])))
        for pk in parsed["picks"][:5]:
            nm = client.names.get(pk["playerId"], {}).get("name", "?")
            print("   %s.%02d  team %-3s  %s" % (pk["round"], pk["roundPick"] or 0,
                                                 pk["teamId"], nm))
        if not parsed["picks"]:
            print("   (no picks yet -- normal before the draft starts)")
    except Exception as e:
        print("PARSE FAILED: %s: %s" % (type(e).__name__, e))
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", type=int, help="league id (overrides config; use for mocks)")
    ap.add_argument("--season", type=int)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--interval", type=float)
    ap.add_argument("--demo", action="store_true", help="simulate a draft; no ESPN, no cookies")
    ap.add_argument("--room-only", action="store_true",
                    help="don't poll the ESPN API at all -- take picks only from the "
                         "draft-room bookmarklet (the only thing that works for "
                         "practice and mock drafts)")
    ap.add_argument("--dump", action="store_true",
                    help="fetch once, print what ESPN actually returned, and exit "
                         "(safe to share -- no cookies, no owner names)")
    args = ap.parse_args()

    cfg = {}
    if os.path.exists(CONFIG):
        cfg = json.load(open(CONFIG))

    global INGEST, NEWS
    INGEST = Ingest(os.path.join(HERE, "data.json"))
    NEWS = News(os.path.join(HERE, "data.json"))
    threading.Thread(target=news_loop, daemon=True).start()

    season = args.season or cfg.get("season") or 2026
    interval = args.interval or cfg.get("pollInterval") or 5

    if args.room_only:
        STATE.set(ok=True, status="waiting", updated=time.time(),
                  message="Room mode - run the bookmarklet in your ESPN draft room")
        print("ROOM-ONLY MODE - picks come from the draft-room bookmarklet")
        print("Open bookmarklet.txt and follow the two lines at the top.")
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        except OSError as e:
            sys.exit("Port %d is already in use -- a helper is probably running "
                     "already (%s). Nothing to do." % (args.port, e))
        print("Draft helper on http://127.0.0.1:%d" % args.port)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        return

    if args.demo:
        client = Demo(os.path.join(HERE, "data.json"))
        print("DEMO MODE - simulated draft, one pick every ~4s")
    else:
        league = args.league or cfg.get("leagueId")
        if not league:
            sys.exit("No leagueId. Create draft_config.json or pass --league. "
                     "See the docstring at the top of this file.")
        s2, swid = cfg.get("espn_s2"), cfg.get("SWID")
        if not (s2 and swid):
            print("WARNING: no espn_s2/SWID in draft_config.json - this only works "
                  "if the league is public.", file=sys.stderr)
        client = Espn(league, season, s2, swid)
        print("league %s, season %s, polling every %ss" % (league, season, interval))

    if args.dump:
        dump(client)
        return

    threading.Thread(target=poll_loop, args=(client, interval), daemon=True).start()

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        sys.exit("Port %d is already in use -- a helper is probably running "
                 "already (%s). Nothing to do." % (args.port, e))
    print("Draft helper on http://127.0.0.1:%d" % args.port)
    print("Open the dashboard and flip the Live Draft switch. Ctrl-C to stop.")
    print("Practice/mock draft? Also run bookmarklet.txt in the draft room -- "
          "ESPN never writes those picks to the API.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
