import type { StorySegment, StoryStudioResult } from './types.ts';

export function storyGenerationSegments(segments: StorySegment[], defaultModelId: string) {
	return segments.map((segment) => ({
		id: segment.id,
		text: ((segment.segment_type !== 'sfx' && segment.language !== 'ko' && segment.translated_text?.trim()) || segment.text).trim(),
		language: segment.language,
		voice_id: segment.voice_id || null,
		model_id: segment.model_id || defaultModelId,
		tone_prompt: segment.tone_prompt || null,
		accent: segment.accent || null,
		speed: segment.speed,
		pause_after_ms: segment.pause_after_ms,
		segment_type: segment.segment_type ?? 'speech',
		speaker_name: segment.speaker_name || null,
		sfx_duration_seconds: segment.sfx_duration_seconds ?? 3
	})).filter((segment) => segment.text);
}

export function storyResultIsStale(result: StoryStudioResult | null, segments: StorySegment[], defaultModelId: string) {
	if (!result?.source_segments) return false;
	return JSON.stringify(storyGenerationSegments(result.source_segments, defaultModelId)) !== JSON.stringify(storyGenerationSegments(segments, defaultModelId));
}
