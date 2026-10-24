import { setLocaleProvider, t, type Locale, type MessageKey } from './core.ts';

export { t };
export type { Locale, MessageKey };

export const LOCALES: ReadonlyArray<{ code: Locale; label: string; intl: string }> = [
	{ code: 'ko', label: '한국어', intl: 'ko-KR' },
	{ code: 'en', label: 'English', intl: 'en-US' }
];

const STORAGE_KEY = 'clonevoice.locale.v1';
function isLocale(value: unknown): value is Locale {
	return value === 'ko' || value === 'en';
}

class I18n {
	locale = $state<Locale>('ko');

	get intl() {
		return LOCALES.find((item) => item.code === this.locale)?.intl ?? 'ko-KR';
	}

	/** Picks the saved language, otherwise the browser language. Call once on the client. */
	init() {
		let saved: string | null = null;
		try { saved = localStorage.getItem(STORAGE_KEY); } catch { /* Storage can be blocked; the browser language still applies. */ }
		const preferred = isLocale(saved) ? saved : navigator.language?.toLowerCase().startsWith('ko') ? 'ko' : 'en';
		this.apply(preferred);
	}

	set(locale: Locale) {
		this.apply(locale);
		try { localStorage.setItem(STORAGE_KEY, locale); } catch { /* The choice still applies for this session. */ }
	}

	private apply(locale: Locale) {
		this.locale = locale;
		if (typeof document !== 'undefined') document.documentElement.lang = locale;
	}
}

export const i18n = new I18n();

// Reading `i18n.locale` inside `t()` makes templates and $derived values re-render when the language changes.
setLocaleProvider(() => i18n.locale);
