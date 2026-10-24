// Translation lookup without any UI framework dependency, so pure modules and node:test can use it too.
// The Svelte layer (index.svelte.ts) plugs in a reactive locale provider; without one the locale is Korean.
import { ko, type MessageKey } from './messages/ko.ts';
import { en } from './messages/en.ts';

export type Locale = 'ko' | 'en';
export type { MessageKey };
export type Params = Record<string, string | number>;

const tables: Record<Locale, Record<string, string>> = { ko, en };
let currentLocale: () => Locale = () => 'ko';

export function setLocaleProvider(provider: () => Locale) {
	currentLocale = provider;
}

export function getLocale(): Locale {
	return currentLocale();
}

/** Translate a key; `{name}` placeholders are replaced from `params`. Missing English falls back to Korean. */
export function t(key: MessageKey, params?: Params): string {
	const template = tables[currentLocale()][key] ?? ko[key] ?? key;
	if (!params) return template;
	return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

/** Adds a `label` getter so lists of options re-render when the display language changes. */
export function labeled<T extends object>(base: T, key: MessageKey): T & { readonly label: string } {
	return Object.defineProperty({ ...base }, 'label', { get: () => t(key), enumerable: true }) as T & { readonly label: string };
}

/** Same idea for any other translated field (title, description, ...). */
export function localized<T extends object>(base: T, fields: Record<string, MessageKey>): T {
	const target = { ...base } as T;
	for (const [field, key] of Object.entries(fields)) Object.defineProperty(target, field, { get: () => t(key), enumerable: true });
	return target;
}

/** A record whose values are translated on every read (use for `Record<Key, string>` label maps). */
export function localizedRecord<K extends string>(keys: Record<K, MessageKey>): Record<K, string> {
	const target = {} as Record<K, string>;
	for (const [field, key] of Object.entries(keys) as [K, MessageKey][]) Object.defineProperty(target, field, { get: () => t(key), enumerable: true });
	return target;
}
