from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_voice_store
from app.config import Settings, get_settings
from app.schemas import (
    SpeechToSpeechResponse,
    public_file_url,
)
from app.services.audio_effects import apply_output_effects
from app.services.generation_helpers import (
    ensure_generated_audio,
    voice_with_reference_transcript,
)
from app.services.omnivoice_service import (
    MockVoiceEngine,
    OmniVoiceEngine,
    combine_omnivoice_instruct,
    get_voice_engine,
    language_code_to_omnivoice_language,
)
from app.services.voice_store import VoiceStore

router = APIRouter()

@router.post("/api/speech-to-speech", response_model=SpeechToSpeechResponse)
async def speech_to_speech(
    voice_id: str | None = Form(default=None),
    language: str | None = Form(default=None),
    speed: float = Form(default=1.0),
    num_step: int = Form(default=32),
    pitch_shift: float = Form(default=0.0),
    volume_gain_db: float = Form(default=0.0),
    normalize_output: bool = Form(default=True),
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: VoiceStore = Depends(get_voice_store),
    engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine),
):
    extension = Path(audio.filename or "speech.webm").suffix or ".webm"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    input_path = settings.uploads_dir / f"{uuid4().hex}{extension}"
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=422, detail="Recorded audio is required")
    input_path.write_bytes(content)

    voice = store.get(voice_id) if voice_id else None
    if voice_id and voice is None:
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    try:
        transcript = engine.transcribe(input_path, language=language)
        output_path, duration = engine.generate(
            text=transcript,
            voice=voice_with_reference_transcript(voice),
            instruct=combine_omnivoice_instruct(None, language),
            language=language_code_to_omnivoice_language(language) or language,
            speed=speed,
            num_step=num_step,
        )
        if pitch_shift or volume_gain_db or normalize_output:
            output_path, duration = apply_output_effects(
                output_path,
                settings.outputs_dir,
                pitch_shift=pitch_shift,
                volume_gain_db=volume_gain_db,
                normalize_output=normalize_output,
            )
        ensure_generated_audio(output_path, duration)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Speech conversion failed: {exc}") from exc
    return SpeechToSpeechResponse(
        text=transcript,
        transcript=transcript,
        voice_id=voice_id or None,
        audio_url=public_file_url(output_path, "outputs"),
        duration_seconds=duration,
    )
