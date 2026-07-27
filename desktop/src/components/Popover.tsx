import { ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  /** The trigger element. Cloned with onClick/ref so we can position relative to it. */
  trigger: (props: {
    ref: React.RefObject<HTMLButtonElement | null>;
    onClick: () => void;
    "aria-expanded": boolean;
  }) => ReactNode;

  /** Content rendered inside the floating panel. */
  children: ReactNode;

  /** Optional fixed width for the panel. If omitted, the panel fits its content. */
  panelWidth?: number;

  /** Horizontal alignment relative to the trigger. */
  align?: "start" | "end";

  /** Vertical offset in px between trigger and panel. */
  offset?: number;
}

/**
 * Portal-based popover. Solves three problems for our floating mentor window:
 *   1. Escapes `overflow-hidden` ancestors (the rounded outer container clips
 *      absolutely-positioned children).
 *   2. Stays fully inside the viewport — clamps to window edges on resize.
 *   3. Repositions while open if the window moves or resizes.
 */
export function Popover({
  trigger,
  children,
  panelWidth,
  align = "start",
  offset = 4,
}: Props) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef   = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null);

  // Position the panel under the trigger; clamp to viewport on all sides.
  const recompute = () => {
    const btn = triggerRef.current;
    if (!btn) return;

    const rect    = btn.getBoundingClientRect();
    const vw      = window.innerWidth;
    const vh      = window.innerHeight;
    const margin  = 8;

    // Width: explicit, or measured panel width, or fit-to-window
    let width = panelWidth ?? panelRef.current?.offsetWidth ?? 280;
    width = Math.min(width, vw - margin * 2);

    // Horizontal: align to start or end of trigger, then clamp
    let left = align === "start" ? rect.left : rect.right - width;
    left = Math.max(margin, Math.min(left, vw - width - margin));

    // Vertical: open downward; if not enough room, open upward
    let top = rect.bottom + offset;
    const panelH    = panelRef.current?.offsetHeight ?? 320;
    const spaceBelow = vh - top - margin;
    const spaceAbove = rect.top  - margin;
    let maxHeight = spaceBelow;

    if (spaceBelow < 200 && spaceAbove > spaceBelow) {
      // flip upward
      top = Math.max(margin, rect.top - offset - Math.min(panelH, spaceAbove));
      maxHeight = spaceAbove;
    }

    setPos({ top, left, width, maxHeight });
  };

  useLayoutEffect(() => {
    if (!open) return;
    recompute();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = () => recompute();
    window.addEventListener("resize", handler);
    window.addEventListener("scroll",  handler, true);
    return () => {
      window.removeEventListener("resize", handler);
      window.removeEventListener("scroll",  handler, true);
    };
  }, [open]);

  // Click outside to close (handled by backdrop)
  // Escape key to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {trigger({
        ref: triggerRef,
        onClick: () => setOpen((o) => !o),
        "aria-expanded": open,
      })}

      {open && pos && createPortal(
        <>
          {/* Backdrop — also closes on click */}
          <div
            className="fixed inset-0 z-[1000]"
            onClick={() => setOpen(false)}
          />
          {/* Panel */}
          <div
            ref={panelRef}
            className="
              fixed z-[1001]
              bg-[var(--companion-bg)] border border-[var(--companion-border)]
              rounded-lg shadow-2xl py-1 overflow-y-auto
            "
            style={{
              top: pos.top,
              left: pos.left,
              width: pos.width,
              maxHeight: pos.maxHeight,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {children}
          </div>
        </>,
        document.body,
      )}
    </>
  );
}
