"""
Merge Whoop CSVs (journal, physiological cycles, sleeps, workouts) into one
dataset indexed by date, with numbered entry columns per type.

Output schema (one row per date):
    date | workout_entry_1 | workout_entry_2 | ... | sleep_entry_1 | ... | journal_entry_1 | ...

Each *_entry_N cell is a JSON dict containing all the original columns for that
record, so no data is lost.
"""

import json
import pandas as pd

BASE_PATH = "/Users/franciscoerramuspe/Desktop/health_data_analyzer/server/data"

# Map: short name used in column prefix -> (csv filename, column to use as the date)
SOURCES = {
    "journal":       ("journal_entries.csv",     "Cycle start time"),
    "physiological": ("physiological_cycles.csv", "Cycle start time"),
    "sleep":         ("sleeps.csv",               "Cycle start time"),
    "workout":       ("workouts.csv",             "Workout start time"),
}


def load_and_tag(name: str, filename: str, date_col: str) -> pd.DataFrame:
    """Load one CSV, parse its date column, and add a normalized 'date' column."""
    df = pd.read_csv(f"{BASE_PATH}/{filename}")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df["date"] = df[date_col].dt.date           # date only, no time
    return df


def pivot_wide(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """
    Convert a long dataframe (many rows per date) into a wide dataframe
    (one row per date) with columns prefix_entry_1, prefix_entry_2, ...

    Each cell is a JSON string with all the original record's fields.
    """
    # Drop the helper 'date' column from the payload, but keep it for grouping.
    payload_cols = [c for c in df.columns if c != "date"]

    rows = []
    for date, group in df.groupby("date"):
        row = {"date": date}
        # Stable order: by the date column we parsed earlier (first payload col).
        # Fall back to insertion order if sorting fails.
        try:
            group = group.sort_values(payload_cols[0])
        except Exception:
            pass
        for i, (_, record) in enumerate(group.iterrows(), start=1):
            entry = {k: (None if pd.isna(v) else v) for k, v in record[payload_cols].items()}
            # default=str handles datetimes / Timestamps cleanly
            row[f"{prefix}_entry_{i}"] = json.dumps(entry, default=str)
        rows.append(row)

    return pd.DataFrame(rows).set_index("date")


def main() -> pd.DataFrame:
    wide_frames = []
    for name, (filename, date_col) in SOURCES.items():
        df = load_and_tag(name, filename, date_col)
        wide = pivot_wide(df, prefix=name)
        wide_frames.append(wide)
        print(f"{name:14s} {len(df):4d} rows -> {wide.shape[1]:2d} '{name}_entry_*' columns "
              f"across {len(wide)} dates")

    # Outer-join everything on date so a date appears if ANY source has it.
    merged = pd.concat(wide_frames, axis=1).sort_index()
    merged.index.name = "date"

    out_path = f"{BASE_PATH}/merged_by_date.csv"
    merged.to_csv(out_path)
    print(f"\nMerged shape: {merged.shape}")
    print(f"Saved to: {out_path}")
    return merged


if __name__ == "__main__":
    merged = main()
    print("\nFirst 3 dates, column names only:")
    print(list(merged.columns))
    print("\nSample row (most recent date):")
    print(merged.tail(1).T)
