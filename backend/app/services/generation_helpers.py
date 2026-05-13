import asyncio
import json
import re
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from app.config import Settings, get_settings
from app.schemas import GenerationPreviewRequest, GenerationPreviewResponse, TranscriptSegmentsResponse, VoiceProfile, public_file_url
from app.services.omnivoice_service import (
    MockVoiceEngine,
    OmniVoiceEngine,
    combine_omnivoice_instruct,
    effective_accent_for_language,
    language_code_to_omnivoice_language,
    normalize_accent_override,
    normalize_omnivoice_instruct,
)
from app.services.voxcpm_service import build_voxcpm_control_prompt
from app.services.progress import publish_progress
from app.services.stt_service import STTProvider, transcribe_audio

DEFAULT_REFERENCE_PROMPTS = {
    "안녕하세요. 이 목소리는 음성 합성을 위한 샘플입니다. 또렷하고 자연스럽게 말하며 억양과 발음이 잘 드러나도록 녹음합니다.",
    "안녕하세요. 이 목소리는 로컬 음성 합성을 위한 샘플입니다. 또렷하고 자연스럽게 말하며 억양과 발음이 잘 드러나도록 녹음합니다.",
    "안녕하세요. 이 목소리는 음성 콘텐츠 제작을 위한 샘플입니다. 또렷하고 자연스럽게 말하며, 발음과 억양이 잘 드러나도록 녹음하고 있습니다.",
}

VOXCPM_AUTO_CHUNK_CHARS = 220
VOXCPM_AUTO_CHUNK_CHARS_KO = 900
VOXCPM_AUTO_CHUNK_CHARS_CJK_TRANSLATION = 120
VOXCPM_AUTO_CHUNK_ESTIMATED_SECONDS = 90.0
VOXCPM_LONG_SCRIPT_CHUNK_CHARS = 180
VOXCPM_LONG_SCRIPT_CHUNK_CHARS_KO = 450
VOXCPM_LONG_SCRIPT_CHUNK_CHARS_CJK_TRANSLATION = 100
AUTO_CHUNK_PAUSE_MS = 220
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？…])\s+|\n+")
_SOFT_SPLIT_RE = re.compile(r"(?<=[,，、;；:：])\s*")
_HANGUL_RE = re.compile(r"[가-힣]")


def cleaned_reference_transcript(transcript: str | None) -> str | None:
    if not transcript:
        return None
    cleaned = re.sub(r"\s+", " ", transcript).strip()
    if not cleaned or cleaned in DEFAULT_REFERENCE_PROMPTS:
        return None
    if len(cleaned) > 500:
        return None
    return cleaned


def voice_with_reference_transcript(voice: VoiceProfile | None) -> VoiceProfile | None:
    if voice is None:
        return None
    return voice.model_copy(update={"transcript": cleaned_reference_transcript(voice.transcript)})


def estimate_tts_duration(text: str, speed: float = 1.0) -> float:
    compact = re.sub(r"\s+", "", text.strip())
    if not compact:
        return 1.0
    pause_marks = len(re.findall(r"[.!?。！？…\n]", text))
    safe_speed = max(0.5, min(2.0, speed or 1.0))
    seconds = (len(compact) / 6.0 + pause_marks * 0.25) / safe_speed
    return round(max(1.0, min(300.0, seconds)), 2)


def requested_or_estimated_duration(duration: float | None, text: str, speed: float) -> float:
    return duration if duration is not None else estimate_tts_duration(text, speed)


def tts_control_instruct_for_model(
    model_id: str | None,
    *,
    tone_prompt: str | None,
    instruct: str | None = None,
    style_prompt: str | None = None,
    language: str | None,
    accent: str | None,
    speed: float = 1.0,
) -> str | None:
    if model_id == "voxcpm":
        return build_voxcpm_control_prompt(
            style_prompt=style_prompt,
            tone_prompt=tone_prompt,
            instruct=instruct,
            language=language,
            accent=accent,
            speed=speed,
        )
    return combine_omnivoice_instruct(tone_prompt or instruct, language, accent)


