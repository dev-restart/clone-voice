import { expect, test } from '@playwright/test';

const appUrl = process.env.APP_URL ?? 'http://127.0.0.1:18185/';

test.beforeEach(async ({ page }) => {
	// These legacy navigation/story scenarios explicitly enable the optional tools.
	await page.route('**/api/studio/preferences', async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		await route.fulfill({ status: 200, contentType: 'application/json', json: {
			preferences: { start_menu: 'home', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: true },
			platform: { is_mac: true, apple_speech_supported: true, apple_speech_message: 'UI 회귀 테스트용 상태' },
			generation_concurrency: 1
		} });
	});
});

function createSilentWav(seconds = 1, sampleRate = 24000) {
	const sampleCount = Math.max(1, Math.floor(sampleRate * seconds));
	const byteRate = sampleRate * 2;
	const blockAlign = 2;
	const dataSize = sampleCount * 2;
	const buffer = Buffer.alloc(44 + dataSize);
	buffer.write('RIFF', 0);
	buffer.writeUInt32LE(36 + dataSize, 4);
	buffer.write('WAVE', 8);
	buffer.write('fmt ', 12);
	buffer.writeUInt32LE(16, 16);
	buffer.writeUInt16LE(1, 20);
	buffer.writeUInt16LE(1, 22);
	buffer.writeUInt32LE(sampleRate, 24);
	buffer.writeUInt32LE(byteRate, 28);
	buffer.writeUInt16LE(blockAlign, 32);
	buffer.writeUInt16LE(16, 34);
	buffer.write('data', 36);
	buffer.writeUInt32LE(dataSize, 40);
	return buffer;
}

