"""Persistent sound-effect projects with revision-guarded edits.

Project and asset removal only remove metadata. Generated files remain in the
output library, including when generation completes after its target is removed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.config import Settings, get_settings
from app.db.models import DbStudioSetting
from app.db.session import session_scope
from app.schemas import SoundEffectResult


PREFIX = "sound-project:"
MAX_RESULTS_PER_ASSET = 100
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_OUTPUT_URL_PATTERN = re.compile(r"/api/files/outputs/[A-Za-z0-9_-][A-Za-z0-9._-]{0,254}\Z")
SafeId = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    # Earlier browser drafts used ISO dates without an explicit offset.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _validated_results(results: list[SoundEffectResult]) -> list[SoundEffectResult]:
    if len(results) > MAX_RESULTS_PER_ASSET:
        raise ValueError("한 사운드에는 생성 결과를 최대 100개까지 보관할 수 있습니다.")
    seen: set[str] = set()
    for result in results:
        if not _ID_PATTERN.fullmatch(result.id):
            raise ValueError("생성 결과 ID가 올바르지 않습니다.")
        if result.id in seen:
            raise ValueError("같은 사운드 안에서 생성 결과 ID가 중복될 수 없습니다.")
        seen.add(result.id)
        if not _OUTPUT_URL_PATTERN.fullmatch(result.audio_url):
            raise ValueError("생성 결과는 이 앱의 /api/files/outputs/ 파일만 참조할 수 있습니다.")
    return results


class SoundAsset(BaseModel):
    """An editable generation draft and independent generated-result snapshots."""

    model_config = ConfigDict(extra="forbid")

    id: SafeId
    title: str = Field(min_length=1, max_length=160)
    category: str = Field(default="other", pattern=r"^(ui|impact|movement|ambience|transition|foley|other)$")
    prompt: str = Field(default="", max_length=2000)
    negative_prompt: str = Field(default="", max_length=1000)
    duration_seconds: float = Field(default=3.0, ge=0.5, le=15.0, allow_inf_nan=False)
    auto_duration: bool = False
    variations: int = Field(default=1, ge=1, le=4, strict=True)
    guidance_scale: float = Field(default=3.0, ge=0.0, le=8.0, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=2147483643, strict=True)
    results: list[SoundEffectResult] = Field(default_factory=list, max_length=MAX_RESULTS_PER_ASSET)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @field_validator("title")
    @classmethod
    def nonempty_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("사운드 이름을 입력해 주세요.")
        return value

    @field_validator("results")
    @classmethod
    def safe_results(cls, value: list[SoundEffectResult]) -> list[SoundEffectResult]:
        return _validated_results(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_dates(cls, value: datetime) -> datetime:
        return _utc(value)


class SoundProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: SafeId
    title: str = Field(min_length=1, max_length=160)
    category: str = Field(default="general", pattern=r"^(game|video|ambient|general)$")
    assets: list[SoundAsset] = Field(default_factory=list, max_length=300)
    revision: int = Field(default=0, ge=0, strict=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @field_validator("title")
    @classmethod
    def nonempty_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("프로젝트 이름을 입력해 주세요.")
        return value

    @field_validator("assets")
    @classmethod
    def unique_asset_ids(cls, value: list[SoundAsset]) -> list[SoundAsset]:
        ids = [asset.id for asset in value]
        if len(ids) != len(set(ids)):
            raise ValueError("프로젝트 안에서 사운드 ID가 중복될 수 없습니다.")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_dates(cls, value: datetime) -> datetime:
        return _utc(value)


class SoundProjectError(RuntimeError):
    status_code = 500


class SoundProjectNotFound(SoundProjectError):
    status_code = 404


class SoundProjectConflict(SoundProjectError):
    status_code = 409


def _key(project_id: str) -> str:
    if not isinstance(project_id, str) or not _ID_PATTERN.fullmatch(project_id):
        raise ValueError("프로젝트 ID가 올바르지 않습니다.")
    return PREFIX + project_id


def _settings(settings: Settings | None) -> Settings:
    return settings if settings is not None else get_settings()


def _decode(key: str, value: object) -> SoundProject:
    try:
        project = SoundProject.model_validate(value)
        if key != _key(project.id) or project.revision < 1:
            raise ValueError("Stored project key or revision is invalid.")
        return project
    except (ValidationError, ValueError) as exc:
        raise SoundProjectError("사운드 프로젝트 저장 데이터를 읽지 못했습니다. 원본 데이터는 보존되어 있습니다.") from exc


def list_projects(*, settings: Settings | None = None) -> list[SoundProject]:
    with session_scope(_settings(settings)) as session:
        rows = session.execute(
            select(DbStudioSetting.key, DbStudioSetting.value).where(DbStudioSetting.key.startswith(PREFIX))
        ).all()
        projects = [_decode(key, value) for key, value in rows]
    return sorted(projects, key=lambda project: (project.updated_at, project.id), reverse=True)


def get_project(project_id: str, *, settings: Settings | None = None) -> SoundProject:
    key = _key(project_id)
    with session_scope(_settings(settings)) as session:
        row = session.get(DbStudioSetting, key)
        if row is None:
            raise SoundProjectNotFound("사운드 프로젝트를 찾을 수 없습니다.")
        return _decode(key, row.value)


def _replace_if_revision(project: SoundProject, expected_revision: int, *, settings: Settings) -> bool:
    # Keep reads outside this transaction to avoid a SQLite read-to-write lock
    # upgrade. The database predicate performs the actual compare-and-swap.
    with session_scope(settings) as session:
        result = session.execute(
            update(DbStudioSetting)
            .where(
                DbStudioSetting.key == _key(project.id),
                DbStudioSetting.value["revision"].as_integer() == expected_revision,
            )
            .values(value=project.model_dump(mode="json"), updated_at=project.updated_at)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1


def _saved_project(incoming: SoundProject, current: SoundProject | None) -> SoundProject:
    now = _now()
    old_assets = {asset.id: asset for asset in current.assets} if current is not None else {}
    assets: list[SoundAsset] = []
    for asset in incoming.assets:
        old = old_assets.get(asset.id)
        data = asset.model_dump(mode="python")
        if old is None:
            data.update(created_at=now, updated_at=now)
        else:
            # A draft edit may remove a result, but cannot rewrite the original
            # prompt or other metadata of a result already saved under that ID.
            snapshots = {result.id: result for result in old.results}
            data["results"] = [snapshots.get(result.id, result) for result in asset.results]
            data["created_at"] = old.created_at
            comparison = SoundAsset.model_validate(data)
            changed = comparison.model_dump(exclude={"created_at", "updated_at"}) != old.model_dump(
                exclude={"created_at", "updated_at"}
            )
            data["updated_at"] = now if changed else old.updated_at
        assets.append(SoundAsset.model_validate(data))
    return SoundProject.model_validate(
        {
            **incoming.model_dump(mode="python"),
            "assets": assets,
            "revision": (current.revision if current is not None else 0) + 1,
            "created_at": current.created_at if current is not None else now,
            "updated_at": now,
        }
    )


def save_project(
    project_id: str, project: SoundProject, *, settings: Settings | None = None
) -> SoundProject:
    settings = _settings(settings)
    key = _key(project_id)
    # Validate a copy so callers cannot bypass validation via model_copy(update=).
    project = SoundProject.model_validate(project.model_dump(mode="python"))
    if project.id != project_id:
        raise ValueError("주소의 프로젝트 ID와 저장할 프로젝트 ID가 다릅니다.")
    try:
        current = get_project(project_id, settings=settings)
    except SoundProjectNotFound:
        current = None
    if current is None:
        if project.revision != 0:
            raise SoundProjectNotFound("프로젝트가 삭제되었거나 존재하지 않습니다. 새로고침 후 다시 확인해 주세요.")
        saved = _saved_project(project, None)
        try:
            with session_scope(settings) as session:
                session.add(DbStudioSetting(key=key, value=saved.model_dump(mode="json"), updated_at=saved.updated_at))
        except IntegrityError as exc:
            raise SoundProjectConflict("같은 프로젝트가 다른 화면에서 저장되었습니다. 새로고침 후 다시 저장해 주세요.") from exc
        return saved
    if project.revision != current.revision:
        raise SoundProjectConflict("프로젝트가 다른 작업에서 변경되었습니다. 최신 내용을 불러온 후 다시 저장해 주세요.")
    saved = _saved_project(project, current)
    if not _replace_if_revision(saved, current.revision, settings=settings):
        raise SoundProjectConflict("저장 중 프로젝트가 변경되거나 삭제되었습니다. 최신 내용을 불러온 후 다시 저장해 주세요.")
    return saved


def delete_project(project_id: str, revision: int, *, settings: Settings | None = None) -> None:
    settings = _settings(settings)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("삭제할 프로젝트의 현재 revision이 필요합니다.")
    with session_scope(settings) as session:
        result = session.execute(
            delete(DbStudioSetting).where(
                DbStudioSetting.key == _key(project_id),
                DbStudioSetting.value["revision"].as_integer() == revision,
            )
        )
        deleted = result.rowcount == 1
    if deleted:
        return
    # Distinguish an already removed project from a still-present stale edit.
    get_project(project_id, settings=settings)
    raise SoundProjectConflict("프로젝트가 변경되었습니다. 최신 내용을 불러온 후 다시 삭제해 주세요.")


def save_result(
    project_id: str,
    asset_id: str,
    results: Sequence[SoundEffectResult],
    *,
    settings: Settings | None = None,
) -> SoundProject:
    """Append generation snapshots without overwriting edits made while running.

    Retry only the optimistic write, never generation. Missing destinations are
    conflicts rather than implicit creates, and duplicate result IDs are a no-op.
    """
    settings = _settings(settings)
    _key(project_id)
    if not isinstance(asset_id, str) or not _ID_PATTERN.fullmatch(asset_id):
        raise ValueError("사운드 ID가 올바르지 않습니다.")
    additions = _validated_results([SoundEffectResult.model_validate(result).model_copy(deep=True) for result in results])
    for _attempt in range(3):
        try:
            project = get_project(project_id, settings=settings)
        except SoundProjectNotFound as exc:
            raise SoundProjectConflict(
                "프로젝트가 삭제되어 생성 결과를 연결하지 못했습니다. 생성된 파일은 결과 라이브러리에 남아 있습니다."
            ) from exc
        index = next((index for index, asset in enumerate(project.assets) if asset.id == asset_id), None)
        if index is None:
            raise SoundProjectConflict(
                "사운드가 삭제되어 생성 결과를 연결하지 못했습니다. 생성된 파일은 결과 라이브러리에 남아 있습니다."
            )
        asset = project.assets[index]
        existing_ids = {result.id for result in asset.results}
        new_results = [result for result in additions if result.id not in existing_ids]
        if not new_results:
            return project
        if len(asset.results) + len(new_results) > MAX_RESULTS_PER_ASSET:
            raise SoundProjectConflict(
                "이 사운드의 생성 결과가 100개를 초과합니다. 이전 결과를 목록에서 정리한 후 다시 연결해 주세요. "
                "새로 생성된 파일은 결과 라이브러리에 남아 있습니다."
            )
        now = _now()
        updated_asset = SoundAsset.model_validate(
            {**asset.model_dump(mode="python"), "results": [*asset.results, *new_results], "updated_at": now}
        )
        assets = [*project.assets]
        assets[index] = updated_asset
        saved = SoundProject.model_validate(
            {**project.model_dump(mode="python"), "assets": assets, "revision": project.revision + 1, "updated_at": now}
        )
        if _replace_if_revision(saved, project.revision, settings=settings):
            return saved
    raise SoundProjectConflict(
        "다른 작업이 프로젝트를 계속 변경하여 생성 결과를 연결하지 못했습니다. "
        "최신 프로젝트를 다시 불러와 주세요. 생성된 파일은 결과 라이브러리에 남아 있습니다."
    )


class SoundProjectStore:
    """Settings-bound facade for routes and existing generation services."""

    def __init__(self, settings: Settings | None = None):
        self.settings = _settings(settings)

    def list(self) -> list[SoundProject]:
        return list_projects(settings=self.settings)

    def get(self, project_id: str) -> SoundProject:
        return get_project(project_id, settings=self.settings)

    def save(self, project_id: str, project: SoundProject) -> SoundProject:
        return save_project(project_id, project, settings=self.settings)

    def delete(self, project_id: str, revision: int) -> None:
        delete_project(project_id, revision, settings=self.settings)

    def save_result(self, project_id: str, asset_id: str, results: Sequence[SoundEffectResult]) -> SoundProject:
        return save_result(project_id, asset_id, results, settings=self.settings)
