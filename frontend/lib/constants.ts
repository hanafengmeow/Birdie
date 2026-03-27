// Streaming protocol markers — must match backend/agents/birdie_agent.py
export const BIRDIE_DATA_MARKER_START = "__BIRDIE_DATA_START__";
export const BIRDIE_DATA_MARKER_END = "__BIRDIE_DATA_END__";

// localStorage keys
export const PLAN_CONTEXT_KEY = "birdie_plan_context";
export const LANGUAGE_KEY = "birdie_language";
export const CHAT_HISTORY_KEY = "birdie_chat_history";

// Chat history
export const MAX_HISTORY_ENTRIES = 20;
export const HISTORY_TITLE_MAX_LENGTH = 40;

// API
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
