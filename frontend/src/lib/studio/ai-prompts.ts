import { localizedRecord } from '../i18n/core.ts';
export type ProductionKind = 'sound_effect' | 'music' | 'song' | 'cover';
export const productionKinds: ProductionKind[] = ['sound_effect', 'music', 'song', 'cover'];
export const productionLabels: Record<ProductionKind, string> = localizedRecord({
 sound_effect: 'prod.kind.sound_effect', music: 'prod.kind.music', song: 'prod.kind.song', cover: 'prod.kind.cover'
});
export type ProductionPrompt = {
 id: ProductionKind; label: string; description: string; default_prompt: string; prompt: string; customized: boolean;
};
export type ProductionPromptsResponse = { revision: number; templates: ProductionPrompt[] };
export type CoverSettings = {
 quality: 'fast' | 'balanced' | 'quality'; cfg_scale: number; pitch_shift: number;
 auto_shift: boolean; separate_vocals: boolean; mix_accompaniment: boolean;
};
export type ProductionAssistResponse = {
 kind: ProductionKind; generation_prompt: string; lyrics: string; structure: string; advice: string;
 settings: CoverSettings | null; provider: string; model: string; prompt_revision: number; prompt_id: string;
};
export function validCoverSettings(value: unknown): value is CoverSettings {
 if (!value || typeof value !== 'object') return false;
 const item = value as Record<string, unknown>;
 return typeof item.quality === 'string' && ['fast', 'balanced', 'quality'].includes(item.quality)
  && typeof item.cfg_scale === 'number' && Number.isFinite(item.cfg_scale) && item.cfg_scale >= .5 && item.cfg_scale <= 4
  && typeof item.pitch_shift === 'number' && Number.isInteger(item.pitch_shift) && item.pitch_shift >= -24 && item.pitch_shift <= 24
  && typeof item.auto_shift === 'boolean' && typeof item.separate_vocals === 'boolean'
  && typeof item.mix_accompaniment === 'boolean' && (!item.mix_accompaniment || item.separate_vocals);
}
export function validProductionAssist(value: unknown, expected: ProductionKind): value is ProductionAssistResponse {
 if (!value || typeof value !== 'object') return false;
 const item = value as Record<string, unknown>;
 if (item.kind !== expected || typeof item.provider !== 'string' || typeof item.model !== 'string'
  || item.prompt_id !== expected || !Number.isInteger(item.prompt_revision) || (item.prompt_revision as number) < 0) return false;
 for (const [key, max] of Object.entries({ generation_prompt: 4000, lyrics: 8000, structure: 3000, advice: 3000 })) {
  if (typeof item[key] !== 'string' || (item[key] as string).length > max) return false;
 }
 if (!(item.advice as string).trim()) return false;
 if (expected === 'cover') return validCoverSettings(item.settings);
 if (item.settings !== null || !(item.generation_prompt as string).trim()) return false;
 if (expected === 'song' && (!(item.lyrics as string).trim() || !(item.structure as string).trim())) return false;
 if (expected === 'music' && !(item.structure as string).trim()) return false;
 return true;
}
