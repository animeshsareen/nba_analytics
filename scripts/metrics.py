"""Descriptive analysis with sample sizes; no forecasts or causal interpretation."""


def summarize(games):
    if games.empty:
        raise ValueError("No valid played games remain")
    return {
        "games": len(games),
        "date_start": games.date.min().date().isoformat(),
        "date_end": games.date.max().date().isoformat(),
        "points_per_game": round(float(games.pts.mean()), 2),
        "rebounds_per_game": round(float(games.reb.mean()), 2),
        "assists_per_game": round(float(games.ast.mean()), 2),
        "minutes_per_game": round(float(games.minutes.mean()), 2),
        "double_doubles": int(games.double_double.sum()),
        "triple_doubles": int(games.triple_double.sum()),
    }


def opponent_summary(games):
    return (
        games.groupby("opponent", as_index=False)
        .agg(
            games=("pts", "size"),
            points_mean=("pts", "mean"),
            points_std=("pts", "std"),
            rebounds_mean=("reb", "mean"),
            assists_mean=("ast", "mean"),
        )
        .sort_values(["points_mean", "opponent"], ascending=[False, True])
        .reset_index(drop=True)
    )


def rolling_points(games, window=5):
    if window < 1:
        raise ValueError("window must be positive")
    ordered = games.sort_values("date").copy()
    ordered["rolling_points"] = ordered.pts.rolling(window, min_periods=window).mean()
    return ordered


def location_summary(games):
    return games.groupby("location", as_index=False).agg(
        games=("pts", "size"), points_mean=("pts", "mean"), minutes_mean=("minutes", "mean")
    )
