export type StudioPreferences = {
  start_menu: 'tts' | 'sfx' | 'changer' | 'home';
  source_language: 'ko' | 'en' | 'ja' | 'zh' | 'es' | 'fr' | 'de';
  stt_provider: 'apple-speech' | 'whisper';
  show_auxiliary_tools: boolean;
};
export type StudioPreferencesResponse = {
  preferences: StudioPreferences;
  platform: { is_mac: boolean; apple_speech_supported: boolean; apple_speech_message: string };
  generation_concurrency: number;
};
export const defaultStudioPreferences: StudioPreferences = {
  start_menu: 'tts', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: false
};
