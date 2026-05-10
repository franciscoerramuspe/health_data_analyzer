"""
Flatten the four Whoop CSVs into one row-per-date dataframe with named,
typed columns. Output: data/daily_flat.csv

This is the source of truth for the analysis tools the LLM will call.

Date convention
---------------
For physiological cycles, sleeps, and journal entries, `date` is the calendar
date of the Whoop "Cycle start time" — i.e., the evening you went to bed.
So the row labelled 2026-05-09 contains:
  - the sleep that began that evening (and ended on the morning of May 10)
  - the recovery / HRV / RHR computed from that sleep
  - the day strain accumulated during May 9's daytime hours
  - the journal answers logged at that day's check-in.

For workouts, `date` is the calendar date of `Workout start time` — so a
workout that happened on the morning of May 9 is on the May 9 row, even
though it belongs to the previous Whoop cycle (which started May 8 evening).
This matches how a person naturally thinks about "what did I do on May 9".
"""

import os
from pathlib import Path

import pandas as pd

DATA_DIR = Path(
    os.environ.get(
        "HEALTH_DATA_DIR",
        "/Users/franciscoerramuspe/Desktop/health_data_analyzer/server/data",
    )
)

# Journal question text -> short column name
JOURNAL_MAP = {
    "Have an injury or wound?":                  "jq_injury",
    "Have any alcoholic drinks?":                "jq_alcohol",
    "Feeling sick or ill?":                      "jq_sick",
    "Viewed a screen device in bed?":            "jq_screen_in_bed",
    "Shared your bed?":                          "jq_shared_bed",
    "Took prescription sleep medication?":       "jq_sleep_meds",
    "Consumed caffeine?":                        "jq_caffeine",
    "Read (non-screened device) while in bed?":  "jq_read_in_bed",
    "Ate food close to bedtime?":                "jq_late_food",
    "Slept in a dark room?":                     "jq_dark_room",
}

# Physiological-cycle column rename
PHYSIO_RENAME = {
    "Recovery score %":            "recovery_pct",
    "Resting heart rate (bpm)":    "rhr_bpm",
    "Heart rate variability (ms)": "hrv_ms",
    "Skin temp (celsius)":         "skin_temp_c",
    "Blood oxygen %":              "spo2_pct",
    "Day Strain":                  "day_strain",
    "Energy burned (cal)":         "energy_kcal",
    "Max HR (bpm)":                "max_hr",
    "Average HR (bpm)":            "avg_hr",
    "Respiratory rate (rpm)":      "respiratory_rate",
    "Sleep onset":                 "sleep_onset",
    "Wake onset":                  "wake_onset",
    "Sleep performance %":         "sleep_performance_pct",
    "Asleep duration (min)":       "asleep_min",
    "In bed duration (min)":       "in_bed_min",
    "Light sleep duration (min)":  "light_sleep_min",
    "Deep (SWS) duration (min)":   "deep_sleep_min",
    "REM duration (min)":          "rem_min",
    "Awake duration (min)":        "awake_min",
    "Sleep need (min)":            "sleep_need_min",
    "Sleep debt (min)":            "sleep_debt_min",
    "Sleep efficiency %":          "sleep_efficiency_pct",
    "Sleep consistency %":         "sleep_consistency_pct",
}


def to_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date


def build_physio() -> pd.DataFrame:
    """One row per date, holding the canonical daily stats."""
    df = pd.read_csv(DATA_DIR / "physiological_cycles.csv")
    df["date"] = to_date(df["Cycle start time"])
    df = df.dropna(subset=["date"])
    # Some dates have multiple cycles (timezone shifts, partial re-records).
    # Keep the latest cycle per date — typically the one with full data.
    df = df.sort_values("Cycle start time").drop_duplicates("date", keep="last")
    df = df.rename(columns=PHYSIO_RENAME)
    keep = ["date"] + list(PHYSIO_RENAME.values())
    return df[keep].set_index("date")


def build_naps() -> pd.DataFrame:
    """Aggregate naps from sleeps.csv. Main sleep is already in physio."""
    df = pd.read_csv(DATA_DIR / "sleeps.csv")
    df["date"] = to_date(df["Cycle start time"])
    df = df.dropna(subset=["date"])
    naps = df[df["Nap"] == True].copy()
    if naps.empty:
        return pd.DataFrame(index=pd.Index([], name="date"),
                            columns=["nap_count", "nap_total_min"])
    return naps.groupby("date").agg(
        nap_count=("Asleep duration (min)", "size"),
        nap_total_min=("Asleep duration (min)", "sum"),
    )


def build_workouts() -> pd.DataFrame:
    """Aggregate all workouts on a given calendar date."""
    df = pd.read_csv(DATA_DIR / "workouts.csv")
    df["date"] = to_date(df["Workout start time"])
    df = df.dropna(subset=["date"])

    agg = df.groupby("date").agg(
        workout_count=("Duration (min)", "size"),
        workout_total_min=("Duration (min)", "sum"),
        workout_total_strain=("Activity Strain", "sum"),
        workout_total_kcal=("Energy burned (cal)", "sum"),
        workout_max_hr=("Max HR (bpm)", "max"),
        workout_avg_hr=("Average HR (bpm)", "mean"),
    )

    # All activity names that day, comma-separated
    activities = (df.groupby("date")["Activity name"]
                    .apply(lambda s: ", ".join(s))
                    .rename("workout_activities"))

    # Primary activity = the one with the highest strain that day
    primary = (df.sort_values("Activity Strain", ascending=False)
                 .drop_duplicates("date")[["date", "Activity name"]]
                 .set_index("date")
                 .rename(columns={"Activity name": "workout_primary_activity"}))

    return agg.join(activities).join(primary)


def build_journal() -> pd.DataFrame:
    """Pivot journal questions into one boolean column per question."""
    df = pd.read_csv(DATA_DIR / "journal_entries.csv")
    df["date"] = to_date(df["Cycle start time"])
    df = df.dropna(subset=["date"])
    df["short"] = df["Question text"].map(JOURNAL_MAP)
    df = df.dropna(subset=["short"])
    df["yes"] = df["Answered yes"].astype("boolean")
    return df.pivot_table(
        index="date", columns="short", values="yes", aggfunc="first"
    )


def main() -> pd.DataFrame:
    physio   = build_physio()
    naps     = build_naps()
    workouts = build_workouts()
    journal  = build_journal()

    flat = (physio
            .join(naps,     how="outer")
            .join(workouts, how="outer")
            .join(journal,  how="outer")
            .sort_index())
    flat.index.name = "date"

    # Counts: a missing day means "didn't happen", so 0 not NaN
    for col in ("workout_count", "nap_count"):
        if col in flat.columns:
            flat[col] = flat[col].fillna(0).astype(int)

    out = DATA_DIR / "daily_flat.csv"
    flat.to_csv(out)
    print(f"Wrote {len(flat)} rows x {flat.shape[1]} cols -> {out}")
    print(f"Date range: {flat.index.min()} -> {flat.index.max()}")
    print(f"\nColumns ({flat.shape[1]}):")
    for c in flat.columns:
        non_null = flat[c].notna().sum()
        print(f"  {c:30s}  {non_null:4d} non-null ({100*non_null/len(flat):.0f}%)")
    return flat


if __name__ == "__main__":
    main()
