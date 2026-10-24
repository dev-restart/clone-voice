export type MenuKey = 'home' | 'voices' | 'files' | 'tts' | 'story' | 'sfx' | 'stt' | 'changer' | 'settings';

export type VoiceProfile = {
	id: string;
	name: string;
	transcript?: string | null;
	audio_url: string;
	source_audio_url?: string | null;
	trim_start?: number | null;
	trim_end?: number | null;
	kind?: 'custom' | 'preset';
	description?: string | null;
	avatar?: string | null;
	language?: string | null;
	is_default?: boolean;
	tags?: string[];
	created_at: string;
};

export type ModelCapabilities = {
	tts: boolean;
	voice_clone_tts: boolean;
	voice_design: boolean;
	stt: boolean;
	voice_conversion: boolean;
	singing_voice_conversion?: boolean;
	sound_effect_generation?: boolean;
	music_generation?: boolean;
};

/** A studio area where the user picks a model. */
export type ModelDomain = 'voice' | 'music' | 'cover' | 'sfx';

export type RuntimeModelStatus = {
	id: string;
	label: string;
	provider: string;
	status: 'available' | 'unavailable';
	enabled: boolean;
	loaded: boolean;
	model_id?: string | null;
	device?: string | null;
	sample_rate: number;
	capabilities: ModelCapabilities;
	recommended_for: string[];
	message?: string | null;
	domains?: ModelDomain[];
	homepage?: string | null;
	license?: string | null;
	platforms?: string[];
	install_command?: string | null;
};

export type ModelPreference = {
	id: string;
	enabled: boolean;
	order: number;
};

export type ModelPreferencesResponse = {
	model_preferences: Record<string, ModelPreference>;
	default_tts_model: string;
	default_vc_model: string;
	default_models?: Partial<Record<ModelDomain, string>>;
};

export type ModelListResponse = ModelPreferencesResponse & {
	models: RuntimeModelStatus[];
};

export type RuntimeHealth = {
	ok: boolean;
	model: {
		engine: string;
		loaded: boolean;
		model_id?: string | null;
		device?: string | null;
		error?: string | null;
	};
};

export type PronunciationRule = {
	source: string;
	replacement: string;
	language: 'all' | 'ko' | 'en' | 'ja' | 'zh' | 'es' | 'fr' | 'de';
};

export type ContentProductionSettings = {
	model_id: string | null;
	voice_id: string | null;
	language: 'ko' | 'en' | 'ja' | 'zh' | 'es' | 'fr' | 'de';
	accent: string;
	tone_prompt: string;
	style_prompt: string;
	speed: number;
	normalize_output: boolean;
	quality: 'fast' | 'balanced' | 'high';
	pronunciation_rules: PronunciationRule[];
};

export type ContentResult = {
    spoken_text?: string | null;
    production_settings?: ContentProductionSettings | null;
	id: string;
	language: string;
	text: string;
	voice_id?: string | null;
	voice_name?: string | null;
	model_id?: string | null;
	audio_url: string;
	duration_seconds?: number | null;
	tone_prompt?: string | null;
	created_at: string;
};

export type ContentItem = {
	source_language?: string;
    production_settings?: ContentProductionSettings | null;
	id: string;
	title: string;
	source_text: string;
	translations: Record<string, string>;
	results: ContentResult[];
	created_at: string;
	updated_at: string;
};

export type StorySegment = {
	id: string;
	text: string;
	language: string;
	translated_text?: string | null;
	voice_id?: string | null;
	model_id?: string | null;
	tone_prompt?: string | null;
	accent?: string | null;
	speed: number;
	pause_after_ms: number;
	segment_type?: 'speech' | 'sfx';
	speaker_name?: string | null;
	sfx_duration_seconds?: number;
};

export type StorySpeakerProfile = {
	name: string;
	voice_id: string;
	tone_prompt: string;
	segment_count: number;
	has_mixed_voices: boolean;
	has_mixed_tones: boolean;
};

export type StoryDialogueFormat = 'deep-dive' | 'interview' | 'debate' | 'briefing';

export type DialogueDraftTurn = {
	index: number;
	speaker: 'A' | 'B' | 'C' | 'D';
	text: string;
	sfx_cue?: string | null;
};

export type DialogueDraftResponse = {
	title: string;
	summary: string;
	format: StoryDialogueFormat;
	language: 'ko' | 'en' | 'ja' | 'zh';
	speech_turns: number;
	include_sfx_cues: boolean;
	speakers: {
		speaker_a: string;
		speaker_b: string;
	};
	additional_speakers?: Partial<Record<'C' | 'D', string>>;
	turns: DialogueDraftTurn[];
	provider: string;
	model: string;
};

