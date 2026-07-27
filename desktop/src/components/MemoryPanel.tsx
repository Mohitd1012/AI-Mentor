import { useEffect, useState } from "react";

interface MemoryRow {
  id: string;
  content: string;
  kind: string;
  source: string;
  role_id: string | null;
  created_at: string;
  updated_at: string;
  enabled: boolean;
}

interface MemoriesResponse {
  extraction_enabled: boolean;
  memories: MemoryRow[];
}

const KIND_BADGES: Record<string, { color: string; emoji: string }> = {
  preference: { color: "bg-blue-500/20 text-blue-300",     emoji: "❤️" },
  fact:       { color: "bg-emerald-500/20 text-emerald-300", emoji: "📌" },
  goal:       { color: "bg-amber-500/20 text-amber-300",   emoji: "🎯" },
  project:    { color: "bg-purple-500/20 text-purple-300", emoji: "🚀" },
  pinned:     { color: "bg-pink-500/20 text-pink-300",     emoji: "📍" },
  note:       { color: "bg-gray-500/20 text-gray-300",     emoji: "📝" },
};

const KINDS = ["preference", "fact", "goal", "project", "pinned", "note"] as const;

interface Props {
  onClose: () => void;
}

export function MemoryPanel({ onClose }: Props) {
  const [data, setData]     = useState<MemoriesResponse | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText]   = useState("");
  const [newText, setNewText]     = useState("");
  const [newKind, setNewKind]     = useState<typeof KINDS[number]>("note");

  const refresh = () => {
    fetch("http://localhost:8765/memories").then(r => r.json()).then(setData).catch(() => {});
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []);

  const onAdd = async () => {
    const content = newText.trim();
    if (!content) return;
    await fetch("http://localhost:8765/memories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, kind: newKind }),
    });
    setNewText("");
    refresh();
  };

  const onToggleEnabled = async (m: MemoryRow) => {
    await fetch(`http://localhost:8765/memories/${m.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !m.enabled }),
    });
    refresh();
  };

  const onDelete = async (id: string) => {
    if (!confirm("Delete this memory?")) return;
    await fetch(`http://localhost:8765/memories/${id}`, { method: "DELETE" });
    refresh();
  };

  const onSaveEdit = async (id: string) => {
    if (!editText.trim()) return;
    await fetch(`http://localhost:8765/memories/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: editText.trim() }),
    });
    setEditingId(null);
    setEditText("");
    refresh();
  };

  const onToggleExtraction = async () => {
    if (!data) return;
    await fetch("http://localhost:8765/memories/extraction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !data.extraction_enabled }),
    });
    refresh();
  };

  const onClearAll = async () => {
    if (!confirm("Delete ALL memories? This cannot be undone.")) return;
    await fetch("http://localhost:8765/memories/clear-all", { method: "POST" });
    refresh();
  };

  if (!data) return null;

  return (
    <div className="absolute inset-0 z-50 bg-[var(--companion-bg)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--companion-border)]">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--companion-text)]">🧠 Memory</span>
          <span className="text-[10px] text-[var(--companion-muted)]">{data.memories.length} entries</span>
        </div>
        <button
          onClick={onClose}
          className="w-6 h-6 rounded-md text-[var(--companion-muted)]
                     hover:bg-[var(--companion-surface)] hover:text-[var(--companion-text)]
                     flex items-center justify-center"
          title="Close"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* Settings strip */}
      <div className="px-3 py-2 border-b border-[var(--companion-border)] flex items-center justify-between text-xs">
        <label className="flex items-center gap-2 cursor-pointer text-[var(--companion-muted)]">
          <input type="checkbox" checked={data.extraction_enabled}
                 onChange={onToggleExtraction} className="accent-[var(--companion-accent)]" />
          Auto-extract memories from conversations
        </label>
        <button onClick={onClearAll}
                className="text-red-400 hover:text-red-300 text-[11px]">
          Clear all
        </button>
      </div>

      {/* Add new */}
      <div className="px-3 py-2 border-b border-[var(--companion-border)] flex items-center gap-2">
        <select
          value={newKind}
          onChange={(e) => setNewKind(e.target.value as typeof KINDS[number])}
          className="text-xs bg-[var(--companion-surface)] border border-[var(--companion-border)]
                     text-[var(--companion-text)] rounded-md px-1.5 py-1 cursor-pointer"
        >
          {KINDS.map((k) => <option key={k} value={k}>{KIND_BADGES[k].emoji} {k}</option>)}
        </select>
        <input
          type="text"
          value={newText}
          onChange={(e) => setNewText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onAdd()}
          placeholder="Add a memory…"
          className="selectable flex-1 text-xs bg-[var(--companion-surface)] border border-[var(--companion-border)]
                     text-[var(--companion-text)] rounded-md px-2 py-1
                     focus:outline-none focus:border-[var(--companion-accent)]"
        />
        <button
          onClick={onAdd}
          disabled={!newText.trim()}
          className="px-2 py-1 rounded-md text-xs bg-[var(--companion-accent)] text-white
                     disabled:opacity-30 hover:bg-[var(--companion-accent-dim)]"
        >
          Add
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {data.memories.length === 0 ? (
          <div className="p-6 text-center text-[var(--companion-muted)] text-xs">
            No memories yet. Add one above, or chat a few turns and let the AI extract some automatically.
          </div>
        ) : (
          data.memories.map((m) => {
            const badge = KIND_BADGES[m.kind] ?? KIND_BADGES.note;
            const isEditing = editingId === m.id;
            return (
              <div key={m.id} className={`
                px-3 py-2 border-b border-[var(--companion-border)]/50
                ${m.enabled ? "" : "opacity-40"}
              `}>
                <div className="flex items-start gap-2">
                  <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${badge.color}`}>
                    {badge.emoji} {m.kind}
                  </span>
                  <div className="flex-1 min-w-0">
                    {isEditing ? (
                      <input
                        type="text"
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") onSaveEdit(m.id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        className="selectable w-full text-xs bg-[var(--companion-surface)]
                                   border border-[var(--companion-accent)] text-[var(--companion-text)]
                                   rounded px-1.5 py-0.5 focus:outline-none"
                        autoFocus
                        onBlur={() => onSaveEdit(m.id)}
                      />
                    ) : (
                      <div
                        className="selectable text-xs text-[var(--companion-text)] leading-snug cursor-text"
                        onDoubleClick={() => { setEditingId(m.id); setEditText(m.content); }}
                        title="Double-click to edit"
                      >
                        {m.content}
                      </div>
                    )}
                    <div className="flex items-center gap-2 mt-1 text-[9px] text-[var(--companion-muted)]">
                      <span>{m.source}</span>
                      <span>•</span>
                      <span>{new Date(m.updated_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => onToggleEnabled(m)}
                      className="w-5 h-5 rounded text-[var(--companion-muted)]
                                 hover:bg-[var(--companion-surface)] hover:text-[var(--companion-text)]
                                 flex items-center justify-center"
                      title={m.enabled ? "Disable (excluded from recall)" : "Enable"}
                    >
                      {m.enabled ? "👁" : "🚫"}
                    </button>
                    <button
                      onClick={() => onDelete(m.id)}
                      className="w-5 h-5 rounded text-[var(--companion-muted)]
                                 hover:bg-red-500/20 hover:text-red-400
                                 flex items-center justify-center"
                      title="Delete"
                    >
                      ×
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
