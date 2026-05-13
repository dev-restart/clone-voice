import {
	AudioLines,
	BookOpenText,
	Home,
	Mic,
	Settings,
	TextCursorInput,
	UserRound,
	Wand2
} from 'lucide-svelte';
import type { MenuKey } from '$lib/studio/types';

export type StudioMenuItem = {
	key: MenuKey;
	label: string;
	icon: typeof Home;
	group?: string;
};

export const studioMenus: StudioMenuItem[] = [
	{ key: 'home', label: '대시보드', icon: Home },
	{ key: 'voices', label: '음성 라이브러리', icon: UserRound, group: '자산' },
	{ key: 'tts', label: 'TTS 제작', icon: AudioLines, group: '제작' },
	{ key: 'story', label: '스토리 오디오', icon: BookOpenText },
	{ key: 'stt', label: 'STT 변환', icon: Mic },
	{ key: 'changer', label: '보이스 체인저', icon: Wand2 },
	{ key: 'settings', label: '모델 설정', icon: Settings, group: '관리' }
];
