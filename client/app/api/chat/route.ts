/**
 * POST /api/chat
 * Body: { messages: ChatMessage[] }
 * Returns: { text: string, trace: ToolTrace[] }
 *
 * No streaming yet — returns the final answer once the tool-use loop
 * completes. Streaming is in Step 8 polish.
 */

import { NextRequest, NextResponse } from "next/server";
import { chat, type ChatMessage } from "@/lib/gemini";

export const runtime = "nodejs"; // we spawn child processes, not Edge

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const messages: ChatMessage[] = body?.messages;

    if (!Array.isArray(messages) || messages.length === 0) {
      return NextResponse.json(
        { error: "messages must be a non-empty array" },
        { status: 400 },
      );
    }

    const result = await chat(messages);
    return NextResponse.json(result);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("/api/chat error:", e);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
