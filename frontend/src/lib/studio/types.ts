export type MenuKey = 'home' | 'voices' | 'tts' | 'story' | 'stt' | 'changer' | 'settings';

export type VoiceProfile = {
	id: string;
	name: string;
	transcript?: string | null;
	audio_path?: string;
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
	realtime_voice_conversion?: boolean;
};

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

export type ContentResult = {
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
	pause_after_ms: number;
	tone_prompt?: string | null;
	effective_instruct?: string | null;
};

export type StoryStudioResult = {
	title: string;
	audio_url: string;
	duration_seconds: number;
	segments: StorySegmentResult[];
};

export type StoryProject = {
	id: string;
	title: string;
	segments: StorySegment[];
	result?: StoryStudioResult | null;
	created_at: string;
	updated_at: string;
};

export type VoiceConversionJob = {
	id: string;
	model_id: string;
	source_audio_path: string;
	target_voice_id?: string | null;
	output_audio_url: string;
	transcript?: string | null;
	created_at: string;
};

export type StudioNotice = {
	type: 'success' | 'error' | 'info';
	text: string;
};
