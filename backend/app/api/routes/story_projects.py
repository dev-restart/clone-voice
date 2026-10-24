import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.config import Settings, get_settings
from app.schemas import StoryProjectItem, StoryStudioGenerateResponse
from app.services.story_project_store import StoryProjectConflictError, StoryProjectStore

router = APIRouter()


@router.get("/api/story-studio/projects", response_model=list[StoryProjectItem])
def list_projects(settings: Settings = Depends(get_settings)):
    return StoryProjectStore(settings).list()


@router.get("/api/story-studio/projects/{project_id}", response_model=StoryProjectItem)
def get_project(project_id: str, settings: Settings = Depends(get_settings)):
    project = StoryProjectStore(settings).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="대화 프로젝트를 찾지 못했습니다.")
    return project


@router.put("/api/story-studio/projects/{project_id}", response_model=StoryProjectItem)
def save_project(project_id: str, project: StoryProjectItem, settings: Settings = Depends(get_settings)):
    if project_id != project.id:
        raise HTTPException(status_code=422, detail="프로젝트 ID가 일치하지 않습니다.")
    try:
        return StoryProjectStore(settings).save(project)
    except StoryProjectConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/story-studio/projects/{project_id}", status_code=204)
def delete_project(project_id: str, revision: int = Query(ge=1), settings: Settings = Depends(get_settings)):
    try:
        removed = StoryProjectStore(settings).delete(project_id, revision)
    except StoryProjectConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="대화 프로젝트를 찾지 못했습니다.")
    # Keep audio files: removing an editor project must not delete reusable media.
    return Response(status_code=204)


def result_script(result: StoryStudioGenerateResponse) -> str:
    return "\n".join(
        f"[효과음: {segment.text}]" if segment.segment_type == "sfx"
        else f"{segment.speaker_name or segment.voice_name or '화자'}: {segment.text}"
        for segment in result.segments
    )


def _srt_timestamp(milliseconds: int) -> str:
    seconds, ms = divmod(milliseconds, 1000)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02}:{minute:02}:{sec:02},{ms:03}"


def result_subtitles(result: StoryStudioGenerateResponse) -> str:
    captions = []
    cursor = 0
    for segment in result.segments:
        if segment.duration_seconds is None or segment.duration_seconds <= 0:
            raise HTTPException(status_code=409, detail="단락 길이 정보가 없어 자막을 만들 수 없습니다. 다시 생성하세요.")
        end = cursor + round(segment.duration_seconds * 1000)
        if segment.segment_type != "sfx":
            speaker = segment.speaker_name or segment.voice_name or "화자"
            captions.append(f"{len(captions) + 1}\n{_srt_timestamp(cursor)} --> {_srt_timestamp(end)}\n{speaker}: {segment.text}\n")
        cursor = end + segment.pause_after_ms
    return "\n".join(captions)


def _output_path(url: str, settings: Settings) -> Path:
    prefix = "/api/files/outputs/"
    filename = url.removeprefix(prefix)
    if not url.startswith(prefix) or not filename or filename != Path(filename).name:
        raise HTTPException(status_code=404, detail="내보낼 로컬 오디오 파일을 찾지 못했습니다.")
    source = (settings.outputs_dir / filename).resolve()
    if source.parent != settings.outputs_dir.resolve() or not source.is_file():
        raise HTTPException(status_code=404, detail="오디오 파일이 없습니다. 프로젝트를 다시 생성하세요.")
    return source


@router.get("/api/story-studio/projects/{project_id}/export")
def export_project(
    project_id: str,
    format: Literal["json", "txt", "srt", "wav", "mp3", "zip"] = "json",
    settings: Settings = Depends(get_settings),
):
    project = get_project(project_id, settings)
    name = re.sub(r"[^\w가-힣 .-]", "_", project.title).strip(" .")[:70] or "dialogue"
    if format == "json":
        content = json.dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2)
    else:
        if project.result is None:
            raise HTTPException(status_code=409, detail="오디오를 먼저 생성하세요. 편집 중인 프로젝트는 JSON으로 백업할 수 있습니다.")
        content = result_script(project.result) if format == "txt" else result_subtitles(project.result) if format == "srt" else None
    if content is not None:
        return Response(
            content=content,
            media_type="application/json" if format == "json" else "text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '.' + format)}"},
        )
    result = project.result
    source = _output_path(result.audio_url, settings)
    if format == "wav" and source.suffix.lower() == ".wav":
        return FileResponse(source, media_type="audio/wav", filename=f"{name}.wav")
    temporary = TemporaryDirectory(prefix="clone-voice-dialogue-export-")
    destination = Path(temporary.name) / f"{name}.{format}"
    try:
        if format in {"mp3", "wav"}:
            codec = ["-codec:a", "libmp3lame", "-b:a", "192k"] if format == "mp3" else ["-codec:a", "pcm_s16le"]
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-vn", *codec, str(destination)],
                check=True, capture_output=True, timeout=120,
            )
        else:
            with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
                archive.write(source, f"audio{source.suffix}")
                archive.writestr("script.txt", result_script(result))
                archive.writestr("captions.srt", result_subtitles(result))
                archive.writestr("project.json", project.model_dump_json(indent=2))
                archive.writestr("source.txt", project.source_text or "")
                archive.writestr("README.txt", "이 패키지의 대본과 자막은 생성 당시 오디오 기준입니다. project.json에는 현재 편집본과 생성 당시 source_segments가 함께 들어 있습니다. 자막 시간은 단락 단위이며 word alignment가 아닙니다. AI 생성 음성입니다. 공개 전에 사실과 음성 사용 권한을 확인하세요.")
    except HTTPException:
        temporary.cleanup()
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        temporary.cleanup()
        raise HTTPException(status_code=503, detail="내보내기에 실패했습니다. ffmpeg 설치와 저장 공간을 확인하세요.") from exc
    return FileResponse(
        destination,
        media_type={"mp3": "audio/mpeg", "wav": "audio/wav", "zip": "application/zip"}[format],
        filename=destination.name,
        background=BackgroundTask(temporary.cleanup),
    )
