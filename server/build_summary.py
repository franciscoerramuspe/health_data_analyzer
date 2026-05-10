"""
Pre-compute an "always-on" summary the LLM can read at the start of every
chat without burning tokens parsing the whole CSV.

Output: data/summary.json

What it contains
----------------
- date_range: coverage span and how many days actually have sleep data
- metrics: for every numeric column, the lifetime mean/SD plus rolling stats
  for the last 7 / 30 / 90 days, a trend direction over the last 30 days,
  and how the most recent week compares to the lifetime baseline (in σ)
- journal_yes_rates: how often each journal question is answered "yes"
- workouts: totals, per-activity counts, average per week
"""

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(
    os.environ.get(
        "HEALTH_DATA_DIR",
        "/Users/franciscoerramuspe/Desktop/health_data_analyzer/server/data",
    )
)

# Metrics to summarize. (name, "higher_is_better" | "lower_is_better" | None)
NUMERIC_METRICS = [
    ("recovery_pct",          "higher"),
    ("hrv_ms",                "higher"),
    ("rhr_bpm",               "lower"),
    ("respiratory_rate",      None),
    ("skin_temp_c",           None),
    ("spo2_pct",              "higher"),
    ("day_strain",            None),
    ("energy_kcal",           None),
    ("sleep_performance_pct", "higher"),
    ("asleep_min",            "higher"),
    ("in_bed_min",            None),
    ("light_sleep_min",       None),
    ("deep_sleep_min",        "higher"),
    ("rem_min",               "higher"),
    ("awake_min",             "lower"),
    ("sleep_efficiency_pct",  "higher"),
    ("sleep_consistency_pct", "higher"),
    ("sleep_debt_min",        "lower"),
    ("workout_total_min",     None),
    ("workout_total_strain",  None),
]

JOURNAL_COLS = [
    "jq_alcohol", "jq_caffeine", "jq_dark_room", "jq_injury",
    "jq_late_food", "jq_read_in_bed", "jq_screen_in_bed",
    "jq_shared_bed", "jq_sick", "jq_sleep_meds",
]


def stats(series: pd.Series) -> dict | None:
    s = series.dropna()
    if s.empty:
        return None
    return {
        "mean":   round(float(s.mean()), 2),
        "median": round(float(s.median()), 2),
        "std":    round(float(s.std()), 2) if len(s) > 1 else None,
        "min":    round(float(s.min()), 2),
        "max":    round(float(s.max()), 2),
        "n":      int(len(s)),
    }


def trend_direction(series: pd.Series, window: int = 30) -> str:
    """Compare the latest value of a rolling mean to its value `window` days
    earlier. Returns 'up', 'down', or 'flat'."""
    s = series.dropna()
    if len(s) < window * 2:
        return "insufficient_data"
    rolling = s.rolling(window).mean().dropna()
    if len(rolling) < 2:
        return "insufficient_data"
    recent = rolling.iloc[-1]
    older  = rolling.iloc[-min(window, len(rolling))]
    pct_change = (recent - older) / older if older else 0
    if abs(pct_change) < 0.03:
        return "flat"
    return "up" if pct_change > 0 else "down"


def vs_baseline(recent: pd.Series, lifetime: pd.Series) -> str:
    """Express recent mean as a Z-score against lifetime distribution."""
    r = recent.dropna()
    l = lifetime.dropna()
    if r.empty or len(l) < 10 or l.std() == 0:
        return "n/a"
    z = (r.mean() - l.mean()) / l.std()
    if abs(z) < 0.3:
        label = "near baseline"
    elif z > 0:
        label = "above baseline"
    else:
        label = "below baseline"
    return f"{label} ({z:+.2f}σ)"


def summarize_metric(df: pd.DataFrame, col: str, direction: str | None) -> dict:
    series = df[col]
    today = df.index.max()
    last_7  = df[df.index >  today - pd.Timedelta(days=7)][col]
    last_30 = df[df.index >  today - pd.Timedelta(days=30)][col]
    last_90 = df[df.index >  today - pd.Timedelta(days=90)][col]

    out = {
        "lifetime": stats(series),
        "last_7d":  stats(last_7),
        "last_30d": stats(last_30),
        "last_90d": stats(last_90),
        "trend_30d_vs_prior_30d": trend_direction(series, 30),
        "last_7d_vs_lifetime":    vs_baseline(last_7, series),
    }
    if direction:
        out["higher_is_better"] = (direction == "higher")
    return out


def summarize_journal(df: pd.DataFrame) -> dict:
    out = {}
    for col in JOURNAL_COLS:
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if s.empty:
            continue
        yes = int(s.sum())
        out[col] = {
            "yes_rate": round(yes / len(s), 3),
            "yes_count": yes,
            "n_answered": int(len(s)),
        }
    return out


def summarize_workouts(df: pd.DataFrame) -> dict:
    workout_days = int((df["workout_count"] > 0).sum())
    total_workouts = int(df["workout_count"].sum())
    span_days = (df.index.max() - df.index.min()).days + 1
    avg_per_week = round(total_workouts / (span_days / 7), 2)

    # Activities — split the comma-joined string back out
    activities = (
        df["workout_activities"]
        .dropna()
        .str.split(", ")
        .explode()
        .value_counts()
        .head(15)
        .to_dict()
    )
    activities = {k: int(v) for k, v in activities.items()}

    return {
        "total_workouts": total_workouts,
        "workout_days": workout_days,
        "non_workout_days": int((df["workout_count"] == 0).sum()),
        "avg_workouts_per_week": avg_per_week,
        "top_activities": activities,
    }


def main() -> dict:
    df = pd.read_csv(DATA_DIR / "daily_flat.csv", parse_dates=["date"])
    df = df.set_index("date").sort_index()

    summary = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "date_range": {
            "start":             str(df.index.min().date()),
            "end":               str(df.index.max().date()),
            "total_days":        int(len(df)),
            "days_with_sleep":   int(df["asleep_min"].notna().sum()),
            "days_with_workout": int((df["workout_count"] > 0).sum()),
            "days_with_journal": int(df["jq_alcohol"].notna().sum()),
        },
        "metrics": {
            name: summarize_metric(df, name, direction)
            for name, direction in NUMERIC_METRICS
            if name in df.columns
        },
        "journal_yes_rates": summarize_journal(df),
        "workouts": summarize_workouts(df),
    }

    out = DATA_DIR / "summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    size_kb = out.stat().st_size / 1024
    print(f"Wrote summary.json ({size_kb:.1f} KB) -> {out}")
    print(f"Date range: {summary['date_range']['start']} -> {summary['date_range']['end']}")
    print(f"Metrics: {len(summary['metrics'])}")
    print(f"Journal questions: {len(summary['journal_yes_rates'])}")
    print(f"Top activity: {next(iter(summary['workouts']['top_activities']))}")
    return summary


if __name__ == "__main__":
    main()
