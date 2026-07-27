import { useVoiceStore } from "@/store/useVoiceStore";
import { Popover } from "./Popover";

type Mode = "off" | "push_to_talk" | "always_listening";

const MODES: Record<Mode, { icon: string; label: string; hint: string }> = {
  off:              { icon: "🔇", label: "Off",       hint: "Microphone disabled" },
  push_to_talk:     { icon: "🎙",  label: "PTT",       hint: "Hold Space (or the mic button) to talk" },
  always_listening: { icon: "👂", label: "Always",    hint: "VAD-gated continuous listening" },
};

export function VoiceModePicker() {
  const { voiceMode, setVoiceMode } = useVoiceStore();
  const active = MODES[voiceMode as Mode];

  return (
    <Popover
      align="start"
      panelWidth={220}
      trigger={({ ref, onClick, "aria-expanded": expanded }) => (
        <button
          ref={ref}
          onClick={onClick}
          aria-expanded={expanded}
          className="
            text-xs bg-[var(--companion-surface)] border border-[var(--companion-border)]
            text-[var(--companion-text)] rounded-md px-1.5 py-0.5
            hover:border-[var(--companion-accent)] focus:outline-none
            flex items-center gap-1 shrink-0
          "
          title={`Voice: ${active.label} — ${active.hint}`}
        >
          <span className="text-sm leading-none">{active.icon}</span>
          <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="3" className="shrink-0 opacity-60">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
      )}
    >
      <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-[var(--companion-muted)]">
        Voice input
      </div>
      {(Object.keys(MODES) as Mode[]).map((m) => {
        const meta = MODES[m];
        const isActive = m === voiceMode;
        return (
          <button
            key={m}
            onClick={() => setVoiceMode(m)}
            className={`
              w-full text-left px-3 py-1.5 text-xs transition-colors
              ${isActive
                ? "bg-[var(--companion-accent)]/20 text-[var(--companion-text)]"
                : "text-[var(--companion-muted)] hover:bg-[var(--companion-surface)] hover:text-[var(--companion-text)]"
              }
            `}
          >
            <div className="flex items-center gap-2">
              <span className="text-base leading-none">{meta.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="text-[var(--companion-text)] font-medium">
                  {isActive && "✓ "}{meta.label}
                </div>
                <div className="text-[10px] text-[var(--companion-muted)] leading-tight">
                  {meta.hint}
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </Popover>
  );
}
