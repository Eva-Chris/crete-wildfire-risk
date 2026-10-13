import {
  AfterViewInit,
  ChangeDetectorRef,
  Component,
  inject,
  NgZone,
  OnDestroy,
  ViewEncapsulation,
} from '@angular/core';
import * as L from 'leaflet';
import { Observable, Subscription, timer } from 'rxjs';
import { RouterLink } from '@angular/router';
import * as XLSX from 'xlsx';
import { RiskDataService } from '../../services/risk-data.service';
import { esc, fmt, isNum } from '../../lib/format';
import {
  distToGeomM,
  geomBBox,
  M_PER_DEG_LAT,
  metresPerDegLng,
  pointInGeom,
} from '../../lib/geometry';
import {
  buildMceFactors,
  classify,
  ColorBy,
  COLOR_OPTIONS,
  FactorDef,
  FACTOR_RAMP,
  fwiClass,
  RISK_CLASSES,
  applyBreaks,
  scoreOf,
} from '../../lib/risk-model';
import {
  Feat,
  FeatColl,
  FwiResponse,
  FwiStation,
  ModelResponse,
  Props,
  WeatherResponse,
} from '../../lib/types';
import { LanguageService } from '../../services/language.service';
import { Params, translate } from '../../lib/i18n';

/* ------------------------------------------------------------------ */
/* Types & constants                                                   */
/* ------------------------------------------------------------------ */
type Basemap = 'terrain' | 'satellite';
type LayerKey =
  | 'forests'
  | 'powerLines'
  | 'powerNodes'
  | 'powerStations'
  | 'settlements'
  | 'rivers'
  | 'lakes'
  | 'roads'
  | 'windArrows'
  | 'fireStations'
  | 'waterPoints'
  | 'helipads'
  | 'burned';

interface LayerDef {
  key: LayerKey;
  label: string;
  group: string;
  swatch: string;
  shape: 'fill' | 'line' | 'dot';
  visible: boolean;
  loading: boolean;
}

interface ExposureRow {
  id: number;
  name: string;
  ll: L.LatLng;
  props: Props;
  share: number; // 0..1 of the circle that is high-risk forest
  ha: number;
  stationKm: number;
  covered: boolean;
}

interface SettlementPoint {
  name: string;
  ll: L.LatLng;
  props: Props;
}

const EXPO_R = 1000; // metres around each settlement
const EXPO_STEP = 125; // sample grid spacing in metres
const EXPO_CHUNK = 40; // settlements indexed per timer tick, so the page stays responsive

/** Used until /api/model answers. Replace with the value from model.json. */
const DEFAULT_TRAIN_END = 2021;

/** A feature's centre point if it is not already a point (so polygons can be shown as markers). */
const asPoints = (fc: FeatColl | null): FeatColl => ({
  type: 'FeatureCollection',
  features: (fc?.features ?? [])
    .filter((f) => f?.geometry)
    .map((f) => {
      if (f.geometry.type === 'Point') return f;
      const c = L.geoJSON(f).getBounds().getCenter();
      return {
        ...f,
        geometry: { type: 'Point' as const, coordinates: [c.lng, c.lat] },
      };
    }),
});

const nameOf = (p: Props | null | undefined, fallback: string): string =>
  p?.['name'] ?? p?.['name:en'] ?? p?.['NAME'] ?? p?.['onoma'] ?? fallback;

