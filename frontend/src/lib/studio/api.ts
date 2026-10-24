import { env } from '$env/dynamic/public';
import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
import { labeled } from '$lib/i18n/core';

export const apiBase = env.PUBLIC_API_BASE || '';

export function apiWebSocketUrl(path: string) {
	if (typeof window === 'undefined') return path;
	const base = apiBase || window.location.origin;
	const url = new URL(path, base);
	url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
	return url.toString();
}

export function audioUrl(path?: string | null) {
	if (!path) return '';
	if (/^(https?:|blob:|data:)/.test(path)) return path;
	return `${apiBase}${path}`;
}

export async function apiFetch(path: string, init?: RequestInit) {
	let response: Response;
	try {
		const headers = new Headers(init?.headers);
		if (!headers.has('Accept-Language')) headers.set('Accept-Language', i18n.locale);
		response = await fetch(`${apiBase}${path}`, { ...init, headers });
	} catch (error) {
		const reason = error instanceof Error ? error.message : String(error);
		throw new Error(t('api.offline', { reason }));
	}
	if (!response.ok) {
		let detail = t('api.failed', { status: response.status });
		try {
			const payload = await response.json();
			const payloadDetail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail ?? payload);
			detail = `${detail} ${payloadDetail}`;
		} catch {
			// Keep default detail when the server returns a non-JSON error body.
		}
		throw new Error(detail);
	}
	return response;
}

export function formatTime(value?: number | null) {
	if (value === null || value === undefined || Number.isNaN(value)) return '--:--';
	const total = Math.max(0, Math.round(value));
	const minutes = Math.floor(total / 60);
	const seconds = String(total % 60).padStart(2, '0');
	return `${minutes}:${seconds}`;
}

export function formatDate(value?: string | null) {
	if (!value) return '-';
	return new Date(value).toLocaleString(i18n.intl, { dateStyle: 'medium', timeStyle: 'short' });
}

export function formatFileSize(value?: number | null) {
	if (value === null || value === undefined || Number.isNaN(value)) return '-';
	const units = ['B', 'KB', 'MB', 'GB'];
	let size = Math.max(0, value);
	let unitIndex = 0;
	while (size >= 1024 && unitIndex < units.length - 1) {
		size /= 1024;
		unitIndex += 1;
	}
	const digits = size >= 10 || unitIndex === 0 ? 0 : 1;
	return `${size.toFixed(digits)} ${units[unitIndex]}`;
}

export const languages = (['ko', 'en', 'ja', 'zh', 'es', 'fr', 'de'] as const).map((code) =>
	labeled({ code }, `lang.${code}` as MessageKey)
);

export const accents = [
	labeled({ value: '' }, 'accent.auto'),
	labeled({ value: 'american accent' }, 'accent.american'),
	labeled({ value: 'british accent' }, 'accent.british'),
	labeled({ value: 'canadian accent' }, 'accent.canadian'),
	labeled({ value: 'australian accent' }, 'accent.australian')
];
