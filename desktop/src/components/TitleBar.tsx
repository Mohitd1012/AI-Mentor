import { getCurrentWindow } from "@tauri-apps/api/window";
import { exit as tauriExit } from "@tauri-apps/plugin-process";
import { demoOverlay, clearOverlay } from "@/lib/overlay";
import { VoicePicker } from "./VoicePicker";
import { ProviderPicker } from "./ProviderPicker";

interface Props {
  model: string;
  onModelChange: (m: string) => void;
  onOpenMemory: () => void;
}

const MODELS = ["qwen2.5:3b", "qwen2.5:7b", "phi3.5:3.8b", "llama3", "mistral", "codellama"];

export function TitleBar({ model, onModelChange, onOpenMemory }: Props) {
  const win = getCurrentWindow();

  const onClose = async () => { try { await win.hide(); } catch { await win.close(); } };
  const onQuit  = async () => { try { await tauriExit(0); } catch { await win.close(); } };

  return (
    <div
      data-tauri-drag-region
      className="
        flex items-center gap-2 px-3 py-2 min-w-0
        border-b border-[var(--companion-border)] select-none
      "
    >
      {/* Logo (draggable) */}
      <div
        data-tauri-drag-region
        className="flex items-center gap-2 shrink-0 cursor-grab active:cursor-grabbing"
      >
        <div className="w-5 h-5 rounded-md bg-[var(--companion-accent)] flex items-center justify-center pointer-events-none">
          <span className="text-white text-xs font-bold">M</span>
        </div>
        <span data-tauri-drag-region className="text-sm font-semibold text-[var(--companion-text)] pointer-events-none">
          AI&nbsp;Mentor
        </span>
      </div>

      {/* Flex drag strip — grows/shrinks with window width */}
      <div
        data-tauri-drag-region
        className="flex-1 min-w-2 h-6 cursor-grab active:cursor-grabbing"
        title="Drag to move"
      />

      {/* Right cluster: shrinkable */}
      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={(e) => (e.shiftKey ? clearOverlay() : demoOverlay())}
          className="w-6 h-6 rounded-md flex items-center justify-center
                     text-[var(--companion-muted)] hover:bg-[var(--companion-surface)]
                     hover:text-[var(--companion-text)] transition-colors"
          title="Demo overlay annotations  •  Shift-click to clear"
        >
          ✨
        </button>
        <button
          onClick={onOpenMemory}
          className="w-6 h-6 rounded-md flex items-center justify-center
                     text-[var(--companion-muted)] hover:bg-[var(--companion-surface)]
                     hover:text-[var(--companion-text)] transition-colors"
          title="Memory"
        >
          🧠
        </button>
        <ProviderPicker />
        <VoicePicker />

        <select
          className="
            text-xs bg-[var(--companion-surface)] border border-[var(--companion-border)]
            text-[var(--companion-muted)] rounded-md px-1 py-0.5
            focus:outline-none focus:border-[var(--companion-accent)]
            cursor-pointer
          "
          style={{ maxWidth: "11ch" }}
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
          title="Select Ollama model"
        >
          {MODELS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>

        <button
          onClick={() => win.minimize()}
          className="w-6 h-6 rounded-md flex items-center justify-center
                     text-[var(--companion-muted)] hover:bg-[var(--companion-surface)]
                     hover:text-[var(--companion-text)] transition-colors"
          title="Minimize"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>

        <button
          onClick={(e) => (e.shiftKey ? onQuit() : onClose())}
          onContextMenu={(e) => { e.preventDefault(); onQuit(); }}
          className="w-6 h-6 rounded-md flex items-center justify-center
                     text-[var(--companion-muted)] hover:bg-red-500 hover:text-white
                     transition-colors"
          title="Click: hide to tray  •  Shift+click or right-click: quit"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
    </div>
  );
}
