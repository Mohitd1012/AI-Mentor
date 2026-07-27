import { create } from "zustand";
import { wsClient } from "@/lib/ws";

type VoiceMode  = "off" | "push_to_talk" | "always_listening";
type VoiceState = "idle" | "listening" | "transcribing" | "speaking";

interface VoiceStore {
  voiceMode: VoiceMode;
  voiceState: VoiceState;
  lastTranscript: string;
  setVoiceMode: (mode: VoiceMode) => void;
  setVoiceState: (state: VoiceState) => void;
  setTranscript: (text: string) => void;
  pttStart: () => void;
  pttStop: () => void;
}

export const useVoiceStore = create<VoiceStore>((set) => ({
  voiceMode:      "push_to_talk",
  voiceState:     "idle",
  lastTranscript: "",

  setVoiceMode: (mode) => {
    wsClient.send({ type: "set_voice_mode", mode });
    set({ voiceMode: mode });
  },

  setVoiceState: (state) => set({ voiceState: state }),

  setTranscript: (text) => set({ lastTranscript: text }),

  pttStart: () => {
    wsClient.send({ type: "ptt_start" });
    set({ voiceState: "listening" });
  },

  pttStop: () => {
    wsClient.send({ type: "ptt_stop" });
    set({ voiceState: "transcribing" });
  },
}));
