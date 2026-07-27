import { WsStatus } from "@/lib/ws";

interface Props {
  status: WsStatus;
}

export function OfflineBanner({ status }: Props) {
  if (status === "connected") return null;

  const label =
    status === "connecting"
      ? "Connecting to backend…"
      : "Backend offline — run: cd backend && .venv/bin/python main.py";

  return (
    <div className="
      mx-3 mb-2 px-3 py-2 rounded-xl text-xs
      bg-yellow-500/10 border border-yellow-500/30 text-yellow-400
      flex items-center gap-2
    ">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 bg-yellow-400 ${status === "connecting" ? "animate-pulse" : ""}`} />
      <span className="leading-snug">{label}</span>
    </div>
  );
}