test('main workspace screens render without console errors', async ({ page }, testInfo) => {
	const consoleErrors: string[] = [];
	page.on('console', (message) => {
		if (message.type() === 'error') consoleErrors.push(message.text());
	});
	page.on('pageerror', (error) => {
		consoleErrors.push(error.message);
	});

	await page.goto(appUrl);
	await page.evaluate(() => window.localStorage.clear());
	await page.reload();
	await page.waitForLoadState('networkidle');
	await expect(page.getByRole('heading', { name: '작업실 홈', exact: true })).toBeVisible();
	const coreWorkflows = page.getByRole('navigation', { name: '주요 제작 작업', exact: true });
	await expect(coreWorkflows.getByRole('button')).toHaveCount(3);
	for (const workflow of ['목소리 클론', '사운드 만들기', '노래 커버']) {
		await expect(coreWorkflows.getByRole('button', { name: new RegExp(workflow) })).toBeVisible();
	}
	await expect(page.getByRole('heading', { name: '작업실 상태', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: /상태 새로고침/ })).toBeVisible();
	await page.getByRole('button', { name: /상태 새로고침/ }).click();
	await expect(page.getByText('서버 연결')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-home.png'), fullPage: true });

	for (const menu of ['목소리 클론', '파일 보관함', '대화 오디오', '사운드 만들기', '받아쓰기', '노래 커버', '설정']) {
		await page.getByRole('button', { name: menu, exact: true }).first().click();
		await expect(page.getByRole('heading', { name: menu, exact: true }).first()).toBeVisible();
		await expect(page.locator('[data-route-heading]')).toBeFocused();
	}

	await page.getByRole('button', { name: '목소리 클론', exact: true }).first().click();
	await page.getByRole('navigation', { name: '목소리 클론 작업', exact: true }).getByRole('button', { name: '내 목소리', exact: true }).click();
	await expect(page.getByLabel('목소리 검색')).toBeVisible();
	await page.getByRole('button', { name: /목소리 등록/ }).first().click();
	await expect(page.getByRole('heading', { name: '목소리 등록' })).toBeVisible();
	await expect(page.getByText('목소리 이름')).toBeVisible();
	await expect(page.getByLabel('샘플 발화 대본', { exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: '기준 음성 준비' })).toBeVisible();
	await page.getByRole('tab', { name: 'YouTube·Instagram', exact: true }).click();
	await expect(page.getByLabel('미디어 주소')).toBeVisible();
	await expect(page.getByRole('button', { name: /주소에서 가져오기/ })).toBeVisible();

	await page.getByRole('button', { name: '목소리 클론', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '저장한 대본', exact: true })).toBeVisible();
	await page.getByRole('button', { name: '새 대본' }).first().click();
	await expect(page.getByRole('heading', { name: '원본 작성', exact: true })).toBeVisible();
	await expect(page.getByLabel('목소리', { exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: '생성 결과' })).toBeVisible();
	await page.getByRole('button', { name: '콘텐츠 목록으로 돌아가기', exact: true }).click();
	await expect(page.getByRole('heading', { name: '저장한 대본', exact: true })).toBeVisible();
	await page.getByRole('button', { name: '새 대본' }).first().click();
	await expect(page.getByRole('heading', { name: '원본 작성', exact: true })).toBeVisible();
	await page.getByRole('button', { name: '목소리 클론', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '저장한 대본', exact: true })).toBeVisible();

	await page.getByRole('button', { name: '대화 오디오', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '대화 오디오' }).first()).toBeVisible();
	await expect(page.getByRole('button', { name: 'AI 대화 만들기' }).first()).toBeVisible();
	await expect(page.getByRole('button', { name: '직접 대본 쓰기' }).first()).toBeVisible();
	await expect(page.getByRole('heading', { name: '아직 저장한 대화 오디오가 없습니다' })).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-dialogue-hero.png'), fullPage: true });
	await page.getByRole('button', { name: '직접 대본 쓰기' }).first().click();
	await expect(page.getByRole('button', { name: /대화 오디오 생성/ })).toBeVisible();
	const storyStageStrip = page.getByLabel('대화 오디오 제작 단계');
	await expect(storyStageStrip.getByText('대본 구성', { exact: true })).toBeVisible();
	await expect(storyStageStrip.getByText('목소리 연출', { exact: true })).toBeVisible();
	await expect(storyStageStrip.getByText('효과음', { exact: true })).toBeVisible();
	await expect(storyStageStrip.getByText('오디오 생성', { exact: true })).toBeVisible();
	await expect(page.getByText('일괄 설정', { exact: true })).toBeVisible();
	let dialogueDraftRequest: Record<string, unknown> | null = null;
	await page.route('**/api/story-studio/dialogue-draft', async (route) => {
		dialogueDraftRequest = route.request().postDataJSON() as Record<string, unknown>;
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				title: '출시 회고 대화',
				summary: '입력 자료의 출시 일정과 대응 방안을 정리한 대화입니다.',
				format: 'interview',
				language: 'ko',
				speech_turns: 6,
				include_sfx_cues: false,
				speakers: { speaker_a: '진행자', speaker_b: '분석가' },
				turns: [
					{ index: 1, speaker: 'A', text: '자료에서 가장 먼저 확인할 내용은 무엇인가요?', sfx_cue: null },
					{ index: 2, speaker: 'B', text: '출시 일정이 일주일 조정됐다는 점입니다.', sfx_cue: null },
					{ index: 3, speaker: 'A', text: '조정 원인은 어떻게 기록되어 있나요?', sfx_cue: null },
					{ index: 4, speaker: 'B', text: '품질 확인 항목이 추가됐다고 적혀 있습니다.', sfx_cue: null },
					{ index: 5, speaker: 'A', text: '대응 방안도 자료에 있습니까?', sfx_cue: null },
					{ index: 6, speaker: 'B', text: '담당자 재배치와 재점검 일정이 제시돼 있습니다.', sfx_cue: null }
				],
				provider: 'local',
				model: 'test-model'
			})
		});
	});
	await page.getByRole('button', { name: 'AI 대화 만들기' }).click();
	const dialogueDraftDialog = page.getByRole('dialog', { name: 'AI 대화 만들기' });
	await expect(dialogueDraftDialog.getByRole('radio', { name: '주제만 적기', exact: true })).toBeChecked();
	await expect(dialogueDraftDialog.getByLabel('주제 또는 요청', { exact: true })).toBeFocused();
	await dialogueDraftDialog.getByRole('radio', { name: '자료로 만들기', exact: true }).click();
	await expect(dialogueDraftDialog.getByLabel('자료 원문', { exact: true })).toBeVisible();
	await expect(dialogueDraftDialog.getByLabel('대화 형식')).toHaveValue('deep-dive');
	await expect(dialogueDraftDialog.getByLabel('화자 1 이름')).toBeVisible();
	await expect(dialogueDraftDialog.getByLabel('화자 2 이름')).toBeVisible();
	await expect(dialogueDraftDialog.getByLabel('대화 언어')).toBeVisible();
	await expect(dialogueDraftDialog.getByLabel('대화 길이')).toBeVisible();
	await expect(dialogueDraftDialog.getByLabel('대화 턴 수')).toHaveValue('10');
	await expect(dialogueDraftDialog.getByLabel('강조할 포인트')).toBeVisible();
	const sfxToggle = dialogueDraftDialog.getByLabel('효과음 큐 포함');
	await expect(sfxToggle).toBeVisible();
	if (await sfxToggle.isDisabled()) {
		await expect(sfxToggle).not.toBeChecked();
		await expect(dialogueDraftDialog.getByText('효과음 모델이 준비되지 않아 효과음 cue는 이번 초안에서 제외됩니다.')).toBeVisible();
	} else {
		await expect(sfxToggle).toBeChecked();
		await expect(dialogueDraftDialog.getByText('효과음 cue를 초안에 함께 넣을 수 있습니다.')).toBeVisible();
		await sfxToggle.uncheck();
	}
	const fullDialogueSource =
		'출시 일정이 일주일 조정됐고 품질 확인 항목이 추가됐습니다. 담당자를 재배치하고 다음 주에 다시 점검합니다. ' +
		'조정 배경은 외부 요구사항 변경이 아니라 내부 품질 기준 강화입니다. 점검 결과는 제품 책임자와 운영 담당자가 함께 검토합니다. ' +
		'일정 변경 공지는 고객에게 사전에 전달하고, 배포 전 회귀 테스트와 접근성 검토를 완료하기로 했습니다. ' +
		'검토가 끝난 뒤에는 변경된 기준과 결과를 회고 문서로 남기고 다음 배포의 점검 목록에도 반영하기로 했습니다.';
	await dialogueDraftDialog.getByLabel('자료 원문').fill(fullDialogueSource);
	await dialogueDraftDialog.getByLabel('대화 형식').selectOption('interview');
	await dialogueDraftDialog.getByLabel('화자 2 이름').fill('분석가');
	await dialogueDraftDialog.getByLabel('대화 길이').selectOption('short');
	await expect(dialogueDraftDialog.getByLabel('대화 턴 수')).toHaveValue('6');
	await dialogueDraftDialog.getByLabel('강조할 포인트').fill('일정 조정 원인과 대응 방안');
	await page.screenshot({ path: testInfo.outputPath('clone-voice-dialogue-modal.png'), fullPage: true });
	await dialogueDraftDialog.getByRole('button', { name: '편집기로 가져오기' }).click();
	await expect(page.getByLabel('대화 오디오 제목')).toHaveValue('출시 회고 대화');
	await expect(page.getByText('초안 형식 · 인터뷰')).toBeVisible();
	await expect(page.getByLabel('대사 1')).toHaveValue('자료에서 가장 먼저 확인할 내용은 무엇인가요?');
	await expect(page.getByLabel('대사 2')).toHaveValue('출시 일정이 일주일 조정됐다는 점입니다.');
	expect(dialogueDraftRequest).toMatchObject({
		mode: 'source',
		source_text: fullDialogueSource,
		format: 'interview',
		language: 'ko',
		speech_turns: 6,
		speaker_a_name: '진행자',
		speaker_b_name: '분석가',
		focus: '일정 조정 원인과 대응 방안',
		include_sfx_cues: false
	});
	await page.screenshot({ path: testInfo.outputPath('clone-voice-dialogue-editor.png'), fullPage: true });
	await page.getByRole('button', { name: '목록' }).first().click();
	await page.reload();
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: '대화 오디오', exact: true }).first().click();
	await page.getByRole('button', { name: '출시 회고 대화 편집' }).click();
	const detailAiDraftButton = page.getByRole('button', { name: 'AI 대화 만들기' });
	await detailAiDraftButton.click();
	await dialogueDraftDialog.getByRole('radio', { name: '자료로 만들기', exact: true }).click();
	await expect(dialogueDraftDialog.getByLabel('자료 원문', { exact: true })).toBeVisible();
	await expect(dialogueDraftDialog.getByLabel('자료 원문', { exact: true })).toHaveValue(fullDialogueSource);
	await page.keyboard.press('Escape');
	await expect(dialogueDraftDialog).toBeHidden();
	await expect(detailAiDraftButton).toBeFocused();
	await page.getByRole('button', { name: '1번 단락 아래로 이동' }).click();
	await expect(page.getByLabel('대사 1')).toHaveValue('출시 일정이 일주일 조정됐다는 점입니다.');
	await page.getByRole('button', { name: '2번 단락 위로 이동' }).click();
	await expect(page.getByLabel('대사 1')).toHaveValue('자료에서 가장 먼저 확인할 내용은 무엇인가요?');
	await page.getByRole('button', { name: '대본 가져오기' }).click();
	const scriptDialog = page.getByRole('dialog', { name: '대본 가져오기' });
	await expect(scriptDialog.getByLabel('미디어 주소')).toBeVisible();
	await expect(scriptDialog.getByRole('button', { name: /미디어 전사/ })).toBeVisible();
	await scriptDialog.getByLabel('화자 대본').fill(
		'진행자: 오늘 이야기의 배경을 소개합니다.\n' +
			'게스트 [톤: 밝고 친근하게]: 반갑습니다. 함께 이야기해 볼게요.\n' +
			'해설: [톤: 긴장감 있게] 그때 예상하지 못한 소리가 들렸습니다.\n' +
			'[효과음: 짧은 전환 알림음]'
	);
	await expect(scriptDialog.getByText('3명', { exact: true })).toBeVisible();
	await expect(scriptDialog.getByLabel('진행자 가져오기 목소리')).toBeVisible();
	await expect(scriptDialog.getByLabel('게스트 가져오기 목소리')).toBeVisible();
	await expect(scriptDialog.getByLabel('해설 가져오기 목소리')).toBeVisible();
	await scriptDialog.getByLabel('진행자 가져오기 기본 톤').fill('차분하고 자연스럽게');
	await scriptDialog.getByRole('button', { name: '타임라인 만들기' }).click();
	await expect(page.getByRole('heading', { name: '화자별 설정' })).toBeVisible();
	await expect(page.getByLabel('진행자 전체 기본 톤')).toHaveValue('차분하고 자연스럽게');
	await expect(page.getByLabel('게스트 전체 기본 톤')).toHaveValue('밝고 친근하게');
	await expect(page.getByLabel('해설 전체 기본 톤')).toHaveValue('긴장감 있게');
	await expect(page.getByText('(밝고 친근하게)', { exact: true })).toBeVisible();
	await expect(page.getByText('(긴장감 있게)', { exact: true })).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-story-speakers.png'), fullPage: true });
	await page.getByRole('button', { name: '목록' }).first().click();
	await expect(page.getByRole('heading', { name: '대화 오디오' }).first()).toBeVisible();
	await page.getByRole('button', { name: '직접 대본 쓰기' }).first().click();
	await expect(page.getByRole('button', { name: /대화 오디오 생성/ })).toBeVisible();
	await page.getByRole('button', { name: '대화 오디오', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '대화 오디오' }).first()).toBeVisible();

	await page.getByRole('button', { name: '사운드 만들기', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '사운드 만들기', exact: true }).first()).toBeVisible();
	// Asset-project creation and prompt controls are exercised by the dedicated SFX workflow tests.
	await page.screenshot({ path: testInfo.outputPath('clone-voice-sfx.png'), fullPage: true });

	await page.getByRole('button', { name: '받아쓰기', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '음성을 글로 바꾸기' })).toBeVisible();
	await expect(page.getByRole('heading', { name: '받아쓰기·번역 설정' })).toBeVisible();
	await expect(page.getByRole('button', { name: '받아쓰기 시작', exact: true })).toBeVisible();

	await page.getByRole('button', { name: '노래 커버', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '저장한 노래 커버', exact: true })).toBeVisible();
	await page.getByRole('button', { name: /새 노래 커버/ }).first().click();
	await expect(page.getByRole('button', { name: /노래 커버 만들기/ })).toBeVisible();
	await expect(page.getByRole('heading', { name: '변환 설정' })).toBeVisible();
	await expect(page.getByRole('combobox', { name: '커버 모델', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: '균형' })).toHaveClass(/active/);
	await expect(page.getByText('원곡에서 보컬 자동 분리')).toBeVisible();
	await expect(page.getByText('목소리에 맞게 음역 조정')).toBeVisible();
	await expect(page.getByLabel('원곡 미디어 주소')).toBeVisible();
	await expect(page.getByRole('button', { name: /주소에서 가져오기/ })).toBeVisible();
	await expect(page.getByRole('heading', { name: '완성된 버전' })).toBeVisible();
	await page.route('**/api/audio/media-import', async (route) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				platform: 'youtube',
				title: 'AI Cover Source',
				webpage_url: 'https://www.youtube.com/watch?v=test-cover',
				duration_seconds: 64,
				audio_url: '/api/files/uploads/cover-import.wav',
				filename: 'cover-import.wav',
				voice_isolated: false
			})
		});
	});
	await page.route('**/api/files/uploads/cover-import.wav', async (route) => {
		await route.fulfill({
			status: 200,
			contentType: 'audio/wav',
			body: createSilentWav()
		});
	});
	await page.getByLabel('원곡 미디어 주소').fill('https://www.youtube.com/watch?v=test-cover');
	await page.getByRole('button', { name: /주소에서 가져오기/ }).click();
	const coverSourceSummary = page.locator('.cover-source-summary');
	await expect(coverSourceSummary.getByRole('heading', { name: '원곡 정보' })).toBeVisible();
	await expect(page.getByText('AI Cover Source')).toBeVisible();
	await expect(coverSourceSummary.getByText('YouTube 영상·Shorts')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-ai-cover.png'), fullPage: true });
	await page.getByRole('button', { name: '목록' }).first().click();
	await expect(page.getByRole('heading', { name: '저장한 노래 커버', exact: true })).toBeVisible();
	await page.getByRole('button', { name: /새 노래 커버/ }).first().click();
	await expect(page.getByRole('button', { name: /노래 커버 만들기/ })).toBeVisible();
	await page.getByRole('button', { name: '노래 커버', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '저장한 노래 커버', exact: true })).toBeVisible();

	await page.getByRole('button', { name: '설정', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '설정', exact: true }).first()).toBeVisible();
	await page.getByRole('tab', { name: '모델', exact: true }).click();
	await expect(page.getByRole('heading', { name: '모델', exact: true })).toBeVisible();
	for (const area of ['음성', '음악', '커버', '효과음']) await expect(page.getByRole('heading', { name: area, exact: true })).toBeVisible();
	await expect(page.getByText('설치된 음악 모델이 없습니다', { exact: true })).toBeVisible();
	const coverEngine = page.locator('[data-model-id="soulx-singer"]');
	await expect(coverEngine.getByText('SoulX-Singer', { exact: true })).toBeVisible();
	await expect(coverEngine.getByRole('button', { name: '기본 모델', exact: true })).toBeVisible();
	await expect(coverEngine.getByRole('switch')).toBeChecked();
	await expect(page.getByText('OmniVoice', { exact: true })).toHaveCount(0);
	await expect(page.getByText('CosyVoice', { exact: true })).toHaveCount(0);
	await page.getByRole('tab', { name: 'AI 연결', exact: true }).click();
	const aiModelPanel = page.locator('.ai-connections');
	await expect(aiModelPanel.getByRole('heading', { name: 'AI 연결', exact: true })).toBeVisible();
	await expect(aiModelPanel.getByRole('button', { name: '연결 추가', exact: true })).toBeVisible();
	// The provider catalog can take a while on the first call (it probes Apple on-device models).
	await expect(aiModelPanel.getByLabel('기본 AI', { exact: true })).toBeVisible({ timeout: 30000 });
	await expect(aiModelPanel.getByText('ChatGPT · Codex 연결', { exact: true })).toBeHidden();
	await aiModelPanel.locator('.native-connections > summary').click();
	await expect(aiModelPanel.getByText('ChatGPT · Codex 연결', { exact: true })).toBeVisible();
	await expect(aiModelPanel.getByText('Kimi 구독', { exact: true })).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-model-settings.png'), fullPage: true });

	expect(consoleErrors).toEqual([]);
});

