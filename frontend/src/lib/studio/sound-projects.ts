import { labeled, t } from '../i18n/core.ts';
import type { SoundEffectResult } from '$lib/studio/types';

export type SoundProjectCategory = 'game' | 'video' | 'ambient' | 'general';
export type SoundAssetCategory = 'ui' | 'impact' | 'movement' | 'ambience' | 'transition' | 'foley' | 'other';
export type SoundAsset = {
  id: string; title: string; category: SoundAssetCategory; prompt: string; negative_prompt: string;
  duration_seconds: number; auto_duration: boolean; variations: number; guidance_scale: number; seed: number | null;
  results: SoundEffectResult[]; created_at: string; updated_at: string;
};
export type SoundProject = {
  id: string; title: string; category: SoundProjectCategory; assets: SoundAsset[];
  revision: number; created_at: string; updated_at: string;
};
export type SoundProjectRecovery = { draft: SoundProject; base: SoundProject; saved_at: string };
export type SoundRecoveryResult = { id: string; project_title: string; asset_title: string; warning: string; results: SoundEffectResult[] };
export type SoundTemplate = { id: string; title: string; category: SoundAssetCategory; prompt: string; duration_seconds: number };
export type SoundStarterPack = { id: string; title: string; category: SoundProjectCategory; description: string; examples: SoundTemplate[] };

export const PROJECT_CATEGORIES: { value: SoundProjectCategory; readonly label: string }[] = [
  labeled({ value: 'game' as const }, 'sound.cat.game'), labeled({ value: 'video' as const }, 'sound.cat.video'),
  labeled({ value: 'ambient' as const }, 'sound.cat.ambient'), labeled({ value: 'general' as const }, 'sound.cat.general'),
];
export const ASSET_CATEGORIES: { value: SoundAssetCategory; readonly label: string }[] = [
  labeled({ value: 'ui' as const }, 'sound.asset.ui'), labeled({ value: 'impact' as const }, 'sound.asset.impact'),
  labeled({ value: 'movement' as const }, 'sound.asset.movement'), labeled({ value: 'ambience' as const }, 'sound.asset.ambience'),
  labeled({ value: 'transition' as const }, 'sound.asset.transition'), labeled({ value: 'foley' as const }, 'sound.asset.foley'), labeled({ value: 'other' as const }, 'sound.asset.other'),
];

