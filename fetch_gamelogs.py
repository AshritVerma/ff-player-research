"""Fetch weekly PPR game logs (2025 + 2024) for all players in data.json."""
import json, os, urllib.request, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

TEAMS = {0:'FA',1:'ATL',2:'BUF',3:'CHI',4:'CIN',5:'CLE',6:'DAL',7:'DEN',8:'DET',9:'GB',10:'TEN',11:'IND',12:'KC',13:'LV',14:'LAR',15:'MIA',16:'MIN',17:'NE',18:'NO',19:'NYG',20:'NYJ',21:'PHI',22:'ARI',23:'PIT',24:'LAC',25:'SF',26:'SEA',27:'TB',28:'WSH',29:'CAR',30:'JAX',33:'BAL',34:'HOU'}

def get(url, headers=None):
    h = dict(UA)
    if headers: h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return json.load(urllib.request.urlopen(req, timeout=30))

def schedules(season):
    """team -> week -> (opp abbrev, is_home)"""
    d = get(f"{BASE}/{season}?view=proTeamSchedules_wl")
    out = {}
    for t in d["settings"]["proTeams"]:
        tid = t["id"]
        for wk, games in (t.get("proGamesByScoringPeriod") or {}).items():
            for g in games:
                h, a = g["homeProTeamId"], g["awayProTeamId"]
                if tid == h: out.setdefault(tid, {})[int(wk)] = (TEAMS.get(a,'?'), True)
                elif tid == a: out.setdefault(tid, {})[int(wk)] = (TEAMS.get(h,'?'), False)
    return out

def weekly(season, ids):
    f = {"players": {"filterIds": {"value": ids},
         "filterStatsForTopScoringPeriodIds": {"value": 18, "additionalValue": [f"00{season}", f"10{season}"]}}}
    d = get(f"{BASE}/{season}/segments/0/leaguedefaults/3?view=kona_playercard",
            {"X-Fantasy-Filter": json.dumps(f)})
    out = {}
    for w in d.get("players", []):
        p = w.get("player") or {}
        rows = []
        for s in p.get("stats", []):
            if s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 1 and s.get("seasonId") == season:
                rows.append({"w": s["scoringPeriodId"], "pts": round(s.get("appliedTotal", 0), 1),
                             "tm": s.get("proTeamId", 0)})
        rows.sort(key=lambda r: r["w"])
        out[p["id"]] = rows
    return out

def main():
    data = json.load(open(DATA))
    ids = [p["id"] for p in data["players"]]
    for season, key in ((2025, "g25"), (2024, "g24")):
        sched = schedules(season)
        logs = {}
        for i in range(0, len(ids), 50):
            logs.update(weekly(season, ids[i:i+50]))
            time.sleep(0.4)
        for p in data["players"]:
            rows = logs.get(p["id"], [])
            out = []
            for r in rows:
                opp = sched.get(r["tm"], {}).get(r["w"])
                out.append([r["w"], r["pts"], (("" if opp[1] else "@") + opp[0]) if opp else ""])
            p[key] = out
        print(season, "logs:", sum(1 for p in data["players"] if p[key]))
    json.dump(data, open(DATA, "w"))
    print("saved")

if __name__ == "__main__":
    main()
