// Records a scripted tour of Clone Voice Studio (cursor, captions, menu changes) as a WebM video.
//
//   node scripts/record-demo.mjs <app-url> <out-dir> [narration.json]
//
// Without narration.json the tour runs at its natural pace and writes scenes.json (how long each scene took).
// With narration.json ({ "<scene>": <seconds of voice-over> }) every scene is paced to its voice-over, and
// scenes.json then holds the start time of each scene so the audio can be mixed in at the right moment.

// Point it at an instance with sample data (a throwaway CLONE_VOICE_STORAGE_DIR) so no personal voices
// or scripts end up in the video. Encode the result with ffmpeg afterwards.
import { chromium } from '@playwright/test';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const [appUrl = 'http://127.0.0.1:18185/', outDir = './demo', narrationPath] = process.argv.slice(2);
const narration = narrationPath ? JSON.parse(readFileSync(narrationPath, 'utf8')) : null;
const naturalPath = `${outDir}/natural.json`;
const natural = existsSync(naturalPath) ? JSON.parse(readFileSync(naturalPath, 'utf8')) : {};
const SIZE = { width: 1440, height: 900 };

const overlay = () => {
	const style = document.createElement('style');
	style.textContent = `
		#demo-cursor{position:fixed;left:0;top:0;width:30px;height:30px;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px);filter:drop-shadow(0 3px 5px rgba(0,0,0,.35))}
		.demo-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;border:3px solid #14b8a6;animation:demo-ripple .6s ease-out forwards}
		@keyframes demo-ripple{to{transform:scale(4.5);opacity:0}}
		#demo-caption{position:fixed;left:50%;bottom:44px;z-index:2147483645;pointer-events:none;transform:translate(-50%,24px);opacity:0;transition:opacity .45s ease,transform .45s ease;
			max-width:min(1100px,88vw);padding:16px 30px;border-radius:18px;background:rgba(15,23,22,.88);color:#fff;text-align:center;backdrop-filter:blur(8px);
			font:600 30px/1.3 -apple-system,'Apple SD Gothic Neo','Pretendard',system-ui,sans-serif;box-shadow:0 14px 40px rgba(0,0,0,.28)}
		#demo-caption small{display:block;margin-top:6px;font-size:19px;font-weight:500;color:#9fe7dc}
		#demo-caption.on{opacity:1;transform:translate(-50%,0)}
		#demo-title{position:fixed;inset:0;z-index:2147483644;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;text-align:center;
			background:radial-gradient(circle at 30% 20%,#0f766e 0,#10211f 55%,#0b1514 100%);color:#fff;opacity:0;pointer-events:none;transition:opacity .7s ease;
			font-family:-apple-system,'Apple SD Gothic Neo','Pretendard',system-ui,sans-serif}
		#demo-title.on{opacity:1}
		#demo-title h1{margin:0;font-size:84px;letter-spacing:-.02em;font-weight:800}
		#demo-title p{margin:0;font-size:34px;color:#9fe7dc;font-weight:500}
		#demo-title i{font-style:normal;font-size:22px;opacity:.7}`;
	document.head.append(style);

	const cursor = document.createElement('div');
	cursor.id = 'demo-cursor';
	cursor.innerHTML = '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M4 2l15 9-6.5 1.6L9.6 19z" fill="#fff" stroke="#10211f" stroke-width="1.6" stroke-linejoin="round"/></svg>';
	const caption = document.createElement('div');
	caption.id = 'demo-caption';
	const title = document.createElement('div');
	title.id = 'demo-title';
	document.body.append(cursor, caption, title);

	addEventListener('mousemove', (event) => {
		cursor.style.transform = `translate(${event.clientX - 4}px, ${event.clientY - 2}px)`;
	}, true);
	addEventListener('mousedown', (event) => {
		const ripple = document.createElement('div');
		ripple.className = 'demo-ripple';
		ripple.style.left = `${event.clientX}px`;
		ripple.style.top = `${event.clientY}px`;
		document.body.append(ripple);
		setTimeout(() => ripple.remove(), 700);
	}, true);

	window.__demo = {
		caption(text, sub = '') {
			caption.innerHTML = `${text}${sub ? `<small>${sub}</small>` : ''}`;
			caption.classList.add('on');
		},
		hideCaption: () => caption.classList.remove('on'),
		title(heading, line, small = '') {
			title.innerHTML = `<h1>${heading}</h1><p>${line}</p><i>${small}</i>`;
			title.classList.add('on');
		},
		hideTitle: () => title.classList.remove('on'),
	};
};

