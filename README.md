# Player Research — Boys Nation FF Connoisseurs

An ESPN-style fantasy football "Add Players" research dashboard for the 2026 season (PPR scoring), built as a single static page.

## Features

- **300 players** ranked by ESPN PPR draft rank, with headshots, injury tags, and recent news
- **Columns**: RK (ESPN overall PPR rank), Draft RK (rank by ESPN average draft position), 2026 projected FPTS/avg, 2025 FPTS, 2025 true average (total points ÷ games actually played), games played, % rostered, and 2026 strength of schedule
- **Sortable columns** — click any header to toggle ascending/descending
- **Position filters** — QB / RB / WR / TE / FLX (RB+WR+TE) / K / D/ST, plus name/team search
- **Expandable rows** — season outlook and latest news per player
- **Compare mode** — select up to 4 players and view expanded side-by-side stats (fantasy summary, position-specific stat lines, 2025 actuals vs 2026 projections), with best values highlighted
- **SOS bars** — 0–5 strength-of-schedule rating per player position, color-coded

## Data sources

- Player stats, projections, ranks, ADP, and news: [ESPN Fantasy API](https://fantasy.espn.com/) (public read endpoints)
- Strength of schedule: [FantasyPros 2026 SOS](https://www.fantasypros.com/nfl/strength-of-schedule.php) (0–5 per-position ratings), stored in `sos_map.json` format inside `fetch_espn.py`'s merge step

## Files

| File | Purpose |
| --- | --- |
| `index.html` | The entire dashboard (HTML/CSS/JS, no build step) |
| `data.json` | Snapshot of the 300-player dataset |
| `fetch_espn.py` | Refresh script — pulls ESPN data, computes draft ranks, merges SOS, rewrites `data.json` |

## Refreshing the data

```bash
python3 fetch_espn.py
cp /home/user/workspace/ff-dashboard-data.json data.json
```

Then serve the folder with any static file server:

```bash
npx serve .
```
