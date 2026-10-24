import test from 'node:test';
import assert from 'node:assert/strict';
import {
	defaultModelFor,
	modelDomains,
	modelsFor,
	normalizeModelState,
	withDefaultModel,
	withModelEnabled,
	withModelMoved
} from '../src/lib/studio/models.ts';
import type { RuntimeModelStatus } from '../src/lib/studio/types.ts';

const caps = { tts: false, voice_clone_tts: false, voice_design: false, stt: false, voice_conversion: false };
function model(id: string, capabilities: Partial<RuntimeModelStatus['capabilities']>, status: 'available' | 'unavailable' = 'available'): RuntimeModelStatus {
	return { id, label: id, provider: 'test', status, enabled: true, loaded: false, sample_rate: 24000, recommended_for: [], capabilities: { ...caps, ...capabilities } };
}

const voxcpm = model('voxcpm', { tts: true });
const altVoice = model('alt-voice', { tts: true });
const singer = model('soulx-singer', { voice_conversion: true });
const sfx = model('stable-audio-sfx', { sound_effect_generation: true });
const music = model('future-music', { music_generation: true }, 'unavailable');
const all = [voxcpm, altVoice, singer, sfx, music];

test('a model is listed under every domain its capabilities cover', () => {
	assert.deepEqual(modelDomains(model('both', { tts: true, voice_conversion: true })), ['voice', 'cover']);
	assert.deepEqual(modelDomains(music), ['music']);
});

test('normalizing gives each domain with models a default, preferring an available one', () => {
	const state = normalizeModelState([model('a', { tts: true }, 'unavailable'), model('b', { tts: true })]);
	assert.equal(state.defaults.voice, 'b');
	assert.equal(state.defaults.cover, undefined);
});

test('a stored default is kept while it stays enabled', () => {
	const state = normalizeModelState(all, {}, { voice: 'alt-voice' });
	assert.equal(state.defaults.voice, 'alt-voice');
});

test('required domains cannot lose their last enabled model', () => {
	const state = normalizeModelState(all);
	const blocked = withModelEnabled(all, state, 'soulx-singer', false);
	assert.deepEqual(blocked, { ok: false, reason: 'cover' });
});

test('optional domains can be switched off entirely', () => {
	const state = normalizeModelState(all);
	const result = withModelEnabled(all, state, 'stable-audio-sfx', false);
	assert.ok(result.ok);
	assert.equal(modelsFor(all, result.state, 'sfx').length, 0);
	assert.equal(result.state.defaults.sfx, undefined);
});

test('disabling the default hands the default to another model of the same domain', () => {
	const state = normalizeModelState(all, {}, { voice: 'voxcpm' });
	const result = withModelEnabled(all, state, 'voxcpm', false);
	assert.ok(result.ok);
	assert.equal(result.state.defaults.voice, 'alt-voice');
});

test('only available models of the right domain can become the default', () => {
	const state = normalizeModelState(all);
	assert.equal(withDefaultModel(all, state, 'music', 'future-music'), null);
	assert.equal(withDefaultModel(all, state, 'voice', 'soulx-singer'), null);
	assert.equal(withDefaultModel(all, state, 'voice', 'alt-voice')?.defaults.voice, 'alt-voice');
});

test('moving swaps order only inside one domain', () => {
	const state = normalizeModelState(all);
	const moved = withModelMoved(all, state, 'voice', 'alt-voice', 'up');
	assert.ok(moved);
	assert.deepEqual(modelsFor(all, moved, 'voice').map((item) => item.id), ['alt-voice', 'voxcpm']);
	assert.equal(withModelMoved(all, moved, 'voice', 'alt-voice', 'up'), null);
});

test('defaultModelFor falls back to the first available enabled model', () => {
	const state = normalizeModelState(all, {}, { voice: 'missing' });
	assert.equal(defaultModelFor(all, state, 'voice')?.id, 'voxcpm');
	assert.equal(defaultModelFor([], state, 'voice'), undefined);
});
