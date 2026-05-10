/**
 * Function declarations Gemini can call, plus the runner that spawns
 * `python server/tools.py <subcommand>` and returns the parsed JSON result.
 *
 * The arg names match server/tools.py CLI exactly. We translate function
 * call args -> CLI flags here.
 */

import { spawn } from "node:child_process";
import path from "node:path";
import { Type, type FunctionDeclaration } from "@google/genai";

const SERVER_DIR = path.resolve(process.cwd(), "..", "server");
const TOOLS_PY = path.join(SERVER_DIR, "tools.py");
const PYTHON = process.env.PYTHON_BIN || "python3";

// ---- Function declarations the model sees -------------------------------

export const functionDeclarations: FunctionDeclaration[] = [
  {
    name: "query",
    description:
      "Get a metric's values over a date range, optionally aggregated. " +
      "Use for 'what's my average X' or 'show X over time' questions.",
    parameters: {
      type: Type.OBJECT,
      properties: {
        metric: {
          type: Type.STRING,
          description: "Column name from schema.md (e.g. 'hrv_ms', 'recovery_pct').",
        },
        start: { type: Type.STRING, description: "Start date YYYY-MM-DD (optional)." },
        end: { type: Type.STRING, description: "End date YYYY-MM-DD (optional)." },
        agg: {
          type: Type.STRING,
          description:
            "Optional aggregation: mean | median | min | max | sum | std. " +
            "Omit to return the time series.",
        },
      },
      required: ["metric"],
    },
  },
  {
    name: "correlate",
    description:
      "Pearson correlation between two metrics, optionally with B lagged. " +
      "lag_days=1 means metric_b on day N+1 vs metric_a on day N — useful " +
      "for 'does today's strain affect tomorrow's recovery'.",
    parameters: {
      type: Type.OBJECT,
      properties: {
        metric_a: { type: Type.STRING },
        metric_b: { type: Type.STRING },
        lag_days: { type: Type.INTEGER, description: "Default 0." },
        start: { type: Type.STRING },
        end: { type: Type.STRING },
      },
      required: ["metric_a", "metric_b"],
    },
  },
  {
    name: "compare_groups",
    description:
      "Compare a metric on days when a journal question was 'yes' vs 'no'. " +
      "Returns means, std, n, mean difference, and Cohen's d effect size.",
    parameters: {
      type: Type.OBJECT,
      properties: {
        metric: { type: Type.STRING },
        journal_question: {
          type: Type.STRING,
          description:
            "A jq_* column name, e.g. 'jq_alcohol', 'jq_caffeine', 'jq_late_food'.",
        },
        start: { type: Type.STRING },
        end: { type: Type.STRING },
      },
      required: ["metric", "journal_question"],
    },
  },
  {
    name: "find_outliers",
    description: "Top/bottom N days for a metric. For 'best/worst day' questions.",
    parameters: {
      type: Type.OBJECT,
      properties: {
        metric: { type: Type.STRING },
        n: { type: Type.INTEGER, description: "Default 5." },
        mode: { type: Type.STRING, description: "'top' | 'bottom' | 'both'. Default 'both'." },
        start: { type: Type.STRING },
        end: { type: Type.STRING },
      },
      required: ["metric"],
    },
  },
  {
    name: "raw_records",
    description:
      "Return raw daily rows for a (small) date range. Capped at 60 rows. " +
      "Use for 'how was last Tuesday' type questions.",
    parameters: {
      type: Type.OBJECT,
      properties: {
        start: { type: Type.STRING, description: "YYYY-MM-DD." },
        end: { type: Type.STRING, description: "YYYY-MM-DD." },
        columns: {
          type: Type.STRING,
          description: "Optional comma-separated column names.",
        },
      },
      required: ["start", "end"],
    },
  },
];

// ---- Runner: arg map -> CLI flags -> JSON --------------------------------

const ARG_TO_FLAG: Record<string, string> = {
  metric_a: "--metric-a",
  metric_b: "--metric-b",
  lag_days: "--lag-days",
  journal_question: "--journal-question",
};

function toFlag(name: string): string {
  return ARG_TO_FLAG[name] || `--${name}`;
}

export async function runTool(
  name: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  const cliArgs: string[] = [name];
  for (const [k, v] of Object.entries(args ?? {})) {
    if (v === undefined || v === null || v === "") continue;
    cliArgs.push(toFlag(k), String(v));
  }

  return new Promise((resolve) => {
    const proc = spawn(PYTHON, [TOOLS_PY, ...cliArgs], {
      cwd: SERVER_DIR,
      env: { ...process.env, HEALTH_DATA_DIR: path.join(SERVER_DIR, "data") },
    });

    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (chunk) => (stdout += chunk));
    proc.stderr.on("data", (chunk) => (stderr += chunk));

    proc.on("close", (code) => {
      if (code !== 0) {
        // tools.py prints {"error": "..."} on failure; try to parse it
        try {
          resolve(JSON.parse(stdout || "{}"));
        } catch {
          resolve({
            error: `tool ${name} failed (exit ${code})`,
            stderr: stderr.slice(0, 500),
          });
        }
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        resolve({
          error: `failed to parse tool output: ${msg}`,
          stdout: stdout.slice(0, 500),
        });
      }
    });

    proc.on("error", (err) =>
      resolve({ error: `failed to spawn python: ${err.message}` }),
    );
  });
}