let pace = 1; // stretches or squeezes the fixed pauses of the current scene
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms * pace));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const browser = await chromium.launch();
const context = await browser.newContext({
	viewport: SIZE,
	locale: 'ko-KR',
	recordVideo: { dir: outDir, size: SIZE },
});
await context.addInitScript(`document.addEventListener('DOMContentLoaded', ${overlay.toString()});`);
const page = await context.newPage();
page.setDefaultTimeout(6000);

const caption = async (text, sub = '', hold = 2600) => {
	await page.evaluate(([t, s]) => window.__demo.caption(t, s), [text, sub]);
	await wait(hold);
};
const hideCaption = async (pause = 450) => {
	await page.evaluate(() => window.__demo.hideCaption());
	await wait(pause);
};

async function moveTo(locator, { steps = 28 } = {}) {
	await locator.scrollIntoViewIfNeeded().catch(() => {});
	const box = await locator.boundingBox();
	if (!box) return false;
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps });
	await wait(250);
	return true;
}

async function click(locator, after = 900) {
	if (!(await moveTo(locator))) return false;
	await page.mouse.down();
	await wait(70);
	await page.mouse.up();
	await wait(after);
	return true;
}

// A missing element must not abort the whole recording.
const attempt = async (label, action) => {
	try {
		await action();
	} catch (error) {
		console.warn(`skipped ${label}: ${String(error.message).split('\n')[0]}`);
	}
};

const origin = Date.now();
const scenes = {};
const LEAD = 0.35; // seconds between a scene starting and its voice-over
const TAIL = 0.6; // seconds of calm after the voice-over ends

async function scene(key, action) {
	const start = (Date.now() - origin) / 1000;
	const voice = narration?.[key];
	pace = voice && natural[key] ? Math.min(1.8, Math.max(0.45, (voice + LEAD + TAIL) / natural[key])) : 1;
	await attempt(key, action);
	pace = 1;
	if (voice) {
		const remaining = start + LEAD + voice + TAIL - (Date.now() - origin) / 1000;
		if (remaining > 0) await sleep(remaining * 1000);
	}
	const end = (Date.now() - origin) / 1000;
	scenes[key] = { start: Number(start.toFixed(2)), duration: Number((end - start).toFixed(2)) };
}

const nav = (name) => page.locator('aside, nav').getByRole('button', { name, exact: true }).first();
const scrollBy = async (distance, steps = 12) => {
	for (let i = 0; i < steps; i += 1) {
		await page.mouse.wheel(0, distance / steps);
		await wait(45);
	}
	await wait(500);
};

await page.goto(appUrl, { waitUntil: 'networkidle' });
await page.mouse.move(720, 450);
await wait(300);

// Intro
await scene('intro', async () => {
	await page.evaluate(() => window.__demo.title('Clone Voice Studio', '내 컴퓨터에서, 인터넷 없이', '목소리 클론 · 다국어 음성 · 효과음 · 노래 커버'));
	await wait(3200);
	await page.evaluate(() => window.__demo.hideTitle());
	await wait(900);
});

// 1. Studio home
await scene('home', async () => {
	await click(nav('작업실 홈'), 1100);
	await caption('작업실 홈', '시작 단계와 최근 작업이 한눈에', 2200);
	await moveTo(page.getByRole('button', { name: '이 목소리로 내레이션' }).first());
	await caption('등록한 목소리로 바로 시작', '', 2200);
	await hideCaption();
});

// 2. Voice clone: scripts
await scene('voice', async () => {
	await click(nav('목소리 클론'), 1100);
	await caption('목소리 클론', '용도별 템플릿으로 대본을 시작합니다', 2200);
	await moveTo(page.getByRole('button', { name: /짧은 영상/ }).first());
	await wait(500);
	await moveTo(page.getByRole('button', { name: /강의·튜토리얼/ }).first());
	await wait(500);
	await hideCaption();
	await click(page.getByRole('button', { name: '편집' }).last(), 1300);
	await caption('대본을 쓰고, 언어별 음성을 만듭니다', '한국어 · English · 日本語 …', 2600);
	await scrollBy(520);
	await caption('목소리 · 속도 · 모델을 고르고 한 번에 생성', '', 2400);
	await scrollBy(-520);
	await hideCaption();
});

