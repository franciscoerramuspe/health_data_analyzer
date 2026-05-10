"""
Materialize the system prompt by filling placeholders in system_prompt.md
with the current schema, summary, and date.

Usage:
    python build_prompt.py            # prints to stdout
    python build_prompt.py --out FILE # writes to file too

The Next.js backend can either shell out to this script once at startup,
or read system_prompt.md + the data files directly and do the substitution
in TypeScript.
"""

import argparse
import json
import os
from datetime import date
from pathlib import Path

DATA_DIR = Path(
    os.environ.get(
        "HEALTH_DATA_DIR",
        "/Users/franciscoerramuspe/Desktop/health_data_analyzer/server/data",
    )
)
SCRIPTS_DIR = Path(__file__).parent


def build() -> str:
    template = (SCRIPTS_DIR / "system_prompt.md").read_text()
    schema   = (DATA_DIR / "schema.md").read_text()
    summary  = json.loads((DATA_DIR / "summary.json").read_text())

    date_range = (f"{summary['date_range']['start']} through "
                  f"{summary['date_range']['end']} "
                  f"({summary['date_range']['total_days']} days, "
                  f"{summary['date_range']['days_with_sleep']} with sleep data)")

    return (template
            .replace("{{DATE_RANGE}}", date_range)
            .replace("{{TODAY}}",      date.today().isoformat())
            .replace("{{SCHEMA_MD}}",  schema)
            .replace("{{SUMMARY_JSON}}", json.dumps(summary, indent=2)))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", help="also write the rendered prompt to this file")
    args = p.parse_args()

    prompt = build()

    if args.out:
        Path(args.out).write_text(prompt)

    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
