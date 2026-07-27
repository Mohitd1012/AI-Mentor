/**
 * Overlay client — wraps the Tauri commands so the main app can drive
 * the transparent annotation window without touching window internals.
 */

import { invoke } from "@tauri-apps/api/core";
import type { Annotation } from "@/overlay/types";

export async function showOverlay(): Promise<void> {
  await invoke("overlay_show");
}

export async function hideOverlay(): Promise<void> {
  await invoke("overlay_hide");
}

export async function clearOverlay(): Promise<void> {
  await invoke("overlay_clear");
}

/** Add one annotation. Auto-shows the overlay if hidden. */
export async function annotate(a: Annotation | Annotation[]): Promise<void> {
  await invoke("overlay_annotate", { payload: a });
}

/** A built-in demo to verify the overlay is wired correctly. */
export async function demoOverlay(): Promise<void> {
  const now = Date.now();
  await annotate([
    {
      id: `demo-${now}-1`,
      kind: "highlight",
      x: 200, y: 200, w: 320, h: 80,
      color: "accent",
      label: "I can see what's on your screen",
      duration_ms: 6000,
    },
    {
      id: `demo-${now}-2`,
      kind: "circle",
      x: 700, y: 400, r: 40,
      color: "success",
      label: "And point at things",
      duration_ms: 6000,
    },
    {
      id: `demo-${now}-3`,
      kind: "arrow",
      x1: 800, y1: 600, x2: 1000, y2: 700,
      color: "warning",
      duration_ms: 6000,
    },
    {
      id: `demo-${now}-4`,
      kind: "label",
      x: 1100, y: 750,
      text: "Demo annotation • 6s",
      color: "info",
      duration_ms: 6000,
    },
  ]);
}
