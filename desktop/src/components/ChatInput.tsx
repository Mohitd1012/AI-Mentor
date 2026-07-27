import { useState, useRef, KeyboardEvent } from "react";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
  hideBorder?: boolean;
}

export function ChatInput({ onSend, disabled, hideBorder }: Props) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Don't intercept Space — it's used for PTT
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
    <div className={`flex items-end gap-2 py-2 ${hideBorder ? "" : "px-3 border-t border-[var(--companion-border)]"}`}>
      <textarea
        ref={textareaRef}
        className="
          selectable flex-1 resize-none rounded-xl px-3 py-2 text-sm
          bg-[var(--companion-surface)] border border-[var(--companion-border)]
          text-[var(--companion-text)] placeholder-[var(--companion-muted)]
          focus:outline-none focus:border-[var(--companion-accent)]
          transition-colors leading-relaxed
        "
        placeholder="Ask anything… (Enter to send)"
        rows={1}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onInput={onInput}
      />
      <button
        onClick={submit}
        disabled={!text.trim() || disabled}
        className="
          w-9 h-9 rounded-xl flex items-center justify-center shrink-0
          bg-[var(--companion-accent)] text-white
          disabled:opacity-30 disabled:cursor-not-allowed
          hover:bg-[var(--companion-accent-dim)] active:scale-95
          transition-all
        "
        aria-label="Send"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="22" y1="2" x2="11" y2="13" />
          <polygon points="22 2 15 22 11 13 2 9 22 2" />
        </svg>
      </button>
    </div>
  );
}
