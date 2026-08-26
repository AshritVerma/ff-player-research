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
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
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
        p["age"] = None if not p.get("updated") else round(time.time() - p["updated"], 1)
        return p


STATE = State()


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

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/api/draft":
            body = json.dumps(STATE.get()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        if self.path.split("?")[0] != "/api/draft":
            self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


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
    ap.add_argument("--dump", action="store_true",
                    help="fetch once, print what ESPN actually returned, and exit "
                         "(safe to share -- no cookies, no owner names)")
    args = ap.parse_args()

    cfg = {}
    if os.path.exists(CONFIG):
        cfg = json.load(open(CONFIG))

    season = args.season or cfg.get("season") or 2026
    interval = args.interval or cfg.get("pollInterval") or 5

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

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("Draft helper on http://127.0.0.1:%d" % args.port)
    print("Open the dashboard and flip the Live Draft switch. Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
