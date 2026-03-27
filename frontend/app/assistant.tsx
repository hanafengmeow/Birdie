"use client";

import { useEffect, useRef } from "react";
import { AssistantRuntimeProvider, useThreadRuntime } from "@assistant-ui/react";
import {
  useChatRuntime,
  AssistantChatTransport,
} from "@assistant-ui/react-ai-sdk";
import { Thread } from "@/components/assistant-ui/thread";
import { getBirdieContext, saveConversation, type ChatMessage } from "@/lib/store";
import { BIRDIE_DATA_MARKER_START } from "@/lib/constants";

const transport = new AssistantChatTransport({
  api: "/api/chat",
  body: () => getBirdieContext(),
});

/** Extract plain text from a runtime message, stripping data markers. */
function extractText(msg: { content: ReadonlyArray<{ type: string; text?: string }> }): string {
  const textPart = msg.content.find(
    (p): p is { type: "text"; text: string } => p.type === "text",
  );
  let text = textPart?.text || "";
  // Strip data markers from assistant messages
  if (text.includes(BIRDIE_DATA_MARKER_START)) {
    text = text.split(BIRDIE_DATA_MARKER_START)[0].trim();
  }
  return text;
}

// Inner component that has access to the runtime context
function ThreadWithMessageListener() {
  const runtime = useThreadRuntime();
  const lastSavedCountRef = useRef(0);

  // Save conversation to localStorage on every new message
  useEffect(() => {
    const unsubscribe = runtime.subscribe(() => {
      const messages = runtime.getState().messages;
      if (messages.length === 0 || messages.length === lastSavedCountRef.current) return;

      // Only save when a new message is complete (not while streaming)
      const lastMsg = messages[messages.length - 1];
      if (lastMsg.role === "assistant" && runtime.getState().isRunning) return;

      lastSavedCountRef.current = messages.length;

      const chatMessages: ChatMessage[] = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({
          role: m.role as "user" | "assistant",
          content: extractText(m),
        }))
        .filter((m) => m.content);

      if (chatMessages.length > 0) {
        saveConversation(chatMessages);
        window.dispatchEvent(new Event("birdie_history_updated"));
      }
    });
    return unsubscribe;
  }, [runtime]);

  // Listen for birdie_send_message events (from LocationModal flow)
  useEffect(() => {
    const handler = (e: Event) => {
      const msg = (e as CustomEvent).detail?.message;
      if (msg && runtime) {
        runtime.append({
          role: "user",
          content: [{ type: "text", text: msg }],
        });
      }
    };
    window.addEventListener("birdie_send_message", handler);
    return () => window.removeEventListener("birdie_send_message", handler);
  }, [runtime]);

  // On mount, check if we should load a saved conversation from sessionStorage
  const loadedRef = useRef(false);
  useEffect(() => {
    if (loadedRef.current) return;
    const saved = sessionStorage.getItem("birdie_load_conv");
    if (!saved) return;
    loadedRef.current = true;
    sessionStorage.removeItem("birdie_load_conv");

    try {
      const messages = JSON.parse(saved) as ChatMessage[];
      if (!Array.isArray(messages) || messages.length === 0) return;

      // Append all saved messages to reconstruct the conversation
      for (const msg of messages) {
        runtime.append({
          role: msg.role,
          content: [{ type: "text", text: msg.content }],
        });
      }
      // Set saved count so we don't re-save immediately
      lastSavedCountRef.current = messages.length;
    } catch {
      // Invalid saved data — ignore
    }
  }, [runtime]);

  return <Thread />;
}

export function Assistant() {
  const runtime = useChatRuntime({ transport });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex-1 overflow-hidden">
        <ThreadWithMessageListener />
      </div>
    </AssistantRuntimeProvider>
  );
}
