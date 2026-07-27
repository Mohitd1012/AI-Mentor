import { useEffect, useState } from "react";
import { wsClient } from "@/lib/ws";
import { Popover } from "./Popover";

interface RoleMeta {
  id: string;
  name: string;
  emoji: string;
  description: string;
  is_builtin: boolean;
  tags: string[];
  voice: string;
  conversation_mode: string;
  proactivity: number;
}

interface RolesResponse {
  active: string;
  roles: RoleMeta[];
}

export function RolePicker() {
  const [data, setData] = useState<RolesResponse | null>(null);

  useEffect(() => {
    refresh();
    const unsub = wsClient.onMessage((m) => {
      if (m.type === "role") refresh();
    });
    return () => { unsub(); };
  }, []);

  const refresh = () => {
    fetch("http://localhost:8765/roles")
      .then((r) => r.json())
      .then(setData)
      .catch(() => {});
  };

  const onChoose = (role_id: string) => {
    wsClient.send({ type: "set_role", role_id });
    setData((prev) => prev ? { ...prev, active: role_id } : prev);
  };

  if (!data) return null;

  const active = data.roles.find((r) => r.id === data.active);

  return (
    <Popover
      align="start"
      panelWidth={360}
      trigger={({ ref, onClick, "aria-expanded": expanded }) => (
        <button
          ref={ref}
          onClick={onClick}
          aria-expanded={expanded}
          className="
            text-xs bg-[var(--companion-accent)]/15 border border-[var(--companion-accent)]/40
            text-[var(--companion-text)] rounded-md px-2 py-0.5
            hover:bg-[var(--companion-accent)]/25 focus:outline-none
            flex items-center gap-1.5 font-medium
            min-w-0 flex-1 max-w-[200px]
          "
          title={`Role: ${active?.name ?? "—"}\n${active?.description ?? ""}\nClick to change`}
        >
          <span className="text-sm leading-none shrink-0">{active?.emoji ?? "🧠"}</span>
          <span className="truncate min-w-0 flex-1 text-left">{active?.name ?? "Pick role"}</span>
          <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="3" className="shrink-0 opacity-70">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
      )}
    >
      <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-[var(--companion-muted)]">
        Choose a role
      </div>
      {data.roles.map((r) => {
        const isActive = r.id === data.active;
        return (
          <button
            key={r.id}
            onClick={() => onChoose(r.id)}
            className={`
              w-full text-left px-3 py-2 transition-colors
              ${isActive
                ? "bg-[var(--companion-accent)]/20"
                : "hover:bg-[var(--companion-surface)]"
              }
            `}
          >
            <div className="flex items-start gap-2">
              <span className="text-lg leading-none mt-0.5">{r.emoji}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-[var(--companion-text)] truncate">
                    {isActive && "✓ "}{r.name}
                  </span>
                  {!r.is_builtin && (
                    <span className="text-[9px] px-1 rounded bg-purple-500/20 text-purple-300">
                      CUSTOM
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-[var(--companion-muted)] mt-0.5 leading-snug">
                  {r.description}
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </Popover>
  );
}
