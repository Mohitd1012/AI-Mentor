import { create } from "zustand";
import { wsClient, WsStatus } from "@/lib/ws";

export interface ToolCallView {
  call_id: string;
  name: string;
  arguments: Record<string, unknown>;
  /** Filled in when the corresponding tool_result arrives. */
  result?: {
    content: string;
    is_error: boolean;
    details?: Record<string, unknown>;
  };
  round: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  timestamp: number;
  proactive?: {
    trigger: string;
    summary: string;
  };
  toolCalls?: ToolCallView[];
}

interface ChatState {
  messages: Message[];
  wsStatus: WsStatus;
  aiState: "idle" | "thinking" | "speaking";
  currentModel: string;
  addUserMessage: (content: string) => string;
  appendChunk: (id: string, chunk: string, done: boolean) => void;
  /** Pre-create an assistant message for an AI-initiated proactive turn. */
  startProactiveMessage: (id: string, trigger: string, summary: string) => void;
  /** Record a tool call the agent emitted. Attached to the most-recent
   *  assistant message (or the next one if none yet). */
  addToolCall: (call: ToolCallView) => void;
  /** Fill in the result for a previously emitted tool call. */
  addToolResult: (
    call_id: string,
    result: { content: string; is_error: boolean; details?: Record<string, unknown> },
  ) => void;
  setWsStatus: (status: WsStatus) => void;
  setAiState: (state: "idle" | "thinking" | "speaking") => void;
  setModel: (model: string) => void;
  clearMessages: () => void;
  sendMessage: (content: string) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  wsStatus: "disconnected",
  aiState: "idle",
  currentModel: "qwen2.5:3b",

  addUserMessage: (content) => {
    const id = crypto.randomUUID();
    set((s) => ({
      messages: [
        ...s.messages,
        { id, role: "user", content, timestamp: Date.now() },
      ],
    }));
    return id;
  },

  appendChunk: (id, chunk, done) => {
    set((s) => {
      // Dedupe: only update the FIRST match. If duplicate messages exist with
      // the same id (e.g. from a re-delivered proactive_start), we collapse
      // them on first chunk by filtering out subsequent ones.
      const firstIdx = s.messages.findIndex((m) => m.id === id);
      if (firstIdx !== -1) {
        const next = s.messages.filter((m, i) => i === firstIdx || m.id !== id);
        // recompute the new index after filter
        const updatedIdx = next.findIndex((m) => m.id === id);
        const updated = next.slice();
        updated[updatedIdx] = {
          ...updated[updatedIdx],
          content: updated[updatedIdx].content + chunk,
          streaming: !done,
        };
        return { messages: updated };
      }
      // First chunk — create assistant message
      return {
        messages: [
          ...s.messages,
          {
            id,
            role: "assistant",
            content: chunk,
            streaming: !done,
            timestamp: Date.now(),
          },
        ],
      };
    });
  },

  startProactiveMessage: (id, trigger, summary) => {
    set((s) => {
      // Idempotent: if a message with this id already exists (e.g. the
      // server re-delivered proactive_start, or the WS handler was registered
      // twice via dev-mode remount), just refresh its proactive metadata
      // instead of appending a second bubble.
      const idx = s.messages.findIndex((m) => m.id === id);
      if (idx !== -1) {
        const next = s.messages.slice();
        next[idx] = {
          ...next[idx],
          role: "assistant",
          streaming: true,
          proactive: { trigger, summary },
        };
        return { messages: next };
      }
      return {
        messages: [
          ...s.messages,
          {
            id,
            role: "assistant",
            content: "",
            streaming: true,
            timestamp: Date.now(),
            proactive: { trigger, summary },
          },
        ],
      };
    });
  },

  addToolCall: (call) => {
    set((s) => {
      // Find the last assistant message (the agent's in-flight turn).
      // If none, create a stub so tool calls aren't orphaned.
      let lastIdx = -1;
      for (let i = s.messages.length - 1; i >= 0; i--) {
        if (s.messages[i].role === "assistant") { lastIdx = i; break; }
      }
      if (lastIdx === -1) {
        // No assistant message yet — make one to host the calls.
        return {
          messages: [
            ...s.messages,
            {
              id: `agent-${Date.now()}`,
              role: "assistant",
              content: "",
              streaming: true,
              timestamp: Date.now(),
              toolCalls: [call],
            },
          ],
        };
      }
      const updated = s.messages.slice();
      const target = updated[lastIdx];
      updated[lastIdx] = {
        ...target,
        toolCalls: [...(target.toolCalls ?? []), call],
      };
      return { messages: updated };
    });
  },

  addToolResult: (call_id, result) => {
    set((s) => {
      const updated = s.messages.map((m) => {
        if (!m.toolCalls) return m;
        const idx = m.toolCalls.findIndex((c) => c.call_id === call_id);
        if (idx === -1) return m;
        const newCalls = m.toolCalls.slice();
        newCalls[idx] = { ...newCalls[idx], result };
        return { ...m, toolCalls: newCalls };
      });
      return { messages: updated };
    });
  },

  setWsStatus: (wsStatus) => set({ wsStatus }),
  setAiState: (aiState) => set({ aiState }),
  setModel: (currentModel) => set({ currentModel }),
  clearMessages: () => set({ messages: [] }),

  sendMessage: (content) => {
    const id = get().addUserMessage(content);
    // The response will arrive with a new server-generated id
    // We pass our message id so the server can correlate logs
    wsClient.send({
      type: "chat",
      id,
      content,
      model: get().currentModel,
    });
    set({ aiState: "thinking" });
  },
}));
