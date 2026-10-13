/** Risk classes, Fire Weather Index classes and the per-factor breakdown shown in popups. */
import { compass, distText, clamp, fmt, isNum } from './format';
import { Props } from './types';

/* ---------------- static risk classes ---------------- */

export interface RiskClass {
  label: string;
  /** Text for the legend, e.g. "44.8 to 52.8". Filled by applyBreaks. */
  range: string;
  /** Lower bound of the class. A score belongs to the first class it reaches. */
  min: number;
  /** Same colour ramp as the QGIS project (ColorBrewer RdYlGn). */
  color: string;
}

export const RISK_CLASSES: RiskClass[] = [
  { label: 'Very high', range: '', min: 0, color: '#d7191c' },
  { label: 'High', range: '', min: 0, color: '#fdae61' },
  { label: 'Moderate', range: '', min: 0, color: '#ffffbf' },
  { label: 'Low', range: '', min: 0, color: '#a6d96a' },
  { label: 'Very low', range: '', min: -Infinity, color: '#1a9641' },
];

/**
 * Sets the class limits from breaks = [p20, p40, p60, p80] of the static score,
 * as written to model.json by build_static_risk.py.
 */
export function applyBreaks(b: number[]): void {
  if (!Array.isArray(b) || b.length !== 4) return;
  const [p20, p40, p60, p80] = b;
  [p80, p60, p40, p20].forEach((min, i) => (RISK_CLASSES[i].min = min));
  RISK_CLASSES[0].range = `${p80.toFixed(1)} and above`;
  RISK_CLASSES[1].range = `${p60.toFixed(1)} to ${p80.toFixed(1)}`;
  RISK_CLASSES[2].range = `${p40.toFixed(1)} to ${p60.toFixed(1)}`;
  RISK_CLASSES[3].range = `${p20.toFixed(1)} to ${p40.toFixed(1)}`;
  RISK_CLASSES[4].range = `below ${p20.toFixed(1)}`;
}
// Defaults until /api/model answers (the legend is never blank). Replaced by the real breaks.
applyBreaks([25.1, 33.6, 44.8, 52.8]);

/** Index into RISK_CLASSES (0 = Very high). A score exactly on a break goes to the higher class. */
export const classify = (score: number): number =>
  RISK_CLASSES.findIndex((c) => score >= c.min);

export const scoreOf = (p: Props | null | undefined): number =>
  clamp(Number(p?.['static_risk_score'] ?? 0), 0, 100);

/* ---------------- Fire Weather Index classes (EFFIS) ---------------- */

export const FWI_CLASSES = [
  { label: 'Very low', min: 0, color: '#1a9641' },
  { label: 'Low', min: 5.2, color: '#a6d96a' },
  { label: 'Moderate', min: 11.2, color: '#e0c200' },
  { label: 'High', min: 21.3, color: '#fdae61' },
  { label: 'Very high', min: 38, color: '#d7191c' },
  { label: 'Extreme', min: 50, color: '#7f0000' },
];

export const fwiClass = (v: number) => {
  let c = FWI_CLASSES[0];
  for (const k of FWI_CLASSES) if (v >= k.min) c = k;
  return c;
};

/* ---------------- colouring zones by a single factor ---------------- */

export type ColorBy =
  | 'score'
  | 'f_fuel'
  | 'f_slope'
  | 'f_aspect'
  | 'f_history'
  | 'f_power'
  | 'f_roads'
  | 'f_wui';

export const COLOR_OPTIONS: { id: ColorBy; label: string; hint: string }[] = [
  { id: 'score', label: 'Total risk score', hint: '' },
  {
    id: 'f_fuel',
    label: 'Fuel (land cover)',
    hint: 'How readily the CORINE land cover in the zone burns.',
  },
  { id: 'f_slope', label: 'Slope', hint: 'Mean slope, steeper scores higher.' },
  {
    id: 'f_aspect',
    label: 'Aspect',
    hint: 'How much of the zone faces the hot, dry south-west.',
  },
  {
    id: 'f_history',
    label: 'Fire history',
    hint: 'Share of the zone burned up to the training end year.',
  },
  {
    id: 'f_power',
    label: 'Close to power grid',
    hint: 'Closer to power lines scores higher (2 km cap).',
  },
  {
    id: 'f_roads',
    label: 'Close to roads',
    hint: 'Closer to roads scores higher (1 km cap).',
  },
  {
    id: 'f_wui',
    label: 'Next to settlements (WUI)',
    hint: 'Zone borders a settlement: 100, otherwise 0.',
  },
];

/** Sequential purple ramp for single factors, so it can't be mistaken for the red-green risk ramp. */
export const FACTOR_RAMP = ['#f1eef6', '#d7b5d8', '#df65b0', '#dd1c77', '#980043'];

/* ---------------- factor breakdown for the zone popup ---------------- */

export interface FactorDef {
  label: string;
  weight: number; // 0..1, from model.json
  score: (p: Props) => number | null; // 0..100, higher = more risk
  /** Raw value shown to the user. Returns plain text; the caller escapes it. */
  value: (p: Props) => string;
}

const FACTOR_META: Record<
  string,
  { label: string; value: (p: Props) => string }
> = {
  fuel: {
    label: 'Fuel (land cover)',
    value: (p) =>
      p['dominant_clc']
        ? `${p['dominant_clc']}, ${fmt(p['dominant_clc_pct'], 0, '%')} of zone`
        : 'land cover unknown',
  },
  aspect: {
    label: 'Aspect (SW-facing)',
    value: (p) =>
      !isNum(p['aspect_deg'])
        ? '—'
        : isNum(p['aspect_str']) && p['aspect_str'] < 0.3
          ? 'mixed or mostly flat'
          : `faces ${compass(p['aspect_deg'])}`,
  },
  power: {
    label: 'Close to power grid',
    value: (p) => distText(p['dist_power_m'], 'power line'),
  },
  roads: {
    label: 'Close to roads',
    value: (p) => distText(p['dist_roads_m'], 'road'),
  },
  slope: { label: 'Slope', value: (p) => fmt(p['mean_slope'], 1, '°') },
  history: {
    label: 'Fire history',
    // f_history = 100 when HISTORY_FULL_AT (50 %) of the zone burned, so share = score / 2
    value: (p) =>
      isNum(p['f_history']) ? `~${(p['f_history'] * 0.5).toFixed(0)}% burned` : '—',
  },
  wui: {
    label: 'Next to settlements (WUI)',
    // is_wui can arrive as "0" / "False" strings, which are truthy; use the numeric factor instead
    value: (p) => (!isNum(p['f_wui']) ? '—' : p['f_wui'] >= 50 ? 'Yes' : 'No'),
  },
};

/** Builds the factor list from model.json weights (keys like "fuel", "slope"). Unknown keys are skipped. */
export function buildMceFactors(weights: Record<string, number>): FactorDef[] {
  return Object.entries(weights)
    .filter(([k]) => FACTOR_META[k])
    .map(([k, w]) => ({
      label: FACTOR_META[k].label,
      weight: w,
      score: (p: Props) => (isNum(p?.[`f_${k}`]) ? p[`f_${k}`] : null),
      value: FACTOR_META[k].value,
    }));
}
