import assert from 'node:assert/strict';
import test from 'node:test';
import { storyGenerationSegments, storyResultIsStale } from '../src/lib/studio/story-production.ts';
import type { StorySegment, StoryStudioResult } from '../src/lib/studio/types.ts';

const segments: StorySegment[] = [
	{ id: 'a', text: '원문', translated_text: 'Translated text', language: 'en', voice_id: 'voice-a', model_id: 'voxcpm', speed: 1, pause_after_ms: 450, speaker_name: '진행자' },
	{ id: 'b', text: '두 번째 대사', language: 'ko', speed: 1, pause_after_ms: 500, speaker_name: '게스트' }
];

test('generation uses translated spoken text and omits unfinished lines', () => {
	const result = storyGenerationSegments([...segments, { ...segments[1], id: 'blank', text: ' ' }], 'voxcpm');
	assert.equal(result.length, 2);
	assert.equal(result[0].text, 'Translated text');
	assert.equal(result[1].voice_id, null);
});

test('edited casting, timing, text, and order make a take stale', () => {
	const result: StoryStudioResult = { title: '대담', audio_url: '/api/files/outputs/take.wav', duration_seconds: 3, segments: [], source_segments: storyGenerationSegments(segments, 'voxcpm') };
	assert.equal(storyResultIsStale(result, segments, 'voxcpm'), false);
	for (const patch of [{ voice_id: 'other' }, { speed: 1.1 }, { pause_after_ms: 0 }, { translated_text: 'New translation' }, { tone_prompt: 'calm' }]) {
		assert.equal(storyResultIsStale(result, [{ ...segments[0], ...patch }, segments[1]], 'voxcpm'), true);
	}
	assert.equal(storyResultIsStale(result, [...segments].reverse(), 'voxcpm'), true);
});

test('legacy takes without a snapshot are not falsely marked as matching or stale', () => {
	assert.equal(storyResultIsStale({ title: '이전 결과', audio_url: '', duration_seconds: 1, segments: [] }, segments, 'voxcpm'), false);
});
