/** Annotation primitives sent to the overlay window. */

export type AnnotationColor =
  | "accent"  // indigo (default)
  | "success" // green
  | "warning" // amber
  | "danger"  // red
  | "info";   // cyan

export interface BaseAnnotation {
  id: string;
  /** Auto-fade after N ms. 0 = persist until cleared. */
  duration_ms?: number;
  color?: AnnotationColor;
  /** Optional caption shown near the shape. */
  label?: string;
}

/** Rectangle highlight — { x, y } is top-left, { w, h } is size. Screen-space pixels. */
export interface HighlightAnnotation extends BaseAnnotation {
  kind: "highlight";
  x: number; y: number; w: number; h: number;
}

/** Circle/dot — { x, y } is center; r is radius. */
export interface CircleAnnotation extends BaseAnnotation {
  kind: "circle";
  x: number; y: number; r: number;
}

/** Arrow from (x1,y1) to (x2,y2). */
export interface ArrowAnnotation extends BaseAnnotation {
  kind: "arrow";
  x1: number; y1: number; x2: number; y2: number;
}

/** Floating text bubble anchored at (x, y). */
export interface LabelAnnotation extends BaseAnnotation {
  kind: "label";
  x: number; y: number;
  text: string;
}

export type Annotation =
  | HighlightAnnotation
  | CircleAnnotation
  | ArrowAnnotation
  | LabelAnnotation;

export const COLOR_HEX: Record<AnnotationColor, string> = {
  accent:  "#6366f1",
  success: "#22c55e",
  warning: "#f59e0b",
  danger:  "#ef4444",
  info:    "#06b6d4",
};
