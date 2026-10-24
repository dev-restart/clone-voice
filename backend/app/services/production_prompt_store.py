from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import Settings

PromptKind = Literal["sound_effect", "music", "song", "cover"]
PROMPT_KINDS = ("sound_effect", "music", "song", "cover")

# Editable craft direction. Callers append their fixed output/capability contract.
BUILTIN_PROMPTS = {
    "sound_effect": (
        "You are a sound designer preparing precise prompts for an audio generation model. "
        "Preserve the requested event count, materials, action, environment, distance and microphone perspective. "
        "Describe the attack, body, decay and relevant ambience with concrete acoustic language. "
        "Use one coherent sound scene rather than unrelated sound lists. Respect explicit duration and avoid "
        "unnecessary silence, clipping, muddiness and excessive reverb. "
        "Do not add dialogue, vocals or music unless explicitly requested. "
        "Do not promise that wording alone guarantees audio quality."
    ),
    "music": (
        "You are a music production assistant drafting an instrumental production brief. "
        "Keep the requested genre, emotional arc, intended use and duration. Specify a compatible tempo or range, "
        "groove, leading instruments, supporting texture, harmonic mood and beginning-development-ending arrangement. "
        "Prefer a cohesive instrument palette and controlled dynamics with space for voiceover when requested. "
        "Describe transitions and an intentional ending or seamless loop. Avoid contradictory style tags and excessive mastering adjectives. "
        "Do not add singing or lyrics to an instrumental request. "
        "You draft text for a musician or suitable audio model; never claim that you have generated audio."
    ),
    "song": (
        "You are a songwriter and vocal production assistant. Create original lyrics and a clear song outline from the brief. "
        "Keep one narrative perspective, a memorable singable hook, natural stresses and phrases that fit a singer's breath. "
        "Use verses to develop the idea and a chorus to repeat its emotional focus without padding. "
        "Respect the requested language and provided lyrics; default to Korean lyrics when unspecified. "
        "Use natural pronunciation and consistent rhythmic phrasing within each part. "
        "Describe genre, tempo, arrangement, vocal delivery and transitions in a separate production prompt. "
        "Keep production instructions out of lyrics. Do not claim lyrics alone generate singing or guarantee vocal quality."
    ),
    "cover": (
        "You are a conservative singing-cover setup assistant for SoulX-Singer. "
        "You receive text and current settings only, not audio or measured voice ranges. "
        "Never claim to have listened, detected a key, measured pitch, separated vocals or assessed recording quality. "
        "Preserve source melody and lyrics. Recommend only supported settings and explain tradeoffs. "
        "quality maps to inference steps: fast=2, balanced=4, quality=8. More steps take longer and do not guarantee improvement. "
        "cfg_scale is 0.5 to 4.0; excessive values may distort timbre. "
        "Keep current pitch_shift and auto_shift unless explicitly asked to change pitch; do not invent a semitone shift. "
        "Keep separation and accompaniment mixing consistent with the described source and requested full mix or vocals only. "
        "If source characteristics are unknown, preserve current settings. "
        "Offer settings for review; never claim the cover has already been generated."
    ),
}
PROMPT_LABELS = {
    "sound_effect": ("효과음", "장면·재질·거리·길이를 보존하는 생성 프롬프트"),
    "music": ("음악", "장르·악기·템포·구성을 정리하는 제작 프롬프트"),
    "song": ("노래", "가사·곡 구성·보컬 표현을 정리하는 제작 초안"),
    "cover": ("커버", "원곡 설명과 현재 옵션을 바탕으로 한 설정 추천"),
}


def clean_prompt(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 8000:
        raise ValueError("프롬프트는 1~8000자로 입력하세요.")
    if any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in value):
        raise ValueError("프롬프트에 제어 문자를 사용할 수 없습니다.")
    return value


class PromptUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0)
    updates: dict[PromptKind, str | None] = Field(min_length=1, max_length=4)

    @field_validator("updates")
    @classmethod
    def validate_updates(cls, values: dict) -> dict:
        return {key: clean_prompt(value) if value is not None else None for key, value in values.items()}


class _PromptState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(default=1, ge=1, le=1)
    revision: int = Field(default=0, ge=0)
    overrides: dict[PromptKind, str] = Field(default_factory=dict, max_length=4)

    @field_validator("overrides")
    @classmethod
    def validate_overrides(cls, values: dict) -> dict:
        return {key: clean_prompt(value) for key, value in values.items()}


class PromptConflict(RuntimeError):
    pass


class ProductionPromptStore:
    """Local revisioned overrides; reading defaults never creates a file."""
    _lock = threading.RLock()

    def __init__(self, settings: Settings):
        self.path = settings.resolved_ai_text_settings_path.with_name("production_prompts.json")

    def _read(self) -> _PromptState:
        if not self.path.exists() and not self.path.is_symlink():
            return _PromptState()
        try:
            if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > 160_000:
                raise ValueError("invalid prompt file")
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"version", "revision", "overrides"}:
                raise ValueError("invalid prompt metadata")
            return _PromptState.model_validate(payload)
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("제작 프롬프트 설정을 읽지 못했습니다. 기존 파일은 변경하지 않았습니다.") from exc

    @staticmethod
    def _public(state: _PromptState) -> dict:
        return {
            "revision": state.revision,
            "templates": [
                {"id": kind, "label": PROMPT_LABELS[kind][0], "description": PROMPT_LABELS[kind][1],
                 "default_prompt": BUILTIN_PROMPTS[kind],
                 "prompt": state.overrides.get(kind, BUILTIN_PROMPTS[kind]),
                 "customized": kind in state.overrides}
                for kind in PROMPT_KINDS
            ],
        }

    def public(self) -> dict:
        with self._lock:
            return self._public(self._read())

    def snapshot(self, kind: PromptKind) -> tuple[str, int]:
        if kind not in PROMPT_KINDS:
            raise ValueError("지원하지 않는 제작 프롬프트입니다.")
        with self._lock:
            state = self._read()
            return state.overrides.get(kind, BUILTIN_PROMPTS[kind]), state.revision

    def _write(self, state: _PromptState) -> None:
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state.model_dump(), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except OSError as exc:
            raise RuntimeError("제작 프롬프트를 저장하지 못했습니다. 입력을 유지한 채 다시 시도하세요.") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def update(self, request: PromptUpdateRequest) -> dict:
        with self._lock:
            current = self._read()
            if current.revision != request.expected_revision:
                raise PromptConflict("다른 화면에서 프롬프트가 변경되었습니다. 입력을 보존하고 최신 내용을 확인하세요.")
            overrides = deepcopy(current.overrides)
            for kind, value in request.updates.items():
                if value is None or value == BUILTIN_PROMPTS[kind]:
                    overrides.pop(kind, None)
                else:
                    overrides[kind] = value
            if overrides == current.overrides:
                return self._public(current)
            updated = _PromptState(revision=current.revision + 1, overrides=overrides)
            self._write(updated)
            return self._public(updated)
