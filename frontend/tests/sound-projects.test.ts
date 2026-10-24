import assert from 'node:assert/strict';
import test, { beforeEach } from 'node:test';
import {
  LEGACY_HISTORY_KEY, SOUND_STARTER_PACKS, copySoundProject, legacySoundProject,
  makeSoundAsset, makeSoundProject, markLegacySoundImported, mergeSoundProject,
  normalizeSoundResult, projectContentKey, readLegacySoundResults, readSoundRecoveries,
  readUnlinkedSounds, saveSoundRecovery, saveUnlinkedSounds,
} from '../src/lib/studio/sound-projects.ts';

class MemoryStorage {
  private values = new Map<string, string>();
  get length() { return this.values.size; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, String(value)); }
  removeItem(key: string) { this.values.delete(key); }
  clear() { this.values.clear(); }
}
const storage = new MemoryStorage();
Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true });
beforeEach(() => storage.clear());

function result(id = 'result-1') {
  return { id, prompt: 'Original sound prompt', generation_prompt: 'Original generation prompt', negative_prompt: 'speech',
    audio_url: `/api/files/outputs/${id}.wav`, duration_seconds: 2, seed: 123,
    model_id: 'stable-audio-sfx', created_at: '2026-10-18T10:00:00Z' };
}
function savedProject() {
  const project = makeSoundProject('프로젝트', 'game');
  project.revision = 1;
  project.assets = [makeSoundAsset()];
  project.assets[0].prompt = 'Original sound prompt';
  return project;
}

test('starter packs provide twelve editable prompts without generated audio', () => {
  assert.equal(SOUND_STARTER_PACKS.length, 3);
  assert.equal(SOUND_STARTER_PACKS.flatMap((pack) => pack.examples).length, 12);
  for (const pack of SOUND_STARTER_PACKS) {
    const project = makeSoundProject(pack.title, pack.category, pack);
    assert.equal(project.assets.length, 4);
    assert.equal(new Set(project.assets.map((asset) => asset.id)).size, 4);
    assert.ok(project.assets.every((asset) => asset.prompt.length > 30 && asset.results.length === 0 && asset.seed === null));
  }
});

test('a new empty project can be saved before any model or sound generation', () => {
  const project = makeSoundProject('  새 프로젝트  ', 'general');
  assert.equal(project.title, '새 프로젝트');
  assert.equal(project.revision, 0);
  assert.deepEqual(project.assets, []);
});

test('a completed generation preserves local edits and applies unrelated server edits', () => {
  const base = savedProject();
  const local = copySoundProject(base); local.assets[0].prompt = 'Edited during generation';
  const server = copySoundProject(base); server.revision = 2; server.title = '서버 이름'; server.assets[0].results = [result()];
  const merged = mergeSoundProject(local, base, server);
  assert.deepEqual(merged.conflicts, []);
  assert.equal(merged.project.revision, 2);
  assert.equal(merged.project.title, '서버 이름');
  assert.equal(merged.project.assets[0].prompt, 'Edited during generation');
  assert.equal(merged.project.assets[0].results[0].prompt, 'Original sound prompt');
  assert.notEqual(projectContentKey(merged.project), projectContentKey(server));
});

test('local result removal stays removed while a new server result is appended', () => {
  const base = savedProject(); base.assets[0].results = [result('old')];
  const local = copySoundProject(base); local.assets[0].results = [];
  const server = copySoundProject(base); server.revision = 2; server.assets[0].results.push(result('new'));
  assert.deepEqual(mergeSoundProject(local, base, server).project.assets[0].results.map((item) => item.id), ['new']);
});

test('editing the same field on both sides keeps the old revision and reports a conflict', () => {
  const base = savedProject();
  const local = copySoundProject(base); local.assets[0].prompt = 'My edit';
  const server = copySoundProject(base); server.revision = 2; server.assets[0].prompt = 'Other edit'; server.assets[0].results = [result()];
  const merged = mergeSoundProject(local, base, server);
  assert.equal(merged.conflicts.length, 1);
  assert.equal(merged.project.revision, 1);
  assert.equal(merged.project.assets[0].prompt, 'My edit');
  assert.equal(merged.project.assets[0].results.length, 1);
});