def parse_narration_script(text: str) -> list[dict] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None

    segments: list[dict] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Narration segment {index} must be an object.")
        segment_text = str(item.get("text", "")).strip()
        if not segment_text:
            raise ValueError(f"Narration segment {index} requires text.")
        speed = item.get("speed")
        pause_after_ms = item.get("pause_after_ms", item.get("pause_ms", 0))
        segments.append(
            {
                "text": segment_text,
                "tone": str(item.get("tone", "")).strip(),
                "pitch": str(item.get("pitch", "")).strip(),
                "speed": max(0.5, min(2.0, float(speed))) if isinstance(speed, int | float) else None,
                "pause_after_ms": max(0, min(5000, int(pause_after_ms))) if isinstance(pause_after_ms, int | float) else 0,
            }
        )
    return segments or None


def split_plain_tts_text(
    text: str,
    *,
    model_id: str | None = None,
    language: str | None = None,
    max_chars: int | None = None,
    speed: float = 1.0,
    pause_after_ms: int = AUTO_CHUNK_PAUSE_MS,
) -> list[dict] | None:
    """Split long plain TTS text into model-sized utterances.

    VoxCPM2 can become very slow or unstable when a long translated script is
    sent as a single utterance. Korean voice-clone scripts are allowed to stay
    much longer before splitting because each chunk is an independent model
    call and may slightly drift in tone/quality. JSON narration scripts are
    already segmented by `parse_narration_script`; this helper is only for
    plain text from the TTS and content-generation screens.
    """

    if model_id and model_id != "voxcpm":
        return None

    cleaned = text.strip()
    if not cleaned:
        return None

    target_max_chars = max(60, int(max_chars or _voxcpm_auto_chunk_chars_for_text(cleaned, language)))
    compact_length = len(re.sub(r"\s+", "", cleaned))
    estimated_seconds = estimate_tts_duration(cleaned, speed)
    long_by_duration = estimated_seconds > VOXCPM_AUTO_CHUNK_ESTIMATED_SECONDS
    if compact_length <= target_max_chars and not long_by_duration:
        return None
    if long_by_duration and max_chars is None:
        target_max_chars = min(target_max_chars, _voxcpm_long_script_chunk_chars_for_text(cleaned, language))

    chunks = [(chunk, pause_after_ms) for chunk in _merge_text_pieces(_split_text_pieces(cleaned, target_max_chars), target_max_chars)]
    if len(chunks) <= 1:
        return None

    return _segments_from_chunks(chunks, target_max_chars, pause_after_ms)


def _voxcpm_auto_chunk_chars_for_text(text: str, language: str | None) -> int:
    normalized = (language or "").strip().lower()
    if normalized in {"ko", "kr", "kor", "korean", "한국어"} or _HANGUL_RE.search(text):
        return VOXCPM_AUTO_CHUNK_CHARS_KO
    if normalized in {"ja", "jp", "jpn", "japanese", "日本語", "zh", "zh-cn", "zh-tw", "chinese", "中文"}:
        return VOXCPM_AUTO_CHUNK_CHARS_CJK_TRANSLATION
    return VOXCPM_AUTO_CHUNK_CHARS


def _voxcpm_long_script_chunk_chars_for_text(text: str, language: str | None) -> int:
    normalized = (language or "").strip().lower()
    if normalized in {"ko", "kr", "kor", "korean", "한국어"} or _HANGUL_RE.search(text):
        return VOXCPM_LONG_SCRIPT_CHUNK_CHARS_KO
    if normalized in {"ja", "jp", "jpn", "japanese", "日本語", "zh", "zh-cn", "zh-tw", "chinese", "中文"}:
        return VOXCPM_LONG_SCRIPT_CHUNK_CHARS_CJK_TRANSLATION
    return VOXCPM_LONG_SCRIPT_CHUNK_CHARS


