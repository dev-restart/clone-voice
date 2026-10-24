<div align="center">

# Clone Voice Studio

**On your computer. No internet needed.**<br>
An offline AI voice studio for voice cloning, multilingual speech, sound effects and song covers

English · [한국어](README.md)

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20WSL2-supported-green)
![Offline](https://img.shields.io/badge/runs-offline-success)

<img src="docs/media/clone-voice-demo.gif" alt="Clone Voice Studio tour" width="860">

[Full video with Korean narration (MP4)](docs/media/clone-voice-demo-narrated.mp4)

</div>

Clone Voice Studio is an **offline production tool that downloads and uses public AI models**. This repository contains no models: the installer fetches each one from its official source, and after the first download everything runs on your own computer without internet. Scripts, voice samples and generated results stay on your machine.

> **Models follow their own licenses.** The code in this repository is MIT, but that license does not cover the models and weights you download. Before commercial use or redistribution, read [Models and their licenses](#models-and-their-licenses).

## What you can do

| | |
| --- | --- |
| 🎙 **Voice cloning** | Register your voice from a 5–10 second sample and generate speech in many languages. |
| ▶️ **Import from YouTube / Instagram** | Paste a link, import just the part you need, and register it as a voice. Long videos are fast because only the chosen part is downloaded. |
| 🎵 **Song covers** | Separate the vocals, convert them to your registered voice and mix the accompaniment back in. |
| 🔊 **Sound effects** | Describe a scene, get a sound effect, and keep versions per project. |
| 💬 **Dialogue audio** | Turn a topic or source text into a 2–4 person dialogue with a voice per speaker. |
| 📝 **Transcribe & translate** | Turn speech into text and translate it. On a Mac it uses Apple on-device features. |

## Install

One line in a terminal. It installs what is missing (uv, Python, Node.js, pnpm, ffmpeg) and the models you choose.

```bash
curl -fsSL https://raw.githubusercontent.com/dev-restart/clone-voice/main/install.sh | bash
```

Already cloned the repository? Run it from inside:

```bash
./install.sh            # pick the models to install
./install.sh --yes      # recommended set (voice + transcription), no questions
./install.sh --models all
```

Then start the app:

```bash
./start.sh              # http://127.0.0.1:18185
```

Right after cloning you can simply run `./start.sh`. It prepares what the app needs to run:

- **Tools and dependencies are prepared automatically.** If uv, Node.js, pnpm or ffmpeg is missing it runs `./install.sh` first, and it also installs the dependencies and creates `backend/.env`.
- **Missing models are installed automatically.** If the voice model (VoxCPM2) or the speech-to-text model (Whisper) is missing, it is downloaded once into this project's `backend/models/` before the app starts. Models you already have in the folder set by `CLONE_VOICE_VOXCPM_CACHE_DIR` or in the global cache (`~/.cache`) are reused, never downloaded twice. Deleting the folder removes the models with it.
- **Song-cover and sound-effect models are installed too (Apple Silicon).** SoulX-Singer and Stable Audio 3 are downloaded on Apple Silicon Macs only and skipped elsewhere. Everything together needs 10 GB or more, so use `./start.sh --core-models` to fetch just the voice and speech-to-text models.
- **Rarely used ports.** The app listens on `18185` (UI) and `18109` (server) so it does not collide with other dev servers.
- **A busy port is freed.** If a previous run is still alive or another program holds the port, that process is stopped (its PID and name are printed) and the app starts.

```bash
./start.sh --core-models                  # only the voice and speech-to-text models
./start.sh --no-models                    # do not download models automatically
./start.sh --no-kill                      # stop with an error instead of freeing a busy port
FRONTEND_PORT=19000 BACKEND_PORT=19001 PUBLIC_API_BASE=http://127.0.0.1:19001 ./start.sh
```

> **Supported** macOS (Apple Silicon recommended), Linux, and Windows through WSL 2. Speed on Linux/WSL 2 depends on your hardware, and the song-cover and sound-effect models currently need Apple Silicon. Each model needs several GB of disk space.

## Pick the model you want

Models are organised into **areas**. Choose a default per area under Settings → Models and the same choice shows up in each workspace's model picker.

| Area | Used by | Included |
| --- | --- | --- |
| Voice | Voice Clone, Dialogue Audio | [VoxCPM2](https://github.com/OpenBMB/VoxCPM) |
| Music | (waiting for a model) | — |
| Cover | Song Cover | [SoulX-Singer](https://github.com/Soul-AILab/SoulX-Singer) |
| Sound effects | Sound Effects | [Stable Audio 3 Small-SFX](https://github.com/Stability-AI/stable-audio-3) |
| Transcription | Voice registration, Transcribe | [Whisper](https://github.com/openai/whisper) · Apple Speech (Mac) |

To add a model, write one adapter and register it — it then appears in its area. See [Adding a model](docs/adding-a-model.md).

## A text AI is optional

Voice cloning and speech generation do not need a text AI (LLM). It is only used by helper features such as script writing, translation and dialogue drafts, and you choose it under Settings → AI connections:

- **Local** — Ollama, LM Studio or any server on your machine
- **Mac built-in** — Apple on-device translation
- **External API** — DeepSeek, OpenRouter, Gemini, Claude, OpenAI and more (only when you add them; the default is “local only”)

## Korean · English

Switch the display language at the top right. It is separate from the language of your scripts and speech.

## Docs

- [User guide](docs/user-guide.en.md) · [사용 가이드 (한국어)](docs/user-guide.md)
- [Adding a model](docs/adding-a-model.md)
- [Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
- Design system: `cd frontend && pnpm storybook`

## Use it responsibly

This is a single-user tool meant to run on your own computer. It has no authentication or user separation, so do not expose it to the internet. When you use someone else's voice or a song, get their consent and the right to use it, and never present generated audio as a real statement. Use YouTube / Instagram import only for your own content or material you may process, and check each service's terms.

## Models and their licenses

Clone Voice Studio **does not bundle or redistribute** the models below. The install scripts download them from their official sources, and whoever uses a model must follow that model's license and terms of use.

| Model | Used for | License (summary) | Official source |
| --- | --- | --- | --- |
| VoxCPM2 | Voice cloning and speech | Apache-2.0 | [OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM) |
| Whisper | Speech to text | MIT | [openai/whisper](https://github.com/openai/whisper) |
| SoulX-Singer | Song cover | Apache-2.0 (check each distribution for converted weights) | [Soul-AILab/SoulX-Singer](https://github.com/Soul-AILab/SoulX-Singer) |
| Stable Audio 3 Small-SFX | Sound effects | Weights: Stability AI Community License | [Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3) |

- The table is a summary. The license text and model card of each model are authoritative, and terms can change when a model is updated.
- What you may do with generated output (commercial use, attribution, limits by revenue and so on) also follows the model's license. Stable Audio 3 weights in particular come with their own community license terms.
- Any text AI you connect (Ollama, LM Studio, external APIs) is governed by that provider's terms.
- A more detailed breakdown per component is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

The **code and documentation** in this repository are under the [MIT License](LICENSE). It does not apply to model weights, external runtimes (yt-dlp, FFmpeg and others) or the videos and music you import; those follow their own licenses and the permission of their rights holders.
