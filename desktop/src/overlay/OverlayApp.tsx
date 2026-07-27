import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { Annotation, COLOR_HEX } from "./types";

/**
 * Full-screen transparent overlay renderer.
 * Listens for `overlay:annotate` / `overlay:clear` events from the main window.
 * Each annotation has an optional `duration_ms` for auto-fade.
 */
export function OverlayApp() {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);

  useEffect(() => {
    let unlistenAdd: (() => void) | undefined;
    let unlistenClear: (() => void) | undefined;

    (async () => {
      unlistenAdd = await listen<Annotation | Annotation[]>("overlay:annotate", (e) => {
        const incoming = Array.isArray(e.payload) ? e.payload : [e.payload];
        setAnnotations((prev) => [...prev, ...incoming]);

        // Schedule auto-removal for any with duration
        incoming.forEach((a) => {
          if (a.duration_ms && a.duration_ms > 0) {
            setTimeout(() => {
              setAnnotations((curr) => curr.filter((x) => x.id !== a.id));
            }, a.duration_ms);
          }
        });
      });

      unlistenClear = await listen("overlay:clear", () => setAnnotations([]));
    })();

    return () => {
      unlistenAdd?.();
      unlistenClear?.();
    };
  }, []);

  return (
    <svg
      width="100vw"
      height="100vh"
      xmlns="http://www.w3.org/2000/svg"
      style={{
        position: "fixed", inset: 0,
        width: "100vw", height: "100vh",
        pointerEvents: "none",
        background: "transparent",
        backgroundColor: "transparent",
        overflow: "visible",
      }}
    >
      <defs>
        {/* Arrowhead per color */}
        {Object.entries(COLOR_HEX).map(([name, hex]) => (
          <marker
            key={name}
            id={`arrow-${name}`}
            viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill={hex} />
          </marker>
        ))}
      </defs>

      {annotations.map((a) => {
        const color = COLOR_HEX[a.color ?? "accent"];
        switch (a.kind) {
          case "highlight":
            return (
              <g key={a.id}>
                <rect
                  x={a.x} y={a.y} width={a.w} height={a.h}
                  rx="6" ry="6"
                  fill={`${color}22`}
                  stroke={color} strokeWidth="3"
                  style={{
                    filter: `drop-shadow(0 0 8px ${color}80)`,
                    animation: "pulse 2s ease-in-out infinite",
                  }}
                />
                {a.label && <CaptionLabel x={a.x} y={a.y - 6} text={a.label} color={color} />}
              </g>
            );

          case "circle":
            return (
              <g key={a.id}>
                <circle
                  cx={a.x} cy={a.y} r={a.r}
                  fill="none" stroke={color} strokeWidth="3"
                  style={{
                    filter: `drop-shadow(0 0 6px ${color}80)`,
                    animation: "ping 1.4s ease-out infinite",
                  }}
                />
                <circle cx={a.x} cy={a.y} r={a.r} fill="none" stroke={color} strokeWidth="2" />
                {a.label && <CaptionLabel x={a.x + a.r + 6} y={a.y} text={a.label} color={color} />}
              </g>
            );

          case "arrow":
            return (
              <g key={a.id}>
                <line
                  x1={a.x1} y1={a.y1} x2={a.x2} y2={a.y2}
                  stroke={color} strokeWidth="3" strokeLinecap="round"
                  markerEnd={`url(#arrow-${a.color ?? "accent"})`}
                  style={{ filter: `drop-shadow(0 0 4px ${color}80)` }}
                />
                {a.label && <CaptionLabel x={(a.x1 + a.x2) / 2} y={(a.y1 + a.y2) / 2 - 10} text={a.label} color={color} />}
              </g>
            );

          case "label":
            return <CaptionLabel key={a.id} x={a.x} y={a.y} text={a.text} color={color} />;
        }
      })}

      <style>{`
        @keyframes pulse {
          0%,100% { opacity: 1; }
          50%     { opacity: 0.6; }
        }
        @keyframes ping {
          0%   { transform: scale(1);   opacity: 1; transform-origin: center; }
          100% { transform: scale(1.4); opacity: 0; }
        }
      `}</style>
    </svg>
  );
}

function CaptionLabel({
  x, y, text, color,
}: {
  x: number; y: number; text: string; color: string;
}) {
  const padX = 8, padY = 4;
  const charW = 7;  // rough char width at 13px
  const w = Math.min(text.length * charW + padX * 2, 360);
  return (
    <g>
      <rect
        x={x} y={y - 14} width={w} height={22} rx="4" ry="4"
        fill="rgba(15,17,23,0.95)"
        stroke={color} strokeWidth="1"
      />
      <text
        x={x + padX} y={y + padY - 4}
        fill="#e2e8f0"
        fontFamily="-apple-system, BlinkMacSystemFont, sans-serif"
        fontSize="13" fontWeight="500"
      >
        {text}
      </text>
    </g>
  );
}
