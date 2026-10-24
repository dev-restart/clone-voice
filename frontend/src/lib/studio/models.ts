// Pure model-registry rules shared by Settings and every workspace. No UI or i18n imports so it runs under node:test.
import type { ModelCapabilities, ModelDomain, ModelPreference, RuntimeModelStatus } from './types.ts';

export const MODEL_DOMAINS: readonly ModelDomain[] = ['voice', 'music', 'cover', 'sfx'];

/** Voice and cover always need one enabled model; music and sound effects may be switched off. */
export const REQUIRED_DOMAINS: readonly ModelDomain[] = ['voice', 'cover'];

const DOMAIN_CAPABILITY: Record<ModelDomain, keyof ModelCapabilities> = {
	voice: 'tts',
	music: 'music_generation',
	cover: 'voice_conversion',
	sfx: 'sound_effect_generation'
};

const DEFAULT_MODEL_ORDER: Record<string, number> = { voxcpm: 10, 'soulx-singer': 20, 'stable-audio-sfx': 30 };

export type ModelDefaults = Partial<Record<ModelDomain, string>>;
export type ModelState = { preferences: Record<string, ModelPreference>; defaults: ModelDefaults };

export function supportsDomain(model: RuntimeModelStatus, domain: ModelDomain): boolean {
	return Boolean(model.capabilities[DOMAIN_CAPABILITY[domain]]);
}

export function modelDomains(model: RuntimeModelStatus): ModelDomain[] {
	return MODEL_DOMAINS.filter((domain) => supportsDomain(model, domain));
}

function defaultOrder(model: RuntimeModelStatus, index: number) {
	return DEFAULT_MODEL_ORDER[model.id] ?? 100 + index;
}

export function sortModels(models: RuntimeModelStatus[], preferences: Record<string, ModelPreference>) {
	return [...models].sort((a, b) => {
		const orderA = preferences[a.id]?.order ?? defaultOrder(a, models.indexOf(a));
		const orderB = preferences[b.id]?.order ?? defaultOrder(b, models.indexOf(b));
		return orderA - orderB || a.label.localeCompare(b.label);
	});
}

export function isEnabled(state: ModelState, modelId: string) {
	return state.preferences[modelId]?.enabled ?? true;
}

/** Enabled models of one domain, in the user's order. */
export function modelsFor(models: RuntimeModelStatus[], state: ModelState, domain: ModelDomain) {
	return sortModels(models, state.preferences).filter((model) => supportsDomain(model, domain) && isEnabled(state, model.id));
}

export function allModelsFor(models: RuntimeModelStatus[], state: ModelState, domain: ModelDomain) {
	return sortModels(models, state.preferences).filter((model) => supportsDomain(model, domain));
}

export function defaultModelFor(models: RuntimeModelStatus[], state: ModelState, domain: ModelDomain) {
	const active = modelsFor(models, state, domain);
	return active.find((model) => model.id === state.defaults[domain]) ?? active.find((model) => model.status === 'available') ?? active[0];
}

/** Reconciles server data with local rules: every required domain keeps an enabled model and a valid default. */
export function normalizeModelState(
	models: RuntimeModelStatus[],
	serverPreferences: Record<string, ModelPreference> = {},
	serverDefaults: ModelDefaults = {},
	current: ModelDefaults = {}
): ModelState {
	const preferences: Record<string, ModelPreference> = {};
	models.forEach((model, index) => {
		const existing = serverPreferences[model.id];
		preferences[model.id] = {
			id: model.id,
			enabled: existing?.enabled ?? true,
			order: Number.isFinite(existing?.order) ? Number(existing.order) : defaultOrder(model, index)
		};
	});

	const defaults: ModelDefaults = {};
	for (const domain of MODEL_DOMAINS) {
		const members = sortModels(models, preferences).filter((model) => supportsDomain(model, domain));
		if (!members.length) continue;
		let active = members.filter((model) => preferences[model.id].enabled);
		if (!active.length && REQUIRED_DOMAINS.includes(domain)) {
			preferences[members[0].id] = { ...preferences[members[0].id], enabled: true };
			active = [members[0]];
		}
		if (!active.length) continue;
		const wanted = serverDefaults[domain] || current[domain];
		defaults[domain] = active.some((model) => model.id === wanted)
			? wanted
			: (active.find((model) => model.status === 'available') ?? active[0]).id;
	}
	return { preferences, defaults };
}

export type ModelChange = { ok: true; state: ModelState } | { ok: false; reason: ModelDomain };

export function withModelEnabled(models: RuntimeModelStatus[], state: ModelState, modelId: string, enabled: boolean): ModelChange {
	const model = models.find((item) => item.id === modelId);
	if (!model) return { ok: true, state };
	if (!enabled) {
		for (const domain of REQUIRED_DOMAINS) {
			const others = modelsFor(models, state, domain).filter((item) => item.id !== modelId);
			if (supportsDomain(model, domain) && !others.length) return { ok: false, reason: domain };
		}
	}
	const index = models.indexOf(model);
	const preferences = {
		...state.preferences,
		[modelId]: { id: modelId, enabled, order: state.preferences[modelId]?.order ?? defaultOrder(model, index) }
	};
	return { ok: true, state: normalizeModelState(models, preferences, state.defaults, state.defaults) };
}

export function withDefaultModel(models: RuntimeModelStatus[], state: ModelState, domain: ModelDomain, modelId: string): ModelState | null {
	const model = models.find((item) => item.id === modelId);
	if (!model || !supportsDomain(model, domain) || model.status === 'unavailable') return null;
	const index = models.indexOf(model);
	const preferences = {
		...state.preferences,
		[modelId]: { id: modelId, enabled: true, order: state.preferences[modelId]?.order ?? defaultOrder(model, index) }
	};
	return normalizeModelState(models, preferences, { ...state.defaults, [domain]: modelId }, state.defaults);
}

/** Swaps the order of a model with its neighbour inside one domain's list. */
export function withModelMoved(models: RuntimeModelStatus[], state: ModelState, domain: ModelDomain, modelId: string, direction: 'up' | 'down'): ModelState | null {
	const members = allModelsFor(models, state, domain);
	const from = members.findIndex((model) => model.id === modelId);
	const to = direction === 'up' ? from - 1 : from + 1;
	if (from < 0 || to < 0 || to >= members.length) return null;
	const [current, target] = [members[from], members[to]];
	const orderOf = (model: RuntimeModelStatus) => state.preferences[model.id]?.order ?? defaultOrder(model, models.indexOf(model));
	const [currentOrder, targetOrder] = [orderOf(current), orderOf(target)];
	// Equal orders would make the swap a no-op, so spread them apart first.
	const [nextCurrent, nextTarget] = currentOrder === targetOrder ? [targetOrder + (direction === 'up' ? -1 : 1), currentOrder] : [targetOrder, currentOrder];
	return {
		...state,
		preferences: {
			...state.preferences,
			[current.id]: { id: current.id, enabled: isEnabled(state, current.id), order: nextCurrent },
			[target.id]: { id: target.id, enabled: isEnabled(state, target.id), order: nextTarget }
		}
	};
}
