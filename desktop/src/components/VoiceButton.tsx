import { useState, useEffect, useCallback } from "react";
import { useVoiceStore } from "@/store/useVoiceStore";
import { useChatStore } from "@/store/useChatStore";

/**
 * Mic button — push-to-talk (PTT) or live indicator for always-listening.
 * The voice MODE selector lives in the ModeBar; this is just the trigger.
 */
export function VoiceButton() {
  const { voiceMode, voiceState, pttStart, pttStop } = useVoiceStore();
  const { wsStatus } = useChatStore();
  const [pressing, setPressing] = useState(false);

  const isConnected    = wsStatus === "connected";
  const isListening    = voiceState === "listening";
  const isTranscribing = voiceState === "transcribing";
  const isActive       = pressing || isListening;

  const handleMouseDown = useCallback(() => {
    if (voiceMode !== "push_to_talk" || !isConnected) return;
    setPressing(true);
    pttStart();
  }, [voiceMode, isConnected, pttStart]);

  const handleMouseUp = useCallback(() => {
    if (!pressing) return;
    setPressing(false);
    pttStop();
  }, [pressing, pttStop]);

  useEffect(() => {
    window.addEventListener("mouseup", handleMouseUp);
    return () => window.removeEventListener("mouseup", handleMouseUp);
  }, [handleMouseUp]);

  // Space bar push-to-talk (ignored inside textarea / input)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "TEXTAREA" || tag === "INPUT") return;
      if (e.code === "Space" && voiceMode === "push_to_talk" && isConnected && !pressing) {
        e.preventDefault();
        setPressing(true);
        pttStart();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space" && pressing) {
        e.preventDefault();
        setPressing(false);
        pttStop();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [voiceMode, isConnected, pressing, pttStart, pttStop]);

  if (voiceMode === "off") return null;

  // Common button styles for both PTT and always-listening
  const baseStyles = "relative w-8 h-8 rounded-full flex items-center justify-center transition-all shrink-0 select-none";

  if (voiceMode === "push_to_talk") {
    return (
      <button
        onMouseDown={handleMouseDown}
        disabled={!isConnected}
        title={
          !isConnected     ? "Backend not connected" :
          isTranscribing   ? "Transcribing…" :
                             "Hold to talk (or hold Space)"
        }
        className={`
          ${baseStyles}
          disabled:opacity-30 disabled:cursor-not-allowed
          ${isActive
            ? "bg-red-500 text-white scale-95 shadow-lg shadow-red-500/40"
            : "bg-[var(--companion-surface)] border border-[var(--companion-border)] text-[var(--companion-muted)] hover:border-[var(--companion-accent)] hover:text-[var(--companion-text)]"
          }
        `}
      >
        {isActive && (
          <span className="absolute inset-0 rounded-full bg-red-500 animate-ping opacity-30" />
        )}
        {isTranscribing ? (
          <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
        ) : (
          <MicIcon active={isActive} />
        )}
      </button>
    );
  }

  // always_listening
  return (
    <div
      className={`
        ${baseStyles}
        ${!isConnected
          ? "opacity-30 bg-[var(--companion-surface)] border border-[var(--companion-border)] text-[var(--companion-muted)]"
          : isListening
          ? "bg-red-500 text-white"
          : isTranscribing
          ? "bg-yellow-500 text-white"
          : "bg-[var(--companion-surface)] border border-[var(--companion-border)] text-[var(--companion-muted)]"
        }
      `}
      title={`Microphone: ${voiceState}`}
    >
      {isListening && (
        <span className="absolute inset-0 rounded-full bg-red-500 animate-ping opacity-30" />
      )}
      <MicIcon active={isListening} />
    </div>
  );
}

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
      {active && <circle cx="12" cy="6" r="1.5" fill="currentColor" />}
    </svg>
  );
}