export type StorySegmentResult = {
	id: string;
	index: number;
	text: string;
	language: string;
	voice_id?: string | null;
	voice_name?: string | null;
	model_id?: string | null;
	audio_url: string;
	duration_seconds?: number | null;
	segment_type?: 'speech' | 'sfx';
	speaker_name?: string | null;
	pause_after_ms: number;
	tone_prompt?: string | null;
	effective_instruct?: string | null;
};

export type SoundEffectResult = {
	id: string;
	prompt: string;
	generation_prompt?: string;
	negative_prompt: string;
	audio_url: string;
	duration_seconds: number;
	seed: number;
	model_id: string;
	created_at: string;
};

export type SoundEffectPromptPlan = {
	source_prompt: string;
	generation_prompt: string;
	duration_seconds: number;
	duration_mode: 'auto' | 'manual';
	translated: boolean;
	planner: 'local-llm' | 'subscription-llm' | 'api-llm' | 'rules-fallback' | 'direct';
	provider?: string | null;
	model?: string | null;
};

export type AiTextModel = {
	id: string;
	label: string;
};

export type AiTextProvider = {
	id: 'apple' | 'local' | 'nvidia' | 'compatible' | 'chatgpt' | 'kimi' | `api-${string}`;
	label: string;
	connection_type: 'local' | 'api' | 'subscription';
	available: boolean;
	authenticated: boolean;
	message: string;
	runtime?: string | null;
	models: AiTextModel[];
};

export type AiTranslationMode = 'auto' | 'apple' | 'selected';

export type AiTranslationSettings = {
	mode: AiTranslationMode;
	effective_provider: string;
	effective_model: string;
	message: string;
	apple_available: boolean;
};

export type AiTranslationTestResult = {
	ok: boolean;
	provider: string;
	model: string;
	elapsed_ms: number;
	source_text: string;
	translations: { en: string };
	detail: string;
};

export type AiTextProviderCatalog = {
	selection: {
		provider_id: AiTextProvider['id'];
		model_id: string;
	};
	providers: AiTextProvider[];
	api_providers?: AiTextProvider[];
	translation: AiTranslationSettings;
	connections: {
		local_only: boolean;
		translation_mode?: AiTranslationMode;
		local: AiTextConnection;
		nvidia: AiTextConnection;
		compatible: AiTextConnection;
	};
};

export type AiTextConnection = { base_url: string; model_id: string; has_api_key: boolean };

export type AiProviderLoginSession = {
	id: string;
	provider_id: AiTextProvider['id'];
	status: 'running' | 'complete' | 'error';
	authorization_url?: string | null;
	user_code?: string | null;
	message: string;
};

export type StoryStudioResult = {
	title: string;
	audio_url: string;
	duration_seconds: number;
	segments: StorySegmentResult[];
	source_segments?: StorySegment[] | null;
	created_at?: string;
};

export type StoryProject = {
	id: string;
	title: string;
	segments: StorySegment[];
	result?: StoryStudioResult | null;
	dialogue_format?: StoryDialogueFormat | null;
	source_text?: string | null;
	source_excerpt?: string | null;
	created_at: string;
	updated_at: string;
	revision?: number;
};

export type VoiceConversionJob = {
	id: string;
	model_id: string;
	source_audio_url?: string | null;
	/** Older browser projects may still contain this field; API responses no longer expose local paths. */
	source_audio_path?: string;
	target_voice_id?: string | null;
	output_audio_url: string;
	transcript?: string | null;
	created_at: string;
};

export type AudioAssetKind = 'registered-voice' | 'tts' | 'ai-cover' | 'dialogue' | 'sound-effect' | 'other';

export type AudioAsset = {
	id: string;
	kind: AudioAssetKind;
	title: string;
	filename: string;
	audio_url: string;
	source_audio_url?: string | null;
	available: boolean;
	size_bytes?: number | null;
	duration_seconds?: number | null;
	voice_id?: string | null;
	voice_name?: string | null;
	model_id?: string | null;
	source_title?: string | null;
	transcript?: string | null;
	trim_start?: number | null;
	trim_end?: number | null;
	created_at: string;
};

export type AudioAssetCatalog = {
	registered_voices: AudioAsset[];
	generated_files: AudioAsset[];
};

export type StudioNotice = {
	type: 'success' | 'error' | 'info';
	text: string;
};