const STARTER_PACK_DATA = (): SoundStarterPack[] => [
  {
    id: 'game-ui', title: t('sound.pack.game-ui.title'), category: 'game', description: t('sound.pack.game-ui.desc'),
    examples: [
      { id: 'confirm', title: t('sound.example.confirm'), category: 'ui', duration_seconds: 1, prompt: 'A single soft wooden UI click with a warm, clean tap and a very short decay. Close and dry, isolated sound effect, no voice, no music.' },
      { id: 'cancel', title: t('sound.example.cancel'), category: 'ui', duration_seconds: 1.5, prompt: 'A short muted electronic double beep descending in pitch, gentle game menu cancel notification. Clean and dry with a quick fade, no voice, no music.' },
      { id: 'coin', title: t('sound.example.coin'), category: 'impact', duration_seconds: 2, prompt: 'A small bright metallic coin ping followed by two tiny sparkling chimes, a playful item pickup sound. Crisp transient and short decay, no voice, no background music.' },
      { id: 'level-up', title: t('sound.example.level-up'), category: 'ui', duration_seconds: 3, prompt: 'A cheerful game achievement sound with three clear ascending synthetic chimes and a soft sparkling tail. One short notification, no voice, no background music.' },
    ],
  },
  {
    id: 'video-transitions', title: t('sound.pack.video-transitions.title'), category: 'video', description: t('sound.pack.video-transitions.desc'),
    examples: [
      { id: 'whoosh', title: t('sound.example.whoosh'), category: 'transition', duration_seconds: 2, prompt: 'A fast airy whoosh sweeping from left to right, smooth acceleration and a soft ending. Clean isolated video transition sound, no voice, no music.' },
      { id: 'cinematic-hit', title: t('sound.example.cinematic-hit'), category: 'impact', duration_seconds: 3, prompt: 'One deep cinematic impact with a tight low thump, subtle metallic texture and a short spacious decay. Powerful but not distorted, no voice, no music.' },
      { id: 'soft-rise', title: t('sound.example.soft-rise'), category: 'transition', duration_seconds: 5, prompt: 'A smooth airy sound design riser gradually increasing in pitch and intensity, ending with a gentle release. Suitable for a short video reveal, no voice, no melody.' },
      { id: 'camera', title: t('sound.example.camera'), category: 'foley', duration_seconds: 1, prompt: 'A single crisp mechanical camera shutter click with a subtle spring snap. Close microphone, dry room, clean isolated foley, no voice, no music.' },
    ],
  },
  {
    id: 'ambient-scenes', title: t('sound.pack.ambient-scenes.title'), category: 'ambient', description: t('sound.pack.ambient-scenes.desc'),
    examples: [
      { id: 'forest', title: t('sound.example.forest'), category: 'ambience', duration_seconds: 10, prompt: 'A quiet early morning forest ambience with sparse distant birds, gentle leaves moving in a light breeze, and a calm natural background. Steady atmosphere, no people, no music.' },
      { id: 'rain', title: t('sound.example.rain'), category: 'ambience', duration_seconds: 10, prompt: 'Steady gentle rain tapping on a window, close delicate droplets with a soft distant wash of rainfall. Consistent indoor listening perspective, no thunder, no speech, no music.' },
      { id: 'city', title: t('sound.example.city'), category: 'ambience', duration_seconds: 10, prompt: 'A quiet city at night heard from an upper-floor window, distant soft traffic passing occasionally with a low steady urban hum. No sirens, no intelligible voices, no music.' },
      { id: 'stream', title: t('sound.example.stream'), category: 'ambience', duration_seconds: 10, prompt: 'A small clear stream flowing gently over smooth stones, close rippling water with soft bubbling details and a calm outdoor background. Even continuous flow, no people, no music.' },
    ],
  },
];

/** Built on access so titles and descriptions use the current display language. */
export const SOUND_STARTER_PACKS: SoundStarterPack[] = new Proxy([] as SoundStarterPack[], {
  get(_target, property, receiver) { return Reflect.get(STARTER_PACK_DATA(), property, receiver); },
  has(_target, property) { return Reflect.has(STARTER_PACK_DATA(), property); },
  ownKeys() { return Reflect.ownKeys(STARTER_PACK_DATA()); },
  getOwnPropertyDescriptor(_target, property) { return Reflect.getOwnPropertyDescriptor(STARTER_PACK_DATA(), property); }
});

const DRAFT_PREFIX = 'clonevoice.soundProjects.draft.v1:';
export const LEGACY_HISTORY_KEY = 'clonevoice.soundEffects.history.v1';
const LEGACY_IMPORT_ID_KEY = 'clonevoice.soundProjects.legacyImportId.v1';
const LEGACY_IMPORTED_KEY = 'clonevoice.soundProjects.legacyImported.v1';
const UNLINKED_KEY = 'clonevoice.soundProjects.unlinked.v1';
const SAFE_ID = /^[A-Za-z0-9_-]{1,80}$/;
const SAFE_OUTPUT = /^\/api\/files\/outputs\/[A-Za-z0-9_-][A-Za-z0-9._-]{0,254}$/;

