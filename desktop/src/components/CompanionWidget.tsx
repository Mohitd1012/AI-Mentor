import { useEffect, useRef, useState } from "react";
import { useChatStore, Message } from "@/store/useChatStore";
import { useVoiceStore } from "@/store/useVoiceStore";
import { wsClient, InboundMessage } from "@/lib/ws";
import { TitleBar } from "./TitleBar";
import { StatusIndicator } from "./StatusIndicator";
import { MessageBubble } from "./MessageBubble";
import { InputRow } from "./InputRow";
import { OfflineBanner } from "./OfflineBanner";
import { ModeBar } from "./ModeBar";
import { useModeStore } from "@/store/useModeStore";
import { ResizeHandle } from "./ResizeHandle";
import { useGlobalPTT } from "@/hooks/useGlobalPTT";
import { MemoryPanel } from "./MemoryPanel";
import { annotate as overlayAnnotate, clearOverlay } from "@/lib/overlay";
import { useWatchingStore } from "@/store/useWatchingStore";

export function CompanionWidget() {
  const {
    messages, wsStatus, aiState, currentModel,
    setWsStatus, setAiState, appendChunk, sendMessage, setModel, addUserMessage,
    startProactiveMessage, addToolCall, addToolResult,
  } = useChatStore();

  const { setVoiceState, setTranscript } = useVoiceStore();
  const { setLastAction } = useModeStore();
  const { setWatching, setAgentMode } = useWatchingStore();

  // Register global hotkey for background-mode PTT
  useGlobalPTT();

  const scrollRef = useRef<HTMLDivElement>(null);
  const [memoryOpen, setMemoryOpen] = useState(false);

  useEffect(() => {
    wsClient.connect();

    const unsubStatus = wsClient.onStatus(setWsStatus);
    const unsubMsg = wsClient.onMessage((msg: InboundMessage) => {
      switch (msg.type) {
        case "chunk":
          if (msg.id !== undefined) {
            appendChunk(msg.id, msg.content ?? "", msg.done ?? false);
            if (msg.done) setAiState("idle");
          }
          break;
        case "status":
          if (msg.state) setAiState(msg.state);
          break;
        case "voice_state":
          if (msg.state) {
            setVoiceState(msg.state as "idle" | "listening" | "transcribing" | "speaking");
            if (msg.state === "speaking") setAiState("speaking");
            else if (msg.state === "idle") setAiState("idle");
          }
          break;
        case "transcript":
          if (msg.text) {
            setTranscript(msg.text);
            if (msg.is_final) addUserMessage(msg.text);
          }
          break;
        case "planner_decision": {
          const dmsg = msg as unknown as { action: string; reasoning?: string };
          if (dmsg.action) setLastAction(dmsg.action);
          break;
        }
        case "proactive_start": {
          const pmsg = msg as unknown as {
            id: string; trigger: string; summary: string;
          };
          if (pmsg.id) {
            startProactiveMessage(pmsg.id, pmsg.trigger, pmsg.summary);
          }
          break;
        }
        case "watching": {
          const wmsg = msg as unknown as {
            app: string | null; content_type: string | null;
            file: string | null; is_blank: boolean;
          };
          setWatching({
            app:         wmsg.app,
            contentType: wmsg.content_type,
            file:        wmsg.file,
            isBlank:     wmsg.is_blank,
          });
          break;
        }
        case "agent_mode": {
          const amsg = msg as unknown as { enabled: boolean };
          setAgentMode(!!amsg.enabled);
          break;
        }
        case "tool_call": {
          const tmsg = msg as unknown as {
            call_id: string; name: string;
            arguments: Record<string, unknown>; round: number;
          };
          addToolCall({
            call_id: tmsg.call_id, name: tmsg.name,
            arguments: tmsg.arguments || {},
            round: tmsg.round ?? 0,
          });
          break;
        }
        case "tool_result": {
          const rmsg = msg as unknown as {
            call_id: string; content: string;
            is_error: boolean; details?: Record<string, unknown>;
          };
          addToolResult(rmsg.call_id, {
            content: rmsg.content, is_error: !!rmsg.is_error,
            details: rmsg.details,
          });
          break;
        }
        case "overlay_annotate": {
          const omsg = msg as unknown as { annotations: any[] };
          if (Array.isArray(omsg.annotations) && omsg.annotations.length > 0) {
            overlayAnnotate(omsg.annotations).catch((e) =>
              console.error("[overlay] annotate failed:", e)
            );
          }
          break;
        }
        case "overlay_clear":
          clearOverlay().catch((e) => console.error("[overlay] clear failed:", e));
          break;
        case "error":
          console.error("[ws] Server error:", msg.message);
          setAiState("idle");
          break;
      }
    });

    return () => {
      unsubStatus();
      unsubMsg();
      wsClient.disconnect();
    };
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const isDisabled = wsStatus !== "connected" || aiState === "thinking";

  return (
    <div
      className="
        relative flex flex-col h-screen w-full rounded-2xl overflow-hidden
        bg-[var(--companion-bg)] border border-[var(--companion-border)]
        shadow-2xl
      "
      style={{ backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)" }}
    >
      <TitleBar model={currentModel} onModelChange={setModel} onOpenMemory={() => setMemoryOpen(true)} />
      <StatusIndicator wsStatus={wsStatus} aiState={aiState} model={currentModel} />
      <ModeBar />
      <ResizeHandle />
      {memoryOpen && <MemoryPanel onClose={() => setMemoryOpen(false)} />}

      <OfflineBanner status={wsStatus} />

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 pt-3 pb-1">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          messages.map((m: Message) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>

      <div className="border-t border-[var(--companion-border)]">
        <InputRow onSend={sendMessage} disabled={isDisabled} />
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 py-12 text-center">
      <div className="w-12 h-12 rounded-2xl bg-[var(--companion-accent)] flex items-center justify-center opacity-80">
        <span className="text-white text-xl font-bold">M</span>
      </div>
      <div>
        <p className="text-[var(--companion-text)] font-medium text-sm">
          Your AI Mentor is ready
        </p>
        <p className="text-[var(--companion-muted)] text-xs mt-1 leading-relaxed max-w-[240px]">
          Ask anything — I can see your screen and remember what we discuss.
        </p>
        <p className="text-[var(--companion-muted)] text-[10px] mt-3 leading-snug">
          Hold the{" "}
          <span className="inline-block px-1.5 py-0.5 rounded bg-[var(--companion-surface)] border border-[var(--companion-border)] font-mono">
            Right ⌘
          </span>{" "}
          key to talk from anywhere, even when this window is hidden.
        </p>
      </div>
    </div>
  );
}
