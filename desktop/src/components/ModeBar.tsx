import { useModeStore } from "@/store/useModeStore";
import { useChatStore } from "@/store/useChatStore";
import { useWatchingStore } from "@/store/useWatchingStore";
import { RolePicker } from "./RolePicker";
import { ModePicker } from "./ModePicker";
import { VoiceModePicker } from "./VoiceModePicker";
import { wsClient } from "@/lib/ws";

const SNOOZE_MINUTES = 15;

const ACTION_BADGES: Record<string, { color: string; emoji: string }> = {
  teach:     { color: "bg-blue-500/20 text-blue-300",     emoji: "📘" },
  ask:       { color: "bg-yellow-500/20 text-yellow-300", emoji: "❓" },
  challenge: { color: "bg-purple-500/20 text-purple-300", emoji: "⚡" },
  summarize: { color: "bg-green-500/20 text-green-300",   emoji: "📋" },
  silent:    { color: "bg-gray-500/20 text-gray-400",     emoji: "🤫" },
};

export function ModeBar() {
  const { proactivity, lastAction, setProactivity, interrupt } = useModeStore();
  const { aiState } = useChatStore();
  const { agentMode } = useWatchingStore();

  const isBusy = aiState === "thinking" || aiState === "speaking";
  const badge = lastAction ? ACTION_BADGES[lastAction] : null;

  const toggleAgentMode = () =>
    wsClient.send({ type: "set_agent_mode", enabled: !agentMode });

  return (
    <div className="
      flex items-center gap-1.5 px-3 py-1.5
      border-b border-[var(--companion-border)] text-xs min-w-0
    ">
      {/* Role picker — primary, takes any leftover space */}
      <div className="min-w-0 flex-1">
        <RolePicker />
      </div>

      <div className="w-px h-4 bg-[var(--companion-border)] shrink-0" />

      <ModePicker />
      <VoiceModePicker />

      {/* Agent Mode — continuous narration toggle */}
      <button
        onClick={toggleAgentMode}
        className={`
          px-1.5 py-0.5 rounded-md shrink-0 text-[10px] font-medium border transition-colors
          ${agentMode
            ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-300"
            : "bg-[var(--companion-surface)] border-[var(--companion-border)] text-[var(--companion-muted)] hover:text-[var(--companion-text)] hover:border-[var(--companion-accent)]"
          }
        `}
        title={
          agentMode
            ? "Agent Mode is ON — AI comments on screen changes (~25s cooldown)"
            : "Agent Mode: continuously watch screen and narrate changes"
        }
      >
        🤖 {agentMode ? "ON" : "Agent"}
      </button>

      {/* Proactivity dots */}
      <div
        className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-md shrink-0
                   bg-[var(--companion-surface)] border border-[var(--companion-border)]"
        title={`Proactivity: ${proactivity}/4`}
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <button
            key={i}
            onClick={() => setProactivity(i)}
            className={`
              w-1.5 h-1.5 rounded-full transition-colors
              ${i <= proactivity ? "bg-[var(--companion-accent)]" : "bg-[var(--companion-border)]"}
            `}
            aria-label={`Set proactivity to ${i}`}
          />
        ))}
      </div>

      {/* Snooze proactive nudges — only meaningful when proactivity ≥ 2 */}
      {proactivity >= 2 && (
        <button
          onClick={() => wsClient.send({
            type: "proactive_snooze",
            seconds: SNOOZE_MINUTES * 60,
          })}
          className="px-1.5 py-0.5 rounded-md shrink-0 text-[10px]
                     bg-[var(--companion-surface)] border border-[var(--companion-border)]
                     text-[var(--companion-muted)] hover:text-[var(--companion-text)]
                     hover:border-[var(--companion-accent)] transition-colors"
          title={`Snooze proactive nudges for ${SNOOZE_MINUTES} minutes`}
        >
          💤
        </button>
      )}

      {/* Action badge — hidden on narrow widths via container query */}
      {badge && (
        <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-medium shrink-0 ${badge.color}`}
              title={`Last action: ${lastAction}`}>
          {badge.emoji}
        </span>
      )}

      {/* Interrupt — only while AI is busy */}
      {isBusy && (
        <button
          onClick={interrupt}
          className="px-1.5 py-0.5 rounded-md bg-red-500/20 border border-red-500/40
                     text-red-300 hover:bg-red-500/30 transition-colors shrink-0"
          title="Stop the AI response"
        >
          ◼
        </button>
      )}
    </div>
  );
}
