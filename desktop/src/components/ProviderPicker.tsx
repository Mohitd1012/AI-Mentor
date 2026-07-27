import { useEffect, useState } from "react";
import { wsClient } from "@/lib/ws";
import { Popover } from "./Popover";

interface Diagnostics {
  configured: boolean;
  model?: string;
  url?: string;
  reason?: string | null;
}

interface ProviderInfo {
  available: string[];
  preferred: string | null;
  diagnostics?: Record<string, Diagnostics>;
}

const LABELS: Record<string, { icon: string; name: string }> = {
  ollama:    { icon: "🏠", name: "Ollama"  },
  openai:    { icon: "✨", name: "OpenAI"  },
  anthropic: { icon: "🅰",  name: "Claude"  },
};

export function ProviderPicker() {
  const [info, setInfo] = useState<ProviderInfo | null>(null);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    const unsub = wsClient.onMessage((m) => {
      if (m.type === "provider") refresh();
    });
    return () => { clearInterval(t); unsub(); };
  }, []);

  const refresh = () => {
    fetch("http://localhost:8765/providers")
      .then((r) => r.json())
      .then(setInfo)
      .catch(() => {});
  };

  const onChange = (provider: string) => {
    const p = provider === "auto" ? null : provider;
    wsClient.send({ type: "set_provider", provider: p });
    setInfo((prev) => prev ? { ...prev, preferred: p } : prev);
  };

  if (!info) return null;

  const active = info.preferred || "auto";
  const allKnown: (keyof typeof LABELS)[] = ["ollama", "openai", "anthropic"];

  return (
    <Popover
      align="end"
      panelWidth={240}
      trigger={({ ref, onClick, "aria-expanded": expanded }) => (
        <button
          ref={ref}
          onClick={onClick}
          aria-expanded={expanded}
          className="
            text-xs bg-[var(--companion-surface)] border border-[var(--companion-border)]
            text-[var(--companion-muted)] rounded-md px-2 py-0.5
            hover:text-[var(--companion-text)] focus:outline-none focus:border-[var(--companion-accent)]
            shrink-0
          "
        >
          {active === "auto" ? "🌐" : LABELS[active]?.icon ?? "•"}
        </button>
      )}
    >
      <ProviderItem
        label="🌐 Auto"
        sub="Default waterfall"
        active={active === "auto"}
        onClick={() => onChange("auto")}
      />
      <div className="my-1 border-t border-[var(--companion-border)]" />
      {allKnown.map((p) => {
        const meta = LABELS[p];
        const diag = info.diagnostics?.[p];
        const isAvailable = info.available.includes(p);
        return (
          <ProviderItem
            key={p}
            label={`${meta.icon} ${meta.name}`}
            sub={isAvailable ? diag?.model : diag?.reason ?? "Not configured"}
            active={active === p}
            disabled={!isAvailable}
            onClick={() => isAvailable && onChange(p)}
          />
        );
      })}
    </Popover>
  );
}

function ProviderItem({
  label, sub, active, disabled, onClick,
}: {
  label: string;
  sub?: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        w-full text-left px-3 py-1.5 text-xs transition-colors
        ${disabled ? "opacity-40 cursor-not-allowed" : "hover:bg-[var(--companion-surface)]"}
        ${active ? "bg-[var(--companion-accent)]/20" : ""}
      `}
    >
      <div className="text-[var(--companion-text)]">
        {active ? "✓ " : ""}{label}
      </div>
      {sub && (
        <div className="text-[10px] text-[var(--companion-muted)] mt-0.5 leading-tight">
          {sub}
        </div>
      )}
    </button>
  );
}
