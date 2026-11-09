import json
from pathlib import Path

import httpx
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from clean import clean_games, parse_minutes
from scrape import parse_game_log, fetch_game_log
from metrics import summarize, opponent_summary, rolling_points
from analyze import main
from analyze import analyze

ROOT = Path(__file__).parents[1]
SAMPLE = ROOT / "data/sample_game_log.csv"


def raw_sample():
    return pd.read_csv(SAMPLE, dtype=str, keep_default_na=False)


def one_game():
    return raw_sample().iloc[:1].copy()


def test_sample_accounting_and_no_mutation():
    raw = raw_sample()
    before = raw.copy(deep=True)
    result = clean_games(raw)
    assert_frame_equal(raw, before)
    assert result.quality == {
        "input_rows": 22,
        "valid_games": 18,
        "repeated_header": 1,
        "did_not_play": 1,
        "invalid_game": 1,
        "duplicate": 1,
    }
    assert len(result.games) + len(result.rejected) == len(raw)
    assert set(result.rejected.source_row) == {20, 21, 22, 23}


def test_minutes_preserve_seconds():
    assert parse_minutes("29:30") == 29.5
    assert parse_minutes("34:45") == 34.75
    assert parse_minutes("32.4") == 32.4
    assert pd.isna(parse_minutes("12:61"))


def test_nonparticipants_not_zero_stat_games():
    raw = one_game()
    raw.loc[0, "minutes"] = "Did Not Play"
    result = clean_games(raw)
    assert result.games.empty
    assert result.quality["did_not_play"] == 1
    with pytest.raises(ValueError, match="No valid"):
        summarize(result.games)


@pytest.mark.parametrize(
    "column,value",
    [
        ("pts", "-1"),
        ("reb", "1.5"),
        ("minutes", "inf"),
        ("date", "2025-02-30"),
        ("result", "W (0)"),
        ("location", "?"),
        ("ast", "NaN"),
    ],
)
def test_invalid_rows_are_explained(column, value):
    raw = one_game()
    raw.loc[0, column] = value
    result = clean_games(raw)
    assert result.quality["invalid_game"] == 1
    assert result.rejected.iloc[0].rejection_reason == "invalid_game"


def test_schema_and_conflicting_same_date():
    with pytest.raises(ValueError, match="Missing required"):
        clean_games(one_game().drop(columns=["pts"]))
    raw = pd.concat([one_game(), one_game()], ignore_index=True)
    raw.loc[1, "pts"] = "30"
    with pytest.raises(ValueError, match="Conflicting games"):
        clean_games(raw)


def test_aliases_and_column_order_independence():
    raw = one_game().rename(columns={"minutes": "mp", "reb": "trb", "opponent": "opp_id"})
    result = clean_games(raw[list(reversed(raw.columns))])
    assert result.games.iloc[0].minutes == 29.5
    assert result.games.iloc[0].opponent == "BOS"


def test_double_double_includes_steals_and_blocks():
    raw = one_game()
    raw.loc[0, ["pts", "reb", "ast", "stl", "blk"]] = ["8", "2", "3", "10", "10"]
    result = clean_games(raw).games.iloc[0]
    assert result.double_double
    assert not result.triple_double
    assert result.pra == 13 and result.stocks == 20


def test_result_sign_and_neutral_venue():
    raw = one_game()
    raw.loc[0, "location"] = "N"
    raw.loc[0, "result"] = "L (8)"
    game = clean_games(raw).games.iloc[0]
    assert game.margin == -8 and not game.win
    assert game.location == "Neutral"


def test_rolling_window_and_opponent_sample_sizes():
    games = clean_games(raw_sample()).games
    rolling = rolling_points(games.iloc[::-1])
    assert rolling.rolling_points.iloc[:4].isna().all()
    assert rolling.rolling_points.iloc[4] == pytest.approx((18 + 24 + 15 + 31 + 22) / 5)
    by_opponent = opponent_summary(games)
    assert by_opponent.games.sum() == len(games)
    assert (by_opponent.games == 3).all()
    assert summarize(games)["points_per_game"] == 24.5


def html_fixture():
    values = {
        "date_game": "2025-01-02",
        "opp_id": "BOS",
        "game_location": "",
        "game_result": "L (-8)",
        "mp": "29:30",
        "pts": "18",
        "trb": "4",
        "ast": "7",
        "stl": "0",
        "blk": "0",
        "tov": "1",
        "fg3": "2",
    }
    cells = "".join(f'<td data-stat="{key}">{value}</td>' for key, value in values.items())
    return "<table><tbody><tr>" + cells + "</tr></tbody></table>"


@pytest.mark.parametrize("commented", [False, True])
def test_html_parser_handles_commented_tables(commented):
    html = html_fixture()
    if commented:
        html = "<!--" + html + "-->"
    parsed = parse_game_log(html)
    assert clean_games(parsed).games.iloc[0].minutes == 29.5


