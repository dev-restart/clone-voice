from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db.models import DbStudioSetting
from app.db.session import session_scope
from app.schemas import StoryProjectItem, StoryStudioGenerateResponse


class StoryProjectConflictError(RuntimeError):
    pass


class StoryProjectStore:
    """Persist projects in the existing JSON table without changing users' databases."""

    PREFIX = "story-project:"

    def __init__(self, settings: Settings):
        self.settings = settings

    def list(self) -> list[StoryProjectItem]:
        with session_scope(self.settings) as session:
            rows = session.scalars(
                select(DbStudioSetting)
                .where(DbStudioSetting.key.startswith(self.PREFIX))
                .order_by(DbStudioSetting.updated_at.desc())
            ).all()
            return [StoryProjectItem.model_validate(row.value) for row in rows]

    def get(self, project_id: str) -> StoryProjectItem | None:
        with session_scope(self.settings) as session:
            row = session.get(DbStudioSetting, self.PREFIX + project_id)
            return StoryProjectItem.model_validate(row.value) if row else None

    def save(self, project: StoryProjectItem) -> StoryProjectItem:
        now = datetime.now(timezone.utc)
        saved = project.model_copy(update={"revision": project.revision + 1, "updated_at": now})
        key = self.PREFIX + project.id
        conflict = "프로젝트가 다른 화면에서 변경되었습니다. 백업을 내려받은 뒤 새로고침해 최신 내용을 확인하세요."
        try:
            with session_scope(self.settings) as session:
                if project.revision == 0:
                    session.add(DbStudioSetting(key=key, value=saved.model_dump(mode="json"), updated_at=now))
                    session.flush()
                else:
                    changed = session.execute(
                        update(DbStudioSetting)
                        .where(DbStudioSetting.key == key, DbStudioSetting.value["revision"].as_integer() == project.revision)
                        .values(value=saved.model_dump(mode="json"), updated_at=now)
                    )
                    if changed.rowcount != 1:
                        raise StoryProjectConflictError(conflict)
        except IntegrityError as exc:
            raise StoryProjectConflictError(conflict) from exc
        return saved

    def save_result(self, project_id: str, result: StoryStudioGenerateResponse) -> StoryProjectItem:
        # Preserve edits made while inference was running. The result carries its own script snapshot.
        for _ in range(3):
            project = self.get(project_id)
            if project is None:
                raise StoryProjectConflictError("프로젝트가 삭제되어 결과를 연결할 수 없습니다. 생성 파일은 파일 보관함에 남아 있습니다.")
            try:
                return self.save(project.model_copy(update={"result": result}))
            except StoryProjectConflictError:
                continue
        raise StoryProjectConflictError("결과 저장 중 프로젝트가 변경되었습니다. 생성 파일은 파일 보관함에 남아 있습니다.")

    def delete(self, project_id: str, revision: int) -> bool:
        with session_scope(self.settings) as session:
            row = session.get(DbStudioSetting, self.PREFIX + project_id)
            if row is None:
                return False
            changed = session.execute(
                delete(DbStudioSetting).where(
                    DbStudioSetting.key == self.PREFIX + project_id,
                    DbStudioSetting.value["revision"].as_integer() == revision,
                )
            )
            if changed.rowcount != 1:
                raise StoryProjectConflictError("프로젝트가 다른 화면에서 변경되어 삭제하지 않았습니다. 새로고침 후 확인하세요.")
            return True