export function soundId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `sound-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}
export function copySoundProject(project: SoundProject): SoundProject {
  return JSON.parse(JSON.stringify(project)) as SoundProject;
}
export function makeSoundAsset(template?: SoundTemplate): SoundAsset {
  const now = new Date().toISOString();
  return {
    id: soundId(), title: template?.title ?? t('sound.newAsset'), category: template?.category ?? 'other',
    prompt: template?.prompt ?? '', negative_prompt: 'speech, vocals, background music',
    duration_seconds: template?.duration_seconds ?? 3, auto_duration: false,
    variations: 1, guidance_scale: 3, seed: null, results: [], created_at: now, updated_at: now,
  };
}
export function makeSoundProject(title: string, category: SoundProjectCategory, pack?: SoundStarterPack): SoundProject {
  const now = new Date().toISOString();
  return { id: soundId(), title: title.trim(), category, assets: pack ? pack.examples.map(makeSoundAsset) : [], revision: 0, created_at: now, updated_at: now };
}
export function projectCategoryLabel(value: string): string {
  return PROJECT_CATEGORIES.find((item) => item.value === value)?.label ?? value;
}
export function assetCategoryLabel(value: string): string {
  return ASSET_CATEGORIES.find((item) => item.value === value)?.label ?? value;
}
export function projectContentKey(project: SoundProject): string {
  return JSON.stringify({ title: project.title, category: project.category, assets: project.assets.map(({ created_at: _created, updated_at: _updated, ...asset }) => asset) });
}

function object(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
export function normalizeSoundResult(value: unknown): SoundEffectResult | null {
  if (!object(value) || typeof value.id !== 'string' || !SAFE_ID.test(value.id)
    || value.id.trim() !== value.id
    || typeof value.audio_url !== 'string' || !SAFE_OUTPUT.test(value.audio_url)
    || value.audio_url.trim() !== value.audio_url
    || typeof value.prompt !== 'string' || typeof value.duration_seconds !== 'number' || !Number.isFinite(value.duration_seconds)
    || value.duration_seconds <= 0 || typeof value.seed !== 'number' || !Number.isInteger(value.seed)) return null;
  const created = typeof value.created_at === 'string' && Number.isFinite(Date.parse(value.created_at)) ? value.created_at : new Date().toISOString();
  return {
    id: value.id, audio_url: value.audio_url, prompt: value.prompt,
    generation_prompt: typeof value.generation_prompt === 'string' ? value.generation_prompt : value.prompt,
    negative_prompt: typeof value.negative_prompt === 'string' ? value.negative_prompt : '',
    duration_seconds: Number(value.duration_seconds), seed: Number(value.seed),
    model_id: typeof value.model_id === 'string' ? value.model_id : 'stable-audio-sfx', created_at: created,
  };
}
export function readLegacySoundResults(): SoundEffectResult[] {
  if (typeof localStorage === 'undefined') return [];
  try {
    if (localStorage.getItem(LEGACY_IMPORTED_KEY) === '1') return [];
    const parsed: unknown = JSON.parse(localStorage.getItem(LEGACY_HISTORY_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.slice(0, 16).map(normalizeSoundResult).filter((item): item is SoundEffectResult => Boolean(item)) : [];
  } catch { return []; }
}
export function legacySoundProject(results: SoundEffectResult[]): SoundProject {
  let id = localStorage.getItem(LEGACY_IMPORT_ID_KEY);
  if (!id || !SAFE_ID.test(id)) {
    id = soundId();
    localStorage.setItem(LEGACY_IMPORT_ID_KEY, id);
  }
  const project = makeSoundProject(t('sound.legacyProject'), 'general');
  project.id = id;
  project.assets = results.slice(0, 16).map((result, index) => ({
    ...makeSoundAsset(), id: `legacy-${index}-${result.id}`.slice(0, 80),
    title: t('sound.legacyAsset', { n: index + 1 }), prompt: result.prompt.slice(0, 2000),
    negative_prompt: result.negative_prompt.slice(0, 1000), duration_seconds: Math.min(15, Math.max(0.5, result.duration_seconds)),
    seed: result.seed >= 0 && result.seed <= 2147483643 ? result.seed : null, results: [result],
  }));
  return project;
}
export function markLegacySoundImported(): void {
  // Retain the original history for recovery; this flag only hides the banner.
  localStorage.setItem(LEGACY_IMPORTED_KEY, '1');
}

export function saveSoundRecovery(draft: SoundProject, base: SoundProject): void {
  localStorage.setItem(DRAFT_PREFIX + draft.id, JSON.stringify({ draft, base, saved_at: new Date().toISOString() } satisfies SoundProjectRecovery));
}
export function removeSoundRecovery(id: string): void {
  localStorage.removeItem(DRAFT_PREFIX + id);
}
function validProject(value: unknown): value is SoundProject {
  if (!object(value) || typeof value.id !== 'string' || !SAFE_ID.test(value.id) || value.id.trim() !== value.id
    || typeof value.title !== 'string' || value.title.length > 160
    || !PROJECT_CATEGORIES.some((item) => item.value === value.category)
    || typeof value.revision !== 'number' || !Number.isInteger(value.revision) || value.revision < 0
    || !Array.isArray(value.assets) || value.assets.length > 300
    || typeof value.created_at !== 'string' || typeof value.updated_at !== 'string') return false;
  const ids = new Set<string>();
  return value.assets.every((asset: unknown) => {
    if (!object(asset) || typeof asset.id !== 'string' || !SAFE_ID.test(asset.id) || asset.id.trim() !== asset.id || ids.has(asset.id)
      || typeof asset.title !== 'string' || asset.title.length > 160
      || !ASSET_CATEGORIES.some((item) => item.value === asset.category)
      || typeof asset.prompt !== 'string' || asset.prompt.length > 2000
      || typeof asset.negative_prompt !== 'string' || asset.negative_prompt.length > 1000
      || typeof asset.duration_seconds !== 'number' || !Number.isFinite(asset.duration_seconds) || asset.duration_seconds < .5 || asset.duration_seconds > 15
      || typeof asset.guidance_scale !== 'number' || !Number.isFinite(asset.guidance_scale) || asset.guidance_scale < 0 || asset.guidance_scale > 8
      || typeof asset.variations !== 'number' || !Number.isInteger(asset.variations) || asset.variations < 1 || asset.variations > 4
      || typeof asset.auto_duration !== 'boolean' || !(asset.seed === null || (typeof asset.seed === 'number' && Number.isInteger(asset.seed) && asset.seed >= 0 && asset.seed <= 2147483643))
      || !Array.isArray(asset.results) || asset.results.length > 100 || !asset.results.every((result) => normalizeSoundResult(result) !== null)
      || typeof asset.created_at !== 'string' || typeof asset.updated_at !== 'string') return false;
    ids.add(asset.id); return true;
  });
}
export function readSoundRecoveries(): SoundProjectRecovery[] {
  if (typeof localStorage === 'undefined') return [];
  const records: SoundProjectRecovery[] = [];
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key?.startsWith(DRAFT_PREFIX)) continue;
      try {
        const value: unknown = JSON.parse(localStorage.getItem(key) ?? 'null');
        if (object(value) && validProject(value.draft) && validProject(value.base)
          && value.draft.id === value.base.id
          && typeof value.saved_at === 'string') records.push(value as unknown as SoundProjectRecovery);
      } catch { /* A damaged backup does not prevent other drafts from opening. */ }
    }
  } catch { return []; }
  return records.sort((left, right) => right.saved_at.localeCompare(left.saved_at));
}
export function readUnlinkedSounds(): SoundRecoveryResult[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(UNLINKED_KEY) ?? '[]');
    if (!Array.isArray(raw)) return [];
    return raw.filter((item) => object(item) && typeof item.id === 'string' && Array.isArray(item.results)).slice(0, 16).map((item) => ({
      id: String(item.id), project_title: String(item.project_title ?? t('sound.projectFallback')), asset_title: String(item.asset_title ?? t('sound.assetFallback')),
      warning: String(item.warning ?? t('sound.warnFallback')),
      results: item.results.map(normalizeSoundResult).filter((result: SoundEffectResult | null): result is SoundEffectResult => Boolean(result)),
    }));
  } catch { return []; }
}
export function saveUnlinkedSounds(items: SoundRecoveryResult[]): void {
  localStorage.setItem(UNLINKED_KEY, JSON.stringify(items.slice(0, 16)));
}

/** Merge result arrivals with local edits. Concurrent edits to the same field
 * are reported and keep the old revision so a later save cannot overwrite them.
 */
export function mergeSoundProject(local: SoundProject, base: SoundProject, server: SoundProject): { project: SoundProject; conflicts: string[] } {
  if (server.revision < base.revision) return { project: copySoundProject(local), conflicts: [] };
  const conflicts: string[] = [];
  const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);
  function choose<T>(before: T, mine: T, theirs: T, label: string): T {
    if (equal(mine, before)) return theirs;
    if (!equal(theirs, before) && !equal(theirs, mine)) conflicts.push(label);
    return mine;
  }
  const oldAssets = new Map(base.assets.map((asset) => [asset.id, asset]));
  const serverAssets = new Map(server.assets.map((asset) => [asset.id, asset]));
  const localIds = new Set(local.assets.map((asset) => asset.id));
  const assets: SoundAsset[] = [];
  for (const mine of local.assets) {
    const before = oldAssets.get(mine.id);
    const theirs = serverAssets.get(mine.id);
    if (!before) {
      if (theirs) {
        const omitHistory = ({ results: _results, created_at: _created, updated_at: _updated, ...asset }: SoundAsset) => asset;
        if (!equal(omitHistory(mine), omitHistory(theirs))) conflicts.push(t('sound.conflict.new', { title: mine.title }));
        const ids = new Set(theirs.results.map((result) => result.id));
        assets.push({ ...mine, results: [...theirs.results, ...mine.results.filter((result) => !ids.has(result.id))] });
      } else assets.push(mine);
      continue;
    }
    if (!theirs) {
      if (!equal({ ...mine, updated_at: '' }, { ...before, updated_at: '' })) {
        conflicts.push(t('sound.conflict.deleted', { title: mine.title })); assets.push(mine);
      }
      continue;
    }
    const oldResultIds = new Set(before.results.map((result) => result.id));
    const mineResultIds = new Set(mine.results.map((result) => result.id));
    const results = theirs.results.filter((result) => !(oldResultIds.has(result.id) && !mineResultIds.has(result.id)));
    const resultIds = new Set(results.map((result) => result.id));
    results.push(...mine.results.filter((result) => !oldResultIds.has(result.id) && !resultIds.has(result.id)));
    assets.push({
      ...theirs,
      title: choose(before.title, mine.title, theirs.title, t('sound.conflict.field.name', { title: mine.title })),
      category: choose(before.category, mine.category, theirs.category, t('sound.conflict.field.type', { title: mine.title })),
      prompt: choose(before.prompt, mine.prompt, theirs.prompt, t('sound.conflict.field.prompt', { title: mine.title })),
      negative_prompt: choose(before.negative_prompt, mine.negative_prompt, theirs.negative_prompt, t('sound.conflict.field.negative', { title: mine.title })),
      duration_seconds: choose(before.duration_seconds, mine.duration_seconds, theirs.duration_seconds, t('sound.conflict.field.duration', { title: mine.title })),
      auto_duration: choose(before.auto_duration, mine.auto_duration, theirs.auto_duration, t('sound.conflict.field.auto', { title: mine.title })),
      variations: choose(before.variations, mine.variations, theirs.variations, t('sound.conflict.field.variations', { title: mine.title })),
      guidance_scale: choose(before.guidance_scale, mine.guidance_scale, theirs.guidance_scale, t('sound.conflict.field.guidance', { title: mine.title })),
      seed: choose(before.seed, mine.seed, theirs.seed, t('sound.conflict.field.seed', { title: mine.title })), results,
    });
  }
  assets.push(...server.assets.filter((asset) => !oldAssets.has(asset.id) && !localIds.has(asset.id)));
  const project: SoundProject = {
    ...server, title: choose(base.title, local.title, server.title, t('sound.conflict.projectName')),
    category: choose(base.category, local.category, server.category, t('sound.conflict.projectType')), assets,
  };
  if (conflicts.length) project.revision = base.revision;
  return { project, conflicts };
}
