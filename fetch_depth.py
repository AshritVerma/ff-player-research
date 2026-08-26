#!/usr/bin/env python3
"""
Build the per-team depth chart block: head coach, offensive coordinator.

Written into data.json as a 32-entry "coaches" map keyed by team abbreviation,
not repeated per player -- the board derives the skill-position depth itself
from the rankings it already has.

ESPN exposes a team's head coach but no coordinators, so the OC comes from
Wikipedia's "List of current NFL offensive coordinators", which is maintained
in-season and is the only structured source I found that carries them.

    python3 fetch_depth.py
"""

import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 Chrome/126.0 Safari/537.36")}
SEASON = 2026

TEAMS = {1:'ATL',2:'BUF',3:'CHI',4:'CIN',5:'CLE',6:'DAL',7:'DEN',8:'DET',9:'GB',10:'TEN',
         11:'IND',12:'KC',13:'LV',14:'LAR',15:'MIA',16:'MIN',17:'NE',18:'NO',19:'NYG',
         20:'NYJ',21:'PHI',22:'ARI',23:'PIT',24:'LAC',25:'SF',26:'SEA',27:'TB',28:'WSH',
         29:'CAR',30:'JAX',33:'BAL',34:'HOU'}

FULL = {
 'Arizona Cardinals':'ARI','Atlanta Falcons':'ATL','Baltimore Ravens':'BAL','Buffalo Bills':'BUF',
 'Carolina Panthers':'CAR','Chicago Bears':'CHI','Cincinnati Bengals':'CIN','Cleveland Browns':'CLE',
 'Dallas Cowboys':'DAL','Denver Broncos':'DEN','Detroit Lions':'DET','Green Bay Packers':'GB',
 'Houston Texans':'HOU','Indianapolis Colts':'IND','Jacksonville Jaguars':'JAX','Kansas City Chiefs':'KC',
 'Las Vegas Raiders':'LV','Los Angeles Chargers':'LAC','Los Angeles Rams':'LAR','Miami Dolphins':'MIA',
 'Minnesota Vikings':'MIN','New England Patriots':'NE','New Orleans Saints':'NO','New York Giants':'NYG',
 'New York Jets':'NYJ','Philadelphia Eagles':'PHI','Pittsburgh Steelers':'PIT','San Francisco 49ers':'SF',
 'Seattle Seahawks':'SEA','Tampa Bay Buccaneers':'TB','Tennessee Titans':'TEN','Washington Commanders':'WSH',
}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read().decode("utf-8", "ignore")


def head_coaches():
    """ESPN: one coach per team, which is the head coach."""
    out = {}
    base = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/%d/teams/%d/coaches"
    for tid, abbr in TEAMS.items():
        try:
            items = json.loads(get(base % (SEASON, tid))).get("items") or []
            if not items:
                continue
            d = json.loads(get(items[0]["$ref"].replace("http://", "https://")))
            name = " ".join(x for x in (d.get("firstName"), d.get("lastName")) if x).strip()
            if name:
                out[abbr] = name
        except Exception as e:
            print("  ! HC %s: %s" % (abbr, e), file=sys.stderr)
    return out


def coordinators():
    """Wikipedia's current-OC list. Rows read: [[Team]] || {{sortname|First|Last}}"""
    out = {}
    try:
        s = get("https://en.wikipedia.org/w/api.php?action=parse&page="
                "List_of_current_NFL_offensive_coordinators&prop=wikitext&format=json&formatversion=2")
        wt = (json.loads(s).get("parse") or {}).get("wikitext") or ""
    except Exception as e:
        print("  ! OC list: %s" % e, file=sys.stderr)
        return out
    for team, first, last in re.findall(
            r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]\s*\|\|\s*\{\{sortname\|([^|}]+)\|([^|}]+)", wt):
        abbr = FULL.get(team.strip())
        if abbr and abbr not in out:
            out[abbr] = ("%s %s" % (first.strip(), last.strip())).strip()
    # some rows spell the name plainly rather than via the sortname template
    for team, name in re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]\s*\|\|\s*\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", wt):
        abbr = FULL.get(team.strip())
        if abbr and abbr not in out:
            out[abbr] = name.strip()
    return out


def main():
    data = json.load(open(DATA))
    print("head coaches...")
    hc = head_coaches()
    print("  got %d" % len(hc))
    print("offensive coordinators...")
    oc = coordinators()
    print("  got %d" % len(oc))

    coaches = {}
    for abbr in sorted(set(TEAMS.values())):
        coaches[abbr] = {"hc": hc.get(abbr), "oc": oc.get(abbr)}
    data["coaches"] = coaches
    json.dump(data, open(DATA, "w"))

    missing_hc = [a for a, v in coaches.items() if not v["hc"]]
    missing_oc = [a for a, v in coaches.items() if not v["oc"]]
    print("saved %s" % DATA)
    print("  teams: %d | missing HC: %s | missing OC: %s"
          % (len(coaches), missing_hc or "none", missing_oc or "none"))


if __name__ == "__main__":
    main()
