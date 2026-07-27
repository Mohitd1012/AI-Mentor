import { useState, useRef, KeyboardEvent } from "react";
import { VoiceButton } from "./VoiceButton";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

/**
 * Unified input row: mic button + auto-growing textarea + send button,
 * all inside one rounded container with a single focus ring.
 */
export function InputRow({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const onInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  };

  return (
    <div className="px-3 pt-2 pb-3">
      <div
        className={`
          flex items-end gap-2 px-2 py-1.5 rounded-2xl
          bg-[var(--companion-surface)] border transition-colors
          ${focused
            ? "border-[var(--companion-accent)]"
            : "border-[var(--companion-border)]"
          }
        `}
      >
        {/* Mic (hidden when voice mode is off) */}
        <div className="flex items-center self-end pb-0.5">
          <VoiceButton />
        </div>

        {/* Textarea — auto-grows up to 120px */}
        <textarea
          ref={textareaRef}
          className="
            selectable flex-1 resize-none bg-transparent border-0 outline-none
            text-sm leading-relaxed text-[var(--companion-text)]
            placeholder-[var(--companion-muted)] py-1.5 min-w-0
          "
          placeholder="Message your mentor…"
          rows={1}
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onInput={onInput}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
        />

        {/* Send */}
        <button
          onClick={submit}
          disabled={!text.trim() || disabled}
          className={`
            w-8 h-8 rounded-full flex items-center justify-center shrink-0 self-end
            transition-all
            ${!text.trim() || disabled
              ? "bg-transparent text-[var(--companion-muted)] opacity-40 cursor-not-allowed"
              : "bg-[var(--companion-accent)] text-white hover:bg-[var(--companion-accent-dim)] active:scale-95 shadow-md shadow-[var(--companion-accent)]/30"
            }
          `}
          aria-label="Send"
          title="Send (Enter)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>

      {/* Subtle hint line */}
      <div className="text-[10px] text-[var(--companion-muted)] mt-1.5 px-2 flex justify-between gap-2">
        <span className="truncate">↵ send  •  Shift+↵ newline</span>
        <span className="truncate text-right">Hold Right ⌘ to talk</span>
      </div>
    </div>
  );
}
