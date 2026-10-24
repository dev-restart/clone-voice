import { t } from '../i18n/core.ts';
import { apiFetch } from './api';

export async function downloadResponse(response: Response, filename: string): Promise<void> {
	const url = URL.createObjectURL(await response.blob());
	const anchor = document.createElement('a');
	anchor.href = url;
	anchor.download = filename;
	anchor.hidden = true;
	document.body.appendChild(anchor);
	anchor.click();
	anchor.remove();
	// Keep the blob alive while the browser hands the download to the OS.
	window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function downloadFile(path: string, filename: string): Promise<void> {
	await downloadResponse(await apiFetch(path), filename);
}

export type AudioDownloadFormat = 'mp3' | 'wav';

export function audioExportPath(path: string, format: AudioDownloadFormat = 'mp3'): string {
	if (format !== 'mp3' && format !== 'wav') throw new Error(t('download.format'));
	const match = /^\/api\/files\/(voices|outputs|uploads)\/([^/]+)$/.exec(path.split(/[?#]/, 1)[0]);
	if (!match) throw new Error(t('download.scope'));
	let filename: string;
	try {
		filename = decodeURIComponent(match[2]);
	} catch {
		// The API can return URLs whose file name has an unencoded %.
		filename = match[2];
	}
	if (!filename || filename === '.' || filename === '..' || /[\\/\u0000-\u001f]/.test(filename)) {
		throw new Error(t('download.path'));
	}
	// Drop any download options from the source URL and request the export API instead.
	return `/api/files/${match[1]}/${encodeURIComponent(filename)}/export?format=${format}`;
}

export function audioDownloadFilename(filename: string, format: AudioDownloadFormat = 'mp3'): string {
	const name = filename
		.replace(/\.(?:wav|mp3|ogg|m4a|aac|flac|aiff?|webm|mp4)$/i, '')
		.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '-')
		.trim()
		.slice(0, 160);
	return `${name || 'audio'}.${format}`;
}

export async function downloadAudio(path: string, filename: string, format: AudioDownloadFormat = 'mp3'): Promise<void> {
	await downloadFile(audioExportPath(path, format), audioDownloadFilename(filename, format));
}