const badgeIcon = (cls: string, html: string, size = 32) =>
  L.divIcon({
    className: 'res-marker',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div class="rm ${cls}">${html}</div>`,
  });

/** Invisible stand-in for stray point features inside line/polygon layers. */
const strayPoint = (_f: unknown, ll: L.LatLng) =>
  L.circleMarker(ll, {
    radius: 2,
    stroke: false,
    fillOpacity: 0,
    interactive: false,
  });

const BASEMAPS: Record<
  Basemap,
  { label: string; url: string; options: L.TileLayerOptions }
> = {
  terrain: {
    label: 'Terrain',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    options: {
      subdomains: 'abc',
      maxZoom: 17,
      attribution: '© OpenStreetMap contributors, SRTM, © OpenTopoMap',
    },
  },
  satellite: {
    label: 'Satellite',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    options: {
      maxZoom: 18,
      attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
    },
  },
};

const CRETE_BOUNDS: L.LatLngBoundsExpression = [
  [34.8, 23.4],
  [35.75, 26.4],
];

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */
@Component({
  selector: 'app-map',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './map.component.html',
  styleUrls: ['./map.component.scss'],
  encapsulation: ViewEncapsulation.None,
})
export class MapComponent implements AfterViewInit, OnDestroy {
  langService = inject(LanguageService);

  /** Translates an English UI string. Reads the language signal, so templates update on toggle. */
  tr = (text: string, params?: Params): string =>
    translate(this.langService.currentLang(), text, params);

  /** Like tr, for [innerHTML]: wraps the named params in <strong>. Only pass numbers here. */
  trHtml(text: string, params: Params, bold: string[] = []): string {
    const p: Params = { ...params };
    for (const k of bold) p[k] = `<strong>${p[k]}</strong>`;
    return this.tr(text, p);
  }

  private map!: L.Map;
  private baseLayer?: L.TileLayer;
  private forestsLayer?: L.GeoJSON;
  private lyr: Partial<Record<LayerKey, L.Layer>> = {};
  private stationMarkers = new Map<number, L.Marker>();
  private features: Feat[] = [];
  private sub = new Subscription();

  /** From /api/model. Empty until it loads, in which case popups skip the factor breakdown. */
  private mceFactors: FactorDef[] = [];

  // Fire weather
  fwi: FwiResponse | null = null;
  fwiLoading = false;
  private fwiMap = new Map<number, FwiStation>();
  fwiClassOf = fwiClass;

  // Settlement exposure
  private settleRaw: SettlementPoint[] = [];
  private settleIdx: (SettlementPoint & { zones: Int32Array })[] = [];
  private exposureReady = false;
  private exposureRun = 0; // bumped on every rebuild so an older, still-running one stops
  exposure: ExposureRow[] = [];
  exposureShown: ExposureRow[] = [];
  onlyUncovered = false;
  showAllExposure = false;

  // Zone colouring
  readonly colorOptions = COLOR_OPTIONS;
  readonly factorRamp = FACTOR_RAMP;
  trainEnd = DEFAULT_TRAIN_END;
  colorBy: ColorBy = 'score';

  // Burned areas
  private burnedLayer?: L.GeoJSON;
  private burnedFeatures: Feat[] = [];
  burnedMin = 2016;
  burnedMax = 2026;
  burnedFrom = 2016;
  burnedTo = 2026;
  burnedCount = { shown: 0, total: 0 };

  readonly basemaps = (Object.keys(BASEMAPS) as Basemap[]).map((id) => ({
    id,
    label: BASEMAPS[id].label,
  }));
  readonly layerGroups = [
    'Risk',
    'Fire history',
    'Firefighting resources',
    'Power grid',
    'Settlements and access',
    'Water',
    'Weather',
  ];

  layers: LayerDef[] = [
    {
      key: 'forests',
      label: 'Forest risk zones',
      group: 'Risk',
      swatch: '#d7191c',
      shape: 'fill',
      visible: true,
      loading: false,
    },
    {
      key: 'powerLines',
      label: 'Transmission lines',
      group: 'Power grid',
      swatch: '#b7791f',
      shape: 'line',
      visible: true,
      loading: false,
    },
    {
      key: 'powerNodes',
      label: 'Pylons and nodes',
      group: 'Power grid',
      swatch: '#4b5563',
      shape: 'dot',
      visible: true,
      loading: false,
    },
    {
      key: 'powerStations',
      label: 'Substations',
      group: 'Power grid',
      swatch: '#7b3294',
      shape: 'fill',
      visible: true,
      loading: false,
    },
    {
      key: 'settlements',
      label: 'Settlements',
      group: 'Settlements and access',
      swatch: '#e7298a',
      shape: 'dot',
      visible: true,
      loading: false,
    },
    {
      key: 'roads',
      label: 'Road network',
      group: 'Settlements and access',
      swatch: '#fb8c2a',
      shape: 'line',
      visible: false,
      loading: false,
    },
    {
      key: 'rivers',
      label: 'Rivers',
      group: 'Water',
      swatch: '#1f78b4',
      shape: 'line',
      visible: false,
      loading: false,
    },
    {
      key: 'lakes',
      label: 'Lakes',
      group: 'Water',
      swatch: '#6baed6',
      shape: 'fill',
      visible: false,
      loading: false,
    },
    {
      key: 'windArrows',
      label: 'Wind at stations',
      group: 'Weather',
      swatch: '#2b6cb0',
      shape: 'dot',
      visible: true,
      loading: false,
    },
    {
      key: 'fireStations',
      label: 'Fire stations',
      group: 'Firefighting resources',
      swatch: '#c81e1e',
      shape: 'dot',
      visible: true,
      loading: false,
    },
    {
      key: 'helipads',
      label: 'Helipads',
      group: 'Firefighting resources',
      swatch: '#1d4ed8',
      shape: 'dot',
      visible: true,
      loading: false,
    },
    {
      key: 'waterPoints',
      label: 'Hydrants and water wells',
      group: 'Firefighting resources',
      swatch: '#0891b2',
      shape: 'dot',
      visible: false,
      loading: false,
    },
    {
      key: 'burned',
      label: 'Burned areas (EFFIS)',
      group: 'Fire history',
      swatch: '#6d28d9',
      shape: 'fill',
      visible: false,
      loading: false,
    },
  ];

  // State shown in the template
  weather: WeatherResponse | null = null;
  weatherLoading = false;
  loadingForests = true;
  error: string | null = null;
  sidebarOpen = true;

  basemap: Basemap = 'terrain';
  forestOpacity = 0.8;
  hiddenClasses = new Set<number>();
  coverageOn = false;
  coverageKm = 10;
  coverage = { known: false, high: 0, gaps: 0, baseGaps: 0, pct: 0 };
  private fireStationPts: L.LatLng[] = [];
  private coverageLayer?: L.LayerGroup;
  stats = RISK_CLASSES.map((c) => ({ ...c, count: 0, pct: 0 }));
  totalZones = 0;

  /** "Add proposed station" mode, and the stations placed so far (not saved anywhere). */
  placing = false;
  hypo: L.Marker[] = [];
  private hypoDist = new Map<Props, number>(); // zone properties -> distance to nearest proposed station

  constructor(
    private api: RiskDataService,
    private cdr: ChangeDetectorRef,
    private zone: NgZone,
  ) {}

  /* ---------------- lifecycle ---------------- */
  ngAfterViewInit(): void {
    setTimeout(() => {
      this.outside(() => this.initMap());
      this.loadModel();
      this.layers.filter((l) => l.visible).forEach((l) => this.activate(l.key));
      this.sub.add(
        timer(0, 10 * 60 * 1000).subscribe(() => this.loadWeather()),
      );
      this.sub.add(timer(0, 3 * 3600 * 1000).subscribe(() => this.loadFwi()));
      this.cdr.markForCheck();
    });
  }

  ngOnDestroy(): void {
    this.exposureRun++; // stop any exposure indexing still running
    this.sub.unsubscribe();
    this.map?.remove();
  }

  /**
   * Runs Leaflet work outside Angular's zone. Leaflet fires many DOM events (every mouse move
   * over a polygon); inside the zone each one would trigger change detection for no reason.
   * Handlers that change component state go back in with zone.run.
   */
  private outside<T>(fn: () => T): T {
    return this.zone.runOutsideAngular(fn);
  }

  private loadModel(): void {
    this.api.getModel().subscribe({
      next: (m: ModelResponse) => {
        applyBreaks(m?.breaks);
        this.mceFactors = buildMceFactors(m?.weights ?? {});
        if (isNum(m?.train_end)) this.trainEnd = m.train_end;
        this.refreshRisk(); // recolours zones and rebuilds the legend
        this.cdr.markForCheck();
      },
      error: () => {
        this.error = this.tr(
          'Could not load /api/model. Using default class breaks.',
        );
        this.cdr.markForCheck();
      },
    });
  }

  layersIn(group: string): LayerDef[] {
    return this.layers.filter((l) => l.group === group);
  }
  isHidden(i: number): boolean {
    return this.hiddenClasses.has(i);
  }

  /* ---------------- map setup ---------------- */
  private initMap(): void {
    this.map = L.map('map', {
      zoomControl: false,
      zoomSnap: 0.5,
      minZoom: 8,
      maxZoom: 17,
      maxBounds: [
        [33.8, 22.4],
        [36.7, 27.4],
      ],
    });
    L.control.zoom({ position: 'bottomright' }).addTo(this.map);
    L.control
      .scale({ position: 'bottomleft', imperial: false })
      .addTo(this.map);

    // Panes fix the drawing order no matter which layer finishes loading first.
    const panes: [string, number][] = [
      ['forestsPane', 410],
      ['coveragePane', 415],
      ['hydroPane', 420],
      ['roadsPane', 430],
      ['burnedPane', 445],
      ['powerPane', 450],
      ['settlePane', 470],
      ['responsePane', 475],
      ['windPane', 480],
    ];
    panes.forEach(
      ([name, z]) => (this.map.createPane(name).style.zIndex = String(z)),
    );

    this.map.on('click', (e: L.LeafletMouseEvent) => {
      if (!this.placing) return;
      this.zone.run(() => {
        this.map.closePopup();
        this.addHypoStation(e.latlng);
      });
    });

    this.setBasemap(this.basemap);
    this.resetView();
    setTimeout(() => this.map.invalidateSize(), 0);
  }

  resetView(): void {
    this.map.fitBounds(CRETE_BOUNDS, { padding: [10, 10] });
  }

  setBasemap(id: Basemap): void {
    this.basemap = id;
    this.outside(() => {
      this.baseLayer?.remove();
      const b = BASEMAPS[id];
      this.baseLayer = L.tileLayer(b.url, b.options).addTo(this.map);
      this.baseLayer.bringToBack();
    });
  }

  toggleSidebar(): void {
    this.sidebarOpen = !this.sidebarOpen;
    setTimeout(() => this.map.invalidateSize(), 320);
  }

  /* ---------------- weather and Fire Weather Index ---------------- */
  loadWeather(manual = false): void {
    this.weatherLoading = true;
    this.cdr.markForCheck();
    this.api.getLiveWeather(manual).subscribe({
      next: (w) => {
        this.weather = w;
        this.weatherLoading = false;
        this.buildStationMarkers();
        this.cdr.markForCheck();
      },
      error: () => {
        this.weatherLoading = false;
        this.error = this.tr(
          'Could not reach the weather service. Check that the API is running and can reach the internet.',
        );
        this.cdr.markForCheck();
      },
    });
  }

  loadFwi(manual = false): void {
    this.fwiLoading = true;
    this.cdr.markForCheck();
    this.api.getFwi(manual).subscribe({
      next: (r) => {
        const stations = (r.stations ?? []).filter((s: FwiStation) =>
          isNum(s.fwi),
        );
        this.fwi = { ...r, stations };
        this.fwiMap = new Map(stations.map((s: FwiStation) => [s.id, s]));
        this.fwiLoading = false;
        this.buildStationMarkers();
        this.cdr.markForCheck();
      },
      error: () => {
        this.fwiLoading = false;
        this.error = this.tr(
          'Could not load the Fire Weather Index. Check the API console.',
        );
        this.cdr.markForCheck();
      },
    });
  }

  refreshFireWeather(): void {
    this.loadWeather(true);
    this.loadFwi(true);
  }

  /** True when either service is showing its last good values because a refresh failed. */
  get weatherStale(): boolean {
    return !!(this.weather?.stale || this.fwi?.stale);
  }

  get fwiSummary() {
    const v = (this.fwi?.stations ?? []).map((s) => s.fwi).filter(isNum);
    if (!v.length) return null;
    const max = Math.max(...v);
    return { max, cls: fwiClass(max) };
  }

  forecastText(s: FwiStation): string {
    return s.forecast?.length
      ? '→ ' + s.forecast.map((d) => d.fwi.toFixed(0)).join(' → ')
      : '';
  }

  flyToFwiStation(s: FwiStation): void {
    this.map.flyTo([s.lat, s.lon], 10.5, { duration: 0.8 });
    this.stationMarkers.get(s.id)?.openPopup();
  }

  /* ---------------- risk zones: styling and statistics ---------------- */

  /** Restyle only. Enough for opacity, class visibility and colour-by changes. */
  private restyle(): void {
    this.forestsLayer?.setStyle((f) => this.forestStyle(f as Feat));
  }

  /** Restyle and recompute the statistics. Needed when the classes or the coverage change. */
  private refreshRisk(): void {
    this.restyle();
    this.updateStats();
  }

  private updateStats(): void {
    const counts = RISK_CLASSES.map(() => 0);
    let high = 0,
      gaps = 0,
      baseGaps = 0,
      known = false;
    for (const f of this.features) {
      const cls = classify(scoreOf(f.properties));
      counts[cls]++;
      if (cls <= 1 && isNum(f.properties?.['dist_fire_m'])) {
        known = true;
        high++;
        if (this.isGap(f.properties)) gaps++;
        if (this.isGap(f.properties, false)) baseGaps++;
      }
    }
    this.coverage = {
      known,
      high,
      gaps,
      baseGaps,
      pct: high ? (gaps / high) * 100 : 0,
    };
    this.totalZones = this.features.length;
    this.stats = RISK_CLASSES.map((c, i) => ({
      ...c,
      count: counts[i],
      pct: this.totalZones ? (counts[i] / this.totalZones) * 100 : 0,
    }));

    this.refreshExposure();
  }

  toggleClass(i: number): void {
    this.hiddenClasses.has(i)
      ? this.hiddenClasses.delete(i)
      : this.hiddenClasses.add(i);
    this.restyle();
  }

  setOpacity(ev: Event): void {
    this.forestOpacity = +(ev.target as HTMLInputElement).value;
    this.restyle();
  }

  setColorBy(ev: Event): void {
    this.colorBy = (ev.target as HTMLSelectElement).value as ColorBy;
    this.restyle();
  }

  get colorHint(): string {
    return COLOR_OPTIONS.find((o) => o.id === this.colorBy)?.hint ?? '';
  }

  layerOn(key: LayerKey): boolean {
    return !!this.layers.find((l) => l.key === key)?.visible;
  }

  private forestStyle(f?: Feat): L.PathOptions {
    const p = f?.properties;
    const cls = classify(scoreOf(p));
    const byScore = this.colorBy === 'score';
    if (byScore && this.hiddenClasses.has(cls))
      return { fill: false, stroke: false };
    const base: L.PathOptions = {
      fill: true,
      stroke: true,
      fillColor: byScore ? RISK_CLASSES[cls].color : this.factorColor(p),
      fillOpacity: this.forestOpacity,
      color: '#1f2937',
      weight: 0.35,
      opacity: 0.45,
      dashArray: '',
    };
    if (!this.coverageOn) return base;

    const gap = this.isGap(p);
    if (gap && cls <= 1) {
      return {
        ...base,
        fillOpacity: Math.min(1, this.forestOpacity + 0.1),
        color: '#111827',
        weight: 1.8,
        opacity: 1,
        dashArray: '5 3',
      };
    }
    return { ...base, fillOpacity: this.forestOpacity * (gap ? 0.55 : 0.3) };
  }

  private factorColor(p: Props | undefined): string {
    const v = p?.[this.colorBy];
    if (!isNum(v)) return '#cbd5e1'; // no data
    return FACTOR_RAMP[Math.min(4, Math.max(0, Math.floor(v / 20)))];
  }

  /* ---------------- coverage ---------------- */

  /** A zone is a gap if it lies farther than the response radius from every station. */
  private isGap(p: Props | undefined, withHypo = true): boolean {
    const base = p?.['dist_fire_m'];
    if (!isNum(base)) return false;
    const d = withHypo
      ? Math.min(base, (p && this.hypoDist.get(p)) ?? Infinity)
      : base;
    return d > this.coverageKm * 1000;
  }

  toggleCoverage(): void {
    this.coverageOn = !this.coverageOn;
    if (this.coverageOn && !this.fireStationPts.length) {
      this.layers.find((l) => l.key === 'fireStations')!.visible = true;
      this.activate('fireStations');
    }
    if (!this.coverageOn) {
      this.placing = false;
      this.map.getContainer().style.cursor = '';
    }
    this.applyCoverage();
  }

  onCoverageKm(ev: Event): void {
    this.coverageKm = +(ev.target as HTMLInputElement).value;
    this.applyCoverage();
  }

  private applyCoverage(): void {
    this.outside(() => {
      this.coverageLayer?.remove();
      this.coverageLayer = undefined;

      if (this.coverageOn) {
        const circle = (ll: L.LatLng, proposed: boolean) =>
          L.circle(ll, {
            pane: 'coveragePane',
            radius: this.coverageKm * 1000,
            interactive: false,
            color: proposed ? '#15803d' : '#b91c1c',
            weight: 1.2,
            opacity: 0.8,
            dashArray: '6 4',
            fillColor: proposed ? '#22c55e' : '#ef4444',
            fillOpacity: 0.08,
          });

        const circles = [
          ...this.fireStationPts.map((ll) => circle(ll, false)),
          ...this.hypo.map((m) => circle(m.getLatLng(), true)),
        ];
        if (circles.length) {
          this.coverageLayer = L.layerGroup(circles).addTo(this.map);
        }
      }
    });

    this.refreshRisk();
    this.cdr.markForCheck();
  }

  togglePlacing(): void {
    this.placing = !this.placing;
    this.map.getContainer().style.cursor = this.placing ? 'crosshair' : '';
  }

  private addHypoStation(ll: L.LatLng): void {
    const marker = this.outside(() => {
      const m = L.marker(ll, {
        pane: 'responsePane',
        draggable: true,
        icon: badgeIcon('fire hypo', '🚒', 34),
      }).addTo(this.map);
      m.bindTooltip(
        () => this.tr('Proposed station (drag to move, click to remove)'),
        {
          direction: 'top',
          offset: [0, -16],
        },
      );
      // Registered outside the zone, so go back in before touching component state
      m.on('dragend', () => this.zone.run(() => this.recomputeHypo()));
      m.on('click', () =>
        this.zone.run(() => {
          m.remove();
          this.hypo = this.hypo.filter((x) => x !== m);
          this.recomputeHypo();
        }),
      );
      return m;
    });
    this.hypo.push(marker);
    this.recomputeHypo();
  }

  clearHypo(): void {
    this.hypo.forEach((m) => m.remove());
    this.hypo = [];
    this.recomputeHypo();
  }

  private recomputeHypo(): void {
    this.hypoDist.clear();
    for (const f of this.features) {
      let d = Infinity;
      for (const m of this.hypo) {
        const ll = m.getLatLng();
        d = Math.min(d, distToGeomM(ll.lat, ll.lng, f.geometry));
      }
      this.hypoDist.set(f.properties, d);
    }
    this.applyCoverage();
    this.cdr.markForCheck();
  }

  /* ---------------- layers ---------------- */
  toggleLayer(key: LayerKey): void {
    const def = this.layers.find((l) => l.key === key)!;
    def.visible = !def.visible;
    if (def.visible) this.activate(key);
    else this.outside(() => this.lyr[key]?.remove());
  }

  /** Adds a layer to the map, downloading it first if this is the first time it's shown. */
  private activate(key: LayerKey): void {
    const def = this.layers.find((l) => l.key === key)!;
    const existing = this.lyr[key];
    if (existing) {
      this.outside(() => existing.addTo(this.map));
      return;
    }
    if (def.loading || key === 'windArrows') return; // wind markers are built when weather arrives

    const source: Observable<FeatColl> = {
      forests: () => this.api.getRiskZones(),
      powerLines: () => this.api.getPowerLines(),
      powerNodes: () => this.api.getPowerNodes(),
      powerStations: () => this.api.getPowerStations(),
      settlements: () => this.api.getSettlements(),
      rivers: () => this.api.getRivers(),
      lakes: () => this.api.getLakes(),
      roads: () => this.api.getRoads(),
      fireStations: () => this.api.getFireStations(),
      waterPoints: () => this.api.getWaterPoints(),
      helipads: () => this.api.getHelipads(),
      burned: () => this.api.getBurnedAreas(),
    }[key as Exclude<LayerKey, 'windArrows'>]();

    def.loading = true;
    if (key === 'forests') this.loadingForests = true;
    this.cdr.markForCheck();

    source.subscribe({
      next: (data) => {
        const layer = this.outside(() =>
          key === 'forests'
            ? this.buildForests(data)
            : this.buildLayer(key, data),
        );
        this.lyr[key] = layer;
        def.loading = false;
        if (key === 'forests') this.loadingForests = false;
        if (def.visible) this.outside(() => layer.addTo(this.map));
        if (key === 'forests' || key === 'settlements')
          this.buildExposureIndex();
        if (key === 'forests' || key === 'fireStations') this.applyCoverage();
        this.cdr.markForCheck();
      },
      error: () => {
        def.loading = false;
        def.visible = false;
        if (key === 'forests') this.loadingForests = false;
        this.error = this.tr(
          'Could not load "{name}". Check the API console for details.',
          { name: this.tr(def.label) },
        );
        this.cdr.markForCheck();
      },
    });
  }

  private buildForests(fc: FeatColl): L.GeoJSON {
    this.features = fc?.features ?? [];
    this.updateStats();
    this.forestsLayer = L.geoJSON(fc, {
      pane: 'forestsPane',
      pointToLayer: strayPoint,
      style: (f) => this.forestStyle(f as Feat),
      onEachFeature: (f, layer) => {
        layer.bindTooltip(
          () => {
            if (this.colorBy !== 'score') {
              const v = f.properties?.[this.colorBy];
              const name = COLOR_OPTIONS.find(
                (o) => o.id === this.colorBy,
              )!.label;
              return `${esc(this.tr(name))}: <b>${isNum(v) ? v.toFixed(0) : '—'}</b>/100`;
            }
            const s = scoreOf(f.properties);
            return `<b>${s.toFixed(1)}</b> ${this.tr(RISK_CLASSES[classify(s)].label).toLowerCase()}`;
          },
          {
            sticky: true,
            className: 'risk-tooltip',
            direction: 'top',
            opacity: 1,
          },
        );
        // Function content: always reflects the current scenario when the popup opens
        layer.bindPopup(() => this.forestPopup(f as Feat), {
          maxWidth: 320,
          className: 'risk-popup wide',
        });
        layer.on({
          mouseover: (e) => {
            const p = e.target as L.Path;
            if (p.options.stroke)
              p.setStyle({ weight: 2.2, color: '#111827', opacity: 1 });
          },
          mouseout: (e) => this.forestsLayer?.resetStyle(e.target),
        });
      },
    });
    return this.forestsLayer;
  }

  private buildLayer(key: LayerKey, data: FeatColl): L.Layer {
    const dot =
      (color: string, radius: number, pane: string) =>
      (_f: unknown, ll: L.LatLng) =>
        L.circleMarker(ll, {
          pane,
          radius,
          fillColor: color,
          fillOpacity: 0.95,
          color: '#fff',
          weight: 1,
        });
    const hydrantOf = (p: Props) =>
      p['emergency'] === 'fire_hydrant' ||
      /hydrant/i.test(String(p['type'] ?? p['fclass'] ?? ''));

    switch (key) {
      case 'powerLines': {
        const glow = L.geoJSON(data, {
          pane: 'powerPane',
          interactive: false,
          pointToLayer: strayPoint,
          style: { color: '#f6ad55', weight: 6, opacity: 0.25 },
        });
        const core = L.geoJSON(data, {
          pane: 'powerPane',
          interactive: false,
          pointToLayer: strayPoint,
          style: { color: '#b7791f', weight: 1.6, opacity: 0.95 },
        });
        return L.layerGroup([glow, core]);
      }
      case 'powerNodes':
        return L.geoJSON(data, {
          pane: 'powerPane',
          interactive: false,
          pointToLayer: (_f, ll) =>
            L.circleMarker(ll, {
              pane: 'powerPane',
              radius: 3,
              fillColor: '#4b5563',
              fillOpacity: 0.95,
              color: '#fff',
              weight: 0.8,
              interactive: false,
            }),
        });
      case 'powerStations':
        return L.geoJSON(data, {
          pane: 'powerPane',
          style: {
            fillColor: '#7b3294',
            color: '#40004b',
            weight: 1.5,
            fillOpacity: 0.65,
          },
          pointToLayer: dot('#7b3294', 7, 'powerPane'),
          onEachFeature: (f, l) =>
            l.bindPopup(
              () => this.propsPopup(this.tr('Substation'), f.properties),
              { className: 'risk-popup' },
            ),
        });
      case 'settlements': {
        this.settleRaw = asPoints(data).features.map((f) => {
          const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates;
          return {
            name: nameOf(f.properties, 'Settlement'),
            ll: L.latLng(lat, lng),
            props: f.properties ?? {},
          };
        });
        return L.geoJSON(data, {
          pane: 'settlePane',
          style: {
            fillColor: '#e7298a',
            color: '#a1155f',
            weight: 1,
            fillOpacity: 0.55,
          },
          pointToLayer: dot('#e7298a', 4.5, 'settlePane'),
          onEachFeature: (f, l) =>
            l.bindPopup(
              () => this.propsPopup(this.tr('Settlement'), f.properties),
              { className: 'risk-popup' },
            ),
        });
      }
      case 'rivers':
        return L.geoJSON(data, {
          pane: 'hydroPane',
          interactive: false,
          pointToLayer: strayPoint,
          style: { color: '#1f78b4', weight: 1.4, opacity: 0.85 },
        });
      case 'lakes':
        return L.geoJSON(data, {
          pane: 'hydroPane',
          interactive: false,
          pointToLayer: strayPoint,
          style: {
            fillColor: '#6baed6',
            color: '#1f78b4',
            weight: 1,
            fillOpacity: 0.75,
          },
        });
      case 'roads':
        return L.geoJSON(data, {
          pane: 'roadsPane',
          interactive: false,
          pointToLayer: strayPoint,
          style: { color: '#fb8c2a', weight: 0.9, opacity: 0.7 },
        });
      case 'fireStations': {
        const pts = asPoints(data);
        this.fireStationPts = pts.features.map((f) => {
          const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates;
          return L.latLng(lat, lng);
        });
        return L.geoJSON(pts, {
          pane: 'responsePane',
          pointToLayer: (_f, ll) =>
            L.marker(ll, {
              pane: 'responsePane',
              icon: badgeIcon('fire', '🚒', 34),
              riseOnHover: true,
            }),
          onEachFeature: (f, l) => {
            const title = () =>
              esc(nameOf(f.properties, this.tr('Fire station')));
            l.bindTooltip(title, {
              direction: 'top',
              offset: [0, -16],
              className: 'risk-tooltip',
            });
            l.bindPopup(() => this.propsPopup(title(), f.properties), {
              className: 'risk-popup',
            });
          },
        });
      }
      case 'burned': {
        this.burnedFeatures = data?.features ?? [];
        const years = this.burnedFeatures
          .map((f) => f.properties?.['year'])
          .filter(isNum);
        if (years.length) {
          this.burnedMin = Math.min(...years);
          this.burnedMax = Math.max(...years);
          this.burnedFrom = this.burnedMin;
          this.burnedTo = this.burnedMax;
        }
        // Not interactive, so clicks still reach the forest zones underneath.
        this.burnedLayer = L.geoJSON(data, {
          pane: 'burnedPane',
          interactive: false,
          pointToLayer: strayPoint,
          style: (f) => this.burnedStyle(f as Feat),
        });
        this.refreshBurned();
        return this.burnedLayer;
      }
      case 'helipads':
        return L.geoJSON(asPoints(data), {
          pane: 'responsePane',
          pointToLayer: (_f, ll) =>
            L.marker(ll, {
              pane: 'responsePane',
              icon: badgeIcon('heli', 'H', 30),
              riseOnHover: true,
            }),
          onEachFeature: (f, l) => {
            const title = () => esc(nameOf(f.properties, this.tr('Helipad')));
            l.bindTooltip(title, {
              direction: 'top',
              offset: [0, -14],
              className: 'risk-tooltip',
            });
            l.bindPopup(() => this.propsPopup(title(), f.properties), {
              className: 'risk-popup',
            });
          },
        });
      case 'waterPoints': {
        const renderer = L.canvas({ pane: 'responsePane', padding: 0.5 });
        return L.geoJSON(asPoints(data), {
          pane: 'responsePane',
          pointToLayer: (f, ll) => {
            const hydrant = hydrantOf(f.properties ?? {});
            return L.circleMarker(ll, {
              renderer,
              radius: hydrant ? 4 : 5,
              fillColor: hydrant ? '#06b6d4' : '#1e3a8a',
              fillOpacity: 0.95,
              color: '#fff',
              weight: 1,
            });
          },
          onEachFeature: (f, l) => {
            const p = f.properties ?? {};
            l.bindPopup(
              () =>
                this.propsPopup(
                  this.tr(hydrantOf(p) ? 'Fire hydrant' : 'Water well'),
                  p,
                ),
              { className: 'risk-popup' },
            );
          },
        });
      }
      default:
        return L.layerGroup();
    }
  }

  /** One arrow per weather station, rotated to the direction the wind is blowing towards. */
  private buildStationMarkers(): void {
    if (!this.weather) return;
    this.outside(() => {
      this.lyr.windArrows?.remove();
      this.stationMarkers.clear();

      const markers = this.weather!.stations.map((s) => {
        const toward = (s.wind_dir + 180) % 360;
        const fw = this.fwiMap.get(s.id);
        const d = fw ? fwiClass(fw.fwi) : { label: 'n/a', color: '#64748b' };
        const icon = L.divIcon({
          className: 'wind-marker',
          iconSize: [60, 54],
          iconAnchor: [30, 27],
          html: `
          <div class="wm" style="--c:${d.color}">
            <svg viewBox="0 0 24 24" width="30" height="30" style="transform:rotate(${toward}deg)">
              <path d="M12 1.5 L19.5 21 L12 16.5 L4.5 21 Z" fill="${d.color}" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>
            </svg>
            <b>${Math.round(s.temp_c)}°</b>
          </div>`,
        });
        const m = L.marker([s.lat, s.lon], {
          icon,
          pane: 'windPane',
          riseOnHover: true,
        });
        m.bindPopup(
          () => `<div class="pop">
    <h4>${esc(this.tr(s.name))}</h4>
    <div class="row"><span>${this.tr('Temperature')}</span><b>${fmt(s.temp_c, 1, ' °C')}</b></div>
    <div class="row"><span>${this.tr('Humidity')}</span><b>${fmt(s.humidity_pct, 0, ' %')}</b></div>
    <div class="row"><span>${this.tr('Wind')}</span><b>${fmt(s.wind_kmh, 0, ' km/h')} ${this.tr('from')} ${fmt(s.wind_dir, 0, '°')}</b></div>
    <div class="row"><span>${this.tr('Fire Weather Index')}</span><b style="color:${d.color}">${fw ? fw.fwi.toFixed(1) + ' ' + this.tr(d.label).toLowerCase() : this.tr('not available')}</b></div>
  </div>`,
          { className: 'risk-popup' },
        );
        this.stationMarkers.set(s.id, m);
        return m;
      });

      const group = L.layerGroup(markers);
      this.lyr.windArrows = group;
      if (this.layerOn('windArrows')) group.addTo(this.map);
    });
  }

  /* ---------------- popups ---------------- */
  private forestPopup(f: Feat): string {
    const tr = this.tr;
    const p = f.properties ?? {};
    const stat = Number(p['static_risk_score'] ?? 0);
    const cls = RISK_CLASSES[classify(stat)];
    const fw = this.fwiMap.get(p['station_id']);
    const fwCls = fw ? fwiClass(fw.fwi) : null;

    const rows = this.mceFactors.map((factor) => {
      const s = factor.score(p);
      return { factor, s, pts: s === null ? null : factor.weight * s };
    });
    const known = rows.reduce((a, r) => a + (r.pts ?? 0), 0);
    const other = stat - known;

    const factorHtml = rows
      .map(
        (r) => `
    <div class="fac">
      <div class="fac-top">
        <span>${esc(tr(r.factor.label))} <em>${Math.round(r.factor.weight * 100)}%</em></span>
        <b>${r.pts === null ? '—' : '+' + r.pts.toFixed(1)}</b>
      </div>
      <i><u style="width:${r.s ?? 0}%"></u></i>
      <small>${esc(tr(r.factor.value(p)))} · ${tr('scored {s}/100', { s: r.s === null ? '—' : r.s.toFixed(0) })}${
        r.pts !== null && stat > 0
          ? ` · ${tr('{pct}% of score', { pct: ((r.pts / stat) * 100).toFixed(0) })}`
          : ''
      }</small>
    </div>`,
      )
      .join('');

    const breakdownHtml = rows.length
      ? `
      <div class="sec">${tr('Why this score')} <b>${stat.toFixed(1)}</b></div>
      ${factorHtml}
      ${
        Math.abs(other) > 0.5
          ? `<div class="fac other"><div class="fac-top"><span>${tr('Unexplained difference')}</span><b>${other >= 0 ? '+' : ''}${other.toFixed(1)}</b></div></div>`
          : `<div class="row calc"><span>${tr('Sum of factors')}</span><b>${known.toFixed(1)}</b></div>`
      }`
      : '';

    const fwiHtml =
      fw && fwCls
        ? `
    <div class="sec">${tr('Fire weather today · {name} station', { name: esc(tr(fw.name)) })}</div>
    <div class="row"><span>${tr('Fire Weather Index')}</span><b style="color:${fwCls.color}">${fw.fwi.toFixed(1)} ${tr(fwCls.label).toLowerCase()}</b></div>
    <div class="row"><span>${tr('Fine fuel dryness (FFMC)')}</span><b>${fw.ffmc.toFixed(0)}</b></div>
    <div class="row"><span>${tr('Drought code (DC)')}</span><b>${fw.dc.toFixed(0)}</b></div>
    <small class="muted">${tr('Weather is shown separately and does not change the score above.')}</small>`
        : '';

    return `
    <div class="pop forest">
      <div class="score" style="--c:${cls.color}">
        <strong>${stat.toFixed(1)}</strong>
        <span>${tr('relative susceptibility: {level}', { level: tr(cls.label) })}</span>
      </div>
      ${breakdownHtml}
      ${fwiHtml}
      <hr/>
      <div class="row"><span>${tr('Zone')}</span><b>#${esc(p['gid'] ?? '—')}</b></div>
      ${isNum(p['elev_m']) ? `<div class="row"><span>${tr('Mean elevation')}</span><b>${fmt(p['elev_m'], 0, ' m')}</b></div>` : ''}
    </div>`;
  }

  /** Popup listing the first few attributes of a feature. `title` must already be escaped. */
  private propsPopup(title: string, props: Props | null, max = 8): string {
    const rows = Object.entries(props ?? {})
      .filter(([, v]) => v !== null && v !== '')
      .slice(0, max)
      .map(
        ([k, v]) =>
          `<div class="row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`,
      )
      .join('');
    return `<div class="pop"><h4>${title}</h4>${rows || `<p class="muted">${this.tr('No attributes in the file.')}</p>`}</div>`;
  }

  /* ---------------- burned areas ---------------- */
  private burnedStyle(f?: Feat): L.PathOptions {
    const y = f?.properties?.['year'];
    if (!isNum(y) || y < this.burnedFrom || y > this.burnedTo) {
      return { fill: false, stroke: false };
    }
    const late = y > this.trainEnd; // validation period
    return {
      fill: true,
      stroke: true,
      fillColor: late ? '#6d28d9' : '#64748b',
      fillOpacity: 0.45,
      color: late ? '#4c1d95' : '#334155',
      weight: 1.2,
      opacity: 0.9,
    };
  }

  private refreshBurned(): void {
    this.burnedLayer?.setStyle((f) => this.burnedStyle(f as Feat));
    const inRange = this.burnedFeatures.filter((f) => {
      const y = f.properties?.['year'];
      return isNum(y) && y >= this.burnedFrom && y <= this.burnedTo;
    });
    this.burnedCount = {
      shown: inRange.length,
      total: this.burnedFeatures.length,
    };
  }

  onBurnedYear(which: 'from' | 'to', ev: Event): void {
    const v = +(ev.target as HTMLInputElement).value;
    if (which === 'from') {
      this.burnedFrom = v;
      if (v > this.burnedTo) this.burnedTo = v;
    } else {
      this.burnedTo = v;
      if (v < this.burnedFrom) this.burnedFrom = v;
    }
    this.refreshBurned();
  }

  setBurnedPeriod(p: 'all' | 'validation'): void {
    this.burnedFrom =
      p === 'all'
        ? this.burnedMin
        : Math.min(this.trainEnd + 1, this.burnedMax);
    this.burnedTo = this.burnedMax;
    this.refreshBurned();
  }

  /* ---------------- settlement exposure ---------------- */

  /**
   * For each settlement, samples a grid of points inside a 1 km circle and records which
   * forest zone each point falls in (-1 = none). Later, refreshExposure only has to look
   * up the class of those zones, so moving a slider is cheap.
   *
   * The sampling is the slow part (point-in-polygon for thousands of settlements), so it runs
   * in small chunks with a timer in between and the page stays responsive while it works.
   */
  private buildExposureIndex(): void {
    if (!this.features.length || !this.settleRaw.length) return;
    const run = ++this.exposureRun;
    this.exposureReady = false;
    this.settleIdx = [];

    const boxes = this.features.map((f) => geomBBox(f.geometry));
    const offsets: [number, number][] = [];
    for (let dx = -EXPO_R; dx <= EXPO_R; dx += EXPO_STEP)
      for (let dy = -EXPO_R; dy <= EXPO_R; dy += EXPO_STEP)
        if (dx * dx + dy * dy <= EXPO_R * EXPO_R) offsets.push([dx, dy]);

    let next = 0;
    const step = () => {
      if (run !== this.exposureRun) return; // a newer rebuild started, or the page closed
      const end = Math.min(next + EXPO_CHUNK, this.settleRaw.length);
      for (; next < end; next++)
        this.settleIdx.push(
          this.indexSettlement(this.settleRaw[next], boxes, offsets),
        );
      if (next < this.settleRaw.length) {
        setTimeout(step, 0);
      } else {
        this.zone.run(() => {
          this.exposureReady = true;
          this.refreshExposure();
        });
      }
    };
    this.outside(step);
  }

  private indexSettlement(
    s: SettlementPoint,
    boxes: ([number, number, number, number] | null)[],
    offsets: [number, number][],
  ) {
    const kx = metresPerDegLng(s.ll.lat);
    const dLng = EXPO_R / kx,
      dLat = EXPO_R / M_PER_DEG_LAT;
    // Only test zones whose bounding box touches the circle's bounding box
    const candidates: number[] = [];
    boxes.forEach((b, i) => {
      if (
        b &&
        b[0] <= s.ll.lng + dLng &&
        b[2] >= s.ll.lng - dLng &&
        b[1] <= s.ll.lat + dLat &&
        b[3] >= s.ll.lat - dLat
      )
        candidates.push(i);
    });
    const zones = new Int32Array(offsets.length).fill(-1);
    if (candidates.length) {
      offsets.forEach(([dx, dy], k) => {
        const x = s.ll.lng + dx / kx,
          y = s.ll.lat + dy / M_PER_DEG_LAT;
        for (const i of candidates)
          if (pointInGeom(x, y, this.features[i].geometry)) {
            zones[k] = i;
            break;
          }
      });
    }
    return { ...s, zones };
  }

  refreshExposure(): void {
    if (!this.exposureReady) return;
    const high = this.features.map((f) => classify(scoreOf(f.properties)) <= 1);
    const stations = [
      ...this.fireStationPts,
      ...this.hypo.map((m) => m.getLatLng()),
    ];
    const limit = this.coverageKm * 1000;
    const circleHa = (Math.PI * EXPO_R * EXPO_R) / 10_000;

    this.exposure = this.settleIdx
      .map((s, id): ExposureRow => {
        let hit = 0;
        for (const z of s.zones) if (z >= 0 && high[z]) hit++;
        const share = hit / s.zones.length;
        let d = Infinity;
        for (const st of stations) d = Math.min(d, s.ll.distanceTo(st));
        return {
          id,
          name: s.name,
          ll: s.ll,
          share,
          ha: share * circleHa,
          stationKm: d / 1000,
          covered: d <= limit,
          props: s.props,
        };
      })
      .filter((r) => r.share > 0)
      .sort((a, b) => b.share - a.share);

    const list = this.onlyUncovered
      ? this.exposure.filter((r) => !r.covered)
      : this.exposure;
    this.exposureShown = this.showAllExposure ? list : list.slice(0, 20);
    this.cdr.markForCheck();
  }

  toggleUncovered(): void {
    this.onlyUncovered = !this.onlyUncovered;
    this.refreshExposure();
  }

  toggleShowAll(): void {
    this.showAllExposure = !this.showAllExposure;
    this.refreshExposure();
  }

  flyToSettlement(r: ExposureRow): void {
    this.map.flyTo(r.ll, 13, { duration: 0.8 });
    this.map.once('moveend', () => {
      L.popup({ className: 'risk-popup', offset: [0, -6] })
        .setLatLng(r.ll)
        .setContent(this.settlementPopup(r))
        .openOn(this.map);
    });
  }

  private settlementPopup(r: ExposureRow): string {
    const tr = this.tr;
    const attrs = Object.entries(r.props ?? {})
      .filter(([, v]) => v !== null && v !== '')
      .slice(0, 6)
      .map(
        ([k, v]) =>
          `<div class="row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`,
      )
      .join('');
    return `
    <div class="pop">
      <h4>${esc(r.name)}</h4>
      <div class="row"><span>${tr('High-risk forest within 1 km')}</span><b>${r.ha.toFixed(0)} ha (${(r.share * 100).toFixed(0)}%)</b></div>
      <div class="row"><span>${tr('Nearest fire station')}</span><b>${r.stationKm.toFixed(1)} km</b></div>
      <div class="row"><span>${tr('Status at {km} km', { km: this.coverageKm })}</span><b style="color:${r.covered ? '#166534' : '#991b1b'}">${tr(r.covered ? 'covered' : 'uncovered')}</b></div>
      ${attrs ? '<hr/>' + attrs : ''}
    </div>`;
  }

  /* ---------------- exports ---------------- */
  exportExposure(): void {
    const tr = this.tr;
    const rows = this.exposure.map((r) => ({
      [tr('Settlement')]: r.name,
      [tr('Latitude')]: +r.ll.lat.toFixed(5),
      [tr('Longitude')]: +r.ll.lng.toFixed(5),
      [tr('High-risk forest within 1 km (ha)')]: Math.round(r.ha),
      [tr('Share of 1 km circle (%)')]: Math.round(r.share * 100),
      [tr('Nearest station (km)')]: +r.stationKm.toFixed(1),
      [tr('Covered')]: tr(r.covered ? 'yes' : 'no'),
    }));

    const ws = XLSX.utils.json_to_sheet(rows);
    ws['!cols'] = [
      { wch: 28 },
      { wch: 12 },
      { wch: 12 },
      { wch: 22 },
      { wch: 16 },
      { wch: 16 },
      { wch: 12 },
    ];

    const info = XLSX.utils.aoa_to_sheet([
      [tr('Exported'), new Date().toISOString().slice(0, 16).replace('T', ' ')],
      [
        tr('Scoring'),
        tr('Static susceptibility score (no weather adjustment)'),
      ],
      [tr('Coverage radius (km)'), this.coverageKm],
      [tr('Proposed stations'), this.hypo.length],
      [
        tr('Note'),
        tr(
          'Straight-line distances. High risk = top two percentile classes of the score.',
        ),
      ],
    ]);
    info['!cols'] = [{ wch: 24 }, { wch: 80 }];

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, tr('Exposure'));
    XLSX.utils.book_append_sheet(wb, info, tr('Scenario'));
    XLSX.writeFile(wb, 'settlement_exposure.xlsx');
  }

  exportCSV(): void {
    const head =
      'settlement,lat,lng,high_risk_forest_ha_within_1km,share_pct,nearest_station_km,covered\n';
    const body = this.exposure
      .map((r) =>
        [
          `"${r.name.replace(/"/g, '""')}"`,
          r.ll.lat.toFixed(5),
          r.ll.lng.toFixed(5),
          r.ha.toFixed(0),
          (r.share * 100).toFixed(0),
          r.stationKm.toFixed(1),
          r.covered ? 'yes' : 'no',
        ].join(','),
      )
      .join('\n');
    // The BOM makes Excel read the file as UTF-8, so Greek names don't turn into gibberish
    const url = URL.createObjectURL(
      new Blob(['\uFEFF' + head + body], { type: 'text/csv;charset=utf-8' }),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = 'settlement_exposure.csv';
    a.click();
    URL.revokeObjectURL(url);
  }
}
