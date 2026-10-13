/** Plain-JavaScript geometry on GeoJSON coordinates (longitude, latitude in degrees). */

type Ring = number[][];
type Polygons = number[][][][];

export const M_PER_DEG_LAT = 110_574;
export const M_PER_DEG_LNG_AT_EQUATOR = 111_320;

/** Metres per degree of longitude at a given latitude. */
export const metresPerDegLng = (lat: number) =>
  M_PER_DEG_LNG_AT_EQUATOR * Math.cos((lat * Math.PI) / 180);

/** Polygon and MultiPolygon as a list of polygons (each: outer ring, then holes). */
export const polysOf = (g: GeoJSON.Geometry | null | undefined): Polygons =>
  g?.type === 'Polygon'
    ? [g.coordinates]
    : g?.type === 'MultiPolygon'
      ? g.coordinates
      : [];

/** [minLng, minLat, maxLng, maxLat], or null if the geometry has no polygons. */
export function geomBBox(
  g: GeoJSON.Geometry | null | undefined,
): [number, number, number, number] | null {
  const polys = polysOf(g);
  if (!polys.length) return null;
  let a = Infinity,
    b = Infinity,
    c = -Infinity,
    d = -Infinity;
  for (const p of polys)
    for (const [x, y] of p[0]) {
      if (x < a) a = x;
      if (y < b) b = y;
      if (x > c) c = x;
      if (y > d) d = y;
    }
  return [a, b, c, d];
}

/** Ray-casting test: is the point inside one ring? */
export function inRing(x: number, y: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i],
      [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}

/** Is the point inside the (Multi)Polygon, respecting holes? */
export function pointInGeom(
  x: number,
  y: number,
  g: GeoJSON.Geometry | null | undefined,
): boolean {
  return polysOf(g).some(
    (p) =>
      inRing(x, y, p[0]) && !p.slice(1).some((hole) => inRing(x, y, hole)),
  );
}

/**
 * Straight-line distance in metres from a point to a (Multi)Polygon: 0 if inside,
 * otherwise the distance to the nearest edge. Uses a flat local projection, which is
 * accurate enough at the scale of Crete. Holes are ignored.
 */
export function distToGeomM(
  lat: number,
  lng: number,
  g: GeoJSON.Geometry | null | undefined,
): number {
  const kx = metresPerDegLng(lat);
  let best = Infinity;
  for (const poly of polysOf(g)) {
    const ring = poly[0];
    let inside = false;
    let min = Infinity;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      // Edge j -> i in metres, with the point at the origin
      const ax = (ring[j][0] - lng) * kx,
        ay = (ring[j][1] - lat) * M_PER_DEG_LAT;
      const bx = (ring[i][0] - lng) * kx,
        by = (ring[i][1] - lat) * M_PER_DEG_LAT;
      if (ay > 0 !== by > 0 && ax + ((0 - ay) * (bx - ax)) / (by - ay) > 0)
        inside = !inside;
      const dx = bx - ax,
        dy = by - ay,
        l2 = dx * dx + dy * dy;
      const t = l2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / l2)) : 0;
      min = Math.min(min, Math.hypot(ax + t * dx, ay + t * dy));
    }
    best = Math.min(best, inside ? 0 : min);
  }
  return best;
}
