/** Build a causal staircase from authoritative effective boundary samples. */
export function buildStepBoundaryPath(rows, key, x, y) {
  let path = "";
  let previous = null;
  rows.forEach((row, index) => {
    const value = Number(row[key]);
    const boxId = String(row.box_id ?? "");
    if (!Number.isFinite(value) || !boxId) {
      previous = null;
      return;
    }
    if (!previous || previous.boxId !== boxId) {
      path += `${path ? " " : ""}M${x(index).toFixed(1)},${y(value).toFixed(1)}`;
    } else if (Math.abs(previous.value - value) > 1e-10) {
      path += ` L${x(index).toFixed(1)},${y(previous.value).toFixed(1)} L${x(index).toFixed(1)},${y(value).toFixed(1)}`;
    } else {
      path += ` L${x(index).toFixed(1)},${y(value).toFixed(1)}`;
    }
    previous = { value, boxId };
  });
  return path;
}
