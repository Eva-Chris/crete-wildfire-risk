import { Injectable, signal } from '@angular/core';

export type Language = 'en' | 'el';

@Injectable({
  providedIn: 'root',
})
export class LanguageService {
  currentLang = signal<Language>('el');

  setLanguage(lang: Language) {
    this.currentLang.set(lang);
    localStorage.setItem('app_lang', lang);
  }

  toggleLanguage() {
    const nextLang = this.currentLang() === 'el' ? 'en' : 'el';
    this.setLanguage(nextLang);
  }

  constructor() {
    const saved = localStorage.getItem('app_lang') as Language;
    if (saved === 'el' || saved === 'en') {
      this.currentLang.set(saved);
    }
  }
}
