/**
 * Tool-use loop for Gemini: given a chat history, run generateContent;
 * if the model returns function calls, execute them, append the results,
 * and call again. Repeat until the model returns plain text or we hit a
 * safety cap on iterations.
 */

import { GoogleGenAI } from "@google/genai";
import { functionDeclarations, runTool } from "./tools";
import { getSystemPrompt } from "./prompt";

const MODEL = process.env.GEMINI_MODEL || "gemini-3.1-flash-lite";
const MAX_TOOL_TURNS = 6;

let client: GoogleGenAI | null = null;
function getClient(): GoogleGenAI {
  if (!client) {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      throw new Error(
        "GEMINI_API_KEY is not set. Add it to client/.env.local " +
          "(or copy from the project root .env).",
      );
    }
    client = new GoogleGenAI({ apiKey });
  }
  return client;
}

export type ChatMessage = {
  role: "user" | "model";
  text: string;
};

// Gemini-shaped content (with parts). We build this from the simpler
// ChatMessage[] the client sends, plus tool-call records we accumulate.
type Content = {
  role: "user" | "model";
  parts: Array<
    | { text: string }
    | { functionCall: { name: string; args: Record<string, unknown> } }
    | {
        functionResponse: {
          name: string;
          response: { result?: unknown; error?: string };
        };
      }
  >;
};

export type ToolTrace = {
  name: string;
  args: Record<string, unknown>;
  result: unknown;
};

export async function chat(
  history: ChatMessage[],
): Promise<{ text: string; trace: ToolTrace[] }> {
  const ai = getClient();
  const systemInstruction = getSystemPrompt();

  const contents: Content[] = history.map((m) => ({
    role: m.role,
    parts: [{ text: m.text }],
  }));

  const trace: ToolTrace[] = [];

  for (let turn = 0; turn < MAX_TOOL_TURNS; turn++) {
    const response = await ai.models.generateContent({
      model: MODEL,
      contents,
      config: {
        systemInstruction,
        tools: [{ functionDeclarations }],
      },
    });

    // The SDK exposes a `functionCalls` accessor when the model decides
    // to call a tool. Otherwise we read the text and return.
    const calls = response.functionCalls ?? [];
    if (calls.length === 0) {
      const text = response.text ?? "";
      return { text, trace };
    }

    // CRITICAL: append the model's actual response content unchanged.
    // Gemini 3.x embeds a `thoughtSignature` on the first functionCall part
    // that MUST be passed back verbatim, or the next call returns 400.
    // The SDK handles this for us as long as we append the original content
    // object instead of reconstructing the parts from `calls`.
    const modelContent = response.candidates?.[0]?.content;
    if (modelContent) {
      contents.push(modelContent as Content);
    } else {
      contents.push({
        role: "model",
        parts: calls.map((fc) => ({
          functionCall: {
            name: fc.name as string,
            args: (fc.args ?? {}) as Record<string, unknown>,
          },
        })),
      });
    }

    // Execute each call, append a single user-role content with all the
    // function responses, in the same order.
    const responseParts: Content["parts"] = [];
    for (const fc of calls) {
      const name = fc.name as string;
      const args = (fc.args ?? {}) as Record<string, unknown>;
      const result = await runTool(name, args);
      trace.push({ name, args, result });
      responseParts.push({
        functionResponse: {
          name,
          response:
            typeof result === "object" && result !== null && "error" in result
              ? { error: String((result as { error: unknown }).error) }
              : { result },
        },
      });
    }
    contents.push({ role: "user", parts: responseParts });
  }

  return {
    text:
      "(Reached max tool-call iterations without a final answer. " +
      "Try rephrasing your question.)",
    trace,
  };
}
