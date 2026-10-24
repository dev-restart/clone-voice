# User guide

[한국어](user-guide.md)

Short explanations live behind the **?** buttons in the app. This guide covers the order of work and the limits worth knowing.

## Getting started

1. Install with `./install.sh`, then run `./start.sh`. The app opens at `http://127.0.0.1:18185`.
2. Follow the **Get started** checklist on the home screen: prepare a voice model → register your voice → make your first voice. Each step ticks itself off from the real state of the app.
3. Check each area's default model in Settings → Models. A model that is not installed shows its install command on its card.

`./start.sh` downloads missing models into the project (voice and speech-to-text into `backend/models/`; song cover and sound effects, on Apple Silicon only, into `backend/vendor/` and `backend/models/`), and stops whatever is using its ports before it starts (adjust with `--core-models`, `--no-models` and `--no-kill`).

To add models later, run from the repository root:

```bash
./download-models.sh --tts            # voice (VoxCPM2)
./download-models.sh --stt            # speech to text (Whisper)
./download-models.sh --soulx-singer   # song cover (Apple Silicon)
./download-models.sh --sfx            # sound effects (Apple Silicon)
```

Installed models are switched on automatically in `backend/.env`.

## Registering a voice

Prepare a reference recording in `Voice clone → Register voice`. There are three ways:

- **File**: pick an audio file.
- **Record**: record 5–10 seconds with the microphone.
- **YouTube · Instagram**: paste a video link.

### Importing from a link

1. Enter the link and press **Check**. The title and length are shown first.
2. **Clip range** (optional): enter a start and end such as `90` or `1:30` to download only that part. The default limit is 60 minutes per import; when a range is set, the limit applies to the range.
3. Turn on **Reduce background music and effects, keep the voice** to clean the speech while importing.
4. Press **Import from link**. The audio is converted to WAV and stored in `backend/storage/uploads/`.

Only single public posts are supported — not profiles, playlists or collections. For your own posts that need a login you can point to a Netscape-format cookie file.

```env
# backend/.env
CLONE_VOICE_MEDIA_IMPORT_MAX_DURATION_SECONDS=3600
CLONE_VOICE_MEDIA_IMPORT_COOKIE_FILE=
```

Keep the cookie file outside the repository, restrict its permissions and never commit it. When a service changes how it serves media, imports can fail for a while even with the latest `yt-dlp`.

### Choosing the part to use

The imported audio is shown as an overview waveform and a zoomed waveform. Aim for 5–10 seconds of clear speech.

1. **Find speech segments**: marks speech, music and singing across the whole file and suggests candidates. On Apple Silicon Macs this uses SoundAnalysis; elsewhere it falls back to loudness, so listen before choosing.
2. **Find by transcript**: transcribes up to 30 seconds around your selection; tap a sentence to select its audio and text together.
3. Listen to the selection, check the name and transcript, and save. After changing the range you must confirm the transcript belongs to the current range before saving.

The transcription engine is chosen in Settings → General: Apple Speech on Mac by default, Whisper elsewhere.

## Making a voice

1. In `Voice clone → Make voice → New script`, enter the source language and text.
2. Under **Make in other languages**, add a language to translate automatically or write it yourself in the empty tab. Existing translations are kept unless you choose to overwrite them.
3. In **Voice settings** on the right, pick the voice, speed, quality and model. Use the **pronunciation dictionary** for rules such as `API → A-P-I` (the original text stays; only the synthesized text is replaced).
4. Press **Short preview** to check the opening, then **Make voice**. Generation runs one job at a time through a queue and continues when you open other screens.
5. Download WAV, MP3, TXT or a production package ZIP. The ZIP contains the audio, the original and pronunciation-adjusted text, and the generation settings.

`⌘S / Ctrl+S` saves. One unsaved last draft is kept temporarily in this browser and can be brought back with **Restore draft**.

## Making sounds

Create a project (game, video, ambience) and store the prompt, length and settings per sound. You can start from 12 sample prompts; they have no pre-made audio.

Regenerating keeps earlier results and adds a new version. Each version shows its prompt, exclusions and seed, and you can continue with `Rebuild with these settings` or `Make a similar one`. Projects are stored on the local server; deleting one keeps the generated files in the file library. Projects and prompts can be saved even when no sound-effect model is installed.

## Song cover

`Song cover` keeps the original melody and timing and replaces the vocal with a registered voice. Choose a song file or import one from a YouTube or Instagram link, select a range on the waveform, then pick the target voice. Vocal separation, accompaniment mixing and automatic pitch matching are toggles in the conversion settings.