// 3. My voices
await scene('mine', async () => {
	await click(nav('목소리 클론'), 700);
	await click(page.getByRole('button', { name: '내 목소리', exact: true }).first(), 1100);
	await caption('내 목소리', '5~10초 샘플이면 충분합니다', 2600);
	await hideCaption();
});

// 4. Register a voice (link import)
await scene('register', async () => {
	await click(page.getByRole('button', { name: '목소리 등록', exact: true }).first(), 1200);
	await caption('목소리 등록', '파일 · 녹음 · YouTube / Instagram 링크', 2600);
	await click(page.getByRole('tab', { name: 'YouTube·Instagram' }), 800);
	const url = page.getByRole('textbox', { name: '미디어 주소' });
	await moveTo(url);
	await url.click();
	await url.pressSequentially('https://www.youtube.com/watch?v=dQw4w9WgXcQ', { delay: 45 });
	await wait(400);
	await moveTo(page.getByRole('textbox', { name: '시작' }));
	await page.getByRole('textbox', { name: '시작' }).click();
	await page.keyboard.type('1:30', { delay: 90 });
	await page.getByRole('textbox', { name: '끝' }).click();
	await page.keyboard.type('1:45', { delay: 90 });
	await wait(500);
	await caption('링크의 필요한 구간만 가져옵니다', '', 2600);
	await hideCaption();
});

// 5. Sound effects
await scene('sfx', async () => {
	await click(nav('사운드 만들기'), 1100);
	await caption('사운드 만들기', '장면 설명으로 효과음을 만들고 버전을 관리', 2400);
	await scrollBy(420);
	await caption('프롬프트 예제로 바로 시작', '', 2200);
	await scrollBy(-420);
	await hideCaption();
});

// 6. Song cover
await scene('cover', async () => {
	await click(nav('노래 커버'), 1100);
	await caption('노래 커버', '보컬을 분리해 내 목소리로 바꾸고 반주와 다시 합칩니다', 2200);
	await click(page.getByRole('button', { name: '노래 커버 만들기' }).first(), 1300);
	await scrollBy(420);
	await caption('원곡 · 구간 · 대상 목소리를 고르면 끝', '', 2400);
	await scrollBy(-420);
	await hideCaption();
});

// 7. File library
await scene('files', async () => {
	await click(nav('파일 보관함'), 1100);
	await caption('파일 보관함', '목소리와 생성 결과를 한곳에서 듣고 내려받기', 2400);
	await click(page.getByRole('button', { name: '등록 목소리' }).first(), 900);
	await hideCaption();
});

// 8. Settings
await scene('settings', async () => {
	await click(nav('설정'), 1100);
	await caption('설정', '', 1400);
	await click(page.getByRole('tab', { name: '모델' }), 1300);
	await caption('영역별 모델 선택', '음성 · 음악 · 커버 · 효과음 — 새 모델을 추가해 고를 수 있습니다', 3000);
	await scrollBy(380);
	await wait(700);
	await scrollBy(-380);
	await click(page.getByRole('tab', { name: 'AI 연결' }), 1200);
	await caption('텍스트 AI는 선택', 'Ollama · LM Studio · Mac 번역 · 외부 API', 2800);
	await hideCaption();
});

// 9. Language switch
await scene('language', async () => {
	await click(nav('작업실 홈'), 800);
	await caption('한국어 ↔ English', '화면 언어를 바로 바꿀 수 있어요', 1800);
	await click(page.getByRole('radio', { name: 'English' }), 1400);
	await hideCaption(300);
	await click(page.locator('aside, nav').getByRole('button', { name: 'Voice Clone', exact: true }).first(), 1000);
	await caption('Everything in your own language', '', 2000);
	await click(page.locator('aside, nav').getByRole('button', { name: 'Studio Home', exact: true }).first(), 1000);
	await hideCaption();
});

// Outro
await scene('outro', async () => {
	await page.evaluate(() => window.__demo.title('Clone Voice Studio', 'Offline · Open source · Runs on your computer', 'github.com/dev-restart/clone-voice'));
	await wait(3600);
});

mkdirSync(outDir, { recursive: true });
if (narration) {
	writeFileSync(`${outDir}/scenes.json`, JSON.stringify(scenes, null, 1));
} else {
	writeFileSync(naturalPath, JSON.stringify(Object.fromEntries(Object.entries(scenes).map(([key, value]) => [key, value.duration])), null, 1));
}
const video = page.video();
await context.close();
console.log(await video.path());
await browser.close();
