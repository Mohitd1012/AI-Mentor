import { useState } from "react";
import { ToolCallView } from "@/store/useChatStore";

interface Props {
  call: ToolCallView;
}

const TOOL_META: Record<string, { emoji: string; label: string }> = {
  search_memory:        { emoji: "🔍", label: "Searching memory" },
  save_memory:          { emoji: "📌", label: "Saving to memory" },
  recall_conversation:  { emoji: "💬", label: "Looking up past conversation" },
  get_screen_context:   { emoji: "👁",  label: "Reading the screen" },
};

export function ToolCallCard({ call }: Props) {
  const [open, setOpen] = useState(false);
  const meta = TOOL_META[call.name] ?? { emoji: "🛠", label: call.name };
  const pending = !call.result;
  const errored = call.result?.is_error === true;

  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen(!open)}
        className={`
          w-full text-left flex items-center gap-2 px-2.5 py-1.5 rounded-lg
          text-[11px] border transition-colors
          ${errored
            ? "bg-red-500/10 border-red-500/30 text-red-300 hover:bg-red-500/15"
            : pending
              ? "bg-amber-500/10 border-amber-500/30 text-amber-300 hover:bg-amber-500/15"
              : "bg-[var(--companion-surface)] border-[var(--companion-border)] text-[var(--companion-muted)] hover:text-[var(--companion-text)]"
          }
        `}
      >
        <span className="shrink-0">{meta.emoji}</span>
        <span className="truncate flex-1">
          {meta.label}
          {pending && <span className="ml-1 opacity-70">…</span>}
          {errored && <span className="ml-1 text-red-400">(failed)</span>}
        </span>
        <span className="shrink-0 opacity-60">
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="mt-1 pl-4 border-l border-[var(--companion-border)]">
          {/* Arguments */}
          {Object.keys(call.arguments).length > 0 && (
            <div className="mt-1">
              <div className="text-[9px] uppercase tracking-wider text-[var(--companion-muted)] mb-0.5">
                Arguments
              </div>
              <pre className="selectable text-[10px] text-[var(--companion-muted)] whitespace-pre-wrap break-words font-mono leading-snug bg-[var(--companion-bg)] rounded px-2 py-1 max-h-32 overflow-y-auto">
                {JSON.stringify(call.arguments, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {call.result && (
            <div className="mt-1.5">
              <div className="text-[9px] uppercase tracking-wider text-[var(--companion-muted)] mb-0.5">
                {call.result.is_error ? "Error" : "Result"}
              </div>
              <pre className="selectable text-[10px] whitespace-pre-wrap break-words font-mono leading-snug bg-[var(--companion-bg)] rounded px-2 py-1 max-h-40 overflow-y-auto
                              text-[var(--companion-text)]/80">
                {call.result.content}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
