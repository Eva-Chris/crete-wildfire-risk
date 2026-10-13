import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { RiskDataService } from '../../services/risk-data.service';
import { ModelResponse, Validation } from '../../lib/types';
import { LanguageService } from '../../services/language.service';

interface Section {
  id: string;
  titleEn: string;
  titleEl: string;
}

@Component({
  selector: 'app-docs',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './docs.component.html',
  styleUrls: ['./docs.component.scss'],
})
export class DocsComponent implements OnInit {
  langService = inject(LanguageService);

  readonly sections: Section[] = [
    {
      id: 'overview',
      titleEn: 'What this tool is',
      titleEl: 'Τι είναι αυτό το εργαλείο',
    },
    {
      id: 'score',
      titleEn: 'The static risk score',
      titleEl: 'Ο στατικός δείκτης κινδύνου',
    },
    { id: 'weather', titleEn: 'Fire weather', titleEl: 'Κίνδυνος λόγω καιρού' },
    {
      id: 'reliability',
      titleEn: 'How reliable is it?',
      titleEl: 'Πόσο αξιόπιστο είναι;',
    },
    {
      id: 'coverage',
      titleEn: 'Response coverage',
      titleEl: 'Κάλυψη ανταπόκρισης',
    },
    {
      id: 'exposure',
      titleEn: 'Settlement exposure',
      titleEl: 'Έκθεση οικισμών',
    },
    { id: 'data', titleEn: 'Data sources', titleEl: 'Πηγές δεδομένων' },
    { id: 'limits', titleEn: 'Limitations', titleEl: 'Περιορισμοί' },
    { id: 'faq', titleEn: 'FAQ', titleEl: 'Συχνές Ερωτήσεις' },
  ];

  /** Δυναμικός τίτλος για το ΤOC ανάλογα με τη γλώσσα */
  getSections() {
    const isEl = this.langService.currentLang() === 'el';
    return this.sections.map((s) => ({
      id: s.id,
      title: isEl ? s.titleEl : s.titleEn,
    }));
  }

  /** Display names and descriptions for the keys in model.json in both languages */
  readonly labels: Record<
    string,
    { nameEn: string; nameEl: string; howEn: string; howEl: string }
  > = {
    fuel: {
      nameEn: 'Fuel (land cover)',
      nameEl: 'Καύσιμη ύλη (κάλυψη γης)',
      howEn:
        'CORINE 2012 class, scored from how much of each class burned in 2016 to the training end year',
      howEl:
        'Κλάση CORINE 2012, βαθμολογημένη με βάση το πόσο κάηκε από το 2016 έως το τέλος της περιόδου εκπαίδευσης',
    },
    slope: {
      nameEn: 'Slope',
      nameEl: 'Κλίση εδάφους',
      howEn: 'Mean slope of the zone, 35° and above scores 100',
      howEl: 'Μέση κλίση της ζώνης, 35° και άνω βαθμολογείται με 100',
    },
    aspect: {
      nameEn: 'Aspect',
      nameEl: 'Προσανατολισμός (Aspect)',
      howEn: 'How much of the zone faces south-west (hot, dry afternoon sun)',
      howEl:
        'Τμήμα της ζώνης με νοτιοδυτικό προσανατολισμό (θερμός, ξηρός απογευματινός ήλιος)',
    },
    history: {
      nameEn: 'Fire history',
      nameEl: 'Ιστορικό πυρκαγιών',
      howEn:
        'Share of the zone burned up to the training end year; 50% burned scores 100',
      howEl:
        'Ποσοστό της ζώνης που κάηκε έως το τέλος της εκπαίδευσης· 50% καμένη έκταση βαθμολογείται με 100',
    },
    power: {
      nameEn: 'Close to power grid',
      nameEl: 'Εγγύτητα σε δίκτυο ηλεκτροδότησης',
      howEn:
        'Distance to nearest power line, 0 m scores 100, 2 km or more scores 0',
      howEl:
        'Απόσταση από πλησιέστερο καλώδιο ρεύματος, 0 m βαθμολογείται με 100, 2 km ή περισσότερο με 0',
    },
    roads: {
      nameEn: 'Close to roads',
      nameEl: 'Εγγύτητα σε οδικό δίκτυο',
      howEn: 'Distance to nearest road, 0 m scores 100, 1 km or more scores 0',
      howEl:
        'Απόσταση από πλησιέστερο δρόμο, 0 m βαθμολογείται με 100, 1 km ή περισσότερο με 0',
    },
    wui: {
      nameEn: 'Next to settlements',
      nameEl: 'Γειτνίαση με οικισμούς',
      howEn: 'Zone borders a settlement: 100, otherwise 0',
      howEl: 'Η ζώνη συνορεύει με οικισμό: 100, διαφορετικά 0',
    },
  };

  /** Λήψη κατάλληλου label ανάλογα με τη γλώσσα */
  getLabel(key: string) {
    const l = this.labels[key];
    if (!l) return { name: key, how: '' };
    const isEl = this.langService.currentLang() === 'el';
    return {
      name: isEl ? l.nameEl : l.nameEn,
      how: isEl ? l.howEl : l.howEn,
    };
  }

  weights = signal<{ key: string; pct: number }[]>([]);
  breaks = signal<number[]>([]);
  trainEnd = signal(2021);
  validation = signal<Validation | null>(null);
  status = signal<'loading' | 'ok' | 'empty' | 'error'>('loading');

  /** Rows of the reliability table */
  validationRows = computed(() => {
    const v = this.validation();
    if (!v) return [];
    const isEl = this.langService.currentLang() === 'el';

    const rows = [
      { label: isEl ? 'Αυτό το μοντέλο' : 'This model', auc: v.auc_model },
    ];
    if (v.auc_previous !== null)
      rows.push({
        label: isEl
          ? 'Προηγούμενη έκδοση του μοντέλου'
          : 'Previous version of the model',
        auc: v.auc_previous,
      });
    for (const [col, auc] of Object.entries(v.auc_factors)) {
      const key = col.replace(/^f_/, '');
      const labelObj = this.getLabel(key);
      rows.push({
        label: isEl ? `${labelObj.name} μόνος/η` : `${labelObj.name} alone`,
        auc,
      });
    }
    return rows;
  });

  constructor(private api: RiskDataService) {}

  ngOnInit(): void {
    this.api.getModel().subscribe({
      next: (m: ModelResponse) => {
        const w = Object.entries(m?.weights ?? {}).map(([key, v]) => ({
          key,
          pct: Math.round(v * 100),
        }));
        this.weights.set(w);
        this.breaks.set(m?.breaks ?? []);
        if (typeof m?.train_end === 'number') this.trainEnd.set(m.train_end);
        this.validation.set(m?.validation ?? null);
        this.status.set(w.length ? 'ok' : 'empty');
      },
      error: (e) => {
        console.error('Could not load /api/model', e);
        this.status.set('error');
      },
    });
  }

  go(id: string, ev: Event): void {
    ev.preventDefault();
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
