import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import { ProviderCard } from "@/components/birdie/ProviderCard";
import { BIRDIE_DATA_MARKER_START, BIRDIE_DATA_MARKER_END } from "@/lib/constants";
import { needsLocation, requestLocation } from "@/lib/location-check";
import {
  ActionBarPrimitive,
  AuiIf,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useMessage,
  useThreadRuntime,
} from "@assistant-ui/react";
import {
  SendIcon,
  CopyIcon,
  CheckIcon,
  RefreshCwIcon,
  SquareIcon,
  BirdIcon,
} from "lucide-react";
import { type FC, useMemo, useCallback } from "react";

// ── Helper: send message, checking location first ────────────

function useSendWithLocationCheck() {
  const runtime = useThreadRuntime();

  return useCallback(
    (text: string) => {
      if (needsLocation(text)) {
        // Always confirm/choose location before searching
        // Page will call runtime.append after location is confirmed
        requestLocation(text);
        return;
      }

      runtime.append({
        role: "user",
        content: [{ type: "text", text }],
      });
    },
    [runtime],
  );
}

// ── Thread ───────────────────────────────────────────────────

export const Thread: FC = () => {
  return (
    <ThreadPrimitive.Root className="aui-root aui-thread-root flex h-full flex-col">
      <ThreadPrimitive.Viewport className="birdie-scroll relative flex flex-1 flex-col overflow-y-auto scroll-smooth px-3 pt-4 pb-2">
        <AuiIf condition={(s) => s.thread.isEmpty}>
          <ThreadWelcome />
        </AuiIf>

        <ThreadPrimitive.Messages>
          {() => <ThreadMessage />}
        </ThreadPrimitive.Messages>

        <ThreadPrimitive.ViewportFooter
          className="sticky bottom-0 mt-auto bg-white pb-3 pt-2"
          style={{ boxShadow: "0 -2px 8px rgba(0,0,0,0.04)" }}
        >
          <Composer />
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);
  if (role === "user") return <UserMessage />;
  return <AssistantMessage />;
};

// ── Empty state ──────────────────────────────────────────────

const ThreadWelcome: FC = () => (
  <div className="flex flex-1 flex-col items-center justify-center pb-8">
    <BirdIcon className="size-10" style={{ color: "var(--b-text-accent)" }} />
    <h2
      className="mt-3 text-lg font-bold"
      style={{ color: "var(--b-text-accent)" }}
    >
      How can I help you today?
    </h2>
    <div className="mt-6 flex w-full max-w-md flex-wrap justify-center gap-2 px-4">
      {SUGGESTIONS.map((text) => (
        <SuggestionChip key={text} text={text} />
      ))}
    </div>
  </div>
);

const SUGGESTIONS = [
  "Find urgent care near me",
  "What\u2019s my copay?",
  "Do I need a referral?",
];

const SuggestionChip: FC<{ text: string }> = ({ text }) => {
  const send = useSendWithLocationCheck();
  return (
    <button className="birdie-chip text-left" onClick={() => send(text)}>
      {text}
    </button>
  );
};

// ── Composer ─────────────────────────────────────────────────

const Composer: FC = () => {
  const runtime = useThreadRuntime();

  return (
    <ComposerPrimitive.Root
      className="flex w-full items-center gap-2 px-1"
      onSubmit={(e) => {
        // Intercept submit to check if location is needed
        const text = runtime.composer.getState().text.trim();
        if (text && needsLocation(text)) {
          e.preventDefault();
          requestLocation(text);
          runtime.composer.setText("");
        }
        // Otherwise let default ComposerPrimitive.Send handle it
      }}
    >
      <ComposerPrimitive.Input
        placeholder="Ask me anything..."
        className="birdie-input flex-1"
        rows={1}
        autoFocus
        aria-label="Message input"
      />
      <AuiIf condition={(s) => !s.thread.isRunning}>
        <ComposerPrimitive.Send className="birdie-send-btn" aria-label="Send">
          <SendIcon className="size-5" />
        </ComposerPrimitive.Send>
      </AuiIf>
      <AuiIf condition={(s) => s.thread.isRunning}>
        <ComposerPrimitive.Cancel className="birdie-send-btn" aria-label="Stop">
          <SquareIcon className="size-3.5 fill-current" />
        </ComposerPrimitive.Cancel>
      </AuiIf>
    </ComposerPrimitive.Root>
  );
};

// ── Typing indicator ─────────────────────────────────────────

const TypingIndicator: FC = () => (
  <div className="flex items-center gap-0.5 py-2 px-1">
    <span className="typing-dot" />
    <span className="typing-dot" />
    <span className="typing-dot" />
  </div>
);

// ── Cleaned markdown (strips data block from display) ────────

