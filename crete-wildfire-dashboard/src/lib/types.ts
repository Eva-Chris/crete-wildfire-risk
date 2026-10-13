/** Shapes of the JSON the API returns. */

export type Props = Record<string, any>;
export type Feat = GeoJSON.Feature<GeoJSON.Geometry, Props>;
export type FeatColl = GeoJSON.FeatureCollection<GeoJSON.Geometry, Props>;

export interface Station {
  id: number;
  name: string;
  lat: number;
  lon: number;
  temp_c: number;
  humidity_pct: number;
  wind_kmh: number;
  wind_dir: number;
}

export interface WeatherResponse {
  updated: string;
  /** True when Open-Meteo could not be reached and this is the last good reading. */
  stale?: boolean;
  stations: Station[];
}

export interface AccessResponse {
  available: boolean;
  max_min?: number;
  zone_buffer_m?: number;
  n_zones?: number;
  n_settlements?: number;
  zones?: (number | null)[]; // minutes, indexed by the zone's `zid`
  settlements?: (number | null)[]; // minutes, same order as the settlements layer
  snap_m?: number[];
}

export interface FwiStation {
  id: number;
  name: string;
  lat: number;
  lon: number;
  date: string;
  fwi: number;
  isi: number;
  bui: number;
  ffmc: number;
  dmc: number;
  dc: number;
  forecast: { date: string; fwi: number }[];
}

export interface FwiResponse {
  live: boolean;
  /** True when the last refresh failed and these are the previous values. */
  stale?: boolean;
  in_season: boolean;
  computed?: string;
  stations: FwiStation[];
}

/** Written by build_static_risk.py. */
export interface Validation {
  n_zones: number;
  n_positive: number;
  min_burned_frac: number;
  auc_model: number;
  auc_previous: number | null;
  /** Keys look like "f_fuel". */
  auc_factors: Record<string, number>;
}

export interface ModelResponse {
  weights: Record<string, number>;
  /** [p20, p40, p60, p80] of the static score. */
  breaks: number[];
  train_end: number;
  validation?: Validation | null;
}
