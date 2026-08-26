#!/usr/bin/env python3
"""Add each player's date of birth to data.json.

We store the DOB rather than the age itself: an age baked into the file is
wrong the day after that player's birthday, and this file gets rebuilt on no
particular schedule. The dashboard does the arithmetic at render time.

ESPN's fantasy player ids are the same athlete ids the core API uses, so this
is a straight lookup. Team defences have no birthday and are skipped.
"""
import json, urllib.request, concurrent.futures as cf, sys

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/athletes/%s"

def dob_for(pid):
    try:
        r = json.load(urllib.request.urlopen(CORE % pid, timeout=15))
        d = r.get("dateOfBirth")
        return (d or "")[:10] or None      # 2002-03-20
    except Exception:
        return None

def main(path="data.json"):
    data = json.load(open(path))
    players = data["players"]
    want = [p for p in players if p["id"] > 0 and p.get("pos") != "D/ST"]
    print("looking up %d birthdays..." % len(want))
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for p, dob in zip(want, ex.map(lambda p: dob_for(p["id"]), want)):
            if dob:
                p["dob"] = dob
    got = sum(1 for p in players if p.get("dob"))
    print("  %d of %d have a birthday" % (got, len(want)))
    missing = [p["name"] for p in want if not p.get("dob")][:8]
    if missing:
        print("  no birthday for: %s" % ", ".join(missing))
    json.dump(data, open(path, "w"), separators=(",", ":"))
    print("wrote %s" % path)

if __name__ == "__main__":
    main(*sys.argv[1:])