const CleanedMarkdownText: FC = () => {
  const message = useMessage();
  const parts = (message?.content ?? []) as Array<{ type: string; text: string }>;
  const hasDataBlock = parts.some(
    (p) => p.type === "text" && p.text?.includes(BIRDIE_DATA_MARKER_START),
  );

  // If no data block, render normally
  if (!hasDataBlock) return <MarkdownText />;

  // Strip data block from display — MarkdownText would show raw JSON
  const fullText = parts
    .filter((p) => p.type === "text")
    .map((p) => p.text)
    .join("");
  const cleanText = fullText.slice(0, fullText.indexOf(BIRDIE_DATA_MARKER_START)).trim();
  if (!cleanText) return null;
  return <div className="whitespace-pre-wrap">{cleanText}</div>;
};

// ── Messages ─────────────────────────────────────────────────

const UserMessage: FC = () => (
  <MessagePrimitive.Root className="flex justify-end py-1" data-role="user">
    <div className="birdie-user-msg animate-slide-up">
      <MessagePrimitive.Parts />
    </div>
  </MessagePrimitive.Root>
);

// ── Birdie data ──────────────────────────────────────────────

interface BirdieData {
  care_router?: Record<string, unknown> | null;
  find_care?: {
    results?: Array<Record<string, unknown>>;
    telehealth_fallback?: boolean;
  } | null;
}

function useBirdieData(): BirdieData | null {
  const message = useMessage();
  return useMemo(() => {
    if (!message || message.role !== "assistant") return null;

    // Check all text parts (v6 uses `content` or `parts`)
    const parts = (message.content ?? (message as Record<string, unknown>).parts ?? []) as Array<{ type: string; text: string }>;
    for (const part of parts) {
      if (
        part.type === "text" &&
        part.text?.includes(BIRDIE_DATA_MARKER_START)
      ) {
        const startIdx = part.text.indexOf(BIRDIE_DATA_MARKER_START);
        const endIdx = part.text.indexOf(BIRDIE_DATA_MARKER_END);
        const jsonStr = endIdx !== -1
          ? part.text.slice(startIdx + BIRDIE_DATA_MARKER_START.length, endIdx)
          : part.text.slice(startIdx + BIRDIE_DATA_MARKER_START.length);
        try {
          return JSON.parse(jsonStr.trim());
        } catch {
          return null;
        }
      }
    }
    return null;
  }, [message]);
}

const BirdieCards: FC = () => {
  const data = useBirdieData();
  if (!data?.find_care?.results?.length) return null;
  return (
    <div className="mt-2">
      {data.find_care.results.map((p, i) => (
        <ProviderCard
          key={`p-${i}`}
          provider={p as Record<string, unknown> & { name: string }}
        />
      ))}
    </div>
  );
};

const AssistantMessage: FC = () => {
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const message = useMessage();
  const parts = (message?.content ?? []) as Array<{ type: string; text: string }>;
  const hasText = parts.some((p) => p.type === "text" && p.text?.trim().length > 0);
  const showTyping = isRunning && !hasText;

  return (
    <MessagePrimitive.Root className="py-1" data-role="assistant">
      <div className="flex items-start gap-2">
        <span
          className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-full"
          style={{ background: "var(--b-bg-light)" }}
        >
          <BirdIcon
            className="size-3.5"
            style={{ color: "var(--b-text-accent)" }}
          />
        </span>
        <div className="min-w-0 flex-1">
          <div className="birdie-assistant-msg animate-slide-up">
            {showTyping ? (
              <TypingIndicator />
            ) : (
              <MessagePrimitive.Parts>
                {({ part }) => {
                  if (part.type === "text") return <CleanedMarkdownText />;
                  return null;
                }}
              </MessagePrimitive.Parts>
            )}
          </div>
          <BirdieCards />
          <MessagePrimitive.Error>
            <ErrorPrimitive.Root
              className="mt-2 rounded-lg border p-3 text-sm"
              style={{
                borderColor: "var(--b-error)",
                background: "rgba(212,104,122,0.06)",
                color: "var(--b-error)",
              }}
            >
              <ErrorPrimitive.Message />
            </ErrorPrimitive.Root>
          </MessagePrimitive.Error>
          <AssistantActions />
        </div>
      </div>
    </MessagePrimitive.Root>
  );
};

const AssistantActions: FC = () => (
  <ActionBarPrimitive.Root
    hideWhenRunning
    autohide="not-last"
    className="mt-1 flex gap-1"
  >
    <ActionBarPrimitive.Copy
      className="inline-flex size-6 items-center justify-center rounded p-1 hover:bg-[var(--b-bg-light)]"
      style={{ color: "var(--b-text-secondary)" }}
    >
      <AuiIf condition={(s) => s.message.isCopied}>
        <CheckIcon className="size-3.5" />
      </AuiIf>
      <AuiIf condition={(s) => !s.message.isCopied}>
        <CopyIcon className="size-3.5" />
      </AuiIf>
    </ActionBarPrimitive.Copy>
    <ActionBarPrimitive.Reload
      className="inline-flex size-6 items-center justify-center rounded p-1 hover:bg-[var(--b-bg-light)]"
      style={{ color: "var(--b-text-secondary)" }}
    >
      <RefreshCwIcon className="size-3.5" />
    </ActionBarPrimitive.Reload>
  </ActionBarPrimitive.Root>
);
