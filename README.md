# FF Player Research

ESPN-style fantasy football draft board — 300 players, 2026 season, PPR.
One static page, no build step, no framework.

**Just want to use it?** Open `ff-research-standalone.html`. Everything is
embedded; it works with no server and no internet.

## What it does

Sortable table of the top 300 by ESPN PPR draft rank — headshots, injury tags,
recent news, 2026 projections, 2025 actuals (including true average: points ÷
games actually played), % rostered, and color-coded 0–5 strength-of-schedule
bars. Filter by position (QB / RB / WR / TE / FLX / K / D/ST) or search by
name and team. Click a row for season outlook, news, and weekly game logs.
Select up to 4 players for a side-by-side compare with best values highlighted.

## Files

| File | Purpose |
| --- | --- |
| `ff-research-standalone.html` | Everything in one file — double-click to open |
| `index.html` | The dashboard source (HTML/CSS/JS) — needs a web server |
| `data.json` | The 300-player snapshot |
| `fetch_espn.py` | Refresh stats, projections, ranks, ADP, news, SOS |
| `fetch_gamelogs.py` | Add weekly PPR game logs (2024/2025) |
| `build_standalone.py` | Bundle it all into the standalone file |
| `draft_sync.py` | Live draft helper — feeds the Live Draft switch |
| `install_autostart.sh` | Optional: run the helper at login so it's always up |
| `extension/` | Chrome extension — auto-runs in any ESPN draft room (the easy way) |
| `draft_room_scraper.js` | Draft-room companion (source for the bookmarklet) |
| `bookmarklet_url.txt` | The bookmarklet URL, one line — fallback if you'd rather not install |

## Two ways to run it

**Standalone** — double-click `ff-research-standalone.html`. Data, all 300
headshots and team logos, and the Inter font are embedded in the file.

It stays online-first: with a connection it fetches `data.json`, pulls
headshots from `a.espncdn.com`, and loads Inter from Google Fonts, exactly like
`index.html`. The embedded copies take over per-request, only when a live one
fails — so a served copy stays live and an offline copy still renders
identically.

**Served** — `index.html` needs a web server, since browsers block
`fetch('data.json')` on `file://` URLs:

```bash
npx serve .          # or: python3 -m http.server 8000
```

## Refreshing

```bash
python3 fetch_espn.py         # rewrites data.json in place
python3 fetch_gamelogs.py     # optional: weekly game logs
python3 build_standalone.py   # rebuild the standalone file
```

`build_standalone.py --no-images` gives a ~1 MB file instead of ~2.4 MB, at the
cost of needing a network for photos. Source images cache in `.asset_cache/`
(gitignored), so rebuilds after the first take under a second.

## Live draft

Flip the **Live Draft** switch in the board's toolbar during a draft and every
player who's been taken is struck through and greyed, tagged with the team that
took them and the pick number (`GRID · 1.01`). **Rosters** opens every team's
full board. There's a *Hide drafted* toggle in there if you'd rather see only
who's actually left.

The board can't read a private ESPN league on its own — the draft endpoint needs
the `espn_s2` / `SWID` session cookies, and a browser page can't set cookie
headers on a cross-site fetch. So a small local process does it:

You shouldn't need to start it by hand. **The Desktop app starts it for you** —
it checks whether anything is listening on `127.0.0.1:8787` and launches the
helper detached if not, so double-clicking twice never gives you two of them.

For always-on, install it as a login agent once:

```bash
./install_autostart.sh              # runs at login, restarts if it dies
./install_autostart.sh --uninstall
```

By hand, if you want a console to watch:

```bash
python3 draft_sync.py --room-only   # what you want in practice
python3 draft_sync.py --demo        # simulated draft, no ESPN, no cookies
```

For the real thing, copy `draft_config.example.json` to `draft_config.json` and
fill in your league id plus the cookies (log in to fantasy.espn.com → DevTools →
Application → Cookies → copy `espn_s2` and `SWID`). **`draft_config.json` is
gitignored — it holds live session cookies, don't commit it.** The cookies never
leave the helper process; the page only ever receives picks, team names and
player names.

Leave the helper running during the draft and flip the switch. If it isn't
running, the switch says `helper offline` and the board behaves exactly as it
always does — nothing about the offline dashboard depends on it.

### Practice and mock drafts

ESPN never writes practice or mock draft picks to the league API — verified
directly: mid-practice-draft the league still reports all 144 pick slots with
`playerId: -1` and every roster empty. Those picks exist only inside the draft
room page.

So for those, a second source: something inside the draft room that reads the
pick feed and hands picks to the helper. Same `/api/draft` shape comes out, so
the dashboard has no idea where picks came from. Player names are matched back
to real ESPN ids against `data.json`; anyone outside the top-300 snapshot still
shows up on a roster.

**Install the extension** (`extension/README.txt`, ~30 seconds, once) and every
draft room works automatically from then on. Chrome refuses every request from
an HTTPS page to a local HTTP server — fetch, XHR and images alike — but an
extension service worker with `host_permissions` is exempt, so picks go
straight through.

`bookmarklet_url.txt` is the no-install fallback. It has to open a small "sink"
window and navigate it to smuggle picks past that same restriction, since a page
may navigate a window it opened even when it can't fetch. Keep that window open.

```bash
python3 draft_sync.py --room-only   # don't bother polling the API at all
```

It works in a real draft room too, and usually sees a pick a beat before the
API does — `python3 draft_sync.py` uses whichever source knows about more picks.

Two things to know. The room's pick feed is virtualised — only ~28 picks exist
in the page at a time — so click the bookmarklet **before the draft starts**, or
it will miss the early rounds. And the bookmarklet posts on every cycle even
when nothing new happened, so "synced 3s ago" tracks the room being open rather
than the last pick; a 30-second gap between picks won't read as stale.

The status readout is deliberately loud: it shows how many seconds ago the last
successful sync was, and turns amber once that passes 20 seconds. A draft board
silently showing stale availability is worse than no board at all.

## Data sources

- Stats, projections, ranks, ADP, news — [ESPN Fantasy API](https://fantasy.espn.com/) (public read endpoints)
- Strength of schedule — [FantasyPros 2026 SOS](https://www.fantasypros.com/nfl/strength-of-schedule.php), merged from `sos_map.json`
