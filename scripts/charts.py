"""Interactive Plotly charts, preserving the original notebook's exploration workflow."""

import math
import plotly.express as px
from metrics import rolling_points

STATS = ["pts", "reb", "ast", "stl", "blk", "tov", "fg3", "pra", "stocks"]


def make_charts(games, label, stat="pts", line=None, synthetic=False):
    if stat not in STATS:
        raise ValueError(f"stat must be one of {STATS}")
    if line is not None and not math.isfinite(line):
        raise ValueError("reference line must be finite")
    prefix = "SYNTHETIC DEMO · " if synthetic else ""
    title = prefix + label
    scatter = px.scatter(
        games,
        x="date",
        y=stat,
        color="opponent",
        hover_data=["minutes", "location", "pts", "reb", "ast"],
        title=f"{title} — {stat} by game",
        template="plotly_white",
    )
    if line is not None:
        scatter.add_hline(y=line, line_dash="dash", annotation_text=f"Reference: {line:g}")
    scatter.update_traces(marker={"size": 10})
    grouped = games.groupby("opponent", as_index=False).agg(
        average=(stat, "mean"), games=(stat, "size")
    )
    grouped = grouped.sort_values("average", ascending=False)
    opponents = px.bar(
        grouped,
        x="opponent",
        y="average",
        hover_data=["games"],
        text="games",
        title=f"{title} — mean {stat} by opponent",
        labels={"average": f"Mean {stat}"},
        template="plotly_white",
    )
    opponents.update_traces(texttemplate="n=%{text}", textposition="outside")
    trend = rolling_points(games)
    rolling = px.line(
        trend,
        x="date",
        y=["pts", "rolling_points"],
        title=f"{title} — points and trailing 5-game mean",
        template="plotly_white",
    )
    for fig in [scatter, opponents, rolling]:
        fig.update_layout(
            height=460,
            margin={"t": 85},
            legend_title_text="",
            font={"family": "Arial, sans-serif", "size": 14},
        )
    return {"game_scatter": scatter, "opponent_means": opponents, "scoring_trend": rolling}