Quality depends heavily on the reference sample and the song. Use a clean reference with little noise or music, and try a clear 30–60 second section before converting the whole song.

## Dialogue audio (auxiliary tool)

Switch it on in Settings → General → **Show auxiliary tools**.

1. In **Make an AI dialogue**, enter a topic or paste source material, choose a format (deep dive, interview, debate, quick brief), 2–4 speakers and a length. You can also import the source text from a video link.
2. In the editor, adjust each speaker's voice and tone, per-line speed and pauses, and sound-effect cues.
3. To import your own script use `Speaker: line`, `Speaker [tone: warm]: line` and `[sfx: short transition]` (the Korean `톤` and `효과음` keywords also work).
4. **Generate dialogue audio**, then download WAV, MP3, TXT, SRT or ZIP.

Projects are saved on the server automatically and can be backed up or restored as JSON. An AI draft is not a fact check — compare it with the source before publishing.

## File library

Replay and download registered voices and generated results (TTS, dialogue audio, song covers, sound effects) in one place. Some project links for sound effects and song covers live in this browser's `localStorage`, so another browser may not show every connection.

## Settings

### General

Display language, start screen, default source language, auxiliary tools, speech-to-text engine and translation method. The Apple translation option appears on Mac only.

### Models

Manage the model list, status, default, enabled state and order for each area (voice, music, cover, sound effects). Voice and cover each need at least one enabled model. Expand a card to see the device, quality, license, supported platforms and install command.

### AI connections

Register the text AI used for script writing, translation and production help, by name. It is not needed for voice generation or voice cloning.

1. In **Add connection**, enter details yourself or start from a preset: LM Studio, Ollama, DeepSeek, OpenRouter, Gemini, Claude, OpenAI, NVIDIA (a preset only fills the address and API format; choose the model ID yourself).
2. Enter the authentication method and key. New keys go to the Mac Keychain; if that fails the app does not silently fall back to a file. Only when you choose **restricted file** is the key stored in a 0600 file.
3. Add models by hand, or save and use **Load model list**, then verify with **Test response** (external APIs may cost a small amount).
4. Choose the **default AI** and the **AI per task** (translation, scripts, production help).

Supported formats are OpenAI Chat Completions, Anthropic Messages and OpenAI Responses, using non-streaming text replies only. With **Local only** (the default) every external API call is blocked, and a failed call is never silently re-sent to another provider.

```env
# backend/.env — legacy single local connection
CLONE_VOICE_LLM_BASE_URL=http://127.0.0.1:11434/v1
CLONE_VOICE_LLM_MODEL=qwen3:4b
CLONE_VOICE_LLM_API_KEY=ollama
```

Below the AI connections tab, **Production system prompts** lets you edit and restore the instructions used for sound-effect, music, song and cover help. Music and song help only produce prompt and lyric drafts, never full-track audio.

### Mac built-in translation

Requires an Apple Silicon Mac, macOS 26 or later and the Apple Intelligence on-device model. The first check compiles a small Swift helper, so Command Line Tools or Xcode must be installed. Use **Check translation** in Settings → General to try a real translation.

## Storage and ports

Uploads, generated results and the SQLite database live in `backend/storage/` by default. Split them with `CLONE_VOICE_VOICE_DIR`, `CLONE_VOICE_UPLOAD_DIR`, `CLONE_VOICE_OUTPUT_DIR` and `CLONE_VOICE_CONTENT_DIR`.

Downloaded models live in `backend/models/` (models already present in `CLONE_VOICE_VOXCPM_CACHE_DIR` or `~/.cache` are reused, never downloaded twice). The default ports are deliberately uncommon so they do not collide with other dev servers: `18185` (frontend) and `18109` (backend). `./start.sh` stops a program that already uses them; with `--no-kill` it exits with an error instead.

```bash
BACKEND_PORT=8010 FRONTEND_PORT=5190 PUBLIC_API_BASE=http://127.0.0.1:8010 ./start.sh
```

## Troubleshooting

- **A model says "Install needed".** Run the install command on its card or run `./install.sh` again. Installed models are switched on automatically in `backend/.env`.
- **A port is already in use.** By default `./start.sh` stops the program using it and starts. If you passed `--no-kill`, quit that program yourself or change the ports as above.
- **A link import fails.** Check whether the post is public or needs a login. If a service change breaks it temporarily, run `uv sync` to refresh `yt-dlp`.
- **Song cover or sound effects cannot be installed.** Both models currently require an Apple Silicon Mac.
