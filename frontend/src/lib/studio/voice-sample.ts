export type SampleRegionKind = 'speech' | 'mixed' | 'music' | 'singing' | 'sound' | 'silence';
export type SampleRegion = { start: number; end: number; kind: SampleRegionKind };
export type SampleCandidate = { id: string; start: number; end: number; label: string; reasons: string[]; speech_fraction: number | null };
export type SampleAnalysis = { duration_seconds: number; engine: 'apple-sound-analysis' | 'signal'; message: string; warnings: string[]; regions: SampleRegion[]; candidates: SampleCandidate[] };
export type TimedTranscript = { start: number; end: number; text: string };

export function clampSampleRange(start: number, end: number, duration: number) {
    if (![start, end, duration].every(Number.isFinite) || duration <= 0) return null;
    const minimum = Math.min(.05, duration);
    const left = Math.min(Math.max(0, start), Math.max(0, duration - minimum));
    const right = Math.min(duration, Math.max(left + minimum, end));
    return { start: Number(left.toFixed(3)), end: Number(right.toFixed(3)) };
}

export function sampleRangeKey(sourceRevision: number, start: number, end: number) {
    return [sourceRevision, Math.round(start * 1000), Math.round(end * 1000)].join(':');
}

export function sampleTranscriptWindow(start: number, end: number, duration: number) {
    const width = Math.min(30, duration);
    const center = start + Math.min(30, end - start) / 2;
    const left = Math.max(0, Math.min(center - width / 2, duration - width));
    return { start: Number(left.toFixed(3)), end: Number(Math.min(duration, left + width).toFixed(3)) };
}

export function groupSampleTranscript(segments: TimedTranscript[]): TimedTranscript[] {
    const rows: TimedTranscript[] = [];
    for (const segment of segments) {
        if (!Number.isFinite(segment.start) || !Number.isFinite(segment.end) || segment.start < 0 || segment.end <= segment.start || !segment.text.trim()) continue;
        const last = rows.at(-1);
        if (last && segment.start >= last.end - .05 && segment.start - last.end < .8
            && segment.end - last.start <= 10 && !/[.!?。！？]$/.test(last.text)) {
            last.end = segment.end;
            last.text += ' ' + segment.text.trim();
        } else rows.push({ ...segment, text: segment.text.trim() });
    }
    return rows;
}

export function sampleTime(seconds: number) {
    const tenths = Math.max(0, Math.round(seconds * 10));
    return Math.floor(tenths / 600) + ':' + String(Math.floor(tenths / 10) % 60).padStart(2, '0') + '.' + (tenths % 10);
}

/** Parses "90", "1:30" or "1:02:03" into seconds. Empty input is `null` (no limit); anything else invalid is `NaN`. */
export function parseClockTime(value: string): number | null {
    const text = value.trim();
    if (!text) return null;
    if (!/^\d+(?::\d{1,2}){0,2}(?:\.\d+)?$/.test(text)) return NaN;
    return text.split(':').reduce((total, part) => total * 60 + Number(part), 0);
}