test('a server deletion removes untouched assets but preserves conflicting local work for recovery', () => {
  const base = savedProject();
  const server = copySoundProject(base); server.revision = 2; server.assets = [];
  assert.deepEqual(mergeSoundProject(copySoundProject(base), base, server).project.assets, []);
  const local = copySoundProject(base); local.assets[0].prompt = 'Unsaved work';
  const merged = mergeSoundProject(local, base, server);
  assert.equal(merged.conflicts.length, 1);
  assert.equal(merged.project.revision, 1);
  assert.equal(merged.project.assets[0].prompt, 'Unsaved work');
});

test('out-of-order older responses cannot replace newer local server state', () => {
  const base = savedProject(); base.revision = 5;
  const local = copySoundProject(base); local.title = 'Pending title';
  const older = copySoundProject(base); older.revision = 4; older.assets = [];
  assert.deepEqual(mergeSoundProject(local, base, older).project, local);
});

test('restoring a newly saved asset keeps results added after its backup', () => {
  const base = savedProject(); base.assets = [];
  const local = copySoundProject(base); local.assets = [makeSoundAsset()];
  const server = copySoundProject(local); server.revision = 2; server.assets[0].results = [result()];
  const merged = mergeSoundProject(local, base, server);
  assert.deepEqual(merged.conflicts, []);
  assert.equal(merged.project.assets[0].results.length, 1);
});

test('recovery storage preserves unfinished fields and a separate server baseline', () => {
  const base = savedProject();
  const local = copySoundProject(base); local.title = ''; local.assets[0].prompt = '아직 작성 중';
  saveSoundRecovery(local, base);
  const records = readSoundRecoveries();
  assert.equal(records.length, 1);
  assert.equal(records[0].draft.title, '');
  assert.equal(records[0].draft.assets[0].prompt, '아직 작성 중');
  assert.equal(records[0].base.assets[0].prompt, 'Original sound prompt');
});

test('malformed recovery data is skipped instead of breaking the workspace', () => {
  const base = savedProject();
  storage.setItem('clonevoice.soundProjects.draft.v1:broken', JSON.stringify({ draft: { ...base, assets: [{}] }, base, saved_at: 'today' }));
  assert.deepEqual(readSoundRecoveries(), []);
});

test('legacy import uses a stable project ID and retains the original history', () => {
  storage.setItem(LEGACY_HISTORY_KEY, JSON.stringify([result('old-one'), result('old-two')]));
  const first = legacySoundProject(readLegacySoundResults());
  const retry = legacySoundProject(readLegacySoundResults());
  assert.equal(first.id, retry.id);
  assert.equal(first.revision, 0);
  assert.equal(new Set(first.assets.map((asset) => asset.id)).size, 2);
  assert.equal(first.assets[0].results[0].id, 'old-one');
  markLegacySoundImported();
  assert.deepEqual(readLegacySoundResults(), []);
  assert.equal(JSON.parse(storage.getItem(LEGACY_HISTORY_KEY)!).length, 2);
});

test('legacy result normalization supplies generation_prompt and excludes unsafe URLs', () => {
  const missing = { ...result(), generation_prompt: undefined };
  assert.equal(normalizeSoundResult(missing)?.generation_prompt, missing.prompt);
  for (const url of ['https://example.com/audio.wav', '/api/files/outputs/../a.wav', '/api/files/outputs/a%2fb.wav', '/api/files/outputs/a.wav?x=1', '/api/files/outputs/a.wav\n']) {
    assert.equal(normalizeSoundResult({ ...result(), audio_url: url }), null);
  }
});

test('unlinked completed audio can survive a reload for playback and download', () => {
  saveUnlinkedSounds([{ id: 'recovery-1', project_title: '게임', asset_title: '클릭', warning: '프로젝트가 삭제되었습니다.', results: [result()] }]);
  const items = readUnlinkedSounds();
  assert.equal(items.length, 1);
  assert.equal(items[0].results[0].audio_url, '/api/files/outputs/result-1.wav');
});
