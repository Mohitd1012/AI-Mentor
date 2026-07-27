import { Message } from "@/store/useChatStore";
import { ToolCallCard } from "./ToolCallCard";

interface Props {
  message: Message;
}

const PROACTIVE_LABELS: Record<string, { emoji: string; text: string }> = {
  stuck:         { emoji: "⏳", text: "Noticed you've been stuck" },
  error_loop:    { emoji: "⚠️", text: "Repeating error spotted" },
  context_shift: { emoji: "🔀", text: "Context switched" },
  idle:          { emoji: "💭", text: "Checking in" },
};

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const proBadge = message.proactive && PROACTIVE_LABELS[message.proactive.trigger];

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      {!isUser && (
        <div className={`
          w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-bold
          mr-2 mt-0.5 shrink-0
          ${message.proactive
            ? "bg-amber-500 ring-2 ring-amber-300/30"
            : "bg-[var(--companion-accent)]"
          }
        `}>
          {message.proactive ? "✨" : "M"}
        </div>
      )}
      <div className="max-w-[85%] min-w-[180px]">
        {/* Proactive badge — only for AI-initiated messages */}
        {proBadge && (
          <div className="flex items-center gap-1 mb-1 ml-1 text-[10px] text-amber-300/80">
            <span>{proBadge.emoji}</span>
            <span>{proBadge.text}</span>
          </div>
        )}

        {/* Tool calls (collapsible cards) — render ABOVE the prose */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-1">
            {message.toolCalls.map((c) => (
              <ToolCallCard key={c.call_id} call={c} />
            ))}
          </div>
        )}

        {/* Hide the prose bubble entirely when the assistant has only made
            tool calls and produced no text yet — avoids an empty bubble. */}
        {(message.content || isUser || !message.toolCalls?.length || message.streaming) && (
          <div
            className={`
              selectable rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed
              ${isUser
                ? "bg-[var(--companion-accent)] text-white rounded-br-sm"
                : message.proactive
                  ? "bg-amber-500/10 text-[var(--companion-text)] rounded-bl-sm border border-amber-500/30"
                  : "bg-[var(--companion-surface)] text-[var(--companion-text)] rounded-bl-sm border border-[var(--companion-border)]"
              }
            `}
          >
            {message.content && (
              <p className="whitespace-pre-wrap break-words m-0">{message.content}</p>
            )}
            {message.streaming && (
              <span className="inline-flex gap-0.5 ml-1 align-middle">
                <span className="w-1 h-1 rounded-full bg-current opacity-60 animate-bounce [animation-delay:0ms]" />
                <span className="w-1 h-1 rounded-full bg-current opacity-60 animate-bounce [animation-delay:150ms]" />
                <span className="w-1 h-1 rounded-full bg-current opacity-60 animate-bounce [animation-delay:300ms]" />
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
