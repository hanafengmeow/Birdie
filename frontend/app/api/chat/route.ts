import { NextRequest } from "next/server";
import { randomUUID } from "crypto";

// Proxy to FastAPI backend.
// Converts FastAPI plain-text stream into AI SDK v6 SSE format.
// Forwards conversation history for multi-turn context.

const DATA_START = "__BIRDIE_DATA_START__";
const MAX_HISTORY_MESSAGES = 20; // 10 turns (user+assistant pairs)

/** Extract text content from a single message (handles both v6 parts and v4 content). */
function extractText(msg: Record<string, unknown>): string {
  // v6 format: { role, parts: [{ type: "text", text: "..." }] }
  const parts = msg.parts as Array<{ type: string; text?: string }> | undefined;
  if (Array.isArray(parts)) {
    const textPart = parts.find((p) => p.type === "text");
    if (textPart?.text) return textPart.text;
  }
  // v4 format: { role, content: string | array }
  if (typeof msg.content === "string") return msg.content;
  if (Array.isArray(msg.content)) {
    const cp = (msg.content as Array<{ type: string; text?: string }>).find(
      (p) => p.type === "text",
    );
    return cp?.text ?? "";
  }
  return "";
}

export async function POST(req: NextRequest) {
  const body = await req.json();

  const messages: Record<string, unknown>[] = body.messages ?? [];
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  const text = lastUser ? extractText(lastUser) : "";

  // Build conversation history from all messages except the last user message.
  // Keep only recent turns to limit token usage.
  const allButLast = messages.slice(0, -1);
  const recentMessages = allButLast.slice(-MAX_HISTORY_MESSAGES);
  const conversationHistory = recentMessages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      role: m.role as string,
      content: extractText(m),
    }))
    .filter((m) => m.content);

  const fastapiUrl =
    process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const upstream = await fetch(`${fastapiUrl}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: text,
      plan_json: body.plan_json ?? null,
      plan_raw_text: body.plan_raw_text ?? null,
      location: body.location ?? null,
      user_language: body.user_language ?? "en",
      conversation_history: conversationHistory.length > 0 ? conversationHistory : null,
    }),
  });

  if (!upstream.ok || !upstream.body) {
    return new Response("upstream error", { status: 502 });
  }

  const encoder = new TextEncoder();
  const partId = randomUUID();

  function sse(obj: Record<string, unknown>): Uint8Array {
    return encoder.encode(`data: ${JSON.stringify(obj)}\n\n`);
  }

  const stream = new ReadableStream({
    async start(controller) {
      controller.enqueue(sse({ type: "start" }));
      controller.enqueue(sse({ type: "start-step" }));
      controller.enqueue(sse({ type: "text-start", id: partId }));

      const reader = upstream.body!.getReader();
      const decoder = new TextDecoder();
      let full = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        full += chunk;

        // Stop streaming text once we see the data marker
        if (full.includes(DATA_START)) continue;

        controller.enqueue(
          sse({ type: "text-delta", id: partId, delta: chunk }),
        );
      }

      // If there's a data block, emit it as a hidden text-delta so
      // the frontend BirdieCards component can parse it from message text.
      const markerIdx = full.indexOf(DATA_START);
      if (markerIdx !== -1) {
        const dataBlock = full.slice(markerIdx);
        controller.enqueue(
          sse({ type: "text-delta", id: partId, delta: dataBlock }),
        );
      }

      controller.enqueue(sse({ type: "text-end", id: partId }));
      controller.enqueue(sse({ type: "finish-step" }));
      controller.enqueue(sse({ type: "finish", finishReason: "stop" }));

      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