def test_html_format_drift_fails_clearly():
    with pytest.raises(ValueError, match="found 0"):
        parse_game_log("<html>Access denied</html>")
    with pytest.raises(ValueError, match="found 2"):
        parse_game_log(html_fixture() + html_fixture())


def test_collector_surfaces_403_without_retry():
    calls = []

    def deny(request):
        calls.append(request)
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(deny)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_game_log(
                "https://www.basketball-reference.com/players/c/example/gamelog/2025", client
            )
    assert len(calls) == 1
    with pytest.raises(ValueError, match="HTTPS"):
        fetch_game_log("http://example.com")


def test_report_artifacts_and_html_escaping(tmp_path):
    output = tmp_path / "report"
    audit = analyze(SAMPLE, output, "<script>bad</script>", "synthetic")
    assert audit["summary"]["games"] == 18
    html = (output / "index.html").read_text()
    assert "&lt;script&gt;bad&lt;/script&gt;" in html
    assert "<script>bad</script>" not in html
    assert "SYNTHETIC DEMO" in html
    from bs4 import BeautifulSoup

    document = BeautifulSoup(html, "html.parser")
    assert {tag["id"] for tag in document.select(".plotly-graph-div")} == {
        "game_scatter",
        "opponent_means",
        "scoring_trend",
    }
    assert len(pd.read_csv(output / "rejected_rows.csv")) == 4
    assert len(json.loads((output / "summary.json").read_text())["source_sha256"]) == 64
    with pytest.raises(ValueError, match="not empty"):
        analyze(SAMPLE, output, "Demo", "synthetic")


def test_cli_has_actionable_schema_error(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("date,pts\n2025-01-01,10\n")
    assert (
        main(
            [
                str(bad),
                "--label",
                "Demo",
                "--source-kind",
                "synthetic",
                "--output",
                str(tmp_path / "report"),
            ]
        )
        == 1
    )
    assert "Missing required columns" in capsys.readouterr().err


def test_multiseason_collection_and_pacing():
    from scrape import scrape_seasons

    urls, delays = [], []

    def respond(request):
        urls.append(str(request.url))
        return httpx.Response(200, text=html_fixture())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        frame = scrape_seasons("curryst01", 2023, 2025, client=client, sleep=delays.append)
    assert frame.season.tolist() == [2023, 2024, 2025]
    assert frame.player_id.tolist() == ["curryst01"] * 3
    assert len(urls) == 3 and delays == [3, 3]
    assert urls[-1].endswith("/curryst01/gamelog/2025/")


def test_scrape_failure_does_not_save_partial_data(tmp_path, monkeypatch):
    import scrape

    def broken(*args, **kwargs):
        raise ValueError("Season missing")

    monkeypatch.setattr(scrape, "scrape_seasons", broken)
    target = tmp_path / "partial.csv"
    assert (
        scrape.main(
            ["--player", "curryst01", "--start", "2023", "--end", "2025", "--output", str(target)]
        )
        == 1
    )
    assert not target.exists()


def test_multiseason_http_failure_stops_collection():
    from scrape import scrape_seasons

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=html_fixture()) if len(calls) == 1 else httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            scrape_seasons("curryst01", 2023, 2025, client=client, sleep=lambda _: None)
    assert len(calls) == 2


def test_plotly_opponent_traces_and_reference_line():
    from charts import make_charts

    games = clean_games(raw_sample()).games
    charts = make_charts(games, "Demo Guard", "fg3", 4.5, True)
    scatter = charts["game_scatter"]
    assert {trace.name for trace in scatter.data} == set(games.opponent)
    assert scatter.layout.shapes[0].y0 == 4.5
    assert "SYNTHETIC DEMO" in scatter.layout.title.text
    assert charts["opponent_means"].data[0].text.tolist() == [3] * 6


def test_current_page_selects_regular_season_and_reads_dnp():
    regular = html_fixture().replace("<table>", '<table id="player_game_log_reg">')
    playoffs = html_fixture().replace("<table>", '<table id="player_game_log_post">')
    dnp = '<tr><td data-stat="date">2025-01-03</td><td data-stat="is_starter" colspan="26">Inactive</td></tr>'
    regular = regular.replace("</tbody>", dnp + "</tbody>")
    parsed = parse_game_log(regular + playoffs)
    assert len(parsed) == 2
    result = clean_games(parsed)
    assert result.quality["valid_games"] == 1
    assert result.quality["did_not_play"] == 1


@pytest.mark.parametrize(
    "score,expected",
    [("W, 140-104", 36), ("L, 104-112", -8), ("L, 119-124 (OT)", -5), ("W, 140-138 (2OT)", 2)],
)
def test_current_score_format(score, expected):
    raw = one_game()
    raw.loc[0, "result"] = score
    games = clean_games(raw).games
    assert len(games) == 1
    assert games.iloc[0].margin == expected


def test_score_result_disagreement_rejected():
    raw = one_game()
    raw.loc[0, "result"] = "W, 100-110"
    assert clean_games(raw).quality["invalid_game"] == 1
