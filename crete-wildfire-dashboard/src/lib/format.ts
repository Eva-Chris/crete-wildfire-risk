/** Small formatting and number helpers shared by the map and docs pages. */

export const isNum = (v: unknown): v is number =>
  typeof v === 'number' && isFinite(v);

export const clamp = (v: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, v));

/** Escape text before putting it into an HTML string (popups, tooltips). */
export const esc = (v: unknown) =>
  String(v).replace(
    /[&<>"']/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[
        c
      ]!,
  );

export const fmt = (v: unknown, digits = 0, unit = '') =>
  isNum(v) ? v.toFixed(digits) + unit : '—';

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
export const compass = (deg: number): string =>
  COMPASS[Math.round(deg / 45) % 8];

/** 0 m means the zone touches or contains the feature, so say that instead of "0 m". */
export const distText = (v: unknown, what: string): string =>
  !isNum(v) ? '—' : v < 1 ? `${what} touches the zone` : fmt(v, 0, ' m');
