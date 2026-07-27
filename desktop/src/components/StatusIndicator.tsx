import { WsStatus } from "@/lib/ws";
import { useWatchingStore } from "@/store/useWatchingStore";
import { useEffect, useState } from "react";

interface Props {
  wsStatus: WsStatus;
  aiState: "idle" | "thinking" | "speaking";
  model: string;
}

const STATUS_COLORS: Record<WsStatus, string> = {
  connected:    "bg-green-500",
  connecting:   "bg-yellow-500 animate-pulse",
  disconnected: "bg-red-500",
  error:        "bg-red-600 animate-pulse",
};

const AI_STATE_LABEL: Record<string, string> = {
  idle:     "Ready",
  thinking: "Thinking...",
  speaking: "Speaking...",
};

const STALE_MS = 8000;

export function StatusIndicator({ wsStatus, aiState, model }: Props) {
  const { app, file, isBlank, lastUpdate, agentMode } = useWatchingStore();
  const [, force] = useState(0);

  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const stale = lastUpdate === 0 || Date.now() - lastUpdate > STALE_MS;
  const eyeIcon = "👁";
  const eyeColor =
    isBlank
      ? "text-amber-400"
      : stale
      ? "text-[var(--companion-muted)] opacity-40"
      : agentMode
      ? "text-emerald-400"
      : "text-[var(--companion-muted)]";

  const watchingLabel =
    isBlank
      ? "No screen permission"
      : !app
      ? "Initializing…"
      : file
      ? `${app} › ${file.split("/").pop()}`
      : app;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-[var(--companion-muted)] min-w-0">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_COLORS[wsStatus]}`} />
      <span className="shrink-0">
        {wsStatus === "connected" ? AI_STATE_LABEL[aiState] : wsStatus}
      </span>

      <span className="text-[var(--companion-border)] shrink-0">·</span>
      <span
        className={`flex items-center gap-1 min-w-0 ${eyeColor}`}
        title={
          isBlank
            ? "Grant Screen Recording permission in System Settings"
            : `Watching ${watchingLabel} (last update ${
                Math.max(0, Math.floor((Date.now() - lastUpdate) / 1000))
              }s ago)`
        }
      >
        <span className="shrink-0">{eyeIcon}</span>
        <span className="truncate">{watchingLabel}</span>
        {agentMode && !stale && !isBlank && (
          <span className="shrink-0 text-[9px] px-1 rounded
                           bg-emerald-500/20 text-emerald-300 font-medium">
            AGENT
          </span>
        )}
      </span>

      <span className="ml-auto font-mono truncate opacity-60 shrink-0">{model}</span>
    </div>
  );
}
