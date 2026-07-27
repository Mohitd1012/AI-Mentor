import { useEffect, useState } from "react";
import { wsClient } from "@/lib/ws";
import { Popover } from "./Popover";

interface VoiceInfo {
  backend: string;
  current: string;
  voices: string[];
}

const VOICE_LABELS: Record<string, string> = {
  af_heart:   "♥ Heart (US F)",
  af_bella:   "Bella (US F)",
  af_nova:    "Nova (US F)",
  af_sarah:   "Sarah (US F)",
  af_nicole:  "Nicole (US F)",
  af_sky:     "Sky (US F)",
  af_alloy:   "Alloy (US F)",
  af_aoede:   "Aoede (US F)",
  af_jessica: "Jessica (US F)",
  af_kore:    "Kore (US F)",
  af_river:   "River (US F)",
  am_adam:    "Adam (US M)",
  am_echo:    "Echo (US M)",
  am_eric:    "Eric (US M)",
  am_fenrir:  "Fenrir (US M)",
  am_liam:    "Liam (US M)",
  am_michael: "Michael (US M)",
  am_onyx:    "Onyx (US M)",
  am_puck:    "Puck (US M)",
  bf_emma:    "Emma (UK F)",
  bf_isabella:"Isabella (UK F)",
  bm_george:  "George (UK M)",
  bm_lewis:   "Lewis (UK M)",
};

function label(voice: string): string {
  return VOICE_LABELS[voice] ?? voice;
}

export function VoicePicker() {
  const [info, setInfo] = useState<VoiceInfo | null>(null);

  useEffect(() => {
    fetch("http://localhost:8765/voice/voices")
      .then((r) => r.json())
      .then(setInfo)
      .catch(() => {});
  }, []);

  const onChange = (voice: string) => {
    wsClient.send({ type: "set_tts_voice", voice });
    setInfo((prev) => (prev ? { ...prev, current: voice } : prev));
  };

  if (!info) return null;

  const featured = ["af_heart", "af_bella", "af_nova", "am_michael", "am_adam", "bf_emma", "bm_george"];
  const featuredVoices = featured.filter((v) => info.voices.includes(v));
  const otherVoices    = info.voices.filter((v) => !featured.includes(v));

  return (
    <Popover
      align="end"
      panelWidth={220}
      trigger={({ ref, onClick, "aria-expanded": expanded }) => (
        <button
          ref={ref}
          onClick={onClick}
          aria-expanded={expanded}
          className="
            text-xs bg-[var(--companion-surface)] border border-[var(--companion-border)]
            text-[var(--companion-muted)] rounded-md px-2 py-0.5
            hover:text-[var(--companion-text)] focus:outline-none focus:border-[var(--companion-accent)]
            flex items-center gap-1 shrink-0
          "
          title={`TTS: ${info.backend}`}
        >
          🔊 <span className="truncate max-w-[60px]">{label(info.current).split(" ")[0]}</span>
        </button>
      )}
    >
      <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-[var(--companion-muted)]">
        Featured
      </div>
      {featuredVoices.map((v) => (
        <VoiceItem key={v} voice={v} current={info.current} onClick={onChange} />
      ))}
      {otherVoices.length > 0 && (
        <div className="px-3 py-1 mt-1 text-[10px] uppercase tracking-wider text-[var(--companion-muted)] border-t border-[var(--companion-border)]">
          More voices
        </div>
      )}
      {otherVoices.map((v) => (
        <VoiceItem key={v} voice={v} current={info.current} onClick={onChange} />
      ))}
    </Popover>
  );
}

function VoiceItem({
  voice, current, onClick,
}: {
  voice: string;
  current: string;
  onClick: (v: string) => void;
}) {
  const active = voice === current;
  return (
    <button
      onClick={() => onClick(voice)}
      className={`
        w-full text-left px-3 py-1.5 text-xs transition-colors
        ${active
          ? "bg-[var(--companion-accent)]/20 text-[var(--companion-text)]"
          : "text-[var(--companion-muted)] hover:bg-[var(--companion-surface)] hover:text-[var(--companion-text)]"
        }
      `}
    >
      {active && "✓ "}{label(voice)}
    </button>
  );
}
