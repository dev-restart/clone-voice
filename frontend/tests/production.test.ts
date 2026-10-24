import assert from 'node:assert/strict';
import test from 'node:test';
import { applyPronunciations, defaultProductionSettings, pronunciationError, readRecoveryDraft } from '../src/lib/studio/production.ts';

test('Korean pronunciation preview preserves acronyms, tags, and replacement literals', () => {
	const rules = [
		{ source: 'API', replacement: '에이피아이', language: 'ko' as const },
		{ source: 'AI', replacement: '에이아이', language: 'ko' as const },
		{ source: 'C++', replacement: '$&', language: 'ko' as const }
	];
	assert.equal(applyPronunciations('API를 AI로 MAIL [AI] api C++', rules, 'ko'), '에이피아이를 에이아이로 MAIL [AI] api $&');
	assert.equal(applyPronunciations('API', rules, 'en'), 'API');
});

test('specific language wins, longest phrase wins, and replacements do not cascade', () => {
	assert.equal(applyPronunciations('Clone Voice API', [
		{ source: 'Clone', replacement: '복제', language: 'all' },
		{ source: 'Clone Voice', replacement: 'CV', language: 'all' },
		{ source: 'Clone Voice', replacement: '클론보이스', language: 'ko' },
		{ source: 'API', replacement: 'Clone Voice', language: 'ko' }
	], 'ko'), '클론보이스 Clone Voice');
});

test('incomplete and duplicate entries stop saving but remain recoverable', () => {
	const production = defaultProductionSettings('voxcpm');
	production.pronunciation_rules = [{ source: 'API', replacement: '', language: 'ko' }];
	assert.ok(pronunciationError(production.pronunciation_rules));
	const draft = { version: 1, contentId: '', title: '초안', source_text: 'API 안내', translations: {}, production_settings: production, updatedAt: '2026-09-12T00:00:00Z' };
	assert.deepEqual(readRecoveryDraft(JSON.stringify(draft)), draft);
	const alias = { source: 'API', replacement: '에이피아이', language: 'ko' as const };
	assert.ok(pronunciationError([alias, alias]));
	assert.equal(pronunciationError([alias]), '');
});

test('invalid local backups do not break the editor', () => {
	assert.equal(readRecoveryDraft('not json'), null);
	assert.equal(readRecoveryDraft('{"version":1}'), null);
	assert.equal(readRecoveryDraft(null), null);
});
