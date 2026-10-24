"""Project metadata APIs for the sound-effect asset workspace."""

from typing import Annotated, Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.sound_project_store import SoundProject, SoundProjectError, SoundProjectStore


router = APIRouter(prefix="/api/sound-projects", tags=["sound-projects"])
T = TypeVar("T")
ProjectPath = Annotated[str, Path(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


class SoundProjectList(BaseModel):
    projects: list[SoundProject]


def _store(settings: Annotated[Settings, Depends(get_settings)]) -> SoundProjectStore:
    return SoundProjectStore(settings)


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except SoundProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=SoundProjectList)
def list_sound_projects(store: Annotated[SoundProjectStore, Depends(_store)]) -> SoundProjectList:
    return SoundProjectList(projects=_run(store.list))


@router.get("/{project_id}", response_model=SoundProject)
def get_sound_project(project_id: ProjectPath, store: Annotated[SoundProjectStore, Depends(_store)]) -> SoundProject:
    return _run(lambda: store.get(project_id))


@router.put("/{project_id}", response_model=SoundProject)
def put_sound_project(
    project_id: ProjectPath,
    project: SoundProject,
    store: Annotated[SoundProjectStore, Depends(_store)],
) -> SoundProject:
    return _run(lambda: store.save(project_id, project))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_sound_project(
    project_id: ProjectPath,
    store: Annotated[SoundProjectStore, Depends(_store)],
    revision: Annotated[int, Query(ge=1)],
) -> Response:
    _run(lambda: store.delete(project_id, revision))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/export")
def export_sound_project(project_id: ProjectPath, store: Annotated[SoundProjectStore, Depends(_store)]) -> JSONResponse:
    project = _run(lambda: store.get(project_id))
    return JSONResponse(
        content=project.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="clone-voice-sounds-{project.id}.json"'},
    )
