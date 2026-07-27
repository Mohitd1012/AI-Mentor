import { create } from "zustand";
import { wsClient } from "@/lib/ws";

export type ConversationMode = "direct" | "socratic" | "think_aloud";

interface ModeStore {
  mode: ConversationMode;
  proactivity: number;        // 0–4
  lastAction: string | null;  // shown as a tiny badge
  setMode: (m: ConversationMode) => void;
  setProactivity: (n: number) => void;
  setLastAction: (a: string | null) => void;
  interrupt: () => void;
}

export const useModeStore = create<ModeStore>((set) => ({
  mode:        "direct",
  proactivity: 2,
  lastAction:  null,

  setMode: (m) => {
    wsClient.send({ type: "set_conversation_mode", mode: m });
    set({ mode: m });
  },

  setProactivity: (n) => {
    const clamped = Math.max(0, Math.min(4, n));
    wsClient.send({ type: "set_proactivity", level: clamped });
    set({ proactivity: clamped });
  },

  setLastAction: (a) => set({ lastAction: a }),

  interrupt: () => wsClient.send({ type: "interrupt" }),
}));
