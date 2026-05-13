import { env } from '$env/dynamic/public';

export const apiBase = env.PUBLIC_API_BASE || '';

export function apiWebSocketUrl(path: string) {
	if (typeof window === 'undefined') return path;
	const base = apiBase || window.location.origin;
	const url = new URL(path, base);
	url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
	return url.toString();
}

export type ApiLogEntry = {
	id: string;
	method: string;
	url: string;
	status?: number;
	ok: boolean;
	duration_ms: number;
	error?: string;
	at: string;
};

export function audioUrl(path?: string | null) {
	if (!path) return '';
	if (/^(https?:|blob:|data:)/.test(path)) return path;
	return `${apiBase}${path}`;
}

function emitApiLog(entry: ApiLogEntry) {
	if (typeof window === 'undefined') return;
	window.dispatchEvent(new CustomEvent<ApiLogEntry>('clonevoice:api-log', { detail: entry }));
}

function buildApiLog(path: string, init: RequestInit | undefined, started: number, response?: Response, error?: unknown): ApiLogEntry {
	const method = init?.method ?? 'GET';
	const url = `${apiBase}${path}`;
	return {
		id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
		method,
		url,
		status: response?.status,
		ok: response?.ok ?? false,
		duration_ms: Math.round(performance.now() - started),
		error: error instanceof Error ? error.message : error ? String(error) : undefined,
		at: new Date().toLocaleTimeString('ko-KR')
	};
}

export async function apiFetch(path: string, init?: RequestInit) {
	const started = performance.now();
	let response: Response;
	try {
		response = await fetch(`${apiBase}${path}`, init);
	} catch (error) {
		const entry = buildApiLog(path, init, started, undefined, error);
		emitApiLog(entry);
		throw new Error(`네트워크 오류: ${entry.method} ${entry.url} (${entry.error})`);
	}
	emitApiLog(buildApiLog(path, init, started, response));
	if (!response.ok) {
		const method = init?.method ?? 'GET';
		const url = `${apiBase}${path}`;
		let detail = `${method} ${url} 요청 실패 (${response.status})`;
		try {
			const payload = await response.json();
			const payloadDetail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail ?? payload);
			detail = `${method} ${url} 요청 실패 (${response.status}): ${payloadDetail}`;
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
	return new Date(value).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' });
}

export const languages = [
	{ code: 'ko', label: '한국어' },
	{ code: 'en', label: 'English' },
	{ code: 'ja', label: '日本語' },
	{ code: 'zh', label: '中文' },
	{ code: 'es', label: 'Español' },
	{ code: 'fr', label: 'Français' },
	{ code: 'de', label: 'Deutsch' }
];

export const accents = [
	{ value: '', label: '언어 기준 자동' },
	{ value: 'american accent', label: '미국식 영어' },
	{ value: 'british accent', label: '영국식 영어' },
	{ value: 'canadian accent', label: '캐나다식 영어' },
	{ value: 'australian accent', label: '호주식 영어' }
];
