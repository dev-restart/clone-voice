import { labeled, localizedRecord } from '../i18n/core.ts';
import type { AiTextProvider } from './types';

export type Protocol = 'openai_chat' | 'anthropic_messages' | 'openai_responses';
export type ModelProfile = {
 id: string; label: string; max_input_chars: number; max_output_tokens: number;
 temperature: number | null; token_parameter: 'max_tokens' | 'max_completion_tokens'; structured_output: 'prompt' | 'json_schema';
};
export type RouteSelection = { provider_id: AiTextProvider['id']; model_id: string };
export type TaskKey = 'translation' | 'writing' | 'sound_prompt';
export type ProfileDraft = {
 name: string; protocol: Protocol; base_url: string; auth_type: 'none' | 'bearer' | 'x-api-key';
 credential_storage: 'keychain' | 'private_file'; enabled: boolean; local_engine: 'generic' | 'ollama';
 models: ModelProfile[]; default_model_id: string; timeout_seconds: number; max_concurrency: number;
};
export type ApiProfile = Omit<ProfileDraft, 'credential_storage'> & {
 id: `api-${string}`; revision: number; credential_storage: 'keychain' | 'private_file' | 'legacy';
 has_api_key: boolean; extra_headers: Record<string, string>; request_url: string;
 local: boolean; blocked: boolean; status: string; created_at: string; updated_at: string;
};
export type ProfilesResponse = {
 revision: number; profiles: ApiProfile[]; routing: Record<TaskKey, RouteSelection | null>; local_only: boolean;
};
export const protocolLabels: Record<Protocol, string> = localizedRecord({
 openai_chat: 'ai.protocol.openai_chat', anthropic_messages: 'ai.protocol.anthropic_messages', openai_responses: 'ai.protocol.openai_responses'
});
export const taskLabels: Record<TaskKey, string> = localizedRecord({ translation: 'ai.task.translation', writing: 'ai.task.writing', sound_prompt: 'ai.task.sound_prompt' });
export const taskKeys: TaskKey[] = ['translation', 'writing', 'sound_prompt'];
export const presets: { id: string; label: string; base_url: string; protocol: Protocol; auth_type: ProfileDraft['auth_type']; local_engine?: 'ollama' }[] = [
 { id: 'custom', ...labeled({}, 'ai.preset.custom'), base_url: '', protocol: 'openai_chat', auth_type: 'bearer' },
 { id: 'lmstudio', label: 'LM Studio', base_url: 'http://127.0.0.1:1234/v1', protocol: 'openai_chat', auth_type: 'none' },
 { id: 'ollama', label: 'Ollama', base_url: 'http://127.0.0.1:11434/v1', protocol: 'openai_chat', auth_type: 'none', local_engine: 'ollama' },
 { id: 'openrouter', label: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1', protocol: 'openai_chat', auth_type: 'bearer' },
 { id: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com', protocol: 'openai_chat', auth_type: 'bearer' },
 { id: 'gemini', label: 'Gemini · OpenAI-compatible', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai', protocol: 'openai_chat', auth_type: 'bearer' },
 { id: 'anthropic', label: 'Claude API', base_url: 'https://api.anthropic.com/v1', protocol: 'anthropic_messages', auth_type: 'x-api-key' },
 { id: 'openai', ...labeled({}, 'ai.preset.openai'), base_url: 'https://api.openai.com/v1', protocol: 'openai_responses', auth_type: 'bearer' },
 { id: 'nvidia', label: 'NVIDIA NIM API', base_url: 'https://integrate.api.nvidia.com/v1', protocol: 'openai_chat', auth_type: 'bearer' }
];
export function newModel(id = '', label = ''): ModelProfile {
 return { id, label, max_input_chars: 32000, max_output_tokens: 4096, temperature: null, token_parameter: 'max_tokens', structured_output: 'prompt' };
}
export function newProfile(): ProfileDraft {
 return { name: '', protocol: 'openai_chat', base_url: '', auth_type: 'bearer', credential_storage: 'keychain', enabled: true, local_engine: 'generic', models: [], default_model_id: '', timeout_seconds: 120, max_concurrency: 1 };
}
export function profileDraft(profile: ApiProfile): ProfileDraft {
 return { name: profile.name, protocol: profile.protocol, base_url: profile.base_url, auth_type: profile.auth_type, credential_storage: profile.credential_storage === 'private_file' ? 'private_file' : 'keychain', enabled: profile.enabled, local_engine: profile.local_engine, models: profile.models.map(model => ({ ...model })), default_model_id: profile.default_model_id, timeout_seconds: profile.timeout_seconds, max_concurrency: profile.max_concurrency };
}
export function endpointPreview(base: string, protocol: Protocol) {
 const path = { openai_chat: 'chat/completions', anthropic_messages: 'messages', openai_responses: 'responses' }[protocol];
 return base.trim().replace(/\/+$/, '').replace(/\/(chat\/completions|messages|responses|models)$/, '') + '/' + path;
}
export function selectionValue(value: RouteSelection | null | undefined): string { return value ? JSON.stringify(value) : ''; }
export function parseSelection(value: string): RouteSelection | null {
 if (!value) return null;
 try { const parsed = JSON.parse(value); return typeof parsed.provider_id === 'string' && typeof parsed.model_id === 'string' ? parsed : null; }
 catch { return null; }
}
