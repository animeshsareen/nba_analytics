"""Pure transformations; invalid rows are accounted for, never silently imputed."""

from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

COUNTS = ["pts", "reb", "ast", "stl", "blk", "tov", "fg3"]
REQUIRED = ["date", "opponent", "location", "result", "minutes", *COUNTS]
ALIASES = {
    "date_game": "date",
    "opp_id": "opponent",
    "opp": "opponent",
    "game_location": "location",
    "game_result": "result",
    "mp": "minutes",
    "trb": "reb",
}
DNP = {"did not play", "inactive", "did not dress", "not with team", "player suspended"}


@dataclass
class CleanResult:
    games: pd.DataFrame
    rejected: pd.DataFrame
    quality: dict[str, int]


def parse_minutes(value):
    text = str(value).strip()
    if ":" in text:
        match = re.fullmatch(r"(\d+):(\d{2})", text)
        if not match or int(match[2]) >= 60:
            return np.nan
        return int(match[1]) + int(match[2]) / 60
    try:
        return float(text)
    except ValueError:
        return np.nan


def normalize_result(value):
    text = re.sub(r"\s*\((?:\d+)?OT\)$", "", str(value).strip())
    score = re.fullmatch(r"(W|L),\s*(\d+)\s*[-–]\s*(\d+)", text)
    if score:
        margin = int(score[2]) - int(score[3])
        if margin == 0 or (score[1] == "W") != (margin > 0):
            return ""
        return f"{score[1]} ({margin:+d})"
    return text


def clean_games(raw: pd.DataFrame) -> CleanResult:
    """Clean ONE player's game log. Dates identify games; conflicts raise an error."""
    frame = raw.copy(deep=True)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    frame = frame.rename(columns=ALIASES)
    if frame.columns.duplicated().any():
        raise ValueError("Duplicate columns after alias normalization")
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    frame = frame.reset_index(drop=True)
    original = frame.copy(deep=True)
    reasons = pd.Series("", index=frame.index, dtype="string")
    # Repeated HTML headers and nonparticipation rows never become zero-stat games.
    repeated = frame["date"].astype(str).str.strip().str.lower().isin({"date", "date_game"})
    reasons.loc[repeated] = "repeated_header"
    statuses = frame["minutes"].astype(str).str.strip().str.lower()
    if "reason" in frame:
        statuses = statuses.where(
            ~frame["reason"].astype(str).str.strip().str.lower().isin(DNP),
            frame["reason"].astype(str).str.strip().str.lower(),
        )
    reasons.loc[(reasons == "") & statuses.isin(DNP)] = "did_not_play"
    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
    frame["minutes"] = frame["minutes"].map(parse_minutes)
    for col in COUNTS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["opponent"] = frame["opponent"].fillna("").astype(str).str.strip().str.upper()
    location = frame["location"].fillna("").astype(str).str.strip().str.upper()
    frame["location"] = location.map(
        {
            "": "Home",
            "HOME": "Home",
            "@": "Away",
            "AWAY": "Away",
            "N": "Neutral",
            "NEUTRAL": "Neutral",
        }
    )
    parsed = (
        frame["result"].fillna("").map(normalize_result).str.extract(r"^(W|L)\s*\(([+-]?\d+)\)$")
    )
    frame["win"] = parsed[0].map({"W": True, "L": False})
    margin = pd.to_numeric(parsed[1], errors="coerce")
    # W/L is authoritative for margin sign; tolerate unsigned source margins.
    frame["margin"] = margin.abs().where(parsed[0] == "W", -margin.abs())
    numbers = frame[COUNTS].to_numpy(dtype=float)
    valid_counts = pd.Series(
        (np.isfinite(numbers) & (numbers >= 0) & (numbers == np.floor(numbers))).all(axis=1),
        index=frame.index,
    )
    valid = (
        frame["date"].notna()
        & frame["opponent"].str.fullmatch(r"[A-Z]{2,4}")
        & frame["location"].notna()
        & frame["win"].notna()
        & (frame["margin"] != 0)
        & frame["minutes"].gt(0)
        & np.isfinite(frame["minutes"])
        & valid_counts
    )
    reasons.loc[(reasons == "") & ~valid] = "invalid_game"
    eligible = frame.loc[reasons == ""].copy()
    # Compare normalized values, not unnormalized formatting in the raw result column.
    core = ["date", "opponent", "location", "minutes", "win", "margin", *COUNTS]
    duplicates = eligible.duplicated(subset=core, keep="first")
    reasons.loc[eligible.index[duplicates]] = "duplicate"
    games = eligible.loc[~duplicates, core].sort_values("date").reset_index(drop=True)
    if games["date"].duplicated().any():
        raise ValueError("Conflicting games on the same date; input must contain one player")
    for col in COUNTS:
        games[col] = games[col].astype("int64")
    games["margin"] = games["margin"].astype("int64")
    games["win"] = games["win"].astype(bool)
    games["pra"] = games["pts"] + games["reb"] + games["ast"]
    games["stocks"] = games["stl"] + games["blk"]
    categories = games[["pts", "reb", "ast", "stl", "blk"]].ge(10).sum(axis=1)
    games["double_double"] = categories.ge(2)
    games["triple_double"] = categories.ge(3)
    rejected = original.loc[reasons != ""].copy()
    rejected.insert(0, "source_row", rejected.index + 2)  # CSV header is row 1
    rejected["rejection_reason"] = reasons.loc[rejected.index]
    quality = {
        "input_rows": len(frame),
        "valid_games": len(games),
        **{
            key: int((reasons == key).sum())
            for key in ["repeated_header", "did_not_play", "invalid_game", "duplicate"]
        },
    }
    return CleanResult(games, rejected.reset_index(drop=True), quality)
