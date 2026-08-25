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

## Data sources

- Stats, projections, ranks, ADP, news — [ESPN Fantasy API](https://fantasy.espn.com/) (public read endpoints)
- Strength of schedule — [FantasyPros 2026 SOS](https://www.fantasypros.com/nfl/strength-of-schedule.php), merged from `sos_map.json`
