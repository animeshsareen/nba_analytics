"""Multi-season player game-log scraping and saved HTML parsing."""

from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment
import httpx
import pandas as pd
from clean import DNP

# Both legacy and newer data-stat names are mapped explicitly; never by column position.
FIELDS = {
    "date_game": "date",
    "date": "date",
    "opp_id": "opponent",
    "opp_name_abbr": "opponent",
    "game_location": "location",
    "game_result": "result",
    "mp": "minutes",
    "pts": "pts",
    "trb": "reb",
    "ast": "ast",
    "stl": "stl",
    "blk": "blk",
    "tov": "tov",
    "fg3": "fg3",
    "reason": "reason",
}


def parse_game_log(html):
    soup = BeautifulSoup(html, "html.parser")
    candidates = list(soup.find_all("table"))
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        if "<table" in comment:
            candidates.extend(BeautifulSoup(comment, "html.parser").find_all("table"))
    tables = []
    for table in candidates:
        if table.select('[data-stat="pts"]') and (
            table.select('[data-stat="date_game"]') or table.select('[data-stat="date"]')
        ):
            tables.append(table)
    regular = [t for t in tables if t.get("id") in {"player_game_log_reg", "pgl_basic"}]
    if regular:
        tables = regular
    if len(tables) != 1:
        raise ValueError(
            f"Expected one player game-log table; found {len(tables)}. "
            "Choose a single season/table export; the source format may have changed."
        )
    rows = []
    for tr in tables[0].select("tbody tr"):
        if "thead" in tr.get("class", []):
            continue
        row = {
            FIELDS[cell["data-stat"]]: cell.get_text(strip=True)
            for cell in tr.select("[data-stat]")
            if cell["data-stat"] in FIELDS
        }
        for cell in tr.select("td[colspan]"):
            status = cell.get_text(strip=True)
            if status.lower() in DNP:
                row["reason"] = status
                row["minutes"] = status
        if row.get("date"):
            rows.append(row)
    if not rows:
        raise ValueError("Game-log table contains no data rows")
    return pd.DataFrame(rows)


def fetch_game_log(url, client=None):
    """One bounded GET. Never bypasses denial responses or guesses a player ID."""
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.basketball-reference.com", "basketball-reference.com"}
        or not parsed.path.startswith("/players/")
    ):
        raise ValueError("Provide an HTTPS Basketball Reference player game-log URL")
    if client is None:
        with httpx.Client(timeout=20, follow_redirects=False) as owned:
            return fetch_game_log(url, owned)
    response = client.get(url)
    response.raise_for_status()
    return parse_game_log(response.text)


def read_html(path):
    return parse_game_log(Path(path).read_text(encoding="utf-8"))


def scrape_seasons(player_id, start_year, end_year, delay=3, client=None, sleep=None):
    """Collect inclusive season-ending years; abort on any incomplete season."""
    import re
    import time

    if not re.fullmatch(r"[a-z]+\d{2}", player_id):
        raise ValueError("Use the exact player ID from their profile URL, e.g. curryst01")
    if start_year > end_year or start_year < 1947 or end_year > 2100:
        raise ValueError("Use an ascending season range between 1947 and 2100")
    if delay < 3:
        raise ValueError("delay must be at least 3 seconds")
    sleep = sleep or time.sleep
    if client is None:
        with httpx.Client(timeout=20, follow_redirects=False) as owned:
            return scrape_seasons(player_id, start_year, end_year, delay, owned, sleep)
    frames = []
    for year in range(start_year, end_year + 1):
        if frames:
            sleep(delay)
        url = f"https://www.basketball-reference.com/players/{player_id[0]}/{player_id}/gamelog/{year}/"
        frame = fetch_game_log(url, client)
        frame["season"] = year
        frame["player_id"] = player_id
        frame["source_url"] = url
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Scrape one player's multi-season game logs")
    parser.add_argument("--player", help="Exact profile ID, e.g. curryst01")
    parser.add_argument("--start", type=int, help="First season-ending year")
    parser.add_argument("--end", type=int, help="Last season-ending year")
    parser.add_argument("--html", type=Path, help="Alternatively parse a saved single-season page")
    parser.add_argument("--delay", type=float, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("Output exists; choose a new file")
        if args.html:
            if any(x is not None for x in [args.player, args.start, args.end]):
                raise ValueError("Use --html OR --player/--start/--end")
            frame = read_html(args.html)
        else:
            if args.player is None or args.start is None or args.end is None:
                raise ValueError("Provide --player, --start and --end, or --html")
            frame = scrape_seasons(args.player, args.start, args.end, args.delay)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="") as handle:
            frame.to_csv(handle, index=False)
        print(f"Saved {len(frame)} raw rows to {args.output}")
        return 0
    except (ValueError, OSError, httpx.HTTPError) as exc:
        print(f"scrape: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
