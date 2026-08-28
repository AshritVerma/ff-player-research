#!/usr/bin/env python3
"""Add Yahoo's draft ranks to data.json.

Yahoo and ESPN do not agree about the draft board, and drafting on Yahoo while
reading ESPN's order is how you reach for someone who went two rounds ago. So
the board carries both, and the dashboard shows whichever site you are actually
drafting in.

Source: pub-api-ro.fantasysports.yahoo.com. It is the read-only public mirror of
the Fantasy API and needs no OAuth, no cookies and no app registration -- the
authenticated endpoint (fantasysports.yahooapis.com) 401s without a token, which
would have meant a login dance for a number that is public anyway.

`sort=AR` is Yahoo's own draft-board order. We renumber it densely, the same way
Draft RK is derived from ESPN's PPR rank, so the two are directly comparable.

Players Yahoo ranks that ESPN's top 300 leaves out are appended rather than
dropped: on Yahoo they are draftable, and a player missing from the board is a
player you cannot see going.

    python3 fetch_yahoo.py            # update ./data.json in place
    python3 fetch_yahoo.py --count 400
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
BASE = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "Chrome/126.0 Safari/537.36")
PAGE = 25

# Yahoo's abbreviations are title case and differ in a handful of places.
# Yahoo calls a team defence "Rams" / DEF; ESPN calls it "Rams D/ST" / D/ST.
# Matched on team abbreviation instead of name, or every defence duplicates.
POSFIX = {"DEF": "D/ST"}

TEAMFIX = {"WAS": "WSH", "JAC": "JAX", "LA": "LAR", "SD": "LAC", "OAK": "LV",
           "STL": "LAR", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}


def norm_name(n):
    """Same shape as the helper's matcher, so a name that resolves in a draft
    room resolves here too."""
    n = (n or "").lower()
    for junk in (" jr.", " jr", " sr.", " sr", " iii", " ii", " iv", "'", ".", "-"):
        n = n.replace(junk, " " if junk.startswith(" ") else "")
    return " ".join(n.split())


def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(r, timeout=25) as x:
                return json.loads(x.read().decode())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def _flat(node):
    """Yahoo returns each player as a list of dicts and lists of dicts."""
    out = {}
    for chunk in node:
        if isinstance(chunk, list):
            for it in chunk:
                if isinstance(it, dict):
                    out.update(it)
        elif isinstance(chunk, dict):
            out.update(chunk)
    return out


def fetch(count):
    rows, start = [], 0
    while len(rows) < count:
        url = ("%s/game/nfl/players;sort=AR;start=%d;count=%d;out=draft_analysis"
               "?format=json" % (BASE, start, PAGE))
        d = get(url)
        game = d["fantasy_content"]["game"]
        bag = [x for x in game if isinstance(x, dict) and "players" in x]
        if not bag:
            break
        players = bag[0]["players"]
        n = int(players.get("count") or 0)
        if not n:
            break
        for i in range(n):
            f = _flat(players[str(i)]["player"])
            da = {k: v for c in (f.get("draft_analysis") or []) for k, v in c.items()}
            team = (f.get("editorial_team_abbr") or "").upper()
            rows.append({
                "yahooId": f.get("player_id"),
                "name": (f.get("name") or {}).get("full"),
                "pos": POSFIX.get(f.get("display_position"), f.get("display_position")),
                "team": TEAMFIX.get(team, team) or "FA",
                "bye": ((f.get("bye_weeks") or {}).get("week")),
                "avgPick": da.get("average_pick"),
                "pctDrafted": da.get("percent_drafted"),
            })
        start += n
        if n < PAGE:
            break
        time.sleep(0.25)
    return rows[:count]


def main(count=350, path=DATA):
    print("asking Yahoo for its top %d by draft rank..." % count)
    rows = fetch(count)
    print("  got %d" % len(rows))
    if len(rows) < 50:
        sys.exit("too few players came back; leaving data.json alone")

    data = json.load(open(path))
    players = data["players"]
    by_name = {}
    by_dst = {}
    for p in players:
        by_name.setdefault(norm_name(p["name"]), p)
        if p.get("pos") == "D/ST":
            by_dst.setdefault(p["team"].upper(), p)

    matched = added = 0
    for i, r in enumerate(rows, start=1):
        if not r["name"]:
            continue
        p = (by_dst.get(r["team"].upper()) if r["pos"] == "D/ST"
             else by_name.get(norm_name(r["name"])))
        if p is None:
            # Yahoo ranks him, ESPN's 300 does not. He is draftable on Yahoo, so
            # he goes on the board -- with no ESPN id, so no headshot and no
            # ESPN rank, which the renderer already handles.
            p = {"id": -(900000000 + int(r["yahooId"] or i)),
                 "name": r["name"], "team": r["team"], "pos": r["pos"] or "?",
                 "injuryStatus": None, "pctOwned": None, "pctStarted": None,
                 "rank": None, "adp": None, "adpRank": None,
                 "outlook": "", "news": [],
                 "proj26": None, "projAvg26": None, "pts25": None, "avg25": None,
                 "gp25": None, "raw25": {}, "raw26": {}, "sos": None,
                 "yahooOnly": True}
            players.append(p)
            by_name[norm_name(r["name"])] = p
            if p["pos"] == "D/ST":
                by_dst[r["team"].upper()] = p
            added += 1
        else:
            matched += 1
        p["yahooRank"] = i
        p["yahooId"] = r["yahooId"]
        try:
            p["yahooAdp"] = round(float(r["avgPick"]), 1) if r["avgPick"] else None
        except (TypeError, ValueError):
            p["yahooAdp"] = None

    for p in players:
        p.setdefault("yahooRank", None)

    data["yahooUpdated"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(data, open(path, "w"), separators=(",", ":"))
    ranked = sum(1 for p in players if p.get("yahooRank"))
    print("  matched %d, added %d Yahoo-only" % (matched, added))
    print("  %d of %d players now carry a Yahoo rank" % (ranked, len(players)))
    print("wrote %s" % path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=350)
    ap.add_argument("--data", default=DATA)
    a = ap.parse_args()
    main(a.count, a.data)
