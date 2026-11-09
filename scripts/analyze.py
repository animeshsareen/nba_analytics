"""Clean game logs and write an interactive Plotly report with CSV audit outputs."""

import argparse
import hashlib
import html
import json
from pathlib import Path
import sys
import pandas as pd
from charts import make_charts, STATS
from clean import clean_games
from metrics import summarize, opponent_summary


def analyze(source, output, label, source_kind, stat="pts", line=None):
    source, output = Path(source), Path(output)
    if source_kind not in {"synthetic", "user"}:
        raise ValueError("source_kind must be synthetic or user")
    raw = pd.read_csv(source, dtype=str, keep_default_na=False)
    if "player_id" in raw and raw.player_id.nunique() != 1:
        raise ValueError("Input must contain exactly one player")
    result = clean_games(raw)
    summary = summarize(result.games)
    charts = make_charts(result.games, label, stat, line, source_kind == "synthetic")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty; choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    result.games.to_csv(output / "clean_games.csv", index=False, date_format="%Y-%m-%d")
    result.rejected.to_csv(output / "rejected_rows.csv", index=False)
    opponent_summary(result.games).to_csv(output / "opponent_summary.csv", index=False)
    metadata = {
        "label": label,
        "source_kind": source_kind,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "quality": result.quality,
        "summary": summary,
        "stat": stat,
        "reference_line": line,
    }
    (output / "summary.json").write_text(json.dumps(metadata, indent=2) + "\n")
    plots = []
    for i, (name, figure) in enumerate(charts.items()):
        plots.append(
            figure.to_html(
                full_html=False,
                include_plotlyjs=True if i == 0 else False,
                div_id=name,
                config={"responsive": True, "displaylogo": False},
            )
        )
    disclosure = (
        "SYNTHETIC DEMO — invented data, not an actual NBA player or season."
        if source_kind == "synthetic"
        else "Analysis of user-provided player game logs."
    )
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(label)} · NBA Analytics</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;color:#18304b;max-width:1150px;margin:40px auto;padding:0 20px}}h1{{font-size:36px}}.notice{{background:#edf4ff;padding:14px}}a{{color:#1262c4}}</style>
</head><body><h1>{html.escape(label)}</h1><p class="notice">{disclosure}</p>
<p>{summary["games"]} played games · {summary["points_per_game"]} points/game · {summary["assists_per_game"]} assists/game</p>
<p>Click an opponent in the legend to hide it; double-click to isolate it. Hover for details, drag to zoom, and double-click the plot to reset.</p>
{"".join(plots)}
<h2>Data quality</h2><pre>{html.escape(json.dumps(result.quality, indent=2))}</pre>
<p><a href="clean_games.csv">Clean games</a> · <a href="rejected_rows.csv">Excluded rows</a> · <a href="opponent_summary.csv">Opponent summary</a> · <a href="summary.json">Run manifest</a></p>
<p>Opponent means describe this sample and are not causal effects. The trailing average includes the current game and starts at game five. Reference lines are visual guides, not predictions. The report bundles Plotly and works offline.</p>
</body></html>"""
    (output / "index.html").write_text(page, encoding="utf-8")
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Analyze player logs with interactive Plotly charts"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--source-kind", choices=["synthetic", "user"], required=True)
    parser.add_argument("--stat", choices=STATS, default="pts")
    parser.add_argument("--line", type=float, help="Optional horizontal reference line")
    args = parser.parse_args(argv)
    try:
        result = analyze(
            args.input, args.output, args.label, args.source_kind, args.stat, args.line
        )
        print(
            json.dumps({"report": str(args.output / "index.html"), **result["quality"]}, indent=2)
        )
        return 0
    except (ValueError, OSError) as exc:
        print(f"analyze: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