def _split_text_pieces(text: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    for candidate in _SENTENCE_SPLIT_RE.split(text):
        cleaned = candidate.strip()
        if not cleaned:
            continue
        if len(cleaned) <= max_chars:
            pieces.append(cleaned)
            continue
        pieces.extend(_split_overlong_piece(cleaned, max_chars))
    return pieces


def _segments_from_chunks(chunks: list[tuple[str, int]], max_chars: int, fallback_pause_after_ms: int) -> list[dict]:
    safe_fallback_pause_after_ms = max(0, min(5000, int(fallback_pause_after_ms)))
    segments: list[dict] = []
    for chunk, explicit_pause_after_ms in chunks:
        pieces = _merge_text_pieces(_split_text_pieces(chunk, max_chars), max_chars)
        for index, piece in enumerate(pieces):
            pause_after_ms = explicit_pause_after_ms if index == len(pieces) - 1 else safe_fallback_pause_after_ms
            segments.append(
                {
                    "text": piece,
                    "tone": "",
                    "pitch": "",
                    "speed": None,
                    "pause_after_ms": max(0, min(5000, int(pause_after_ms))),
                }
            )
    if segments:
        segments[-1]["pause_after_ms"] = 0
    return segments


def _split_overlong_piece(text: str, max_chars: int) -> list[str]:
    soft_parts = [part.strip() for part in _SOFT_SPLIT_RE.split(text) if part.strip()]
    if len(soft_parts) > 1:
        merged = _merge_text_pieces(soft_parts, max_chars)
        if all(len(part) <= max_chars for part in merged):
            return merged

    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at < max(30, int(max_chars * 0.45)):
            split_at = max_chars
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _merge_text_pieces(pieces: list[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip() if current else piece
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def narration_instruct(segment: dict, fallback: str | None, language: str | None, accent: str | None) -> str | None:
    prompts = [segment.get("tone") or "", segment.get("pitch") or "", fallback or ""]
    normalized: list[str] = []
    for prompt in prompts:
        value = str(prompt).strip()
        if value.lower() == "low":
            value = "low pitch"
        elif value.lower() == "high":
            value = "high pitch"
        safe = normalize_omnivoice_instruct(value)
        if safe and safe not in normalized:
            normalized.append(safe)
    return combine_omnivoice_instruct(", ".join(normalized) or None, language, accent)


def combine_generated_segments(parts: list[tuple[Path, int]], output_dir: Path, sample_rate: int | None = None) -> tuple[Path, float]:
    loaded_parts: list[tuple[np.ndarray, int, int]] = []
    target_rate = sample_rate or 0
    for path, pause_after_ms in parts:
        waveform, loaded_rate = sf.read(path, dtype="float32", always_2d=False)
        if waveform.ndim > 1:
            waveform = np.mean(waveform, axis=1)
        loaded_parts.append((np.asarray(waveform, dtype=np.float32), int(loaded_rate), pause_after_ms))
        target_rate = max(target_rate, int(loaded_rate))

    target_rate = target_rate or 24000
    waveforms: list[np.ndarray] = []
    for waveform, loaded_rate, pause_after_ms in loaded_parts:
        if loaded_rate != target_rate:
            try:
                import librosa

                waveform = librosa.resample(waveform, orig_sr=loaded_rate, target_sr=target_rate)
            except Exception as exc:
                raise RuntimeError(f"Could not resample generated segment: {exc}") from exc
        waveforms.append(np.asarray(waveform, dtype=np.float32))
        if pause_after_ms > 0:
            waveforms.append(np.zeros(int(target_rate * pause_after_ms / 1000), dtype=np.float32))

    combined = np.concatenate(waveforms) if waveforms else np.array([], dtype=np.float32)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{uuid4().hex}.wav"
    sf.write(output, combined, target_rate, subtype="PCM_16")
    return output, float(len(combined) / target_rate)


def ensure_generated_audio(output_path: Path, duration: float | None) -> None:
    if duration is not None and duration > 0 and output_path.stat().st_size > 44:
        return
    raise RuntimeError("Generated empty audio. Please save the sample voice again with the displayed sample sentence, then try again.")


async def run_generation_with_progress(
    *,
    progress_id: str | None,
    engine: MockVoiceEngine | OmniVoiceEngine,
    text: str,
    voice: VoiceProfile | None,
    tone_prompt: str | None,
    language_code: str | None,
    accent: str | None,
    speed: float,
    duration: float | None,
    num_step: int,
    guidance_scale: float,
    denoise: bool,
    position_temperature: float,
    class_temperature: float,
    preprocess_prompt: bool,
    postprocess_output: bool,
    audio_chunk_duration: float,
    audio_chunk_threshold: float,
    start_percent: int,
    end_percent: int,
    label: str,
) -> tuple[Path, float | None]:
    task = asyncio.create_task(
        asyncio.to_thread(
            engine.generate,
            text=text,
            voice=voice_with_reference_transcript(voice),
            instruct=combine_omnivoice_instruct(tone_prompt, language_code, accent),
            language=language_code_to_omnivoice_language(language_code) or language_code,
            speed=speed,
            duration=duration,
            num_step=num_step,
            guidance_scale=guidance_scale,
            denoise=denoise,
            position_temperature=position_temperature,
            class_temperature=class_temperature,
            preprocess_prompt=preprocess_prompt,
            postprocess_output=postprocess_output,
            audio_chunk_duration=audio_chunk_duration,
            audio_chunk_threshold=audio_chunk_threshold,
        )
    )
    heartbeat = 0
    percent = start_percent
    while not task.done():
        message = f"{label} 모델 합성 중입니다. 경과 {heartbeat}s"
        publish_progress(progress_id, percent, message)
        await asyncio.sleep(1)
        heartbeat += 1
        percent = min(end_percent - 1, start_percent + 8 + heartbeat * 4)
    return await task


def public_audio_url(path: Path, settings: Settings, default_bucket: str = "voices") -> str:
    try:
        if path.is_relative_to(settings.uploads_dir):
            return public_file_url(path, "uploads")
        if path.is_relative_to(settings.voices_dir):
            return public_file_url(path, "voices")
        if path.is_relative_to(settings.outputs_dir):
            return public_file_url(path, "outputs")
    except ValueError:
        pass
    return public_file_url(path, default_bucket)


def build_generation_preview(request: GenerationPreviewRequest, voice: VoiceProfile | None) -> GenerationPreviewResponse:
    language = request.language.strip().lower() or "ko"
    language_hint = language_code_to_omnivoice_language(language)
    effective_instruct = combine_omnivoice_instruct(request.tone_prompt, language, request.accent)
    accent_hint = effective_accent_for_language(language, request.accent)
    explicit_accent = normalize_accent_override(request.accent, language)
    safe_tone = normalize_omnivoice_instruct(request.tone_prompt)
    if voice:
        mode = "clone"
    elif safe_tone:
        mode = "design"
    else:
        mode = "auto"
    notes: list[str] = []
    if voice:
        notes.append(f"복제 모드: '{voice.name}' 목소리의 음색을 reference로 사용합니다.")
    elif mode == "design":
        notes.append("Voice Design: 등록 목소리 없이 instruct 속성으로 목소리를 설계합니다.")
    else:
        notes.append("Auto Voice: reference와 instruct 없이 모델 기본 목소리로 생성합니다.")
    if language_hint:
        notes.append(f"선택 대본 언어는 {language_hint}로 OmniVoice language hint에 전달됩니다.")
    if language == "en" and explicit_accent:
        notes.append(f"영어는 선택한 {explicit_accent} 억양 힌트를 적용합니다.")
    elif accent_hint:
        notes.append(f"{language_hint or language} 대본에는 {accent_hint} 힌트를 자동 적용합니다.")
    elif request.accent:
        notes.append("선택한 억양은 이 언어에서 OmniVoice 지원 항목이 아니므로 적용하지 않습니다.")
    if request.tone_prompt and not safe_tone:
        notes.append("입력한 톤 문구는 OmniVoice 지원 instruct가 아니어서 안전하게 제외됩니다.")
    return GenerationPreviewResponse(
        mode=mode,
        voice_id=voice.id if voice else None,
        voice_name=voice.name if voice else None,
        language=language,
        language_hint=language_hint,
        accent_hint=accent_hint,
        tone_prompt=request.tone_prompt,
        effective_instruct=effective_instruct,
        speed=request.speed,
        duration=request.duration,
        notes=notes,
    )


def transcribe_with_segments(
    audio_path: Path,
    offset_seconds: float = 0,
    *,
    provider: STTProvider = "whisper",
    language: str | None = None,
    settings: Settings | None = None,
) -> TranscriptSegmentsResponse:
    text_result = transcribe_audio(
        audio_path,
        provider=provider,
        offset_seconds=offset_seconds,
        language=language,
        settings=settings or get_settings(),
    )
    if not text_result.segments and not text_result.text:
        raise RuntimeError("음성에서 텍스트를 찾지 못했습니다.")
    return text_result
