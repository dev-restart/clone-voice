import { ai } from './ko/ai.ts';
import { app } from './ko/app.ts';
import { assist } from './ko/assist.ts';
import { common } from './ko/common.ts';
import { cover } from './ko/cover.ts';
import { files } from './ko/files.ts';
import { helpers } from './ko/helpers.ts';
import { home } from './ko/home.ts';
import { models } from './ko/models.ts';
import { nav } from './ko/nav.ts';
import { prefs } from './ko/prefs.ts';
import { production } from './ko/production.ts';
import { promptmgr } from './ko/promptmgr.ts';
import { queue } from './ko/queue.ts';
import { sound } from './ko/sound.ts';
import { soundresult } from './ko/soundresult.ts';
import { story } from './ko/story.ts';
import { stt } from './ko/stt.ts';
import { tts } from './ko/tts.ts';
import { ttsws } from './ko/ttsws.ts';
import { voice } from './ko/voice.ts';
import { voicelib } from './ko/voicelib.ts';

// Korean is the source language. English must define every key (enforced by the Record type in en.ts).
export const ko = { ...ai, ...app, ...assist, ...common, ...cover, ...files, ...helpers, ...home, ...models, ...nav, ...prefs, ...production, ...promptmgr, ...queue, ...sound, ...soundresult, ...story, ...stt, ...tts, ...ttsws, ...voice, ...voicelib } as const;
export type MessageKey = keyof typeof ko;
