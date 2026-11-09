# NBA Analytics

Scrape a player's season game logs, clean them with pandas, and explore performance in interactive Plotly charts.

## Setup

Python 3.11+, from this folder:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 1. Scrape game logs

Use the exact player ID from their Basketball Reference profile URL. For example, Stephen Curry's ID is `curryst01`. Years refer to the **season-ending year**; `2025` means the 2024–25 season.

```bash
python scripts/scrape.py --player curryst01 --start 2023 --end 2025 \
  --output data/local/curry.csv
```

The scraper fetches each requested regular season (excluding the separate playoff table), parses table cells by `data-stat` name, and combines the logs into a CSV with player ID, season, and source URL. It also handles tables embedded in HTML comments. Requests have a timeout and a minimum three-second interval. Any failed season aborts the run rather than saving a silently incomplete dataset.

```bash
python scripts/scrape.py --html data/local/player.html --output data/local/player.csv
```

## 2. Analyze with Plotly

```bash
python scripts/analyze.py data/local/curry.csv --label 'Stephen Curry' \
  --source-kind user --stat fg3 --line 4.5 --output reports/local/curry
```

Open `reports/local/curry/index.html` in your browser. The self-contained report works offline and includes:

- **Game-by-game scatter:** choose a statistic, hover for game details, click opponent legend entries to hide them, double-click to isolate, and drag to zoom. `--line` adds an optional horizontal reference.
- **Opponent averages:** compare means with game counts visible on each bar.
- **Scoring trend:** points alongside a trailing five-game average.

Supported statistics: `pts`, `reb`, `ast`, `stl`, `blk`, `tov`, `fg3`, `pra` (points + rebounds + assists), and `stocks` (steals + blocks). Reference lines are visual guides, not forecasts.

Each run also exports `clean_games.csv`, `rejected_rows.csv`, `opponent_summary.csv`, and `summary.json` with the input hash and cleaning counts. Existing output files/directories are not overwritten; choose a new path to rerun.

## Try it offline

The included CSV is **synthetic**: “Demo Guard” is not a real NBA player. It exercises the full analysis without website access.

```bash
python scripts/analyze.py data/sample_game_log.csv --label 'Demo Guard' \
  --source-kind synthetic --stat pts --line 25 --output reports/local/demo
```

Expected: **22 input rows → 18 played games**, excluding one duplicate, one DNP row, one invalid row, and one repeated header. The synthetic sample averages 24.50 points per game. See the included [interactive example](reports/demo/index.html) by opening it locally; GitHub's file viewer does not execute Plotly HTML.

## Code

```text
README.md
requirements.txt
requirements-dev.txt
scripts/
  scrape.py       multi-season HTTP collection and HTML parsing
  clean.py        validation, exclusions, deduplication, derived statistics
  metrics.py      summaries and trailing averages
  charts.py       interactive Plotly figures
  analyze.py      analysis CLI and self-contained HTML/CSV export
data/
  sample_game_log.csv
  provenance.json
tests/            parsing, cleaning, chart, collection, and report tests
reports/demo/     generated synthetic example
```

## Data and cleaning

Input is one player's CSV with these fields:

| Fields | Format |
|---|---|
| `date`, `opponent` | ISO date; 2–4 letter team abbreviation |
| `location` | Blank/`Home`, `@`/`Away`, or `N`/`Neutral` |
| `result`, `minutes` | `W (+8)` / `L (-8)` or scores such as `W, 140-104` (including OT); `29:30` or decimal minutes |
| `pts`, `reb`, `ast`, `stl`, `blk`, `tov`, `fg3` | Nonnegative integer box-score counts |

Common source aliases (`date_game`, `opp_id`, `mp`, `trb`, etc.) are accepted. The parser uses explicit names rather than column positions. Minutes retain seconds; DNPs do not become zero-stat games. Exclusions retain their source row and reason. Exact normalized duplicates are removed; conflicting same-date games fail clearly. Double/triple-doubles use points, rebounds, assists, steals, and blocks.

The trailing mean includes the current game and starts at game five. Opponent comparisons are descriptive, with no adjustment for minutes, pace, injury, or role. Small samples do not establish an opponent effect or a betting edge. All shipped game data are invented; keep your own authorized data in ignored `data/local/` and outputs in `reports/local/`.

## Test

```bash
pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
```

**31 tests pass** in a fresh environment. Tests use offline fixtures and mocked HTTP: season aggregation, request pacing, failed-season handling, minutes parsing, DNPs, duplicates, five-category double-doubles, rolling windows, and Plotly report output. The [Plotly HTML export documentation](https://plotly.com/python/interactive-html-export/) explains the self-contained chart export used here.
