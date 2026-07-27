import { Popover } from "./Popover";
import { useModeStore, ConversationMode } from "@/store/useModeStore";

const MODES: Record<ConversationMode, { icon: string; label: string; hint: string }> = {
  direct:      { icon: "💬", label: "Direct",   hint: "Just answer" },
  socratic:    { icon: "🤔", label: "Socratic", hint: "Ask back / challenge" },
  think_aloud: { icon: "🪞", label: "Mirror",   hint: "Mirror & coach" },
};

export function ModePicker() {
  const { mode, setMode } = useModeStore();
  const active = MODES[mode];

  return (
    <Popover
      align="start"
      panelWidth={200}
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
          title={`Mode: ${active.label} — ${active.hint}`}
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
        Conversation mode
      </div>
      {(Object.keys(MODES) as ConversationMode[]).map((m) => {
        const meta = MODES[m];
        const isActive = m === mode;
        return (
          <button
            key={m}
            onClick={() => setMode(m)}
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
