import { useEffect } from "react";
import { listen, UnlistenFn } from "@tauri-apps/api/event";
import { useVoiceStore } from "@/store/useVoiceStore";

/**
 * Wires the OS-level global hotkey (Ctrl+Shift+Space) to the voice pipeline.
 *
 * On the Rust side, lib.rs registers the shortcut and emits `global-ptt-start`
 * / `global-ptt-stop` events on key press/release. We listen for those here
 * and call into the existing PTT logic — the same path the in-app mic uses.
 *
 * Behavior:
 *   • If voice mode is OFF, the hotkey temporarily flips it to PTT, runs
 *     the capture, and restores the previous mode on release.
 *   • If mode is already PTT, it just runs PTT.
 *   • If always_listening, the hotkey is a no-op (mic is already on).
 */
export function useGlobalPTT() {
  useEffect(() => {
    let unlistenStart: UnlistenFn | null = null;
    let unlistenStop:  UnlistenFn | null = null;
    let restoreMode: string | null = null;

    (async () => {
      unlistenStart = await listen("global-ptt-start", () => {
        const state = useVoiceStore.getState();

        if (state.voiceMode === "always_listening") {
          return; // mic already capturing
        }

        if (state.voiceMode === "off") {
          // Temporarily switch to PTT for this utterance
          restoreMode = "off";
          state.setVoiceMode("push_to_talk");
          // Small delay so the backend acknowledges the mode change first.
          setTimeout(() => useVoiceStore.getState().pttStart(), 80);
          return;
        }

        state.pttStart();
      });

      unlistenStop = await listen("global-ptt-stop", () => {
        const state = useVoiceStore.getState();

        if (state.voiceMode === "always_listening") return;

        state.pttStop();

        if (restoreMode === "off") {
          // Restore mic-off after a brief grace period so the recording finishes
          setTimeout(() => {
            useVoiceStore.getState().setVoiceMode("off");
          }, 250);
          restoreMode = null;
        }
      });
    })();

    return () => {
      unlistenStart?.();
      unlistenStop?.();
    };
  }, []);
}
