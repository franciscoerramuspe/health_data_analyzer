"""
Analysis tools the LLM can call to ground its answers in the user's data.

CLI interface — every subcommand prints a JSON result to stdout, so the
Next.js backend can spawn `python tools.py <subcommand> ...` and parse the
output directly.

Tools
-----
1. query           - get a metric's values over a date range, optionally aggregated
2. correlate       - Pearson correlation between two metrics, with optional time lag
3. compare_groups  - compare a metric on days when a journal question was yes vs no
4. find_outliers   - top/bottom N days for a metric
5. raw_records     - return raw rows for a date range (truncated if large)

All commands accept --json (default) and emit results suitable for an LLM tool
result. Errors return {"error": "..."} with exit code 1.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(
    os.environ.get(
        "HEALTH_DATA_DIR",
        "/Users/franciscoerramuspe/Desktop/health_data_analyzer/server/data",
    )
)

MAX_RAW_ROWS = 60   # safety cap on raw_records to keep tool output small


# ---------- shared helpers ---------------------------------------------------

def load_df() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "daily_flat.csv", parse_dates=["date"])
    return df.set_index("date").sort_index()


def slice_dates(df: pd.DataFrame,
                start: str | None,
                end: str | None) -> pd.DataFrame:
    if start:
        df = df[df.index >= pd.to_datetime(start)]
    if end:
        df = df[df.index <= pd.to_datetime(end)]
    return df


def need_col(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        raise ValueError(f"unknown column '{col}'. "
                         f"see schema.md for valid names.")


def to_jsonable(v):
    """Convert numpy / pandas scalars into plain Python types for json."""
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(v) else round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if pd.isna(v):
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


# ---------- tool implementations --------------------------------------------

def tool_query(metric: str,
               start: str | None,
               end: str | None,
               agg: str | None) -> dict:
    """Return a metric's values over a date range, or a single aggregate."""
    df = load_df()
    need_col(df, metric)
    df = slice_dates(df, start, end)
    s = df[metric].dropna()

    if s.empty:
        return {"metric": metric, "n": 0, "values": [],
                "note": "no data in this range"}

    base = {
        "metric": metric,
        "start": str(s.index.min().date()),
        "end":   str(s.index.max().date()),
        "n":     int(len(s)),
    }

    if agg:
        funcs = {"mean": s.mean, "median": s.median, "min": s.min,
                 "max": s.max, "sum": s.sum, "std": s.std}
        if agg not in funcs:
            raise ValueError(f"unknown agg '{agg}'. "
                             f"use one of {list(funcs)}")
        return {**base, "agg": agg, "value": to_jsonable(funcs[agg]())}

    # Full series, but cap the response size
    values = [{"date": str(d.date()), "value": to_jsonable(v)}
              for d, v in s.items()]
    if len(values) > 200:
        # Down-sample to ~200 points: keep evenly-spaced rows
        step = max(1, len(values) // 200)
        values = values[::step]
        base["downsampled"] = True
        base["downsample_step_days"] = step
    return {**base, "values": values}


def tool_correlate(metric_a: str,
                   metric_b: str,
                   lag_days: int,
                   start: str | None,
                   end: str | None) -> dict:
    """Pearson correlation between two metrics, optionally with B lagged.

    lag_days = +1  ->  metric_b on day N+1 vs metric_a on day N
                       (i.e. 'does today's A predict tomorrow's B')
    """
    df = load_df()
    need_col(df, metric_a)
    need_col(df, metric_b)
    df = slice_dates(df, start, end)

    a = df[metric_a]
    b = df[metric_b].shift(-lag_days)
    paired = pd.concat({"a": a, "b": b}, axis=1).dropna()
    if len(paired) < 5:
        return {"error": f"not enough paired observations (n={len(paired)}, "
                         f"need at least 5)"}

    r = paired["a"].corr(paired["b"])
    # rough significance via Fisher transform
    z = math.atanh(r) if abs(r) < 0.9999 else math.copysign(5, r)
    se = 1 / math.sqrt(len(paired) - 3) if len(paired) > 3 else float("inf")
    abs_z = abs(z / se) if se else 0
    significant = abs_z > 1.96  # ~p<0.05

    return {
        "metric_a": metric_a,
        "metric_b": metric_b,
        "lag_days": lag_days,
        "n_pairs": int(len(paired)),
        "pearson_r": round(float(r), 3),
        "approx_significant_at_0.05": bool(significant),
        "interpretation": _interpret_r(r),
    }


def _interpret_r(r: float) -> str:
    a = abs(r)
    if a < 0.1:  strength = "negligible"
    elif a < 0.3: strength = "weak"
    elif a < 0.5: strength = "moderate"
    elif a < 0.7: strength = "strong"
    else: strength = "very strong"
    sign = "positive" if r > 0 else "negative"
    return f"{strength} {sign} association"


def tool_compare_groups(metric: str,
                        journal_question: str,
                        start: str | None,
                        end: str | None) -> dict:
    """Compare a metric on days when a journal question was yes vs no."""
    df = load_df()
    need_col(df, metric)
    need_col(df, journal_question)
    df = slice_dates(df, start, end)

    sub = df[[metric, journal_question]].dropna()
    if sub.empty:
        return {"error": "no overlapping data"}

    yes = sub[sub[journal_question] == True][metric]
    no  = sub[sub[journal_question] == False][metric]

    if len(yes) < 3 or len(no) < 3:
        return {"error": f"too few observations to compare "
                         f"(yes n={len(yes)}, no n={len(no)})"}

    diff = yes.mean() - no.mean()
    pooled_sd = math.sqrt(
        ((len(yes) - 1) * yes.var() + (len(no) - 1) * no.var())
        / (len(yes) + len(no) - 2)
    )
    cohens_d = diff / pooled_sd if pooled_sd else 0

    return {
        "metric": metric,
        "split_by": journal_question,
        "yes": {"n": int(len(yes)), "mean": round(float(yes.mean()), 2),
                "std":  round(float(yes.std()), 2)},
        "no":  {"n": int(len(no)),  "mean": round(float(no.mean()), 2),
                "std":  round(float(no.std()), 2)},
        "mean_difference_yes_minus_no": round(float(diff), 2),
        "cohens_d": round(float(cohens_d), 2),
        "effect_size": _interpret_d(cohens_d),
    }


def _interpret_d(d: float) -> str:
    a = abs(d)
    if a < 0.2: return "negligible"
    if a < 0.5: return "small"
    if a < 0.8: return "medium"
    return "large"


def tool_find_outliers(metric: str,
                       n: int,
                       mode: str,
                       start: str | None,
                       end: str | None) -> dict:
    """Top/bottom N days for a metric."""
    df = load_df()
    need_col(df, metric)
    df = slice_dates(df, start, end)
    s = df[metric].dropna()
    if s.empty:
        return {"error": "no data"}

    out: dict[str, list] = {"metric": metric, "n_per_side": n, "mode": mode}
    if mode in ("top", "both"):
        top = s.nlargest(n)
        out["top"] = [{"date": str(d.date()), "value": to_jsonable(v)}
                      for d, v in top.items()]
    if mode in ("bottom", "both"):
        bot = s.nsmallest(n)
        out["bottom"] = [{"date": str(d.date()), "value": to_jsonable(v)}
                         for d, v in bot.items()]
    out["lifetime_mean"] = to_jsonable(s.mean())
    out["lifetime_std"] = to_jsonable(s.std())
    return out


def tool_raw_records(start: str,
                     end: str,
                     columns: str | None) -> dict:
    """Return raw daily rows for a (small) date range. Capped at MAX_RAW_ROWS."""
    df = load_df()
    df = slice_dates(df, start, end)
    if columns:
        cols = [c.strip() for c in columns.split(",")]
        for c in cols:
            need_col(df, c)
        df = df[cols]
    if df.empty:
        return {"start": start, "end": end, "n": 0, "rows": []}

    truncated = False
    if len(df) > MAX_RAW_ROWS:
        df = df.head(MAX_RAW_ROWS)
        truncated = True

    rows = []
    for date, row in df.iterrows():
        rec = {"date": str(date.date())}
        for col, val in row.items():
            rec[col] = to_jsonable(val)
        rows.append(rec)

    return {"start": start, "end": end, "n": len(rows),
            "truncated": truncated, "max_rows": MAX_RAW_ROWS, "rows": rows}


# ---------- CLI --------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tools",
                                description="LLM-callable analysis tools")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("query", help="get a metric over a date range")
    q.add_argument("--metric", required=True)
    q.add_argument("--start")
    q.add_argument("--end")
    q.add_argument("--agg", help="mean|median|min|max|sum|std")

    c = sub.add_parser("correlate", help="Pearson correlation")
    c.add_argument("--metric-a", required=True, dest="metric_a")
    c.add_argument("--metric-b", required=True, dest="metric_b")
    c.add_argument("--lag-days", type=int, default=0, dest="lag_days")
    c.add_argument("--start")
    c.add_argument("--end")

    g = sub.add_parser("compare_groups",
                       help="metric on yes vs no days for a journal question")
    g.add_argument("--metric", required=True)
    g.add_argument("--journal-question", required=True, dest="journal_question")
    g.add_argument("--start")
    g.add_argument("--end")

    o = sub.add_parser("find_outliers", help="top/bottom days for a metric")
    o.add_argument("--metric", required=True)
    o.add_argument("--n", type=int, default=5)
    o.add_argument("--mode", choices=["top", "bottom", "both"], default="both")
    o.add_argument("--start")
    o.add_argument("--end")

    r = sub.add_parser("raw_records", help="raw rows for a date range")
    r.add_argument("--start", required=True)
    r.add_argument("--end", required=True)
    r.add_argument("--columns", help="comma-separated column names (optional)")

    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.cmd == "query":
            result = tool_query(args.metric, args.start, args.end, args.agg)
        elif args.cmd == "correlate":
            result = tool_correlate(args.metric_a, args.metric_b,
                                    args.lag_days, args.start, args.end)
        elif args.cmd == "compare_groups":
            result = tool_compare_groups(args.metric, args.journal_question,
                                         args.start, args.end)
        elif args.cmd == "find_outliers":
            result = tool_find_outliers(args.metric, args.n, args.mode,
                                        args.start, args.end)
        elif args.cmd == "raw_records":
            result = tool_raw_records(args.start, args.end, args.columns)
        else:
            print(json.dumps({"error": f"unknown command {args.cmd}"}))
            return 1
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}))
        return 1

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
