import { getCurrentWindow } from "@tauri-apps/api/window";

/**
 * Bottom-right resize grip — visible cue + click-drag handle.
 * Uses Tauri's native start_resize_dragging for smooth OS-level resize.
 */
export function ResizeHandle() {
  const onMouseDown = async (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    try {
      await getCurrentWindow().startResizeDragging("bottom-right" as any);
    } catch (err) {
      console.error("[resize] startResizeDragging failed:", err);
    }
  };

  return (
    <div
      onMouseDown={onMouseDown}
      className="
        absolute bottom-0 right-0 w-4 h-4 z-50
        cursor-nwse-resize
        flex items-end justify-end
      "
      title="Drag to resize"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" className="opacity-40 hover:opacity-80 transition-opacity">
        <path d="M 1 13 L 13 1" stroke="currentColor" strokeWidth="1.2" />
        <path d="M 5 13 L 13 5" stroke="currentColor" strokeWidth="1.2" />
        <path d="M 9 13 L 13 9" stroke="currentColor" strokeWidth="1.2" />
      </svg>
    </div>
  );
}
