export interface TreemapItem<T> {
  value: number;
  data: T;
}

export interface TreemapRect<T> {
  x: number;
  y: number;
  w: number;
  h: number;
  data: T;
}

/** Worst aspect ratio of a row laid along a side of length `side`. */
function worst(row: number[], side: number): number {
  const sum = row.reduce((a, b) => a + b, 0);
  const max = Math.max(...row);
  const min = Math.min(...row);
  const s2 = side * side;
  const sum2 = sum * sum;
  return Math.max((s2 * max) / sum2, sum2 / (s2 * min));
}

/**
 * Squarified treemap (Bruls et al.). Returns rectangles in the same units as width/height.
 * Items with non-positive value are dropped.
 */
export function squarify<T>(items: TreemapItem<T>[], width: number, height: number): TreemapRect<T>[] {
  const valid = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  const total = valid.reduce((s, i) => s + i.value, 0);
  if (!valid.length || width <= 0 || height <= 0 || total <= 0) return [];

  // Scale values to areas.
  const scale = (width * height) / total;
  const areas = valid.map((i) => i.value * scale);
  const out: TreemapRect<T>[] = [];

  let x = 0;
  let y = 0;
  let w = width;
  let h = height;
  let i = 0;

  while (i < areas.length) {
    const side = Math.min(w, h);
    const row: number[] = [areas[i]];
    let j = i + 1;
    while (j < areas.length && worst([...row, areas[j]], side) <= worst(row, side)) {
      row.push(areas[j]);
      j++;
    }
    const rowSum = row.reduce((a, b) => a + b, 0);
    if (w >= h) {
      // Lay out a column on the left.
      const colW = rowSum / h;
      let cy = y;
      row.forEach((a, k) => {
        const rh = a / colW;
        out.push({ x, y: cy, w: colW, h: rh, data: valid[i + k].data });
        cy += rh;
      });
      x += colW;
      w -= colW;
    } else {
      // Lay out a row on top.
      const rowH = rowSum / w;
      let cx = x;
      row.forEach((a, k) => {
        const rw = a / rowH;
        out.push({ x: cx, y, w: rw, h: rowH, data: valid[i + k].data });
        cx += rw;
      });
      y += rowH;
      h -= rowH;
    }
    i = j;
  }
  return out;
}
