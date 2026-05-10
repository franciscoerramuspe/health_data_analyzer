/**
 * Loads the system prompt by reading the template + summary + schema and
 * filling placeholders. Cached at module init so we don't hit disk on every
 * request. Set FORCE_RELOAD_PROMPT=1 in dev to rebuild on each request.
 */

import fs from "node:fs";
import path from "node:path";

const SERVER_DIR = path.resolve(process.cwd(), "..", "server");
const DATA_DIR = path.join(SERVER_DIR, "data");

let cached: string | null = null;

export function getSystemPrompt(): string {
  if (cached && !process.env.FORCE_RELOAD_PROMPT) return cached;

  const template = fs.readFileSync(
    path.join(SERVER_DIR, "system_prompt.md"),
    "utf-8",
  );
  const schema = fs.readFileSync(path.join(DATA_DIR, "schema.md"), "utf-8");
  const summary = JSON.parse(
    fs.readFileSync(path.join(DATA_DIR, "summary.json"), "utf-8"),
  );

  const dr = summary.date_range;
  const dateRange =
    `${dr.start} through ${dr.end} ` +
    `(${dr.total_days} days, ${dr.days_with_sleep} with sleep data)`;

  const today = new Date().toISOString().slice(0, 10);

  cached = template
    .replace("{{DATE_RANGE}}", dateRange)
    .replace("{{TODAY}}", today)
    .replace("{{SCHEMA_MD}}", schema)
    .replace("{{SUMMARY_JSON}}", JSON.stringify(summary, null, 2));

  return cached;
}
