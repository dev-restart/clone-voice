import { AudioLines, AudioWaveform, BookOpenText, FolderDown, Home, Mic, Settings, UserRound, Wand2 } from '@lucide/svelte';
import type { MessageKey } from '$lib/i18n/index.svelte';
import type { MenuKey } from '$lib/studio/types';

export type StudioMenuItem = {
  key: MenuKey;
  labelKey: MessageKey;
  icon: typeof Home;
  groupKey?: MessageKey;
  auxiliary?: boolean;
};
export const studioMenus: StudioMenuItem[] = [
  { key: 'tts', labelKey: 'nav.tts', icon: AudioLines, groupKey: 'nav.group.create' },
  { key: 'sfx', labelKey: 'nav.sfx', icon: AudioWaveform },
  { key: 'changer', labelKey: 'nav.changer', icon: Wand2 },
  { key: 'home', labelKey: 'nav.home', icon: Home, groupKey: 'nav.group.library' },
  { key: 'files', labelKey: 'nav.files', icon: FolderDown },
  { key: 'story', labelKey: 'nav.story', icon: BookOpenText, groupKey: 'nav.group.tools', auxiliary: true },
  { key: 'stt', labelKey: 'nav.stt', icon: Mic, auxiliary: true },
  { key: 'settings', labelKey: 'nav.settings', icon: Settings, groupKey: 'nav.group.manage' }
];
export const voiceSections = [
  { key: 'tts' as const, labelKey: 'nav.voice.make' as const, icon: AudioLines },
  { key: 'voices' as const, labelKey: 'nav.voice.mine' as const, icon: UserRound }
];
export function mainMenuKey(active: MenuKey): MenuKey { return active === 'voices' ? 'tts' : active; }