test('mobile navigation keeps primary screens accessible', async ({ page }, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(appUrl);
	await page.evaluate(() => window.localStorage.clear());
	await page.reload();
	await page.waitForLoadState('networkidle');
	await expect(page.getByRole('heading', { name: '작업실 홈', exact: true })).toBeVisible();
	await page.getByRole('button', { name: '목소리 클론', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '목소리 클론', exact: true })).toBeVisible();
	const mobileNav = page.getByRole('navigation', { name: '모바일 스튜디오 메뉴' });
	const activeMobileMenu = mobileNav.getByRole('button', { name: '목소리 클론', exact: true });
	await expect(activeMobileMenu).toHaveAttribute('aria-current', 'page');
	const mobileMenuBox = await activeMobileMenu.boundingBox();
	expect(mobileMenuBox?.height ?? 0).toBeGreaterThanOrEqual(44);
	await page.screenshot({ path: testInfo.outputPath('clone-voice-mobile-tts.png'), fullPage: true });
	await page.getByRole('button', { name: '대화 오디오', exact: true }).first().click();
	await page.getByRole('button', { name: 'AI 대화 만들기' }).click();
	const mobileDialogueDialog = page.getByRole('dialog', { name: 'AI 대화 만들기' });
	await expect(mobileDialogueDialog.getByRole('radio', { name: '주제만 적기', exact: true })).toBeChecked();
	await expect(mobileDialogueDialog.getByLabel('주제 또는 요청', { exact: true })).toBeFocused();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-mobile-dialogue-modal.png'), fullPage: true });
	await page.keyboard.press('Escape');
	await expect(mobileDialogueDialog).toBeHidden();
	await page.getByRole('button', { name: '직접 대본 쓰기' }).first().click();
	await page.getByRole('button', { name: '대본 가져오기' }).click();
	const mobileScriptDialog = page.getByRole('dialog', { name: '대본 가져오기' });
	await mobileScriptDialog.getByLabel('화자 대본').fill(
		'진행자: 첫 번째 대사입니다.\n게스트 [톤: 밝고 친근하게]: 두 번째 대사입니다.\n해설: 세 번째 대사입니다.'
	);
	await expect(mobileScriptDialog.getByText('3명', { exact: true })).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-mobile-story-import.png'), fullPage: true });
	await mobileScriptDialog.getByRole('button', { name: '타임라인 만들기' }).click();
	await expect(page.getByRole('heading', { name: '화자별 설정' })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	await page.screenshot({ path: testInfo.outputPath('clone-voice-mobile-story-speakers.png'), fullPage: true });
	await page.getByRole('button', { name: '사운드 만들기', exact: true }).first().click();
	await expect(page.getByRole('heading', { name: '사운드 만들기', exact: true }).first()).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	await page.screenshot({ path: testInfo.outputPath('clone-voice-mobile-sfx.png'), fullPage: true });
	await page.getByRole('button', { name: '노래 커버', exact: true }).first().click();
	await page.getByRole('button', { name: /새 노래 커버/ }).first().click();
	await expect(page.getByRole('heading', { name: '변환 설정' })).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-mobile-ai-cover.png'), fullPage: true });
	await page.getByRole('button', { name: '설정', exact: true }).first().click();
	await page.getByRole('tab', { name: '모델', exact: true }).click();
	await expect(page.getByRole('heading', { name: '모델', exact: true })).toBeVisible();
	await expect(page.locator('[data-model-id]').first()).toBeVisible();
	await page.getByRole('tab', { name: 'AI 연결', exact: true }).click();
	const mobileAiModelPanel = page.locator('.ai-connections');
	await expect(mobileAiModelPanel.getByRole('heading', { name: 'AI 연결', exact: true })).toBeVisible();
	await expect(mobileAiModelPanel.getByText('ChatGPT · Codex 연결', { exact: true })).toBeHidden();
	await mobileAiModelPanel.locator('.native-connections > summary').click();
	await expect(mobileAiModelPanel.getByText('ChatGPT · Codex 연결', { exact: true })).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('clone-voice-mobile-model-settings.png'), fullPage: true });
});
