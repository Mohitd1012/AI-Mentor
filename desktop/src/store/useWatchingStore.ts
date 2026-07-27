import { create } from "zustand";

interface WatchingState {
  app:          string | null;
  contentType:  string | null;
  file:         string | null;
  isBlank:      boolean;
  lastUpdate:   number;      // unix ms, for "stale" detection
  agentMode:    boolean;
  setWatching:  (info: { app?: string | null; contentType?: string | null;
                          file?: string | null; isBlank?: boolean }) => void;
  setAgentMode: (enabled: boolean) => void;
}

export const useWatchingStore = create<WatchingState>((set) => ({
  app:         null,
  contentType: null,
  file:        null,
  isBlank:     false,
  lastUpdate:  0,
  agentMode:   false,

  setWatching: (info) =>
    set({
      app:         info.app ?? null,
      contentType: info.contentType ?? null,
      file:        info.file ?? null,
      isBlank:     info.isBlank ?? false,
      lastUpdate:  Date.now(),
    }),

  setAgentMode: (enabled) => set({ agentMode: enabled }),
}));
