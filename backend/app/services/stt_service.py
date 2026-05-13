import json
import platform
import shutil
import subprocess
from uuid import uuid4
from pathlib import Path
from typing import Literal

from app.config import Settings
from app.schemas import TranscriptSegment, TranscriptSegmentsResponse

STTProvider = Literal["whisper", "apple-speech"]


def apple_speech_helper_binary(settings: Settings) -> Path:
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    source_path = scripts_dir / "apple_speech_transcribe.swift"
    plist_path = scripts_dir / "apple_speech_info.plist"
    app_dir = settings.storage_dir / "bin" / "Clone Voice Apple Speech.app"
    contents_dir = app_dir / "Contents"
    macos_dir = contents_dir / "MacOS"
    binary_path = macos_dir / "apple_speech_transcribe"
    bundled_plist_path = contents_dir / "Info.plist"
    if not source_path.exists():
        raise RuntimeError("Apple Speech helper script was not found.")
    if not plist_path.exists():
        raise RuntimeError("Apple Speech Info.plist was not found.")
    needs_build = (
        not binary_path.exists()
        or not bundled_plist_path.exists()
        or binary_path.stat().st_mtime < source_path.stat().st_mtime
        or bundled_plist_path.stat().st_mtime < plist_path.stat().st_mtime
    )
    if not needs_build:
        return binary_path
    macos_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plist_path, bundled_plist_path)
    completed = subprocess.run(
        [
            "swiftc",
            str(source_path),
            "-o",
            str(binary_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Apple Speech helper build failed.")
    signed = subprocess.run(
        ["codesign", "--force", "--sign", "-", str(app_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if signed.returncode != 0:
        raise RuntimeError(signed.stderr.strip() or "Apple Speech helper signing failed.")
    return binary_path


def transcribe_with_whisper(audio_path: Path, offset_seconds: float = 0, model_name: str = "base") -> TranscriptSegmentsResponse:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("시간대별 텍스트 추출은 openai-whisper 설치가 필요합니다. backend에서 uv sync --extra omnivoice --extra dev 또는 whisper 의존성을 설치해 주세요.") from exc
    model = whisper.load_model(model_name)
    result = model.transcribe(str(audio_path))
    segments = [
        TranscriptSegment(
            start=float(segment.get("start", 0)) + offset_seconds,
            end=float(segment.get("end", 0)) + offset_seconds,
            text=str(segment.get("text", "")).strip(),
        )
        for segment in result.get("segments", [])
        if str(segment.get("text", "")).strip()
    ]
    text = str(result.get("text", "")).strip()
    return TranscriptSegmentsResponse(segments=segments, text=text)


def transcribe_with_apple_speech(
    audio_path: Path,
    *,
    offset_seconds: float = 0,
    language: str | None = None,
    settings: Settings,
) -> TranscriptSegmentsResponse:
    if platform.system() != "Darwin":
        raise RuntimeError("Apple Speech provider는 macOS에서만 사용할 수 있습니다.")
    helper_path = apple_speech_helper_binary(settings)
    app_dir = helper_path.parents[2]
    output_path = settings.uploads_dir / f"{uuid4().hex}-apple-speech.json"
    try:
        completed = subprocess.run(
            [
                "open",
                "-W",
                "-n",
                str(app_dir),
                "--args",
                str(audio_path.resolve()),
                language or "",
                "true" if settings.apple_speech_require_on_device else "false",
                str(output_path.resolve()),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.apple_speech_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Apple Speech transcription timed out.") from exc

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        raise RuntimeError(stderr or stdout or "Apple Speech helper could not be launched.")
    if not output_path.exists():
        raise RuntimeError("Apple Speech helper가 결과를 반환하지 못했습니다. 시스템 설정 > 개인정보 보호 및 보안 > 음성 인식에서 Clone Voice Apple Speech 권한을 허용한 뒤 다시 실행해 주세요.")
    stdout = output_path.read_text()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Apple Speech returned an invalid response. {stderr or stdout}") from exc

    if payload.get("error"):
        raise RuntimeError(payload["error"])

    segments = [
        TranscriptSegment(
            start=float(item.get("start", 0)) + offset_seconds,
            end=float(item.get("end", 0)) + offset_seconds,
            text=str(item.get("text", "")).strip(),
        )
        for item in payload.get("segments", [])
        if str(item.get("text", "")).strip()
    ]
    return TranscriptSegmentsResponse(text=str(payload.get("text", "")).strip(), segments=segments)


def transcribe_audio(
    audio_path: Path,
    *,
    provider: STTProvider = "whisper",
    offset_seconds: float = 0,
    language: str | None = None,
    settings: Settings,
) -> TranscriptSegmentsResponse:
    if provider == "apple-speech":
        return transcribe_with_apple_speech(audio_path, offset_seconds=offset_seconds, language=language, settings=settings)
    if provider != "whisper":
        raise RuntimeError(f"지원하지 않는 STT provider입니다: {provider}")
    return transcribe_with_whisper(audio_path, offset_seconds=offset_seconds, model_name=settings.whisper_model)
