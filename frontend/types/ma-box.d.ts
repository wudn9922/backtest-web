declare module "@/lib/chartBoundary.mjs" {
  export type BoundaryRow = { box_id?: string | null; [key: string]: unknown };
  export function buildStepBoundaryPath(
    rows: BoundaryRow[],
    key: string,
    x: (index: number, row: BoundaryRow) => number,
    y: (value: number, row: BoundaryRow) => number,
  ): string;
}

declare module "@/lib/chartViewport.mjs" {
  export type Viewport = { start: number; end: number };
  export type IndexRange = { from: number; to: number };
  export function zoomIn(scale: number): number;
  export function zoomOut(scale: number): number;
  export function resetZoom(): number;
  export function focusWindow(total: number, start?: number | null, end?: number | null): Viewport;
  export function panViewport(range: IndexRange, delta: number, bounds: { min?: number; max?: number }): IndexRange;
}
