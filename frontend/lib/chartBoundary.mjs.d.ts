export type BoundaryRow = {
  box_id?: string | null;
  [key: string]: unknown;
};

export function buildStepBoundaryPath(
  rows: BoundaryRow[],
  key: string,
  x: (index: number, row: BoundaryRow) => number,
  y: (value: number, row: BoundaryRow) => number,
): string;
