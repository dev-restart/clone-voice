<script lang="ts">
	import type { MenuKey } from '$lib/studio/types';
	import { studioMenus } from './navigation';

	let { active }: { active: MenuKey } = $props();

	let title = $derived(studioMenus.find((menu) => menu.key === active)?.label ?? '홈');
	const descriptions: Record<MenuKey, string> = {
		home: '최근 작업, 생성 상태, 목소리 자산을 한 화면에서 확인합니다.',
		voices: '기준 목소리 샘플을 등록하고 설명, 아바타, 녹음 파일을 관리합니다.',
		tts: '대본을 저장하고 원하는 목소리와 언어로 음성을 제작합니다.',
		story: '여러 화자와 언어가 섞인 긴 스토리 오디오를 단락 단위로 제작합니다.',
		stt: '음성 파일 또는 녹음을 텍스트로 변환하고 번역 초안을 만듭니다.',
		changer: '원본 음성을 선택한 기준 목소리로 변환하고 버전별 결과를 비교합니다.',
		settings: '사용할 모델, 노출 순서, 기본 생성 모델을 관리합니다.'
	};
</script>

<header class="studio-topbar">
	<div>
		<h1>{title}</h1>
		<p>{descriptions[active]}</p>
	</div>
</header>
